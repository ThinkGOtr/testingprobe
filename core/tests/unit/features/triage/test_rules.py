"""Deterministik kurallar (saf; DB'siz): sıra, sinyaller, LLM'e düşme koşulu."""

from __future__ import annotations

from typing import Any

from tp_core.features.triage.rules import Girdi, LocatorAnalizi, hata_imzasi, siniflandir

SAGLIK_OK = {"ok": True}


def _kodlar(sinyaller: list[dict[str, Any]]) -> list[str]:
    return [s["kod"] for s in sinyaller]


def _yasak(_g: Girdi) -> LocatorAnalizi:
    raise AssertionError("locator analizi çağrılmamalı")


def test_saglik_basarisiz_environment_ve_locator_analizine_gitmez() -> None:
    g = Girdi(
        "t",
        hata_turu="locator_timeout",
        locator="getByTestId('add-to-cart')",
        saglik={"ok": False, "hata": "web erişilemedi"},
    )
    karar, ek, _ = siniflandir(g, _yasak)
    assert karar is not None and karar.sinif == "environment"
    assert karar.kural == "environment" and karar.karar_kaynagi == "rule"
    assert "saglik_basarisiz" in _kodlar(karar.sinyaller)
    assert ek == []


def test_sagliksiz_error_kosusu_environment() -> None:
    g = Girdi("(koşu)", sonuc="kosu", run_sonuc="error", testsiz=True, runner_hata="timeout")
    karar, _, _ = siniflandir(g)
    assert karar is not None and karar.sinif == "environment"
    assert _kodlar(karar.sinyaller) == ["saglik_yok_hata"]


def test_ag_hatasi_ve_uygulama_sha_farkli_environment() -> None:
    g = Girdi("t", mesaj="page.goto: net::ERR_CONNECTION_REFUSED at /katalog", saglik=SAGLIK_OK)
    karar, _, _ = siniflandir(g)
    assert karar is not None and karar.sinif == "environment"
    assert "ag_hatasi" in _kodlar(karar.sinyaller)
    g2 = Girdi("t", hata_turu="assertion", uygulama_farkli="web ağacı farklı")
    karar2, _, _ = siniflandir(g2)
    assert karar2 is not None and karar2.sinif == "environment"


def test_flaky_retry_ve_tekrar() -> None:
    g = Girdi("t", sonuc="flaky", hata_turu="assertion", deneme_durumlari=["failed", "passed"])
    karar, _, _ = siniflandir(g, _yasak)
    assert karar is not None and karar.sinif == "flaky"
    assert "playwright_flaky" in _kodlar(karar.sinyaller)
    g2 = Girdi(
        "t",
        hata_turu="assertion",
        beklenen='"0"',
        gerceklesen='"1"',
        tekrar_durumlari=["failed", "passed", "failed"],
    )
    karar2, _, _ = siniflandir(g2, _yasak)
    assert karar2 is not None and karar2.sinif == "flaky"
    assert "tekrarlarin_bir_kismi_gecti" in _kodlar(karar2.sinyaller)


def test_locator_onerisi_varsa_test_maintenance() -> None:
    oneri = {"locator_key": "catalog.addToCart", "old_testid": "add-to-cart", "new_testid": "x"}

    def analiz(_g: Girdi) -> LocatorAnalizi:
        return LocatorAnalizi(oneri, [{"kod": "test_id_farkli", "aciklama": "a", "kaynak": "k"}])

    g = Girdi("t", hata_turu="locator_timeout", locator="getByTestId('add-to-cart')")
    karar, _, _ = siniflandir(g, analiz)
    assert karar is not None
    assert (karar.sinif, karar.alt_tur, karar.kural) == (
        "test_maintenance",
        "locator",
        "test_maintenance/locator",
    )
    assert karar.oneri == oneri and karar.oneri_turu == "locator_fix"
    assert _kodlar(karar.sinyaller) == ["locator_0_eleman", "test_id_farkli"]


