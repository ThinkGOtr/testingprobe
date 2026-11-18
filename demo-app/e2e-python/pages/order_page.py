"""Sipariş onayı ve sipariş geçmişi (TS: pages/order/order.page.ts `OrderPage`)."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from pages.destek import PATHS, test_id_of
from pages.kimlikler import NAV, ORDER

_ORDER_NUMBER = re.compile(r"^SP-\d{6}$")


class OrderPage:
    """Sipariş onayı ve sipariş geçmişi."""

    def __init__(self, page: Page) -> None:
        self._page = page

    def goto_history(self) -> None:
        """Sipariş geçmişi sayfasını açar."""
        self._page.goto(PATHS["orders"])
        expect(
            self._page.get_by_test_id(ORDER["ordersTable"]["testId"]).or_(
                self._page.get_by_test_id(ORDER["ordersEmpty"]["testId"])
            )
        ).to_be_visible()

    def open_history(self) -> None:
        """Üst menüden sipariş geçmişine gider."""
        self._page.get_by_test_id(NAV["orders"]["testId"]).click()
        expect(self._page).to_have_url(re.compile(re.escape(PATHS["orders"]) + "$"))

    def read_order_number(self) -> str:
        """Onay sayfasındaki sipariş numarasını okur. (TS ile eşit: değer döndürür; üretilen
        testler bunu çağırmaz, `expect_confirmed_order_in_history` kullanır.)"""
        el = self._page.get_by_test_id(ORDER["orderNumber"]["testId"])
        expect(el).to_have_text(_ORDER_NUMBER)
        return el.inner_text().strip()

    def expect_confirmation(self) -> None:
        """Sipariş onayının ve sipariş numarasının gösterildiğini doğrular."""
        expect(self._page.get_by_test_id(ORDER["confirmation"]["testId"])).to_be_visible()
        expect(self._page.get_by_test_id(ORDER["orderNumber"]["testId"])).to_have_text(
            _ORDER_NUMBER
        )

    def expect_confirmed_total(self, amount: str) -> None:
        """Onaylanan siparişin genel toplamını doğrular (ör. "1.025,00 TL")."""
        expect(self._page.get_by_test_id(ORDER["orderTotal"]["testId"])).to_have_text(amount)

    def expect_confirmed_order_in_history(self) -> None:
        """Onay sayfasında gösterilen siparişin sipariş geçmişinde listelendiğini doğrular."""
        order_number = self.read_order_number()
        self.open_history()
        self.expect_order_in_history(order_number)

    def expect_order_in_history(self, order_number: str) -> None:
        """Verilen sipariş numarasının sipariş geçmişinde listelendiğini doğrular."""
        expect(
            self._page.get_by_test_id(test_id_of(ORDER["orderRow"], order_number))
        ).to_be_visible()

    def expect_order_total_in_history(self, order_number: str, amount: str) -> None:
        """Sipariş geçmişindeki siparişin genel toplamını doğrular."""
        expect(
            self._page.get_by_test_id(test_id_of(ORDER["orderRowTotal"], order_number))
        ).to_have_text(amount)

    def expect_no_orders(self) -> None:
        """Sipariş geçmişinin boş olduğunu doğrular."""
        expect(self._page.get_by_test_id(ORDER["ordersEmpty"]["testId"])).to_be_visible()
