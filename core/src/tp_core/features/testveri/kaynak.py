"""Test verisi kaynakları: katalog projenin salt okuma veritabanından sorguyla dolar.

Kaynak tanımı (`test_verisi_kaynagi`, göç 0049): grup adı, tek SELECT, anahtar kolonu ve değer
kolonları. Sonucun her satırı için her değer kolonu bir katalog kaydı olur:
`<grup>.<slug(anahtar değeri)>.<alan>` (alan varsayılanı kolon adının slug'ı). Tek değer kolonlu
kaynakta alan boş bırakılabilir: kayıt `<grup>.<slug(anahtar)>` (ör. `ayar.min_siparis_tutari`).
Kolon başına biçim (`metin` | `tutar`: `1.250,00 TL`) ve açıklama şablonu (`{kolon}` yer
tutucuları satırdaki değerle dolar; ör. `Kampanya kodu; ürün: {urun_kodu}`) verilebilir. Gizli
işaret yoktur: parola ve benzeri değerler sır olarak (elle, gizli kayıt) kalır.

Güvenlik: sorgu yalnız core-worker'da, projenin salt okuma bağlantısıyla (`tp_core.veri.
ro_baglanti`: salt okuma işlemi, zaman aşımı) koşar ve önce sorgu muhafızından geçer
(`sqlguard.validate_select`, `izinli` = sorgunun okuduğu tabloların gerçek şeması eksi hassas adlı
kolonlar). En fazla `KAYNAK_MAX_SATIR` satır okunur.

**Yenile** (`testveri.yenile` işi) kataloğu idempotent günceller (mevcut CRUD / sürüm / denetim
kurallarıyla):

- yeni anahtar eklenir (sürüm 1, `olustur` sürüm satırı; toplu `testveri.kaynak_yenile` denetimi);
- değeri (ya da kaynaktan gelen açıklaması) değişen kayıt sürümlenir (`guncelle` sürüm satırı,
  kayıt başına `testveri.guncelle` denetimi: önceki değer + etkilenen case'ler; K10 uyarısı);
- kaynağın döndürmediği, önceden bu kaynaktan gelmiş kayıt silinmez, `kaynakta_yok` işaretlenir;
  yeniden dönerse işaret kalkar;
- silinmiş (analistin kaldırdığı) anahtar yeniden açılmaz; gizli kayıtla aynı anahtar ya da
  bilinen bir gizli değerle aynı değer atlanır (değer rapora yazılmaz).

Kaynak sırasıyla (`sira`, `grup`) her kaynak ayrı kayıt noktasında (SAVEPOINT) işlenir: biri hata
verirse diğerleri yine güncellenir; hata metni kaynağın `son_durum`'una yazılır.

Bayi Portalı (varsayılan proje) bugünkü tohumunu bu mekanizmanın ön tanımlı kaynakları olarak
taşır (`on_tanimli_kaynaklar`; sorgular `cases.testdata.SORGULAR`): aynı anahtarlar, aynı değerler,
aynı açıklamalar.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from tp_core.audit.session import audit_on_commit
from tp_core.features.testveri import atif
from tp_core.models.otomasyon_feature import TestVerisi, TestVerisiKaynagi, TestVerisiSurum
from tp_core.proje import mevcut_pid

log = logging.getLogger(__name__)

YENILE_JOB = "testveri.yenile"
ONIZLE_JOB = "testveri.onizle"
IS_TURLERI = (YENILE_JOB, ONIZLE_JOB)

KAYNAK_MAX_SATIR = 500
ONIZLEME_SATIR = 20
MAX_KOLON = 20
MAX_UYARI = 20
BICIMLER = ("metin", "tutar")
GRUP_RE = re.compile(r"^[a-z0-9_]{1,40}$")
ALAN_RE = re.compile(r"^[a-z0-9_]{0,40}$")
KOLON_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$#]{0,63}$")
_YER_TUTUCU = re.compile(r"\{([A-Za-z_][A-Za-z0-9_$#]{0,63})\}")
MAX_SORGU = 2000
MAX_ACIKLAMA = 500


class KaynakHatasi(RuntimeError):
    """Kaynak sorgusu çalıştırılamadı (bağlantı, muhafız reddi, sorgu hatası; metin maskeli)."""


# --------------------------------------------------------------------------- tanım


@dataclass(frozen=True)
class KolonTanimi:
    kolon: str
    alan: str
    bicim: str = "metin"
    aciklama: str = ""

    def json(self) -> dict[str, str]:
        return {
            "kolon": self.kolon,
            "alan": self.alan,
            "bicim": self.bicim,
            "aciklama": self.aciklama,
        }


@dataclass(frozen=True)
class KaynakTanimi:
    grup: str
    sorgu: str
    anahtar_kolonu: str
    deger_kolonlari: tuple[KolonTanimi, ...]
    aciklama: str = ""

    def anahtar(self, slug_: str, k: KolonTanimi) -> str:
        return f"{self.grup}.{slug_}.{k.alan}" if k.alan else f"{self.grup}.{slug_}"


def _hata(mesaj: str) -> Exception:
    from tp_core.features.testveri.service import TestVerisiGecersiz

    return TestVerisiGecersiz(mesaj)


def _metin_alani(ad: str, deger: Any, uzunluk: int) -> str:
    if deger is None:
        return ""
    if not isinstance(deger, str):
        raise _hata(f"{ad} metin olmalı")
    deger = deger.strip()
    if len(deger) > uzunluk:
        raise _hata(f"{ad} en çok {uzunluk} karakter olabilir")
    return deger


def tanim_dogrula(girdi: Mapping[str, Any]) -> KaynakTanimi:
    """API girdisini doğrular (yapısal; sorgunun şemaya göre denetimi önizleme / yenilemede)."""
    from tp_core.features.requirements.sqlguard import QueryRejected, tablo_adlari

    grup = girdi.get("grup")
    if not isinstance(grup, str) or not GRUP_RE.match(grup):
        raise _hata("Grup adı küçük harf, rakam ve '_' olmalı (en çok 40 karakter; ör. musteri)")
    sorgu = girdi.get("sorgu")
    if not isinstance(sorgu, str) or not sorgu.strip():
        raise _hata("Sorgu boş olamaz")
    sorgu = sorgu.strip().rstrip(";").strip()
    if len(sorgu) > MAX_SORGU:
        raise _hata(f"Sorgu en çok {MAX_SORGU} karakter olabilir")
    try:
        if not tablo_adlari(sorgu, lehce=_lehce()):
            raise _hata("Sorgu en az bir tabloyu okumalı (FROM gerekli)")
    except QueryRejected as exc:
        raise _hata(f"Sorgu geçersiz: {exc}") from exc
    if not sorgu.lstrip().lower().startswith("select"):
        raise _hata("Yalnızca SELECT sorgusu tanımlanabilir")
    anahtar_kolonu = girdi.get("anahtar_kolonu")
    if not isinstance(anahtar_kolonu, str) or not KOLON_RE.match(anahtar_kolonu.strip()):
        raise _hata("Anahtar kolonu sorgu sonucundaki bir kolon adı olmalı")
    ham_kolonlar = girdi.get("deger_kolonlari")
    if not isinstance(ham_kolonlar, list) or not ham_kolonlar:
        raise _hata("En az bir değer kolonu verin")
    if len(ham_kolonlar) > MAX_KOLON:
        raise _hata(f"En çok {MAX_KOLON} değer kolonu verilebilir")
    kolonlar: list[KolonTanimi] = []
    for h in ham_kolonlar:
        if isinstance(h, str):
            h = {"kolon": h}
        if not isinstance(h, Mapping):
            raise _hata("Değer kolonu tanımı geçersiz")
        kolon = h.get("kolon")
        if not isinstance(kolon, str) or not KOLON_RE.match(kolon.strip()):
            raise _hata("Değer kolonu sorgu sonucundaki bir kolon adı olmalı")
        kolon = kolon.strip()
        alan = h.get("alan")
        alan = _slug(kolon) if alan is None else _metin_alani("Alan", alan, 40)
        if not ALAN_RE.match(alan):
            raise _hata("Alan adı küçük harf, rakam ve '_' olmalı")
        bicim = h.get("bicim") or "metin"
        if bicim not in BICIMLER:
            raise _hata("Biçim 'metin' ya da 'tutar' olmalı")
        aciklama = _metin_alani("Kolon açıklaması", h.get("aciklama"), MAX_ACIKLAMA)
        kolonlar.append(KolonTanimi(kolon, alan, bicim, aciklama))
    alanlar = [k.alan for k in kolonlar]
    if len(set(alanlar)) != len(alanlar):
        raise _hata("Değer kolonlarının alan adları tekil olmalı")
    if "" in alanlar and len(kolonlar) > 1:
        raise _hata("Alan adı yalnız tek değer kolonlu kaynakta boş bırakılabilir")
    aciklama = _metin_alani("Açıklama", girdi.get("aciklama"), MAX_ACIKLAMA)
    tanim = KaynakTanimi(grup, sorgu, anahtar_kolonu.strip(), tuple(kolonlar), aciklama)
    for k in kolonlar:
        if not atif.ANAHTAR_RE.match(tanim.anahtar("x", k)):
            raise _hata("Grup ve alan adlarından geçerli bir anahtar kurulamıyor")
    return tanim


def _lehce() -> str:
    """Bağlamdaki projenin salt okuma veritabanı lehçesi (yapılandırılmamışsa PostgreSQL)."""
    try:
        from tp_core.features.requirements.settings import get_requirements_settings

        tanim = get_requirements_settings().ro_baglanti()
        return tanim.lehce if tanim is not None else "postgres"
    except Exception:
        return "postgres"


def tanim_modelden(k: TestVerisiKaynagi) -> KaynakTanimi:
    return KaynakTanimi(
        grup=k.grup,
        sorgu=k.sorgu,
        anahtar_kolonu=k.anahtar_kolonu,
        deger_kolonlari=tuple(
            KolonTanimi(
                str(d.get("kolon") or ""),
                str(d.get("alan") or ""),
                str(d.get("bicim") or "metin"),
                str(d.get("aciklama") or ""),
            )
            for d in (k.deger_kolonlari or [])
        ),
        aciklama=k.aciklama or "",
    )


# --------------------------------------------------------------------------- ön tanımlı (demo)


def on_tanimli_kaynaklar() -> list[KaynakTanimi]:
    """Bayi Portalı'nın bugünkü tohumu (013 §3.3) kaynak tanımları olarak; sıra = tohum sırası."""
    from tp_core.features.cases import testdata

    s = testdata.SORGULAR
    return [
        KaynakTanimi(
            "bayi",
            s["bayi"],
            "kullanici_adi",
            (
                KolonTanimi(
                    "kullanici_adi", "kullanici_adi", "metin", "Test kullanıcısının kullanıcı adı"
                ),
                KolonTanimi("ad", "ad", "metin", "Bayi adı"),
                KolonTanimi("kredi_limiti", "kredi_limiti", "tutar", "Kredi limiti"),
            ),
            "Test kullanıcıları (bayiler)",
        ),
        KaynakTanimi(
            "urun",
            s["urun"],
            "kod",
            (
                KolonTanimi("kod", "kod", "metin", "Ürün kodu"),
                KolonTanimi("ad", "ad", "metin", "Ürün adı"),
                KolonTanimi("fiyat", "fiyat", "tutar", "Birim fiyat"),
            ),
            "Aktif ürünler",
        ),
        KaynakTanimi(
            "kampanya",
            s["kampanya"],
            "kod",
            (
                KolonTanimi("kod", "kod", "metin", "Kampanya kodu; ürün: {urun_kodu}"),
                KolonTanimi("ad", "ad", "metin", "Kampanya adı"),
            ),
            "Aktif kampanyalar",
        ),
        KaynakTanimi(
            "ayar",
            s["ayar"],
            "anahtar",
            (KolonTanimi("deger", "", "metin", "Uygulama ayarı ({anahtar})"),),
            "Uygulama ayarları",
        ),
    ]


