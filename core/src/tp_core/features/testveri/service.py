"""Merkezi test verisi kataloğu: okuma, çözüm, CRUD, tohumlama (specs/013-sprint-otomasyonu §3.3).

- `katalog`: gizli olmayan etkin kayıtlar (anahtar → değer).
- `eslem_katalogu`: eşleme kataloğu = `katalog` + değeri ortamda tanımlı gizli kayıtlar; böylece
  parola case metnine düz yazılmaz, `{veri:ortak.demo_parola}` olur. K18: yalnız bayi / ürün /
  kampanya / ortak grupları (`atif.case_esle` ayrıca tutar kuralını uygular).
- `cozum_degerleri`: kod üretimi / koşu için (değerler, sürümler); gizli değer
  `os.environ[sir_adi]`'den, sır tanımsızsa o anahtar çözülemez.
- `veri_izi` (013 §9/§10): `{anahtar: "h1:" + HMAC-SHA256(sunucu anahtarı, değer)[:16]}`.
  Anahtar `TP_SESSION_SECRET`'tan türetilir (alan ayrımlı). Oturum sırrı yoksa gizli olmayan
  değerler `h0:` (anahtarsız HMAC; değer zaten katalogda açık) ile özetlenir, gizli değer hiç
  özetlenmez (izde yer almaz). Eski kayıtlardaki düz `sha256[:12]` özetler yalnız içeride
  karşılaştırılır, hiçbir API'de dönmez (`api_veri_izi`). "Veri değişti" yalnız değer (ya da
  gizlide sır değeri) değişince doğar, açıklama/grup değişimi saymaz.
- K19: `gizli_degerler` bilinen gizli değerler: ortamda tanımlı sır değerleri + `ortak.demo_parola`
  gizli kaydı etkinse DB bloğunun sabit demo parolası (`testdata.DEMO_PAROLA`; replay / sır
  tanımsız yolunda modele giden değer). `maskele*` kullanıcıya görünen içerikte bunları `•••` yapar.
  Eşlemede sabit demo parolası her zaman `ortak.demo_parola` atfına çevrilir (`takma_degerler`):
  sır tanımsızsa kod üretimi `test_verisi` engeliyle durur, PR'a düz parola girmez. Gizli bir
  değerle aynı değeri taşıyan gizli olmayan kayıt reddedilir (genel metin + denetim).
- CRUD: her değişiklik `test_verisi_surum` satırı + denetim (`testveri.olustur|guncelle|sil`).
  İyimser kilit `beklenen_surum` (409); silme yumuşaktır ve atıf yapan etkin case varsa 409.
- `tohumla`: demo DB (`cases/testdata.py` sorguları) + sabitlerden; anahtar başına idempotent
  (var olan ya da silinmiş anahtara dokunmaz).

Gizli kaydın değeri katalogda yoktur, API'den dönmez, denetime yazılmaz. `sir_adi` yalnız
`TP_TESTVERI_` önekli olabilir: aksi hâlde katalog düzenleyen biri herhangi bir süreç sırrını
(model anahtarı vb.) kod üretimine çözdürebilirdi.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Text, cast, select
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
    """Eşleme kataloğu: `katalog` + değeri ortamda tanımlı gizli kayıtlar. Tüm gruplar döner:
    tekillik tüm katalogla sınanır, K18 grup süzgecini `atif.case_esle` uygular (QA #11)."""
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


def gizli_anahtarlar(session: Session) -> set[str]:
    return set(
        session.scalars(
            select(TestVerisi.anahtar).where(
                TestVerisi.silindi.is_(False), TestVerisi.gizli.is_(True)
            )
        ).all()
    )


def kilitli_anahtarlar(session: Session, istenen: Iterable[str]) -> set[str]:
    """Mimar #5: atıf yazılacak anahtarların etkin satırları `FOR SHARE` ile okunur; `sil`
    (`FOR UPDATE`) ile sıralanır. Silme önce commit olduysa satır `silindi` görünür ve dönmez;
    sonra gelirse `sil`, case'ler commit olunca kullanımı görür (409)."""
    liste = sorted(set(istenen))
    if not liste:
        return set()
    return set(
        session.scalars(
            select(TestVerisi.anahtar)
            .where(TestVerisi.anahtar.in_(liste), TestVerisi.silindi.is_(False))
            .order_by(TestVerisi.anahtar)
            .with_for_update(read=True)
        ).all()
    )


def anahtarlar(session: Session) -> set[str]:
    return set(
        session.scalars(select(TestVerisi.anahtar).where(TestVerisi.silindi.is_(False))).all()
    )


def _sabit_demo_parolasi() -> str:
    from tp_core.features.cases.testdata import DEMO_PAROLA

    return DEMO_PAROLA


def takma_degerler(session: Session) -> dict[str, str]:
    """Katalog dışı bilinen gizli değer → anahtar: `ortak.demo_parola` gizli kaydı etkinse DB
    bloğunun sabit demo parolası (replay / katalog kurulamayınca modele giden değer)."""
    var = session.scalars(
        select(TestVerisi.id).where(
            TestVerisi.anahtar == DEMO_PAROLA_ANAHTARI,
            TestVerisi.silindi.is_(False),
            TestVerisi.gizli.is_(True),
        )
    ).first()
    return {_sabit_demo_parolasi(): DEMO_PAROLA_ANAHTARI} if var is not None else {}


def gizli_degerler(session: Session) -> list[str]:
    """K19: bilinen gizli değerler (etkin gizli kayıtların ortamda tanımlı sır değerleri + sabit
    demo parolası takması; bkz. `takma_degerler`)."""
    out: list[str] = []
    for sir_adi in session.scalars(
        select(TestVerisi.sir_adi).where(TestVerisi.silindi.is_(False), TestVerisi.gizli.is_(True))
    ):
        deger = sir_degeri(sir_adi)
        if deger is not None and deger not in out:
            out.append(deger)
    for deger in takma_degerler(session):
        if deger not in out:
            out.append(deger)
    return out


def gizli_ortam_adlari(session: Session) -> dict[str, str]:
    """K19 kod üretimi: gizli değer → sır (ortam değişkeni) adı (ortamda tanımlı olanlar)."""
    out: dict[str, str] = {}
    for sir_adi in session.scalars(
        select(TestVerisi.sir_adi)
        .where(TestVerisi.silindi.is_(False), TestVerisi.gizli.is_(True))
        .order_by(TestVerisi.anahtar)
    ):
        deger = sir_degeri(sir_adi)
        if deger is not None and sir_adi:
            out.setdefault(deger, sir_adi)
    return out


def maskele(session: Session, obj: Any, gizliler: Iterable[str] | None = None) -> Any:
    """Kullanıcıya görünen içerikte bilinen gizli değerleri `•••` yapar (dict/list/str)."""
    return atif.maskele_obje(obj, gizli_degerler(session) if gizliler is None else gizliler)


OZET_ANAHTARLI = "h1:"
OZET_ANAHTARSIZ = "h0:"
_OZET_ALANI = b"tp-testveri-deger-ozeti:"


def _ozet_anahtari() -> bytes | None:
    """`veri_izi` HMAC anahtarı: `TP_SESSION_SECRET`'tan alan ayrımlı türetilir; yoksa None."""
    sir = os.environ.get("TP_SESSION_SECRET") or ""
    if not sir:
        try:
            from tp_core.config import get_settings

            ayar = get_settings().session_secret
            sir = ayar.get_secret_value() if ayar is not None else ""
        except Exception:
            sir = ""
    if not sir:
        return None
    return hashlib.sha256(_OZET_ALANI + sir.encode("utf-8")).digest()


def deger_ozeti(deger: str, *, gizli: bool = False) -> str | None:
    """`veri_izi` değeri: tuzlu (sunucu anahtarlı) HMAC özeti. Anahtar yoksa gizli olmayan değer
    `h0:` (anahtarsız; değer zaten açık), gizli değer None (özetlenmez: sözlük saldırısı yok)."""
    anahtar = _ozet_anahtari()
    if anahtar is None:
        if gizli:
            return None
        anahtar, onek = _OZET_ALANI, OZET_ANAHTARSIZ
    else:
        onek = OZET_ANAHTARLI
    return onek + hmac.new(anahtar, deger.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def _eski_ozet(deger: str) -> str:
    """013 §9 ilk biçimi (düz sha256[:12]); yalnız eski izleri içeride karşılaştırmak için."""
    return hashlib.sha256(deger.encode("utf-8")).hexdigest()[:12]


def yeni_bicim_mi(ozet: Any) -> bool:
    return isinstance(ozet, str) and ozet.startswith((OZET_ANAHTARLI, OZET_ANAHTARSIZ))


def veri_izi_hesapla(
    degerler: Mapping[str, str],
    anahtarlar: Iterable[str],
    gizliler: Iterable[str] = (),
) -> dict[str, str]:
    """`{anahtar: değer özeti}`; `degerler` çözülmüş değerlerdir (gizli için ortam değeri),
    `gizliler` gizli kayıt anahtarları."""
    gizli = set(gizliler)
    out: dict[str, str] = {}
    for a in dict.fromkeys(anahtarlar):
        if a in degerler and (o := deger_ozeti(degerler[a], gizli=a in gizli)) is not None:
            out[a] = o
    return out


def api_veri_izi(veri_izi: Mapping[str, Any] | None) -> dict[str, str | None]:
    """API'ye giden `veri_izi`: yalnız tuzlu özetler; eski düz sha256 özetler `null` (§10)."""
    return {a: (o if yeni_bicim_mi(o) else None) for a, o in (veri_izi or {}).items()}


def guncel_ozetler(session: Session, istenen: Iterable[str]) -> dict[str, tuple[str | None, str]]:
    """Verilen anahtarların güncel (tuzlu özet, eski düz özet) çifti — iç karşılaştırma için;
    API'ye dönmez. Silinmiş/olmayan ya da sırrı tanımsız gizli anahtar sözlükte yer almaz. Tek
    sorgu (script listesi tüm anahtarları birlikte verir)."""
    liste = list(dict.fromkeys(istenen))
    if not liste:
        return {}
    out: dict[str, tuple[str | None, str]] = {}
    for k in session.scalars(
        select(TestVerisi).where(TestVerisi.anahtar.in_(liste), TestVerisi.silindi.is_(False))
    ):
        deger = sir_degeri(k.sir_adi) if k.gizli else k.deger
        if deger is not None:
            out[k.anahtar] = (deger_ozeti(deger, gizli=k.gizli), _eski_ozet(deger))
    return out


def degisen_anahtarlar(
    session: Session,
    veri_izi: Mapping[str, Any] | None,
    guncel: Mapping[str, tuple[str | None, str]] | None = None,
) -> list[str]:
    """Script'in kullandığı değerlerden değişen / silinen / çözülemeyenler (K10 uyarısı).

    `guncel` verilirse (liste: `guncel_ozetler` tek sorguyla) yeniden sorgulanmaz. Tuzlu özet
    tuzlu güncel özetle, eski düz özet (013 §9 ilk biçimi) güncel değerin düz özetiyle içeride
    karşılaştırılır. Sürüm biçimli (`{anahtar: sürüm}`) iz değişmiş sayılmaz.
    """
    if not veri_izi:
        return []
    if guncel is None:
        guncel = guncel_ozetler(session, veri_izi)
    out: list[str] = []
    for a, ozet in veri_izi.items():
        if not isinstance(ozet, str):
            continue
        g = guncel.get(a)
        if g is None or ozet != (g[0] if yeni_bicim_mi(ozet) else g[1]):
            out.append(a)
    return out


def izler_ayni(session: Session, eski: Mapping[str, Any] | None, yeni: Mapping[str, Any]) -> bool:
    """Aynı hash'li PR'ın atlama kararı: aynı anahtarlar ve hiçbirinin değeri değişmemiş (eski
    biçimli iz de değer karşılaştırmasıyla yorumlanır)."""
    eski = eski or {}
    return set(eski) == set(yeni) and not degisen_anahtarlar(session, eski)


def case_esle(session: Session, icerik: Mapping[str, Any]) -> dict[str, Any]:
    """Case üretimi / IDE kanalı: değerleri atfa çevirir. Katalog boşsa içerik aynen döner."""
    kat, takma = eslem_katalogu(session), takma_degerler(session)
    return atif.case_esle(icerik, kat, takma) if kat or takma else dict(icerik)


def case_coz(session: Session, icerik: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Kod üretimi / koşu: atıfları değere çevirir; (çözülmüş içerik, `veri_izi` değer özetleri).

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
    return atif.case_coz(icerik, degerler), veri_izi_hesapla(
        degerler, istenen, gizli_anahtarlar(session)
    )


def case_coz_gevsek(session: Session, icerik: Mapping[str, Any]) -> dict[str, Any]:
    """Model girdisi (bug taslağı vb.) için: çözülebilen atıfları çözer, kalanları bırakır."""
    if not atif.case_atiflari(icerik):
        return dict(icerik)
    degerler, _ = cozum_degerleri(session)
    return atif.case_coz(icerik, degerler, bilinmeyen="birak")


def yayin_icin_coz(session: Session, icerik: Mapping[str, Any]) -> dict[str, Any]:
    """Jira/Xray yayını (Y4): gizli olmayan atıflar değere çözülür, gizliler atıf kalır.

    K19: ayrıca tüm alanlarda (başlık, etiketler dahil) bilinen gizli değerlerin düz geçişleri
    `•••` yapılır (analistin elle yazdığı ya da modelin başlığa koyduğu parola).
    """
    out = (
        atif.case_coz(icerik, katalog(session), bilinmeyen="birak")
        if atif.case_atiflari(icerik)
        else dict(icerik)
    )
    return maskele(session, out)


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
    """Script'in kullandığı değerlerden biri değişti / silindi mi (K10 uyarısı)?"""
    return bool(degisen_anahtarlar(session, veri_izi))


def _like_kacis(metin: str) -> str:
    return metin.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def kullanim(session: Session, anahtar: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Anahtar → atıf yapan etkin case'ler (`{case_id, case_ref, requirement_id, baslik, durum}`).

    `anahtar` verilirse SQL ön süzgeci (`icerik::text LIKE '%{veri:<anahtar>}%'`) yalnız o
    anahtara atıf yapan satırları getirir; kesin kontrol yine atıf ayrıştırmasıyla yapılır.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    gizli = gizli_degerler(session)
    sorgu = (
        select(
            TestCase.id,
            TestCase.icerik,
            TestCase.durum,
            TestCase.sira_no,
            TestCase.requirement_id,
            Requirement.jira_key,
        )
        .join(Requirement, Requirement.id == TestCase.requirement_id)
        .where(TestCase.durum.in_(ETKIN_CASE))
        .order_by(TestCase.olusturma)
    )
    if anahtar is not None:
        desen = "%" + _like_kacis(atif.atif(anahtar)) + "%"
        sorgu = sorgu.where(cast(TestCase.icerik, Text).like(desen, escape="\\"))
    for cid, icerik, durum, sira, rid, jira_key in session.execute(sorgu).all():
        for a in atif.case_atiflari(icerik or {}):
            if anahtar is not None and a != anahtar:
                continue
            out.setdefault(a, []).append(
                {
                    "case_id": str(cid),
                    "case_ref": f"{jira_key or 'SERBEST'}-C{sira}",
                    "requirement_id": str(rid),
                    "baslik": atif.maskele(str((icerik or {}).get("title") or "")[:200], gizli),
                    "durum": durum,
                }
            )
    return out


def anahtar_kullanimi(session: Session, anahtar: str) -> list[dict[str, Any]]:
    return kullanim(session, anahtar).get(anahtar, [])


# --------------------------------------------------------------------------- serileştirme


def serialize(k: TestVerisi, kullanim_sayisi: int | None = None) -> dict[str, Any]:
    if kullanim_sayisi is None:  # olustur/guncelle'nin saydığı (API ikinci kez saymaz)
        kullanim_sayisi = int(getattr(k, "_kullanim_sayisi", 0) or 0)
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


GIZLI_CAKISMA_METNI = (
    "Bu değer kabul edilmedi; parola ve benzeri değerleri gizli kayıt (ortam sırrı) olarak "
    "tanımlayın"
)


def _gizli_cakisma_denetimi(aktor: str, anahtar: str | None) -> None:
    """Reddi ayrı işlemde denetime yazar (istek işlemi geri alınır); değer yazılmaz."""
    try:
        from tp_core.audit import append_audit
        from tp_core.db import get_engine

        with get_engine().begin() as conn:
            append_audit(conn, aktor, "testveri.gizli_cakisma_reddi", None, {"anahtar": anahtar})
    except Exception as exc:  # denetim yazılamazsa red yine döner
        log.warning("Test verisi gizli çakışma reddi denetime yazılamadı: %s", type(exc).__name__)


def _gizliyle_ayni_degil(
    session: Session, deger: str, aktor: str = "", anahtar: str | None = None
) -> None:
    """K19: bilinen bir gizli değerle aynı değeri taşıyan gizli olmayan kayıt açılamaz (değer
    katalogda ve API'de düz görünür, maskeleme ile eşleme belirsizleşirdi). Güvenlik #9: metin
    genel (hangi kayıtla çakıştığını söylemez); her red denetime yazılır (aktör + anahtar)."""
    if deger in gizli_degerler(session):
        _gizli_cakisma_denetimi(aktor or "bilinmiyor", anahtar)
        raise TestVerisiGecersiz(GIZLI_CAKISMA_METNI)


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
        _gizliyle_ayni_degil(session, deger, aktor, anahtar)
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
    k._kullanim_sayisi = len(anahtar_kullanimi(session, k.anahtar))  # type: ignore[attr-defined]
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
    """Değer / açıklama / grup / sır adı günceller; sürüm +1 (iyimser kilit). Onay düşmez (K10).

    Açıklama boş metin ya da açıkça `null` ile temizlenir (`girdi`de anahtar varsa). Grup boş
    metin ya da açıkça `null` ile varsayılana (anahtarın ilk parçası) döner.
    """
    k = _kilitli(session, kid, beklenen_surum)
    onceki = None if k.gizli else k.deger
    degisti = False
    if "deger" in girdi and girdi["deger"] is not None:
        if k.gizli:
            raise TestVerisiGecersiz("Gizli kaydın değeri kataloğa yazılmaz (ortam sırrı)")
        yeni = _deger_dogrula(girdi["deger"])
        if yeni != k.deger:
            _gizliyle_ayni_degil(session, yeni, aktor, k.anahtar)
        degisti |= yeni != k.deger
        k.deger = yeni
    if "sir_adi" in girdi and girdi["sir_adi"] is not None:
        if not k.gizli:
            raise TestVerisiGecersiz("Sır adı yalnız gizli kayıtta verilir")
        yeni = _sir_dogrula(girdi["sir_adi"])
        degisti |= yeni != k.sir_adi
        k.sir_adi = yeni
    if "grup" in girdi:
        # Frontend #4: boş metin ya da açık `null` grubu temizler → anahtarın ilk parçası.
        yeni = _metin("Grup", girdi["grup"], 100) or k.anahtar.split(".")[0]
        degisti |= yeni != k.grup
        k.grup = yeni
    if "aciklama" in girdi:
        yeni = _metin("Açıklama", girdi["aciklama"])
        degisti |= yeni != k.aciklama
        k.aciklama = yeni
    if not degisti:
        raise TestVerisiGecersiz("Değişiklik yok")
    k.surum += 1
    k.guncelleyen = aktor
    session.flush()
    _surum_yaz(session, k, "guncelle", aktor)
    etkilenen = anahtar_kullanimi(session, k.anahtar)
    ek: dict[str, Any] = {"etkilenen_case": [c["case_id"] for c in etkilenen][:50]}
    if not k.gizli:
        ek["onceki_deger"] = onceki
    _denetim(session, aktor, "testveri.guncelle", k, **ek)
    session.flush()
    session.refresh(k)
    k._kullanim_sayisi = len(etkilenen)  # type: ignore[attr-defined]
    return k


def sil(session: Session, kid: uuid.UUID, beklenen_surum: int | None, aktor: str) -> TestVerisi:
    """Yumuşak silme; atıf yapan etkin case varsa 409 + liste."""
    k = _kilitli(session, kid, beklenen_surum)
    kullanan = anahtar_kullanimi(session, k.anahtar)
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


_BAYI_ALANLARI = ("kullanici_adi", "ad", "kredi_limiti")
_URUN_ALANLARI = ("kod", "ad", "fiyat")
_KAMPANYA_ALANLARI = ("kod", "ad", "urun")


def blok_metni(session: Session, *, gizli_atif: bool = False) -> str | None:
    """`testdata.build_text` biçiminde blok metni, katalogdan (K17: live/record model girdisi).

    Katalog demo DB'yle aynıyken metin `build_text` ile birebir aynıdır (test sabitler). Analistin
    eklediği bayi / ürün / kampanya / ayar / etiket kayıtları ilgili bölüme aynı biçimde girer;
    alanları eksik varlıklar ve başka gruplardaki kayıtlar "Diğer test verileri" bölümünde
    (`- anahtar = değer`; yalnız böyle kayıt varsa) yer alır. Gizli kayıtlar (parola dışında)
    değer değil atıf olarak verilir (`{veri:anahtar}`): model case'e atfı yazar.
    Katalog boşsa, parola sırrı tanımsızsa ya da bayi/ürün yoksa None (çağıran DB bloğuna döner).

    `gizli_atif=True` (IDE/MCP kanalı, güvenlik #3): parola da değer yerine atıf
    (`{veri:ortak.demo_parola}`) olarak verilir; çözülmüş sır istemciye dönmez, sır tanımsız
    olsa da blok kurulur.
    """
    from tp_core.features.cases import testdata

    kayitlar = etkin_kayitlar(session)
    if not kayitlar:
        return None
    bayiler: dict[str, dict[str, str]] = {}
    urunler: dict[str, dict[str, str]] = {}
    kampanyalar: dict[str, dict[str, str]] = {}
    kaynak: dict[tuple[str, str], list[TestVerisi]] = {}
    ayarlar: list[tuple[str, str]] = []
    etiketler: list[str] = []
    diger: list[str] = []
    parola: str | None = None
    for k in kayitlar:
        parca = k.anahtar.split(".")
        if k.anahtar == DEMO_PAROLA_ANAHTARI:
            if gizli_atif and k.gizli:
                parola = atif.atif(k.anahtar)
            else:
                parola = sir_degeri(k.sir_adi) if k.gizli else k.deger
            continue
        if k.gizli or k.deger is None:
            diger.append(f"- {k.anahtar} = {atif.atif(k.anahtar)} (gizli)")
            continue
        grup = {"bayi": bayiler, "urun": urunler, "kampanya": kampanyalar}.get(parca[0])
        if grup is not None and len(parca) == 3:
            grup.setdefault(parca[1], {})[parca[2]] = k.deger
            kaynak.setdefault((parca[0], parca[1]), []).append(k)
            if (
                parca[0] == "kampanya"
                and parca[2] == "kod"
                and (m := _KAMPANYA_URUN.search(k.aciklama or ""))
            ):
                kampanyalar[parca[1]]["urun"] = m.group(1)
        elif parca[0] == "ayar" and len(parca) == 2:
            ayarlar.append((parca[1], k.deger))
        elif parca[0] == "etiket" and len(parca) == 2:
            etiketler.append(k.deger)
        else:
            diger.append(f"- {k.anahtar} = {k.deger}")

    def tam(tur: str, varliklar: dict[str, dict[str, str]], alanlar: tuple[str, ...]) -> list:
        out = []
        for ad, v in varliklar.items():
            if all(a in v for a in alanlar):
                out.append(v)
            else:  # eksik alanlı varlık: kayıtları düz liste olarak
                diger.extend(f"- {k.anahtar} = {k.deger}" for k in kaynak.get((tur, ad), []))
        return out

    bayi_listesi = tam("bayi", bayiler, _BAYI_ALANLARI)
    urun_listesi = tam("urun", urunler, _URUN_ALANLARI)
    kampanya_listesi = tam("kampanya", kampanyalar, _KAMPANYA_ALANLARI)
    if parola is None or not bayi_listesi or not urun_listesi:
        return None
    satirlar = ["Test verisi (demo uygulaması):", "Test kullanıcıları (bayi):"]
    for b in bayi_listesi:
        satirlar.append(
            f'- {b["kullanici_adi"]} / {parola} — bayi adı "{b["ad"]}", '
            f"kredi limiti {b['kredi_limiti']}"
        )
    satirlar.append("Ürünler (kod · ad · birim fiyat):")
    for u in urun_listesi:
        satirlar.append(f'- {u["kod"]} · "{u["ad"]}" · {u["fiyat"]}')
    satirlar.append("Aktif kampanyalar:")
    satirlar += [f'- "{k["ad"]}" ({k["kod"]}) — ürün {k["urun"]}' for k in kampanya_listesi] or [
        "- yok"
    ]
    satirlar.append("Uygulama ayarları:")
    for anahtar, deger in ayarlar:
        ek = f" ({testdata.tl(deger)})" if testdata._tutar_mi(anahtar) else ""
        satirlar.append(f"- {anahtar} = {deger}{ek}")
    if diger:
        satirlar.append("Diğer test verileri (anahtar = değer):")
        satirlar += diger
    satirlar.append("Arayüz etiketleri: " + ", ".join(f'"{e}"' for e in etiketler))
    satirlar.append("Tutar biçimi: 1.250,00 TL (tr-TR, iki ondalık).")
    return "\n".join(satirlar)
