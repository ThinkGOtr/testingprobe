"""Sipariş onayı ve geçmiş (TPD-1 AC5) — TS tests/order.spec.ts karşılığı."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from pages.cart_page import CartPage
from pages.catalog_page import CatalogPage
from pages.order_page import OrderPage

pytestmark = pytest.mark.oturumlu


@pytest.mark.sifir_veri
def test_siparisi_olmayan_bayide_bos_gecmis(page: Page) -> None:
    order_page = OrderPage(page)
    order_page.goto_history()
    order_page.expect_no_orders()


def test_onaylanan_siparis_gecmiste_listelenir(page: Page) -> None:
    catalog_page, cart_page, order_page = CatalogPage(page), CartPage(page), OrderPage(page)
    catalog_page.goto()
    catalog_page.add_to_cart("P-004", 30)
    catalog_page.add_to_cart("P-001", 7)
    catalog_page.open_cart()
    cart_page.expect_total("1.050,00 TL")
    cart_page.checkout()
    order_page.expect_confirmation()
    order_page.expect_confirmed_total("1.050,00 TL")
    catalog_page.expect_cart_count(0)
    order_number = order_page.read_order_number()
    order_page.expect_confirmed_order_in_history()
    order_page.expect_order_total_in_history(order_number, "1.050,00 TL")


def test_minimum_tutar_altindaki_sepet_apide_reddedilir(page: Page) -> None:
    catalog_page = CatalogPage(page)
    catalog_page.goto()
    catalog_page.add_to_cart("P-003", 1)
    yanit = page.request.post("/api/orders")
    assert yanit.status == 422
    assert yanit.json() == {"detail": "Minimum sipariş tutarı 750,00 TL"}