def on_tanimlilari_ekle(session: Session, aktor: str) -> int:
    """Ön tanımlı kaynakları ekler (grup başına idempotent; silinmiş kaynak yeniden açılmaz)."""
    eklenen = 0
    for i, t in enumerate(on_tanimli_kaynaklar()):
        sonuc = session.execute(
            insert(TestVerisiKaynagi)
            .values(
                id=uuid.uuid4(),
                project_id=mevcut_pid(),
                grup=t.grup,
                aciklama=t.aciklama,
                sorgu=t.sorgu,
                anahtar_kolonu=t.anahtar_kolonu,
                deger_kolonlari=[k.json() for k in t.deger_kolonlari],
                sira=i,
                on_tanimli=True,
                surum=1,
                silindi=False,
                guncelleyen=aktor,
            )
            .on_conflict_do_nothing(index_elements=["project_id", "grup"])
            .returning(TestVerisiKaynagi.id)
        ).first()
        eklenen += sonuc is not None
    return eklenen


# --------------------------------------------------------------------------- kayıt üretimi (saf)


def _slug(metin: Any) -> str:
    from tp_core.features.testveri.service import slug

    return slug(metin)


def hucre_metni(deger: Any) -> str | None:
    """Sonuç hücresi → metin (None/bytes → None). Decimal olduğu gibi (`750.00`)."""
    if deger is None or isinstance(deger, bytes | bytearray | memoryview):
        return None
    if isinstance(deger, bool):
        return "true" if deger else "false"
    if isinstance(deger, datetime | date):
        return deger.isoformat()
    if isinstance(deger, Decimal):
        return str(deger)
    return str(deger)


