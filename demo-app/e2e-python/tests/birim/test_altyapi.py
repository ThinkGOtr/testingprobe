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
