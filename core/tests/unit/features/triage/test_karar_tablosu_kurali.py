"""012 §4.4: kural 4'ün karar tablosu inceltmesi (saf; DB yok).

Dört satır × Playwright / Java (`Bekle.dogrula`) / TestNG mesaj biçimi × tolerans; tablo değerleri
çelişince, eşleşme yokken, gerçekleşen karşılaştırılamazken ve kural 4 eşleşmezken davranış
bugünküyle aynıdır.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from tp_core.features.triage.rules import (
    BEKLENTI_ONERISI,
    Girdi,
    Karar,
    OracleKarsilastirma,
    karar_tablosu_karari,
    siniflandir,
)

CASE_ID = "11111111-1111-1111-1111-111111111111"
TABLO_ID = "22222222-2222-2222-2222-222222222222"
HASH = "c" * 64
ARIA = '- main:\n  - definition: "125,00 TL"'


def _o(case: Any, tablo: Any, tolerans: str = "0", **kw: Any) -> OracleKarsilastirma:
    return OracleKarsilastirma(
        case_degeri=case,
        tablo_degeri=tablo,
        column=kw.pop("column", "toplam"),
        alan=kw.pop("alan", "steps[2].expected"),
        tablo_id=kw.pop("tablo_id", TABLO_ID),
        tablo_ad=kw.pop("tablo_ad", "Kampanya toplamı"),
        tolerans=Decimal(tolerans),
        test_case_id=CASE_ID,
        icerik_hash=HASH,
    )


def _playwright(beklenen: str, gerceklesen: str, oracle: list[OracleKarsilastirma] | None) -> Girdi:
    return Girdi(
        test_adi="TPD-1 C3 › toplam",
        dosya="tests/generated/TPD-1-c3-abcd1234.spec.ts",
        hata_turu="assertion",
        mesaj="Error: expect(locator).toHaveText(expected) failed\n\n"
        f"Locator: getByTestId('cart-total')\nExpected: \"{beklenen}\"\n"
        f'Received: "{gerceklesen}"',
        beklenen=f'"{beklenen}"',
        gerceklesen=f'"{gerceklesen}"',
        matcher="toHaveText",
        locator="getByTestId('cart-total')",
        aria=ARIA,
        platform="web",
        oracle=oracle,
    )


def _java(beklenen: str, gerceklesen: str, oracle: list[OracleKarsilastirma] | None) -> Girdi:
    return Girdi(
        test_adi="SepetTesti.toplam",
        dosya="src/test/java/bayi/uretilen/SepetTesti.java",
        mesaj=f"java.lang.AssertionError: Sepet toplamı: beklenen <{beklenen}>, "
        f"görülen <{gerceklesen}> (1200 ms)",
        beklenen=beklenen,
        gerceklesen=gerceklesen,
        platform="android",
        oracle=oracle,
    )


def _testng(beklenen: str, gerceklesen: str, oracle: list[OracleKarsilastirma] | None) -> Girdi:
    return Girdi(
        test_adi="SepetTesti.toplam",
        dosya="src/test/java/bayi/uretilen/SepetTesti.java",
        mesaj=f"java.lang.AssertionError: expected [{beklenen}] but found [{gerceklesen}]",
        beklenen=beklenen,
        gerceklesen=gerceklesen,
        platform="windows",
        oracle=oracle,
    )


BICIMLER = {
    "playwright": (_playwright, lambda d: f"{d},00 TL"),
    "java": (_java, lambda d: f"{d},00 TL"),
    "testng": (_testng, lambda d: f"{d}.0"),
}


def _karar(g: Girdi) -> Karar:
    karar, ek, _neden = siniflandir(g)
    assert karar is not None and ek == []
    return karar


def _kodlar(k: Karar) -> list[str]:
    return [s["kod"] for s in k.sinyaller]


def _tablo_sinyali(k: Karar) -> dict[str, Any]:
    [s] = [s for s in k.sinyaller if str(s["kod"]).startswith("karar_tablosu_")]
    return s


@pytest.fixture(params=sorted(BICIMLER))
def bicim(request: pytest.FixtureRequest) -> Any:
    return BICIMLER[request.param]


# ----------------------------------------------------------------------------- dört satır


def test_satir1_beklenti_tabloda_uygulama_farkli_product_defect(bicim: Any) -> None:
    """Senaryo 9: test 150 bekler, uygulama 125, tablo 150."""
    yap, yaz = bicim
    k = _karar(yap(yaz(150), yaz(125), [_o("150.00", "150.00")]))
    assert (k.sinif, k.alt_tur, k.kural, k.oneri_turu) == (
        "product_defect",
        None,
        "karar_tablosu",
        "bug_draft",
    )
    assert "assertion_farki" in _kodlar(k) and "eleman_bulundu" in _kodlar(k)
    s = _tablo_sinyali(k)
    assert s["kod"] == "karar_tablosu_uyumlu"
    assert "Kampanya toplamı" in s["aciklama"]
    assert "test beklentisi 150" in s["aciklama"] and "gerçekleşen 125" in s["aciklama"]
    assert "tablo 150" in s["aciklama"]
    assert CASE_ID in s["kanit"] and HASH in s["kanit"] and TABLO_ID in s["kanit"]
    assert k.oneri is None and k.gerekce is None


def test_satir2_beklenti_farkli_uygulama_tabloda_test_maintenance_beklenti(bicim: Any) -> None:
    """Senaryo 10: test 125 bekler, uygulama 150, tablo 150 → case düzeltilmeli."""
    yap, yaz = bicim
    k = _karar(yap(yaz(125), yaz(150), [_o("125.00", "150.00")]))
    assert (k.sinif, k.alt_tur, k.kural) == ("test_maintenance", "beklenti", "karar_tablosu")
    assert k.oneri_turu == "none" and k.oneri is None
    assert k.gerekce == BEKLENTI_ONERISI
    assert k.oneri_yok_nedeni and BEKLENTI_ONERISI in k.oneri_yok_nedeni
    s = _tablo_sinyali(k)
    assert s["kod"] == "karar_tablosu_beklenti_farkli"
    assert "test beklentisi 125" in s["aciklama"] and "gerçekleşen 150" in s["aciklama"]


def test_satir3_ikisi_de_farkli_product_defect(bicim: Any) -> None:
    yap, yaz = bicim
    k = _karar(yap(yaz(125), yaz(100), [_o("125.00", "150.00")]))
    assert (k.sinif, k.alt_tur, k.kural, k.oneri_turu) == (
        "product_defect",
        None,
        "karar_tablosu",
        "bug_draft",
    )
    assert _tablo_sinyali(k)["kod"] == "karar_tablosu_ikisi_de_farkli"


def test_satir4_tablo_yok_bugunku_davranis(bicim: Any) -> None:
    yap, yaz = bicim
    for oracle in (None, []):
        k = _karar(yap(yaz(150), yaz(125), oracle))
        assert (k.sinif, k.kural) == ("product_defect", "product_defect")
        assert not any(str(c).startswith("karar_tablosu") for c in _kodlar(k))


# ----------------------------------------------------------------------------- tolerans


def test_tolerans_icindeki_gerceklesen_tabloya_esit_sayilir() -> None:
    oracle = [_o("125.00", "150.00", "0.01")]
    k = _karar(_playwright("125,00 TL", "150,01 TL", oracle))
    assert (k.sinif, k.alt_tur) == ("test_maintenance", "beklenti")
    # Tolerans yoksa 150,01 tablodan farklıdır: ikisi de farklı.
    k0 = _karar(_playwright("125,00 TL", "150,01 TL", [_o("125.00", "150.00")]))
    assert _tablo_sinyali(k0)["kod"] == "karar_tablosu_ikisi_de_farkli"


def test_tolerans_beklenen_case_eslesmesinde_de_kullanilir() -> None:
    # "149.995" Türkçe binlik yazımı sayılır (149995); ondalık virgülle yazılır.
    k = _karar(_playwright("149,995 TL", "125,00 TL", [_o("150.00", "150.00", "0.01")]))
    assert _tablo_sinyali(k)["kod"] == "karar_tablosu_uyumlu"


def test_ikisi_de_tolerans_icinde_tabloya_uyuyorsa_ek_sinyal_yok() -> None:
    k = _karar(_playwright("150,00 TL", "150,01 TL", [_o("150.00", "150.00", "0.05")]))
    assert k.kural == "product_defect"


# ----------------------------------------------------------------------------- değer biçimleri


def test_kayit_degerleri_sayi_ve_turkce_metin_olabilir() -> None:
    for case, tablo in ((150, Decimal("150")), ("150,00 TL", 150.0), (Decimal("150.00"), "150")):
        k = _karar(_java("150,00 TL", "125,00 TL", [_o(case, tablo)]))
        assert _tablo_sinyali(k)["kod"] == "karar_tablosu_uyumlu", (case, tablo)


def test_binlik_yazim_ekranda_ve_kayitta_dogru_okunur() -> None:
    # Ekran "1.250,00 TL" = 1250; kayıt düz ondalık "1250.00".
    k = _karar(_playwright("1.250,00 TL", "1.000,00 TL", [_o("1250.00", "1250.00")]))
    assert _tablo_sinyali(k)["kod"] == "karar_tablosu_uyumlu"


def test_metin_ve_mantiksal_tablo_degerleri() -> None:
    k = _karar(_playwright("Ücretsiz", "Ücretli", [_o("Ücretsiz", "Ücretsiz")]))
    assert _tablo_sinyali(k)["kod"] == "karar_tablosu_uyumlu"
    k2 = _karar(_testng("false", "true", [_o(False, True)]))
    assert (k2.sinif, k2.alt_tur) == ("test_maintenance", "beklenti")


# ----------------------------------------------------------------------------- etkisiz durumlar


def test_tablo_degerleri_celisirse_ek_sinyal_yok() -> None:
    oracle = [_o("150.00", "150.00"), _o("150.00", "140.00", column="ara_toplam")]
    k = _karar(_playwright("150,00 TL", "125,00 TL", oracle))
    assert (k.sinif, k.kural) == ("product_defect", "product_defect")
    assert karar_tablosu_karari(_playwright("150,00 TL", "125,00 TL", oracle)) is None


def test_ayni_tablo_degerli_birden_cok_eslesme_karar_verir() -> None:
    oracle = [_o("150.00", "150.00"), _o("150", "150.0", column="ara_toplam"), _o("7", "7")]
    k = _karar(_playwright("150,00 TL", "125,00 TL", oracle))
    assert _tablo_sinyali(k)["kod"] == "karar_tablosu_uyumlu"


def test_eslesen_karsilastirma_yoksa_ek_sinyal_yok() -> None:
    k = _karar(_playwright("150,00 TL", "125,00 TL", [_o("200.00", "150.00")]))
    assert (k.sinif, k.kural) == ("product_defect", "product_defect")


def test_gerceklesen_karsilastirilamiyorsa_ek_sinyal_yok() -> None:
    k = _karar(_playwright("150,00 TL", "Toplam bilinmiyor: yok", [_o("150.00", "150.00")]))
    assert k.kural == "product_defect"


def test_duzenli_ifade_beklentisi_deger_sayilmaz() -> None:
    g = _playwright("x", "125,00 TL", [_o("150.00", "150.00")])
    g.beklenen = "/150,00 TL/"
    assert _karar(g).kural == "product_defect"


def test_kural4_eslesmezse_tablo_kullanilmaz() -> None:
    # Eleman bulunamadı (assertion değil): kural 4 eşleşmez → LLM'e gider (karar None).
    g = Girdi(
        test_adi="t",
        hata_turu="locator_not_found",
        mesaj="Error: expect(locator).toHaveText(expected) failed\nelement(s) not found",
        beklenen='"150,00 TL"',
        gerceklesen=None,
        oracle=[_o("150.00", "150.00")],
    )
    karar, _ek, _neden = siniflandir(g, lambda _g: None)
    assert karar is None


def test_tutarsiz_tekrarlarda_tablo_kullanilmaz() -> None:
    g = _playwright("150,00 TL", "125,00 TL", [_o("150.00", "150.00")])
    g.tekrar_degerleri = [(14, "150", "125"), (14, "150", "120")]
    karar, _ek, _neden = siniflandir(g)
    assert karar is None


def test_ortam_ve_flaky_kurallari_once_gelir() -> None:
    g = _playwright("125,00 TL", "150,00 TL", [_o("125.00", "150.00")])
    g.sonuc = "flaky"
    karar, _ek, _neden = siniflandir(g)
    assert karar is not None and karar.sinif == "flaky"


def test_asistan_kapisi_beklenti_icin_onarim_onermez() -> None:
    from tp_core.features.assistant.tools.probe import _failure_kapisi
    from tp_core.models import Failure

    kapi = _failure_kapisi(
        Failure(sinif="test_maintenance", alt_tur="beklenti", oneri_durumu="none")
    )
    assert kapi is not None and kapi.rol == "analyst" and "case düzeltilmeli" in kapi.ad
    locator = _failure_kapisi(
        Failure(sinif="test_maintenance", alt_tur="locator", oneri_durumu="proposed")
    )
    assert locator is not None and "onarım" in locator.ad
