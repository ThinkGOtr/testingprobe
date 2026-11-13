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
    TABLO_SUPHESI,
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
# Başarısız doğrulamanın case alanı (`triage.adim.hata_alanlari`; servis doldurur).
ALANLAR = frozenset({"steps[2].expected"})


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
        adim_alanlari=ALANLAR,
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
        adim_alanlari=ALANLAR,
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
        adim_alanlari=ALANLAR,
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
    [s] = [
        s
        for s in k.sinyaller
        if str(s["kod"]).startswith("karar_tablosu_") and s["kod"] != "karar_tablosu_tablo_suphesi"
    ]
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
    # Review O7: tablo tek doğruluk kaynağı değil; insan bunu görür.
    [suphe] = [x for x in k.sinyaller if x["kod"] == "karar_tablosu_tablo_suphesi"]
    assert suphe["aciklama"] == TABLO_SUPHESI
    assert TABLO_SUPHESI == (
        "Tablo da yanlış olabilir; uygulama ile tablo aynı yanlış okumayı paylaşıyor olabilir"
    )
    assert suphe["baslik"] == "Tablo da yanlış olabilir"


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
    # 012 rol modeli: case düzeltmesi Testçinin işidir.
    assert kapi is not None and kapi.rol == "tester" and "case düzeltilmeli" in kapi.ad
    locator = _failure_kapisi(
        Failure(sinif="test_maintenance", alt_tur="locator", oneri_durumu="proposed")
    )
    assert locator is not None and "onarım" in locator.ad


# ----------------------------------------------------------------------------- adım eşlemesi (O6)


def test_adim_belirlenemediyse_inceltme_yok(bicim: Any) -> None:
    """Başarısız doğrulamanın case alanı bilinmiyorsa (adım başlığı / üretilen test satırı yok)
    karar tablosu kullanılmaz: bugünkü product_defect."""
    yap, yaz = bicim
    g = yap(yaz(125), yaz(150), [_o("125.00", "150.00")])
    g.adim_alanlari = None
    k = _karar(g)
    assert (k.sinif, k.kural) == ("product_defect", "product_defect")


def test_baska_adimin_karsilastirmasi_kullanilmaz() -> None:
    """Review O6 karşı örneği: case "5 adette bedava adet 1" (tablo 0) uyarıyla onaylanmış;
    sepete ekleme bozulur, S3'teki sepet sayacı 1 beklenir, 0 görülür. Beklenen 1 = case'in bedava
    adedi, gerçekleşen 0 = tablo; ama karşılaştırma S4'e (`steps[3].expected`) ait → inceltme
    yok (gerçek hata `test_maintenance/beklenti` ile gizlenmez)."""
    oracle = [_o("1", "0", column="bedava_adet", alan="steps[3].expected")]
    g = _playwright("1", "0", oracle)
    g.adim_alanlari = frozenset({"steps[2].expected"})
    k = _karar(g)
    assert (k.sinif, k.alt_tur, k.kural) == ("product_defect", None, "product_defect")
    # Aynı değerler S4'ün doğrulamasında olsaydı inceltilirdi.
    g.adim_alanlari = frozenset({"steps[3].expected", "expected_result"})
    assert (_karar(g).sinif, _karar(g).alt_tur) == ("test_maintenance", "beklenti")


# ----------------------------------------------------------------------------- sinyal başlığı


def test_sinyal_basligi_tablo_satir_ve_kural() -> None:
    o = OracleKarsilastirma(
        case_degeri="0",
        tablo_degeri="0",
        column="bedava_adet",
        alan="steps[2].expected",
        tablo_id=TABLO_ID,
        tablo_ad="Kampanya: 6 al 1 bedava",
        test_case_id=CASE_ID,
        icerik_hash=HASH,
        tablo_ref="T1",
        satir_id="R2",
        girdiler=(("adet", "6"),),
    )
    k = _karar(_playwright("0", "1", [o]))
    s = _tablo_sinyali(k)
    assert s["baslik"] == "Uygulama onaylı kurala aykırı (T1 · R2: adet 6 → bedava_adet 0)"
    assert "\n" not in s["baslik"] and len(s["baslik"]) <= 160
    # Ayrıntı açıklamada: tablo adı, değerler, satır ve alan.
    assert "Kampanya: 6 al 1 bedava" in s["aciklama"]
    assert "test beklentisi 0, gerçekleşen 1, tablo 0" in s["aciklama"]
    assert "T1 · R2 · alan steps[2].expected" in s["aciklama"]
    k2 = _karar(_playwright("1", "0", [o.__class__(**{**o.__dict__, "case_degeri": "1"})]))
    assert _tablo_sinyali(k2)["baslik"].startswith("Test beklentisi onaylı kurala aykırı (T1 · R2")
    k3 = _karar(_playwright("1", "2", [o.__class__(**{**o.__dict__, "case_degeri": "1"})]))
    assert _tablo_sinyali(k3)["baslik"].startswith("Test ve uygulama onaylı kurala aykırı (T1")