def _aciklama(sablon: str, satir: Mapping[str, Any]) -> str:
    def _yerine(m: re.Match[str]) -> str:
        ad = m.group(1).lower()
        if ad in satir:
            return hucre_metni(satir[ad]) or ""
        return m.group(0)

    return _YER_TUTUCU.sub(_yerine, sablon or "")[:MAX_ACIKLAMA]


def kayitlari_uret(
    tanim: KaynakTanimi, kolonlar: Sequence[str], satirlar: Iterable[Sequence[Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Sorgu sonucundan katalog kayıtları (`{anahtar, deger, grup, aciklama}`; satır sırasıyla)
    ve uyarılar (değer içermez). Anahtar kolonu sonuçta yoksa `KaynakHatasi`."""
    from tp_core.features.cases import testdata
    from tp_core.features.testveri.service import MAX_DEGER

    adlar = [str(k).lower() for k in kolonlar]
    eksik = [
        k
        for k in (tanim.anahtar_kolonu, *(d.kolon for d in tanim.deger_kolonlari))
        if k.lower() not in adlar
    ]
    if eksik:
        raise KaynakHatasi(
            "Sorgu sonucunda olmayan kolon: "
            + ", ".join(dict.fromkeys(eksik))
            + " (sonuç kolonları: "
            + ", ".join(adlar)
            + ")"
        )
    kayitlar: list[dict[str, Any]] = []
    uyarilar: list[str] = []
    sayac: dict[str, int] = {}

    def uyar(tur: str) -> None:
        sayac[tur] = sayac.get(tur, 0) + 1

    gorulen: set[str] = set()
    for ham in satirlar:
        satir = dict(zip(adlar, ham, strict=False))
        anahtar_ham = hucre_metni(satir.get(tanim.anahtar_kolonu.lower()))
        if anahtar_ham is None or not anahtar_ham.strip():
            uyar("anahtarı boş satır atlandı")
            continue
        s = _slug(anahtar_ham)
        if s in gorulen:
            uyar("aynı anahtara düşen satır atlandı (ilk satır kullanıldı)")
            continue
        gorulen.add(s)
        for k in tanim.deger_kolonlari:
            anahtar = tanim.anahtar(s, k)
            if len(anahtar) > 200 or not atif.ANAHTAR_RE.match(anahtar):
                uyar("geçersiz anahtar atlandı")
                continue
            ham_deger = satir.get(k.kolon.lower())
            deger = testdata.tl(ham_deger) if k.bicim == "tutar" else hucre_metni(ham_deger)
            if ham_deger is None or deger is None or not deger.strip():
                uyar("boş değer atlandı")
                continue
            if len(deger) > MAX_DEGER:
                uyar(f"{MAX_DEGER} karakterden uzun değer atlandı")
                continue
            if "{veri:" in deger:
                uyar("atıf içeren değer atlandı")
                continue
            kayitlar.append(
                {
                    "anahtar": anahtar,
                    "deger": deger,
                    "grup": tanim.grup,
                    "aciklama": _aciklama(k.aciklama, satir),
                }
            )
    uyarilar = [f"{n} {tur}" for tur, n in sayac.items()]
    return kayitlar, uyarilar


# --------------------------------------------------------------------------- sorgu çalıştırma

Calistirici = Callable[[str], tuple[list[str], list[tuple[Any, ...]]]]


def projeksiyon_adlari(sql: str) -> list[str]:
    """SELECT projeksiyonunun çıktı adları (takma ad ya da kolon adı; PostgreSQL lehçesi)."""
    import sqlglot

    agac = sqlglot.parse_one(sql, read="postgres")
    return [e.alias_or_name.lower() for e in agac.expressions]


def satir_calistirici(sorgu: Callable[[str], Sequence[Sequence[Any]]]) -> Calistirici:
    """Yalnız satır döndüren eski sorgu fonksiyonunu (`testdata` fabrikası, testler) sarar: kolon
    adları sorgunun projeksiyonundan."""

    def calistir(sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
        return projeksiyon_adlari(sql), [tuple(r) for r in sorgu(sql)]

    return calistir


def db_calistirici(en_fazla: int = KAYNAK_MAX_SATIR + 1) -> Calistirici:
    """Bağlamdaki projenin salt okuma veritabanı (core-worker). Her çağrı: şema keşfi (sorgunun
    okuduğu tablolar) → muhafız (`izinli` = gerçek kolonlar eksi hassas adlılar) → çalıştırma;
    tek salt okuma oturumunda. Yapılandırma yoksa ya da geçersizse `KaynakHatasi`."""
    from tp_core.features.requirements.datatools import STATEMENT_TIMEOUT_MS
    from tp_core.features.requirements.settings import get_requirements_settings
    from tp_core.features.requirements.sqlguard import (
        QueryRejected,
        tablo_adlari,
        validate_select,
    )
    from tp_core.veri import ro_baglanti

    ayar = get_requirements_settings()
    try:
        tanim = ayar.ro_baglanti()
    except ro_baglanti.BaglantiHatasi as exc:
        raise KaynakHatasi(f"Veri erişimi yapılandırması geçersiz: {exc}") from exc
    if tanim is None:
        raise KaynakHatasi(
            "Projenin salt okuma veritabanı bağlantısı tanımlı değil (Home: proje veritabanı)"
        )

    def calistir(sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
        try:
            tablolar = tablo_adlari(sql, lehce=tanim.lehce)
            with ro_baglanti.oturum(
                tanim, connect_timeout_s=3, timeout_ms=int(STATEMENT_TIMEOUT_MS)
            ) as o:
                izin: dict[str, set[str]] = {t: set() for t in tablolar}
                if tablolar:
                    _, ham = o.calistir(ro_baglanti.sema_sorgusu(tanim.tur, tablolar))
                    for t, k, _tip in ro_baglanti.sema_satirlari(tanim.tur, ham):
                        izin.setdefault(t, set()).add(k)
                izinli = {t: frozenset(ks) for t, ks in izin.items() if ks}
                vq = validate_select(sql, lehce=tanim.lehce, izinli=izinli)
                kolonlar, satirlar = o.calistir(vq.sql, en_fazla=en_fazla)
        except QueryRejected as exc:
            raise KaynakHatasi(f"Sorgu reddedildi: {exc}") from exc
        except ro_baglanti.SorguHatasi as exc:
            if exc.tur == ro_baglanti.ZAMAN:
                raise KaynakHatasi("Sorgu zaman aşımına uğradı") from exc
            raise KaynakHatasi(f"Sorgu hatası: {exc}") from exc
        except ro_baglanti.BaglantiHatasi as exc:
            raise KaynakHatasi(str(exc)) from exc
        except ValueError as exc:  # şema keşfinde geçersiz tablo adı
            raise KaynakHatasi(f"Sorgu reddedildi: {exc}") from exc
        return [str(k).lower() for k in kolonlar], [tuple(r) for r in satirlar]

    return calistir


_calistirici_fabrikasi: Callable[[], Calistirici] = db_calistirici


def set_calistirici_fabrikasi(f: Callable[[], Calistirici] | None) -> None:
    """Testler için (None → projenin salt okuma veritabanı)."""
    global _calistirici_fabrikasi
    _calistirici_fabrikasi = f or db_calistirici


def calistirici() -> Calistirici:
    return _calistirici_fabrikasi()


def kaynak_sonucu(
    tanim: KaynakTanimi, calistir: Calistirici
) -> tuple[list[str], list[tuple[Any, ...]], list[dict[str, Any]], list[str], bool]:
    """(kolonlar, satırlar, kayıtlar, uyarılar, kesildi)."""
    kolonlar, satirlar = calistir(tanim.sorgu)
    kesildi = len(satirlar) > KAYNAK_MAX_SATIR
    satirlar = satirlar[:KAYNAK_MAX_SATIR]
    kayitlar, uyarilar = kayitlari_uret(tanim, kolonlar, satirlar)
    if kesildi:
        uyarilar.append(
            f"sorgu {KAYNAK_MAX_SATIR} satırdan fazla döndürdü; ilk {KAYNAK_MAX_SATIR} satır "
            "kullanıldı, 'kaynakta yok' işareti uygulanmadı"
        )
    return kolonlar, satirlar, kayitlar, uyarilar, kesildi


# --------------------------------------------------------------------------- CRUD


def _kaynak_kayit_sayilari(session: Session) -> dict[uuid.UUID, tuple[int, int]]:
    out: dict[uuid.UUID, tuple[int, int]] = {}
    for kid, toplam, yok in session.execute(
        select(
            TestVerisi.kaynak_id,
            func.count(),
            func.count().filter(TestVerisi.kaynakta_yok.is_(True)),
        )
        .where(TestVerisi.silindi.is_(False), TestVerisi.kaynak_id.is_not(None))
        .group_by(TestVerisi.kaynak_id)
    ).all():
        out[kid] = (int(toplam), int(yok))
    return out


def serialize(k: TestVerisiKaynagi, sayilar: tuple[int, int] = (0, 0)) -> dict[str, Any]:
    return {
        "id": str(k.id),
        "grup": k.grup,
        "aciklama": k.aciklama,
        "sorgu": k.sorgu,
        "anahtar_kolonu": k.anahtar_kolonu,
        "deger_kolonlari": [
            {
                "kolon": str(d.get("kolon") or ""),
                "alan": str(d.get("alan") or ""),
                "bicim": str(d.get("bicim") or "metin"),
                "aciklama": str(d.get("aciklama") or ""),
            }
            for d in (k.deger_kolonlari or [])
        ],
        "sira": k.sira,
        "on_tanimli": k.on_tanimli,
        "surum": k.surum,
        "guncelleyen": k.guncelleyen,
        "guncelleme": k.guncelleme,
        "kayit_sayisi": sayilar[0],
        "kaynakta_yok_sayisi": sayilar[1],
        "son_yenileme": k.son_yenileme,
        "son_durum": k.son_durum,
    }


def etkin_kaynaklar(session: Session) -> list[TestVerisiKaynagi]:
    return list(
        session.scalars(
            select(TestVerisiKaynagi)
            .where(TestVerisiKaynagi.silindi.is_(False))
            .order_by(TestVerisiKaynagi.sira, TestVerisiKaynagi.grup)
        )
    )


def listele(session: Session) -> list[dict[str, Any]]:
    sayilar = _kaynak_kayit_sayilari(session)
    return [serialize(k, sayilar.get(k.id, (0, 0))) for k in etkin_kaynaklar(session)]


def _denetim(session: Session, aktor: str, eylem: str, k: TestVerisiKaynagi, **ek: Any) -> None:
    ozet: dict[str, Any] = {"grup": k.grup, "surum": k.surum, "sorgu": k.sorgu}
    ozet.update(ek)
    audit_on_commit(session, aktor, eylem, f"test_verisi_kaynagi:{k.id}", ozet)


def olustur(session: Session, girdi: Mapping[str, Any], aktor: str) -> TestVerisiKaynagi:
    from tp_core.features.testveri.service import TestVerisiCakisma

    t = tanim_dogrula(girdi)
    var = session.scalars(
        select(TestVerisiKaynagi).where(TestVerisiKaynagi.grup == t.grup).with_for_update()
    ).first()
    if var is not None and not var.silindi:
        raise TestVerisiCakisma(f"Bu grup için kaynak zaten var: {t.grup}")
    sira = session.scalar(select(func.coalesce(func.max(TestVerisiKaynagi.sira), -1))) or 0
    if var is not None:
        k = var
        k.silindi, k.surum = False, k.surum + 1
    else:
        k = TestVerisiKaynagi(grup=t.grup, surum=1, on_tanimli=False)
        session.add(k)
    k.sorgu, k.anahtar_kolonu, k.aciklama = t.sorgu, t.anahtar_kolonu, t.aciklama
    k.deger_kolonlari = [d.json() for d in t.deger_kolonlari]
    k.sira = int(sira) + 1
    k.guncelleyen = aktor
    k.son_yenileme, k.son_durum = None, None
    session.flush()
    _denetim(session, aktor, "testveri.kaynak_olustur", k)
    session.flush()
    session.refresh(k)
    return k


def _kilitli(session: Session, kid: uuid.UUID, beklenen_surum: int | None) -> TestVerisiKaynagi:
    from tp_core.features.testveri.service import (
        TestVerisiCakisma,
        TestVerisiGecersiz,
        TestVerisiYok,
    )

    k = session.get(TestVerisiKaynagi, kid, with_for_update=True)
    if k is None or k.silindi:
        raise TestVerisiYok("Test verisi kaynağı bulunamadı")
    if beklenen_surum is None:
        raise TestVerisiGecersiz("beklenen_surum zorunlu")
    if k.surum != beklenen_surum:
        raise TestVerisiCakisma(
            f"Kaynak siz görüntüledikten sonra değişmiş (güncel sürüm {k.surum}); yeniden yükleyin"
        )
    return k


def guncelle(
    session: Session,
    kid: uuid.UUID,
    girdi: Mapping[str, Any],
    beklenen_surum: int | None,
    aktor: str,
) -> TestVerisiKaynagi:
    """Tanımı değiştirir (grup değiştirilemez: anahtarlar gruptan türer). Katalog bir sonraki
    yenilemede güncellenir."""
    from tp_core.features.testveri.service import TestVerisiGecersiz

    k = _kilitli(session, kid, beklenen_surum)
    mevcut = serialize(k)
    birlesik = {
        "grup": k.grup,
        "sorgu": girdi.get("sorgu", mevcut["sorgu"]),
        "anahtar_kolonu": girdi.get("anahtar_kolonu", mevcut["anahtar_kolonu"]),
        "deger_kolonlari": girdi.get("deger_kolonlari", mevcut["deger_kolonlari"]),
        "aciklama": girdi.get("aciklama", mevcut["aciklama"]) or "",
    }
    if girdi.get("grup") not in (None, k.grup):
        raise TestVerisiGecersiz("Kaynağın grubu değiştirilemez; yeni kaynak tanımlayın")
    t = tanim_dogrula(birlesik)
    yeni = {
        "sorgu": t.sorgu,
        "anahtar_kolonu": t.anahtar_kolonu,
        "deger_kolonlari": [d.json() for d in t.deger_kolonlari],
        "aciklama": t.aciklama,
    }
    eski = {a: mevcut[a] for a in yeni}
    if yeni == eski:
        raise TestVerisiGecersiz("Değişiklik yok")
    k.sorgu, k.anahtar_kolonu = t.sorgu, t.anahtar_kolonu
    k.deger_kolonlari, k.aciklama = yeni["deger_kolonlari"], t.aciklama
    k.surum += 1
    k.guncelleyen = aktor
    session.flush()
    _denetim(session, aktor, "testveri.kaynak_guncelle", k)
    session.flush()
    session.refresh(k)
    return k


def sil(
    session: Session, kid: uuid.UUID, beklenen_surum: int | None, aktor: str
) -> TestVerisiKaynagi:
    """Yumuşak silme. Kaynağın katalog kayıtları silinmez: elle kayda döner (`kaynak_id` NULL,
    `kaynakta_yok` kalkar)."""
    k = _kilitli(session, kid, beklenen_surum)
    kayitlar = list(
        session.scalars(select(TestVerisi).where(TestVerisi.kaynak_id == k.id).with_for_update())
    )
    for r in kayitlar:
        r.kaynak_id = None
        r.kaynakta_yok = False
    k.silindi = True
    k.surum += 1
    k.guncelleyen = aktor
    session.flush()
    _denetim(session, aktor, "testveri.kaynak_sil", k, birakilan_kayit=len(kayitlar))
    session.flush()
    return k


# --------------------------------------------------------------------------- yenileme


def _bos_ozet() -> dict[str, Any]:
    return {
        "eklenen": 0,
        "guncellenen": 0,
        "ayni": 0,
        "kaynakta_yok": 0,
        "geri_gelen": 0,
        "atlanan": 0,
        "satir": 0,
        "kesildi": False,
        "uyarilar": [],
        "hata": None,
    }


def katalogu_guncelle(
    session: Session,
    kaynak: TestVerisiKaynagi | None,
    kayitlar: Sequence[Mapping[str, Any]],
    aktor: str,
    *,
    yalniz_ekle: bool = False,
    kaynakta_yok_isaretle: bool = True,
    kaynak_id: uuid.UUID | None = None,
    taban: datetime | None = None,
) -> dict[str, Any]:
    """Kaynağın kayıtlarını kataloğa yazar (modül belgesindeki kurallar); özet döner.

    `yalniz_ekle=True` (worker açılışı tohumu): yalnız olmayan anahtarlar eklenir, var olan
    kayıtların değeri değişmez (analistin değişikliği korunur); sahipsiz (`kaynak_id` NULL) aynı
    anahtarlı kayıt kaynağa bağlanır. `kaynak` None ise `kaynak_id` kullanılır (tohum)."""
    from tp_core.features.testveri.service import (
        _surum_yaz,
        anahtar_kullanimi,
        gizli_degerler,
    )

    kid = kaynak.id if kaynak is not None else kaynak_id
    ozet = _bos_ozet()
    ozet["satir"] = len(kayitlar)
    anahtarlar = [r["anahtar"] for r in kayitlar]
    mevcut = (
        {
            k.anahtar: k
            for k in session.scalars(
                select(TestVerisi)
                .where(TestVerisi.anahtar.in_(anahtarlar))
                .order_by(TestVerisi.anahtar)
                .with_for_update()
            )
        }
        if anahtarlar
        else {}
    )
    gizliler = set(gizli_degerler(session))
    taban = taban or datetime.now(UTC)
    eklenen: list[str] = []
    for i, r in enumerate(kayitlar):
        anahtar, deger = r["anahtar"], r["deger"]
        k = mevcut.get(anahtar)
        if deger in gizliler:
            ozet["atlanan"] += 1
            continue
        if k is None:
            sonuc = session.execute(
                insert(TestVerisi)
                .values(
                    id=uuid.uuid4(),
                    project_id=mevcut_pid(),
                    anahtar=anahtar,
                    grup=r["grup"],
                    aciklama=r.get("aciklama") or "",
                    deger=deger,
                    gizli=False,
                    sir_adi=None,
                    surum=1,
                    silindi=False,
                    guncelleyen=aktor,
                    olusturma=taban + timedelta(microseconds=i),
                    guncelleme=taban,
                    kaynak_id=kid,
                    kaynakta_yok=False,
                )
                .on_conflict_do_nothing(index_elements=["project_id", "anahtar"])
                .returning(TestVerisi.id)
            ).first()
            if sonuc is None:  # eşzamanlı ekleme
                ozet["atlanan"] += 1
                continue
            session.add(
                TestVerisiSurum(
                    test_verisi_id=sonuc[0],
                    surum=1,
                    islem="olustur",
                    deger=deger,
                    gizli=False,
                    sir_adi=None,
                    degistiren=aktor,
                )
            )
            eklenen.append(anahtar)
            ozet["eklenen"] += 1
            continue
        if k.silindi or k.gizli:
            ozet["atlanan"] += 1
            continue
        if k.kaynak_id is not None and k.kaynak_id != kid:
            ozet["atlanan"] += 1  # başka kaynağın kaydı
            continue
        if yalniz_ekle:
            if k.kaynak_id is None:
                k.kaynak_id = kid
            ozet["ayni"] += 1
            continue
        k.kaynak_id = kid
        if k.kaynakta_yok:
            k.kaynakta_yok = False
            ozet["geri_gelen"] += 1
        yeni_aciklama = r.get("aciklama") or ""
        if deger == k.deger and yeni_aciklama == (k.aciklama or ""):
            ozet["ayni"] += 1
            continue
        onceki = k.deger
        k.deger = deger
        k.aciklama = yeni_aciklama
        k.surum += 1
        k.guncelleyen = aktor
        session.flush()
        _surum_yaz(session, k, "guncelle", aktor)
        etkilenen = anahtar_kullanimi(session, k.anahtar)
        audit_on_commit(
            session,
            aktor,
            "testveri.guncelle",
            f"test_verisi:{k.id}",
            {
                "anahtar": k.anahtar,
                "surum": k.surum,
                "gizli": False,
                "deger": k.deger,
                "onceki_deger": onceki,
                "kaynak": True,
                "etkilenen_case": [c["case_id"] for c in etkilenen][:50],
            },
        )
        ozet["guncellenen"] += 1
    if kaynakta_yok_isaretle and not yalniz_ekle and kid is not None:
        donen = set(anahtarlar)
        for k in session.scalars(
            select(TestVerisi)
            .where(
                TestVerisi.kaynak_id == kid,
                TestVerisi.silindi.is_(False),
                TestVerisi.kaynakta_yok.is_(False),
            )
            .order_by(TestVerisi.anahtar)
            .with_for_update()
        ):
            if k.anahtar not in donen:
                k.kaynakta_yok = True
                ozet["kaynakta_yok"] += 1
    session.flush()
    return ozet


def _kilit(session: Session) -> None:
    """Aynı projede eşzamanlı iki yenileme sıralanır."""
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": f"tp-testveri-kaynak:{mevcut_pid()}"},
    )


def yenile(
    session: Session,
    aktor: str,
    *,
    kaynak_id: uuid.UUID | None = None,
    calistir: Calistirici | None = None,
) -> dict[str, Any]:
    """Kaynakları (ya da yalnız `kaynak_id`) koşar ve kataloğu günceller. Özet:
    `{kaynaklar: [{id, grup, ...özet}], toplam: {...}}`."""
    _kilit(session)
    kaynaklar = etkin_kaynaklar(session)
    if kaynak_id is not None:
        kaynaklar = [k for k in kaynaklar if k.id == kaynak_id]
    if calistir is None:
        try:
            calistir = calistirici()
        except KaynakHatasi as exc:
            calistir = _hata_calistirici(str(exc))
    sonuclar: list[dict[str, Any]] = []
    toplam = _bos_ozet()
    for k in kaynaklar:
        nokta = session.begin_nested()
        try:
            _, _, kayitlar, uyarilar, kesildi = kaynak_sonucu(tanim_modelden(k), calistir)
            ozet = katalogu_guncelle(session, k, kayitlar, aktor, kaynakta_yok_isaretle=not kesildi)
            ozet["uyarilar"] = uyarilar[:MAX_UYARI]
            ozet["kesildi"] = kesildi
            nokta.commit()
        except KaynakHatasi as exc:
            nokta.rollback()
            ozet = _bos_ozet()
            ozet["hata"] = str(exc)[:500]
        k = session.get(TestVerisiKaynagi, k.id) or k
        k.son_yenileme = datetime.now(UTC)
        k.son_durum = {**ozet, "aktor": aktor}
        sonuclar.append({"id": str(k.id), "grup": k.grup, **ozet})
        for a in ("eklenen", "guncellenen", "ayni", "kaynakta_yok", "geri_gelen", "atlanan"):
            toplam[a] += ozet[a]
    toplam["hata"] = sum(1 for s in sonuclar if s["hata"]) or None
    session.flush()
    audit_on_commit(
        session,
        aktor,
        "testveri.kaynak_yenile",
        None,
        {
            "kaynak": [
                {a: s[a] for a in ("grup", "eklenen", "guncellenen", "kaynakta_yok", "hata")}
                for s in sonuclar
            ]
        },
    )
    return {"kaynaklar": sonuclar, "toplam": toplam}


def _hata_calistirici(mesaj: str) -> Calistirici:
    def calistir(_sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
        raise KaynakHatasi(mesaj)

    return calistir


def onizle(
    session: Session, tanim: KaynakTanimi, *, calistir: Calistirici | None = None
) -> dict[str, Any]:
    """İlk `ONIZLEME_SATIR` satır ve onlardan çıkan kayıtların katalogdaki durumu; katalog
    değişmez. Gizli değerle çakışan kaydın değeri gösterilmez."""
    from tp_core.features.testveri.service import gizli_degerler

    calistir = calistir or calistirici()
    kolonlar, satirlar, kayitlar, uyarilar, kesildi = kaynak_sonucu(tanim, calistir)
    gizliler = set(gizli_degerler(session))
    ilk = satirlar[:ONIZLEME_SATIR]
    gosterilen = kayitlari_uret(tanim, kolonlar, ilk)[0]
    mevcut = (
        {
            k.anahtar: k
            for k in session.scalars(
                select(TestVerisi).where(TestVerisi.anahtar.in_([r["anahtar"] for r in gosterilen]))
            )
        }
        if gosterilen
        else {}
    )
    out_kayit = []
    for r in gosterilen:
        k = mevcut.get(r["anahtar"])
        if r["deger"] in gizliler:
            durum, deger = "gizli_cakisma", None
        elif k is None:
            durum, deger = "yeni", r["deger"]
        elif k.silindi:
            durum, deger = "silinmis", r["deger"]
        elif k.gizli:
            durum, deger = "gizli_kayit", None
        elif k.deger == r["deger"]:
            durum, deger = "ayni", r["deger"]
        else:
            durum, deger = "degisecek", r["deger"]
        out_kayit.append({"anahtar": r["anahtar"], "deger": deger, "durum": durum})
    satir_gorunum = [
        [None if (h := hucre_metni(v)) is None else ("•••" if h in gizliler else h) for v in r]
        for r in ilk
    ]
    return {
        "kolonlar": kolonlar,
        "satirlar": satir_gorunum,
        "toplam_satir": len(satirlar),
        "kesildi": kesildi,
        "kayit_sayisi": len(kayitlar),
        "kayitlar": out_kayit,
        "uyarilar": uyarilar[:MAX_UYARI],
    }


# --------------------------------------------------------------------------- işler


def yenile_kuyruga(session: Session, aktor: str, kaynak_id: uuid.UUID | None = None) -> uuid.UUID:
    from tp_core.features.testveri.service import TestVerisiYok
    from tp_core.workflow.jobs import enqueue

    if kaynak_id is not None:
        k = session.get(TestVerisiKaynagi, kaynak_id)
        if k is None or k.silindi:
            raise TestVerisiYok("Test verisi kaynağı bulunamadı")
    return enqueue(
        session.connection(),
        YENILE_JOB,
        {"kaynak_id": str(kaynak_id) if kaynak_id else None, "aktor": aktor},
    )


def onizle_kuyruga(session: Session, aktor: str, tanim: KaynakTanimi) -> uuid.UUID:
    from tp_core.workflow.jobs import enqueue

    return enqueue(
        session.connection(),
        ONIZLE_JOB,
        {
            "aktor": aktor,
            "tanim": {
                "grup": tanim.grup,
                "sorgu": tanim.sorgu,
                "anahtar_kolonu": tanim.anahtar_kolonu,
                "deger_kolonlari": [d.json() for d in tanim.deger_kolonlari],
                "aciklama": tanim.aciklama,
            },
        },
    )


def is_durumu(session: Session, job_id: uuid.UUID) -> dict[str, Any]:
    """Bu projenin yenileme / önizleme işinin durumu (`{durum, sonuc, hata}`)."""
    from tp_core.features.testveri.service import TestVerisiYok
    from tp_core.models.system import Job

    j = session.scalars(
        select(Job).where(Job.id == job_id, Job.project_id == mevcut_pid(), Job.tur.in_(IS_TURLERI))
    ).first()
    if j is None:
        raise TestVerisiYok("İş bulunamadı")
    durum = {"queued": "kuyrukta", "retry": "kuyrukta", "running": "calisiyor", "done": "tamam"}
    return {
        "id": str(j.id),
        "tur": "yenile" if j.tur == YENILE_JOB else "onizle",
        "durum": durum.get(j.durum, "hata"),
        "sonuc": j.sonuc if j.durum == "done" else None,
        "hata": (j.son_hata or "İş tamamlanamadı")[:500]
        if j.durum in ("failed", "cancelled")
        else None,
    }
