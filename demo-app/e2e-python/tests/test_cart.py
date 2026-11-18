"""Sepet (TPD-1) — TS tests/cart.spec.ts karşılığı (temsilî alt küme).

6 adet sınırı bilerek doğrulanmaz (demo senaryosuna bağlı; cart.spec.ts notu): el yazımı testler
yalnız iki senaryoda da doğru olan davranışı (7 → 1) doğrular.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from pages.cart_page import CartPage
from pages.catalog_page import CatalogPage

pytestmark = pytest.mark.oturumlu


@pytest.fixture
def catalog_page(page: Page) -> CatalogPage:
    sayfa = CatalogPage(page)
    sayfa.goto()
    return sayfa


def test_katalog_fiyatlari_tr_bicimi(catalog_page: CatalogPage) -> None:
    catalog_page.expect_product_price("P-001", "25,00 TL")
    catalog_page.expect_product_price("P-002", "15,00 TL")
    catalog_page.expect_campaign("P-001", "6 al 1 bedava")


def test_sepete_ekle_sayaci_artirir(catalog_page: CatalogPage) -> None:
    catalog_page.expect_cart_count(0)
    catalog_page.add_to_cart("P-002", 1)
    catalog_page.expect_cart_count(1)
    catalog_page.add_to_cart("P-003", 2)
    catalog_page.expect_cart_count(3)


@pytest.mark.kampanya
def test_kampanya_7_adet_p001_bir_bedava(page: Page, catalog_page: CatalogPage) -> None:
    cart_page = CartPage(page)
    catalog_page.add_to_cart("P-001", 7)
    catalog_page.open_cart()
    cart_page.expect_line_quantity("P-001", 7)
    cart_page.expect_free_quantity("P-001", 1)
    cart_page.expect_subtotal("175,00 TL")
    cart_page.expect_discount("25,00 TL")
    cart_page.expect_total("150,00 TL")


def test_kampanyasiz_urunde_bedava_adet_yok(page: Page, catalog_page: CatalogPage) -> None:
    cart_page = CartPage(page)
    catalog_page.add_to_cart("P-002", 12)
    catalog_page.open_cart()
    cart_page.expect_free_quantity("P-002", 0)
    cart_page.expect_discount("0,00 TL")


def test_minimum_tutar_altinda_uyari_ve_onay_pasif(page: Page, catalog_page: CatalogPage) -> None:
    cart_page = CartPage(page)
    catalog_page.add_to_cart("P-002", 10)
    catalog_page.open_cart()
    cart_page.expect_total("150,00 TL")
    cart_page.expect_min_order_warning("Minimum sipariş tutarı 750,00 TL")
    cart_page.expect_checkout_disabled()