def test_locator_onerisi_yoksa_llm_e_duser_neden_tasinir() -> None:
    def analiz(_g: Girdi) -> LocatorAnalizi:
        return LocatorAnalizi(None, [], "Rol + ad 2 eleman buldu; tek eşleşme gerekli")

    g = Girdi("t", hata_turu="locator_not_found", locator="getByTestId('x')")
    karar, ek, neden = siniflandir(g, analiz)
    assert karar is None
    assert _kodlar(ek) == ["locator_0_eleman"]
    assert neden and "2 eleman" in neden


def test_belirsiz_locator_rule3_degil() -> None:
    g = Girdi("t", hata_turu="locator_ambiguous", mesaj="strict mode violation")
    karar, ek, _ = siniflandir(g, _yasak)
    assert karar is None and ek == []


def test_assertion_ve_sayfa_yapisi_product_defect() -> None:
    g = Girdi(
        "C3",
        hata_turu="assertion",
        beklenen='"0"',
        gerceklesen='"1"',
        matcher="toHaveText",
        locator="getByTestId('cart-line-free-P-001')",
        aria="- main:\n  - table",
        aria_kapsami="page",
        tekrar_durumlari=["failed", "failed", "failed"],
        tekrar_degerleri=[(37, '"0"', '"1"')] * 3,
        kirma=True,
    )
    karar, _, _ = siniflandir(g, _yasak)
    assert karar is not None and karar.sinif == "product_defect"
    assert karar.oneri_turu == "bug_draft"
    kodlar = _kodlar(karar.sinyaller)
    assert kodlar[:2] == ["assertion_farki", "eleman_bulundu"]
    assert {"sayfa_yapisi_beklenen", "tutarli_tekrar", "kasitli_kirilma"} <= set(kodlar)


def test_tutarsiz_tekrar_degerleri_product_defect_degil() -> None:
    g = Girdi(
        "t",
        hata_turu="assertion",
        beklenen='"0"',
        gerceklesen='"1"',
        tekrar_degerleri=[(37, '"0"', '"1"'), (37, '"0"', '"2"')],
    )
    karar, _, _ = siniflandir(g)
    assert karar is None


def test_assertion_eleman_bulunamadi_product_defect_degil() -> None:
    g = Girdi(
        "t",
        hata_turu="assertion",
        beklenen="visible",
        gerceklesen="<element(s) not found>",
        mesaj="expect(locator).toBeVisible() failed\nError: element(s) not found",
    )
    karar, _, _ = siniflandir(g)
    assert karar is None


def test_veri_on_kosulu_test_data() -> None:
    g = Girdi("t", hata_turu="test_data", mesaj="POST /test/reset başarısız: 401")
    karar, _, _ = siniflandir(g)
    assert karar is not None and karar.sinif == "test_data"
    g2 = Girdi("t", mesaj="Error: POST /test/reset başarısız: 500")
    karar2, _, _ = siniflandir(g2)
    assert karar2 is not None and karar2.sinif == "test_data"


def test_hicbiri_eslesmezse_none() -> None:
    karar, ek, neden = siniflandir(Girdi("t", hata_turu="other", mesaj="TypeError: x"))
    assert karar is None and ek == [] and neden is None


def test_json_suz_mesajdan_tur_cikarimi() -> None:
    g = Girdi(
        "t",
        mesaj="locator.click: Timeout 5000ms exceeded.\nCall log:\n"
        "  - waiting for getByTestId('a')",
    )
    assert g.tur() == "locator_timeout"
    g2 = Girdi("t", mesaj='expect(locator).toHaveText(expected)\nReceived: "1"', gerceklesen="1")
    assert g2.tur() == "assertion"


def test_hata_imzasi_okunur_ve_kararli() -> None:
    g = Girdi(
        "Sepet › 6 adet",
        dosya="tests/cart.spec.ts",
        satir=37,
        hata_turu="assertion",
        matcher="toHaveText",
        locator="getByTestId('cart-line-free-P-001')",
    )
    imza = hata_imzasi(g)
    assert (
        imza
        == "assertion · tests/cart.spec.ts:37 · Sepet › 6 adet · toHaveText cart-line-free-P-001"
    )
    assert hata_imzasi(g) == imza
