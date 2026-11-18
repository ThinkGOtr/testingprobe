"""Tarayıcısız altyapı birim testleri: locator yardımcıları, bayi seçimi, kırılma gövdeleri."""

from __future__ import annotations

import pytest

from altyapi import bayiler, veri_yalitimi
from pages import destek
from pages.kimlikler import CATALOG, CART

pytestmark = pytest.mark.birim


def test_test_id_of() -> None:
    assert destek.test_id_of(CART["total"]) == "cart-total"
    assert destek.test_id_of(CART["line"], "P-001") == "cart-line-P-001"
    with pytest.raises(ValueError, match="sonek"):
        destek.test_id_of(CART["line"])
    with pytest.raises(ValueError, match="sabit"):
        destek.test_id_of(CART["total"], "P-001")
    assert destek.scope_test_id_of(CATALOG["addToCart"], "P-001") == "product-card-P-001"


def test_bayi_ve_kirilma() -> None:
    assert bayiler.sec(None, 1).kullanici_adi == "bayi2"
    with pytest.raises(ValueError, match="doğrulama ajanına"):
        bayiler.sec("bayi3", 0)
    k = veri_yalitimi.kirilma({"TP_FAULT": "kdv_hatasi"})
    assert k is not None and k.on == {"hata": "kdv_hatasi"}
    assert veri_yalitimi.api_koku("http://w:8081/", {}) == "http://w:8081/api"
    assert veri_yalitimi.api_koku(None, {"DEMO_API_URL": "http://a:18000/"}) == "http://a:18000"


def test_kosu_parolasi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Koşu hesabı başına parola (TP_RUN_DEALER_PASSWORDS); girilmeyen hesap seed parolasıyla."""
    seed = {b.kullanici_adi: b.parola for b in bayiler.E2E}
    monkeypatch.delenv("TP_RUN_DEALER_PASSWORDS", raising=False)
    assert bayiler.sec("bayi2", 0).parola == seed["bayi2"]
    monkeypatch.setenv("TP_RUN_DEALER_PASSWORDS", '{"bayi2": "Bayi2 ozel!", "bos": ""}')
    assert bayiler.kosu_parolalari() == {"bayi2": "Bayi2 ozel!"}
    assert bayiler.sec("bayi2", 0).parola == "Bayi2 ozel!"
    assert bayiler.sec(None, 1).parola == "Bayi2 ozel!"
    assert bayiler.sec(None, 0).parola == seed["bayi1"]
    assert bayiler.E2E[1].parola == seed["bayi2"]  # seed listesi değişmez
    for bozuk, mesaj in (("{x", "geçerli JSON"), ('["a"]', "JSON nesnesi")):
        monkeypatch.setenv("TP_RUN_DEALER_PASSWORDS", bozuk)
        with pytest.raises(ValueError, match=mesaj):
            bayiler.sec(None, 0)


def test_kosu_parola_ortami() -> None:
    """Üretilen testin okuduğu `TP_TESTVERI_KOSU_<KULLANICI>`: verilmemişse yazılır, verilmişse korunur."""
    assert bayiler.kosu_parola_adi("bayi1") == "TP_TESTVERI_KOSU_BAYI1"
    assert bayiler.kosu_parola_adi("test.k-2") == "TP_TESTVERI_KOSU_TEST_K_2"
    assert bayiler.kosu_parola_adi("x" * 60) is None
    ortam = {"TP_TESTVERI_KOSU_BAYI2": "runner-verdi"}
    bayiler.kosu_parola_ortamini_yaz(ortam)
    assert ortam["TP_TESTVERI_KOSU_BAYI2"] == "runner-verdi"
    assert ortam["TP_TESTVERI_KOSU_BAYI1"] == bayiler.sec("bayi1", 0).parola