# ----------------------------------------------------------------------------- ayrıştırma (S4)


def test_expected_substring_tocontaintext() -> None:
    """toContainText: `Expected substring:` / `Received string:` satırları okunur."""
    from tp_core.features.codegen.classify import _hata_satiri

    mesaj = (
        "Error: expect(locator).toContainText(expected) failed\n\n"
        "Locator: getByTestId('cart-total')\n"
        'Expected substring: "150,00 TL"\n'
        'Received string:    "Toplam: 125,00 TL"'
    )
    satir = _hata_satiri({"title": "t", "error": mesaj})
    assert (satir["beklenen"], satir["gerceklesen"]) == ('"150,00 TL"', '"Toplam: 125,00 TL"')
    g = _playwright("150,00 TL", "x", [_o("150.00", "150.00")])
    g.mesaj, g.matcher = mesaj, "toContainText"
    g.beklenen, g.gerceklesen = satir["beklenen"], satir["gerceklesen"]
    s = _tablo_sinyali(_karar(g))
    assert s["kod"] == "karar_tablosu_uyumlu" and "gerçekleşen 125,00" in s["aciklama"]


@pytest.mark.parametrize(
    ("metin", "sayi"),
    [
        ("Toplam: 150,00 TL", Decimal("150.00")),
        ("İndirim: −25,00 TL", Decimal("-25.00")),
        ("Sepet 6 ürün", Decimal(6)),
        ("Toplam: 1.250,00 TL.", Decimal("1250.00")),
        ("P-001 satırı 6", Decimal(6)),  # ürün kodu sayı değildir
        ("P-001 satırı 6 adet, 150,00 TL", None),  # iki sayı: belirsiz
        ("Sipariş tarihi 12.11.2026", None),
        ("Toplam bilinmiyor", None),
    ],
)
def test_bicimli_metindeki_tek_sayi(metin: str, sayi: Decimal | None) -> None:
    from tp_core.features.triage.rules import tek_sayi

    assert tek_sayi(metin) == sayi


def test_bicimli_metin_tek_sayisiyla_karsilastirilir() -> None:
    k = _karar(_playwright("Toplam: 150,00 TL", "Toplam: 125,00 TL", [_o("150.00", "150.00")]))
    s = _tablo_sinyali(k)
    assert s["kod"] == "karar_tablosu_uyumlu"
    assert "test beklentisi 150,00, gerçekleşen 125,00" in s["aciklama"]
    # Birden çok sayı: karşılaştırılamaz → bugünkü davranış.
    k2 = _karar(_playwright("6 adet, 150,00 TL", "6 adet, 125,00 TL", [_o("150.00", "150.00")]))
    assert k2.kural == "product_defect"


def test_testng_bigdecimal_noktali_uc_hane_ondaliktir() -> None:
    """TestNG `expected [2.500]` Java `toString()`'dir (BigDecimal ölçek 3): 2,5 — Türkçe binlik
    (2500) değil. `Bekle.dogrula`'nın ekran metni `2.500` ise 2500'dür."""
    k = _karar(_testng("2.500", "3.000", [_o("2.5", "2.5", column="indirim_orani")]))
    s = _tablo_sinyali(k)
    assert s["kod"] == "karar_tablosu_uyumlu"
    assert "test beklentisi 2,500, gerçekleşen 3,000, tablo 2,5" in s["aciklama"]
    # TestNG'de 2500 değildir: 2500'lük kayıtla eşleşmez.
    k2 = _karar(_testng("2.500", "3.000", [_o("2500", "2500", column="indirim_orani")]))
    assert k2.kural == "product_defect"
    # Ekran metni (Bekle.dogrula): Türkçe yazım, 2.500 = 2500.
    k3 = _karar(_java("2.500", "3.000", [_o("2500", "2500", column="adet")]))
    assert _tablo_sinyali(k3)["kod"] == "karar_tablosu_uyumlu"


def test_sinyal_degerleri_turkce_ondalik() -> None:
    """Birleştirme turu 2 ekran turu: başlıkta `ara_toplam 150.00` değil `150,00`."""
    from tp_core.features.triage import rules

    assert rules._goster("150.00") == "150,00"
    assert rules._goster("0") == "0"
    assert rules._goster(True) == "doğru"
    assert rules._goster("P-001") == "P-001"
