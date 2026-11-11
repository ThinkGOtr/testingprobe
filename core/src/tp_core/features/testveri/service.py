"""Merkezi test verisi kataloğu: okuma, çözüm, CRUD, tohumlama (specs/013-sprint-otomasyonu §3.3).

- `katalog`: gizli olmayan etkin kayıtlar (anahtar → değer).
- `eslem_katalogu`: eşleme kataloğu = `katalog` + değeri ortamda tanımlı gizli kayıtlar; böylece
  parola case metnine düz yazılmaz, `{veri:ortak.demo_parola}` olur.
- `cozum_degerleri`: kod üretimi / koşu için (değerler, sürümler); gizli değer
  `os.environ[sir_adi]`'den, sır tanımsızsa o anahtar çözülemez.
- CRUD: her değişiklik `test_verisi_surum` satırı + denetim (`testveri.olustur|guncelle|sil`).
  İyimser kilit `beklenen_surum` (409); silme yumuşaktır ve atıf yapan etkin case varsa 409.
- `tohumla`: demo DB (`cases/testdata.py` sorguları) + sabitlerden; anahtar başına idempotent
  (var olan ya da silinmiş anahtara dokunmaz).

Gizli kaydın değeri katalogda yoktur, API'den dönmez, denetime yazılmaz. `sir_adi` yalnız
`TP_TESTVERI_` önekli olabilir: aksi hâlde katalog düzenleyen biri herhangi bir süreç sırrını
(model anahtarı vb.) kod üretimine çözdürebilirdi.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from tp_core.audit.session import audit_on_commit
from tp_core.features.testveri import atif
from tp_core.models import Requirement, TestCase
from tp_core.models.otomasyon_feature import TestVerisi, TestVerisiSurum
from tp_core.workflow.service import WorkflowError

log = logging.getLogger(__name__)

SIR_ONEKI = "TP_TESTVERI_"
SIR_ADI_RE = re.compile(r"^TP_TESTVERI_[A-Z0-9_]{1,64}$")
DEMO_PAROLA_SIRRI = "TP_TESTVERI_DEMO_PAROLA"
DEMO_PAROLA_ANAHTARI = "ortak.demo_parola"
# Atıf sayımında "etkin" case: karar bekleyen, onaylı ya da yayınlı.
ETKIN_CASE = ("draft", "approved", "published")
MAX_DEGER = 2000
MAX_METIN = 500
TOHUM_AKTOR = "tohum"

_TR = str.maketrans("çğıöşüÇĞİÖŞÜâîû", "cgiosucgiosuaiu")


# --------------------------------------------------------------------------- hatalar


class TestVerisiHatasi(WorkflowError):
    __test__ = False
    status_code = 409


class TestVerisiYok(TestVerisiHatasi):
    status_code = 404


class TestVerisiGecersiz(TestVerisiHatasi):
    status_code = 422


class TestVerisiCakisma(TestVerisiHatasi):
    status_code = 409


class TestVerisiKullanimda(TestVerisiHatasi):
    """Silinmek istenen kayda atıf yapan etkin case'ler var; `kullanan` listesi API'ye gider."""

    status_code = 409

    def __init__(self, mesaj: str, kullanan: list[dict[str, Any]]) -> None:
        super().__init__(mesaj)
        self.kullanan = kullanan


class TestVerisiCozulemedi(Exception):
    """Case'teki atıf çözülemedi (kod üretimi reddi; Türkçe neden `str(exc)`)."""

    __test__ = False

    def __init__(self, neden: str, anahtarlar: Sequence[str]) -> None:
        super().__init__(neden)
        self.anahtarlar = list(anahtarlar)


# --------------------------------------------------------------------------- okuma


def slug(metin: str) -> str:
    """Anahtar parçası: küçük harf, Türkçe harfler ASCII, diğerleri `_` (ör. `P-001` → `p_001`)."""
    s = str(metin).translate(_TR).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "x"


def sir_degeri(sir_adi: str | None) -> str | None:
    if not sir_adi:
        return None
    deger = os.environ.get(sir_adi)
    return deger if deger else None


def etkin_kayitlar(session: Session) -> list[TestVerisi]:
    """Silinmemiş kayıtlar, ekleme sırasıyla (tohum sırası = demo DB sırası)."""
    return list(
        session.scalars(
            select(TestVerisi)
            .where(TestVerisi.silindi.is_(False))
            .order_by(TestVerisi.olusturma, TestVerisi.anahtar)
        )
    )


def katalog(session: Session) -> dict[str, str]:
    """Gizli olmayan etkin kayıtlar: anahtar → değer."""
    return {
        k.anahtar: k.deger for k in etkin_kayitlar(session) if not k.gizli and k.deger is not None
    }


def eslem_katalogu(session: Session) -> dict[str, str]:
    """Eşleme kataloğu: `katalog` + değeri ortamda tanımlı gizli kayıtlar."""
    out: dict[str, str] = {}
    for k in etkin_kayitlar(session):
        deger = sir_degeri(k.sir_adi) if k.gizli else k.deger
        if deger is not None:
            out[k.anahtar] = deger
    return out


def cozum_degerleri(session: Session) -> tuple[dict[str, str], dict[str, int]]:
    """(değerler, sürümler). Sürümlerde tüm etkin anahtarlar; değerlerde yalnız çözülebilenler."""
    degerler: dict[str, str] = {}
    surumler: dict[str, int] = {}
    for k in etkin_kayitlar(session):
        surumler[k.anahtar] = k.surum
        deger = sir_degeri(k.sir_adi) if k.gizli else k.deger
        if deger is not None:
            degerler[k.anahtar] = deger
    return degerler, surumler


def anahtarlar(session: Session) -> set[str]:
    return set(
        session.scalars(select(TestVerisi.anahtar).where(TestVerisi.silindi.is_(False))).all()
    )


def guncel_surumler(session: Session, istenen: Iterable[str]) -> dict[str, int]:
    """Verilen anahtarların güncel sürümü (silinmiş/olmayan anahtar sözlükte yer almaz)."""
    liste = list(dict.fromkeys(istenen))
    if not liste:
        return {}
    return {
        a: s
        for a, s in session.execute(
            select(TestVerisi.anahtar, TestVerisi.surum).where(
                TestVerisi.anahtar.in_(liste), TestVerisi.silindi.is_(False)
            )
        ).all()
    }


def case_esle(session: Session, icerik: Mapping[str, Any]) -> dict[str, Any]:
    """Case üretimi / IDE kanalı: değerleri atfa çevirir. Katalog boşsa içerik aynen döner."""
    kat = eslem_katalogu(session)
    return atif.case_esle(icerik, kat) if kat else dict(icerik)


def case_coz(session: Session, icerik: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """Kod üretimi / koşu: atıfları değere çevirir; (çözülmüş içerik, `veri_izi`).

    Çözülemeyen atıf `TestVerisiCozulemedi` (Türkçe neden): katalogda yok / silinmiş ya da gizli
    kaydın sırrı ortamda tanımsız.
    """
    istenen = atif.case_atiflari(icerik)
    if not istenen:
        return dict(icerik), {}
    degerler, surumler = cozum_degerleri(session)
    yok = [a for a in istenen if a not in surumler]
    sirsiz = [a for a in istenen if a in surumler and a not in degerler]
    if yok or sirsiz:
        parcalar = []
        if yok:
            parcalar.append("katalogda olmayan test verisi anahtarı: " + ", ".join(yok))
        if sirsiz:
            parcalar.append("test verisi sırrı tanımsız: " + ", ".join(sirsiz))
        raise TestVerisiCozulemedi("; ".join(parcalar), yok + sirsiz)
    return atif.case_coz(icerik, degerler), {a: surumler[a] for a in istenen}


def case_coz_gevsek(session: Session, icerik: Mapping[str, Any]) -> dict[str, Any]:
    """Model girdisi (bug taslağı vb.) için: çözülebilen atıfları çözer, kalanları bırakır."""
    if not atif.case_atiflari(icerik):
        return dict(icerik)
    degerler, _ = cozum_degerleri(session)
    return atif.case_coz(icerik, degerler, bilinmeyen="birak")


def yayin_icin_coz(session: Session, icerik: Mapping[str, Any]) -> dict[str, Any]:
    """Jira/Xray yayını (Y4): gizli olmayan atıflar değere çözülür, gizliler atıf kalır."""
    if not atif.case_atiflari(icerik):
        return dict(icerik)
    return atif.case_coz(icerik, katalog(session), bilinmeyen="birak")


def veri_haritasi(session: Session) -> dict[str, dict[str, Any]]:
    """Serileştirme için: anahtar → {deger (gizli → None), gizli, surum}."""
    return {
        k.anahtar: {"deger": None if k.gizli else k.deger, "gizli": k.gizli, "surum": k.surum}
        for k in etkin_kayitlar(session)
    }


def case_verisi(harita: Mapping[str, Mapping[str, Any]], icerik: Mapping[str, Any]) -> dict:
    """`serialize_cases` `veri` alanı: case'in atıfları → {deger|null, gizli, surum, var}."""
    out: dict[str, dict[str, Any]] = {}
    for a in atif.case_atiflari(icerik):
        k = harita.get(a)
        out[a] = (
            {**k, "var": True}
            if k is not None
            else {"deger": None, "gizli": False, "surum": None, "var": False}
        )
    return out


def veri_degisti(session: Session, veri_izi: Mapping[str, Any] | None) -> bool:
    """Script'in kullandığı sürümlerden biri değişti / silindi mi (K10 uyarısı)?"""
    if not veri_izi:
        return False
    guncel = guncel_surumler(session, veri_izi)
    return any(guncel.get(a) != s for a, s in veri_izi.items())


def kullanim(session: Session) -> dict[str, list[dict[str, Any]]]:
    """Anahtar → atıf yapan etkin case'ler (`{case_id, case_ref, baslik, durum}`)."""
    out: dict[str, list[dict[str, Any]]] = {}
    rows = session.execute(
        select(TestCase.id, TestCase.icerik, TestCase.durum, TestCase.sira_no, Requirement.jira_key)
        .join(Requirement, Requirement.id == TestCase.requirement_id)
        .where(TestCase.durum.in_(ETKIN_CASE))
        .order_by(TestCase.olusturma)
    ).all()
    for cid, icerik, durum, sira, jira_key in rows:
        for a in atif.case_atiflari(icerik or {}):
            out.setdefault(a, []).append(
                {
                    "case_id": str(cid),
                    "case_ref": f"{jira_key or 'SERBEST'}-C{sira}",
                    "baslik": str((icerik or {}).get("title") or "")[:200],
                    "durum": durum,
                }
            )
    return out


# --------------------------------------------------------------------------- serileştirme


def serialize(k: TestVerisi, kullanim_sayisi: int = 0) -> dict[str, Any]:
    return {
        "id": str(k.id),
        "anahtar": k.anahtar,
        "grup": k.grup,
        "aciklama": k.aciklama,
        "deger": None if k.gizli else k.deger,
        "gizli": k.gizli,
        "sir_adi": k.sir_adi,
        "sir_tanimli": bool(k.gizli and sir_degeri(k.sir_adi) is not None),
        "surum": k.surum,
        "guncelleyen": k.guncelleyen,
        "guncelleme": k.guncelleme,
        "kullanim": kullanim_sayisi,
    }


def listele(session: Session) -> list[dict[str, Any]]:
    sayim = {a: len(v) for a, v in kullanim(session).items()}
    kayitlar = session.scalars(
        select(TestVerisi)
        .where(TestVerisi.silindi.is_(False))
        .order_by(TestVerisi.grup, TestVerisi.anahtar)
    ).all()
    return [serialize(k, sayim.get(k.anahtar, 0)) for k in kayitlar]


def gecmis(session: Session, kid: uuid.UUID) -> list[dict[str, Any]]:
    if session.get(TestVerisi, kid) is None:
        raise TestVerisiYok("Test verisi bulunamadı")
    return [
        {
            "surum": r.surum,
            "islem": r.islem,
            "deger": None if r.gizli else r.deger,
            "gizli": r.gizli,
            "sir_adi": r.sir_adi,
            "degistiren": r.degistiren,
            "zaman": r.zaman,
        }
        for r in session.scalars(
            select(TestVerisiSurum)
            .where(TestVerisiSurum.test_verisi_id == kid)
            .order_by(TestVerisiSurum.surum.desc())
        )
    ]


# --------------------------------------------------------------------------- CRUD


def _metin(ad: str, deger: Any, uzunluk: int = MAX_METIN) -> str:
    if deger is None:
        return ""
    if not isinstance(deger, str):
        raise TestVerisiGecersiz(f"{ad} metin olmalı")
    if len(deger) > uzunluk:
        raise TestVerisiGecersiz(f"{ad} en çok {uzunluk} karakter olabilir")
    return deger.strip()


def _deger_dogrula(deger: Any) -> str:
    if not isinstance(deger, str) or not deger.strip():
        raise TestVerisiGecersiz("Değer boş olamaz")
    if len(deger) > MAX_DEGER:
        raise TestVerisiGecersiz(f"Değer en çok {MAX_DEGER} karakter olabilir")
    if atif.atiflar(deger) or "{veri:" in deger:
        raise TestVerisiGecersiz("Değer başka bir test verisi atfı içeremez")
    return deger


def _sir_dogrula(sir_adi: Any) -> str:
    if not isinstance(sir_adi, str) or not SIR_ADI_RE.match(sir_adi):
        raise TestVerisiGecersiz(
            f"Sır adı '{SIR_ONEKI}' önekli büyük harf ortam değişkeni adı olmalı "
            f"(ör. {DEMO_PAROLA_SIRRI})"
        )
    return sir_adi


def _surum_yaz(session: Session, k: TestVerisi, islem: str, aktor: str) -> None:
    session.add(
        TestVerisiSurum(
            test_verisi_id=k.id,
            surum=k.surum,
            islem=islem,
            deger=None if k.gizli else k.deger,
            gizli=k.gizli,
            sir_adi=k.sir_adi,
            degistiren=aktor,
        )
    )


def _denetim(session: Session, aktor: str, eylem: str, k: TestVerisi, **ek: Any) -> None:
    ozet: dict[str, Any] = {"anahtar": k.anahtar, "surum": k.surum, "gizli": k.gizli}
    if not k.gizli:
        ozet["deger"] = k.deger
    else:
        ozet["sir_adi"] = k.sir_adi
    ozet.update(ek)
    audit_on_commit(session, aktor, eylem, f"test_verisi:{k.id}", ozet)


def olustur(session: Session, girdi: Mapping[str, Any], aktor: str) -> TestVerisi:
    """Yeni kayıt. Etkin anahtar varsa 409; silinmiş anahtar yeniden etkinleşir (yeni sürüm)."""
    anahtar = girdi.get("anahtar")
    if not isinstance(anahtar, str) or not atif.ANAHTAR_RE.match(anahtar):
        raise TestVerisiGecersiz(
            "Anahtar küçük harf, rakam ve '_' parçalarından oluşmalı, '.' ile ayrılmalı "
            "(ör. bayi.bayi1.kullanici_adi)"
        )
    gizli = bool(girdi.get("gizli"))
    if gizli:
        if girdi.get("deger") not in (None, ""):
            raise TestVerisiGecersiz(
                "Gizli kayıtta değer kataloğa yazılmaz; ortam sırrının adını (sir_adi) verin"
            )
        deger, sir_adi = None, _sir_dogrula(girdi.get("sir_adi"))
    else:
        if girdi.get("sir_adi"):
            raise TestVerisiGecersiz("Sır adı yalnız gizli kayıtta verilir")
        deger, sir_adi = _deger_dogrula(girdi.get("deger")), None
    grup = _metin("Grup", girdi.get("grup"), 100) or anahtar.split(".")[0]
    aciklama = _metin("Açıklama", girdi.get("aciklama"))

    var = session.scalars(
        select(TestVerisi).where(TestVerisi.anahtar == anahtar).with_for_update()
    ).first()
    if var is not None and not var.silindi:
        raise TestVerisiCakisma(f"Bu anahtar katalogda zaten var: {anahtar}")
    if var is not None:
        k = var
        k.silindi, k.surum = False, k.surum + 1
        k.deger, k.gizli, k.sir_adi, k.grup, k.aciklama = deger, gizli, sir_adi, grup, aciklama
        k.guncelleyen = aktor
    else:
        k = TestVerisi(
            anahtar=anahtar,
            grup=grup,
            aciklama=aciklama,
            deger=deger,
            gizli=gizli,
            sir_adi=sir_adi,
            surum=1,
            guncelleyen=aktor,
        )
        session.add(k)
    session.flush()
    _surum_yaz(session, k, "olustur", aktor)
    _denetim(session, aktor, "testveri.olustur", k)
    session.flush()
    session.refresh(k)
    return k


def _kilitli(session: Session, kid: uuid.UUID, beklenen_surum: int | None) -> TestVerisi:
    k = session.get(TestVerisi, kid, with_for_update=True)
    if k is None or k.silindi:
        raise TestVerisiYok("Test verisi bulunamadı")
    if beklenen_surum is None:
        raise TestVerisiGecersiz("beklenen_surum zorunlu")
    if k.surum != beklenen_surum:
        raise TestVerisiCakisma(
            f"Kayıt siz görüntüledikten sonra değişmiş (güncel sürüm {k.surum}); yeniden yükleyin"
        )
    return k


def guncelle(
    session: Session,
    kid: uuid.UUID,
    girdi: Mapping[str, Any],
    beklenen_surum: int | None,
    aktor: str,
) -> TestVerisi:
    """Değer / açıklama / grup / sır adı günceller; sürüm +1. Onay düşmez (K10)."""
    k = _kilitli(session, kid, beklenen_surum)
    onceki = None if k.gizli else k.deger
    degisti = False
    if "deger" in girdi and girdi["deger"] is not None:
        if k.gizli:
            raise TestVerisiGecersiz("Gizli kaydın değeri kataloğa yazılmaz (ortam sırrı)")
        yeni = _deger_dogrula(girdi["deger"])
        degisti |= yeni != k.deger
        k.deger = yeni
    if "sir_adi" in girdi and girdi["sir_adi"] is not None:
        if not k.gizli:
            raise TestVerisiGecersiz("Sır adı yalnız gizli kayıtta verilir")
        yeni = _sir_dogrula(girdi["sir_adi"])
        degisti |= yeni != k.sir_adi
        k.sir_adi = yeni
    if "grup" in girdi and girdi["grup"] is not None:
        yeni = _metin("Grup", girdi["grup"], 100) or k.grup
        degisti |= yeni != k.grup
        k.grup = yeni
    if "aciklama" in girdi and girdi["aciklama"] is not None:
        yeni = _metin("Açıklama", girdi["aciklama"])
        degisti |= yeni != k.aciklama
        k.aciklama = yeni
    if not degisti:
        raise TestVerisiGecersiz("Değişiklik yok")
    k.surum += 1
    k.guncelleyen = aktor
    session.flush()
    _surum_yaz(session, k, "guncelle", aktor)
    etkilenen = kullanim(session).get(k.anahtar, [])
    ek: dict[str, Any] = {"etkilenen_case": [c["case_id"] for c in etkilenen][:50]}
    if not k.gizli:
        ek["onceki_deger"] = onceki
    _denetim(session, aktor, "testveri.guncelle", k, **ek)
    session.flush()
    session.refresh(k)
    return k


def sil(session: Session, kid: uuid.UUID, beklenen_surum: int | None, aktor: str) -> TestVerisi:
    """Yumuşak silme; atıf yapan etkin case varsa 409 + liste."""
    k = _kilitli(session, kid, beklenen_surum)
    kullanan = kullanim(session).get(k.anahtar, [])
    if kullanan:
        raise TestVerisiKullanimda(
            f"{len(kullanan)} etkin case bu test verisine atıf yapıyor; önce case'leri düzeltin",
            kullanan,
        )
    k.silindi = True
    k.surum += 1
    k.guncelleyen = aktor
    session.flush()
    _surum_yaz(session, k, "sil", aktor)
    _denetim(session, aktor, "testveri.sil", k)
    session.flush()
    return k


# --------------------------------------------------------------------------- tohumlama


def tohum_kayitlari(sorgu: Callable[[str], Sequence[Sequence[Any]]] | None) -> list[dict]:
    """`testdata.block()`'un okuduğu verilerden katalog satırları (sırası = blok sırası)."""
    from tp_core.features.cases import testdata

    veri: dict[str, Sequence[Sequence[Any]]] = {}
    if sorgu is not None:
        try:
            veri = {ad: sorgu(sql) for ad, sql in testdata.SORGULAR.items()}
        except Exception as exc:  # demo DB yoksa yalnız sabitler
            log.info("Test verisi tohumu: demo DB okunamadı (%s); yalnız sabitler", exc)
            veri = {}
    satirlar: list[dict[str, Any]] = []

    def ekle(anahtar: str, deger: str, grup: str, aciklama: str) -> None:
        satirlar.append({"anahtar": anahtar, "deger": deger, "grup": grup, "aciklama": aciklama})

    for kullanici, ad, limit in veri.get("bayi", ()):
        b = f"bayi.{slug(kullanici)}"
        ekle(f"{b}.kullanici_adi", str(kullanici), "bayi", "Test kullanıcısının kullanıcı adı")
        ekle(f"{b}.ad", str(ad), "bayi", "Bayi adı")
        ekle(f"{b}.kredi_limiti", testdata.tl(limit), "bayi", "Kredi limiti")
    for kod, ad, fiyat in veri.get("urun", ()):
        u = f"urun.{slug(kod)}"
        ekle(f"{u}.kod", str(kod), "urun", "Ürün kodu")
        ekle(f"{u}.ad", str(ad), "urun", "Ürün adı")
        ekle(f"{u}.fiyat", testdata.tl(fiyat), "urun", "Birim fiyat")
    for kod, ad, urun in veri.get("kampanya", ()):
        k = f"kampanya.{slug(kod)}"
        ekle(f"{k}.kod", str(kod), "kampanya", f"Kampanya kodu; ürün: {urun}")
        ekle(f"{k}.ad", str(ad), "kampanya", "Kampanya adı")
    for anahtar, deger in veri.get("ayar", ()):
        ekle(f"ayar.{slug(anahtar)}", str(deger), "ayar", f"Uygulama ayarı ({anahtar})")
    satirlar.append(
        {
            "anahtar": DEMO_PAROLA_ANAHTARI,
            "deger": None,
            "gizli": True,
            "sir_adi": DEMO_PAROLA_SIRRI,
            "grup": "ortak",
            "aciklama": "Test kullanıcılarının ortak demo parolası (ortam sırrı)",
        }
    )
    for etiket in testdata.UI_ETIKETLERI:
        ekle(f"etiket.{slug(etiket)}", etiket, "etiket", "Arayüz etiketi")
    return satirlar


def tohumla(session: Session, sorgu: Any = ...) -> int:
    """Katalogda olmayan tohum anahtarlarını ekler; eklenen sayısı. İdempotent, eşzamanlı güvenli.

    `sorgu` verilmezse `testdata`'nın sorgu fabrikası (`DEMOAPP_RO_DATABASE_URL`) kullanılır;
    demo DB okunamazsa sessizce yalnız sabitler (parola sırrı + arayüz etiketleri) eklenir.
    Var olan ya da silinmiş anahtara dokunulmaz (analistin değişikliği korunur).
    """
    from tp_core.features.cases import testdata

    if sorgu is ...:
        try:
            sorgu = testdata._sorgu_fabrikasi()
        except Exception as exc:
            log.info("Test verisi tohumu: demo DB kaynağı açılamadı (%s)", exc)
            sorgu = None
    satirlar = tohum_kayitlari(sorgu)
    taban = datetime.now(UTC)
    eklenen: list[str] = []
    for i, satir in enumerate(satirlar):
        sonuc = session.execute(
            insert(TestVerisi)
            .values(
                id=uuid.uuid4(),
                anahtar=satir["anahtar"],
                grup=satir["grup"],
                aciklama=satir["aciklama"],
                deger=satir.get("deger"),
                gizli=bool(satir.get("gizli")),
                sir_adi=satir.get("sir_adi"),
                surum=1,
                silindi=False,
                guncelleyen=TOHUM_AKTOR,
                # Sıra korunur: blok katalogdan aynı sırayla kurulur.
                olusturma=taban + timedelta(microseconds=i),
                guncelleme=taban,
            )
            .on_conflict_do_nothing(index_elements=["anahtar"])
            .returning(TestVerisi.id)
        ).first()
        if sonuc is None:
            continue
        session.add(
            TestVerisiSurum(
                test_verisi_id=sonuc[0],
                surum=1,
                islem="olustur",
                deger=satir.get("deger"),
                gizli=bool(satir.get("gizli")),
                sir_adi=satir.get("sir_adi"),
                degistiren=TOHUM_AKTOR,
            )
        )
        eklenen.append(satir["anahtar"])
    if eklenen:
        session.flush()
        audit_on_commit(session, TOHUM_AKTOR, "testveri.tohumla", None, {"eklenen": len(eklenen)})
    return len(eklenen)


# --------------------------------------------------------------------------- model girdisi bloğu

_KAMPANYA_URUN = re.compile(r"ürün: (.+)$")


def blok_metni(session: Session) -> str | None:
    """`testdata.build_text` biçiminde blok metni, katalogdan. Katalog boşsa / eksikse None.

    `testdata.block()` bunu DB tabanlı metinle karşılaştırır; aynı değilse eski yol kullanılır
    (model girdisi ve replay anahtarları değişmez).
    """
    from tp_core.features.cases import testdata

    kayitlar = etkin_kayitlar(session)
    if not kayitlar:
        return None
    bayiler: dict[str, dict[str, str]] = {}
    urunler: dict[str, dict[str, str]] = {}
    kampanyalar: dict[str, dict[str, str]] = {}
    ayarlar: list[tuple[str, str]] = []
    etiketler: list[str] = []
    parola: str | None = None
    for k in kayitlar:
        parca = k.anahtar.split(".")
        if k.anahtar == DEMO_PAROLA_ANAHTARI:
            parola = sir_degeri(k.sir_adi) if k.gizli else k.deger
            continue
        if k.gizli or k.deger is None:
            continue
        if parca[0] == "bayi" and len(parca) == 3:
            bayiler.setdefault(parca[1], {})[parca[2]] = k.deger
        elif parca[0] == "urun" and len(parca) == 3:
            urunler.setdefault(parca[1], {})[parca[2]] = k.deger
        elif parca[0] == "kampanya" and len(parca) == 3:
            kampanyalar.setdefault(parca[1], {})[parca[2]] = k.deger
            if parca[2] == "kod" and (m := _KAMPANYA_URUN.search(k.aciklama or "")):
                kampanyalar[parca[1]]["urun"] = m.group(1)
        elif parca[0] == "ayar" and len(parca) == 2:
            ayarlar.append((parca[1], k.deger))
        elif parca[0] == "etiket" and len(parca) == 2:
            etiketler.append(k.deger)
    if parola is None or not bayiler or not urunler:
        return None
    try:
        satirlar = ["Test verisi (demo uygulaması):", "Test kullanıcıları (bayi):"]
        for b in bayiler.values():
            satirlar.append(
                f'- {b["kullanici_adi"]} / {parola} — bayi adı "{b["ad"]}", '
                f"kredi limiti {b['kredi_limiti']}"
            )
        satirlar.append("Ürünler (kod · ad · birim fiyat):")
        for u in urunler.values():
            satirlar.append(f'- {u["kod"]} · "{u["ad"]}" · {u["fiyat"]}')
        satirlar.append("Aktif kampanyalar:")
        satirlar += [
            f'- "{k["ad"]}" ({k["kod"]}) — ürün {k["urun"]}' for k in kampanyalar.values()
        ] or ["- yok"]
        satirlar.append("Uygulama ayarları:")
        for anahtar, deger in ayarlar:
            ek = f" ({testdata.tl(deger)})" if testdata._tutar_mi(anahtar) else ""
            satirlar.append(f"- {anahtar} = {deger}{ek}")
    except KeyError:
        return None
    satirlar.append("Arayüz etiketleri: " + ", ".join(f'"{e}"' for e in etiketler))
    satirlar.append("Tutar biçimi: 1.250,00 TL (tr-TR, iki ondalık).")
    return "\n".join(satirlar)
