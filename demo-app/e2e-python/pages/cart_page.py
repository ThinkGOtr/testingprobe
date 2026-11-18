"""Sepet sayfası (TS: pages/cart/cart.page.ts `CartPage`)."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from pages.destek import PATHS, test_id_of
from pages.kimlikler import CART, NAV


class CartPage:
    """Sepet sayfası: satırlar, kampanya, toplamlar ve sipariş onayı."""

    def __init__(self, page: Page) -> None:
        self._page = page

    def goto(self) -> None:
        """Sepet sayfasını açar."""
        self._page.goto(PATHS["cart"])
        expect(
            self._page.get_by_test_id(CART["table"]["testId"]).or_(
                self._page.get_by_test_id(CART["empty"]["testId"])
            )
        ).to_be_visible()

    def remove_product(self, product_code: str) -> None:
        """Ürünü sepetten kaldırır."""
        self._page.get_by_test_id(test_id_of(CART["lineRemove"], product_code)).click()
        expect(self._page.get_by_test_id(test_id_of(CART["line"], product_code))).to_have_count(0)

    def checkout(self) -> None:
        """"Siparişi onayla" butonuna basar ve onay sayfasının açılmasını bekler."""
        self._page.get_by_test_id(CART["checkoutSubmit"]["testId"]).click()
        expect(self._page).to_have_url(re.compile(r"/siparis/[^/]+$"))

    def expect_line_quantity(self, product_code: str, quantity: int) -> None:
        """Sepet satırındaki adedi doğrular."""
        expect(
            self._page.get_by_test_id(test_id_of(CART["lineQuantity"], product_code))
        ).to_have_text(str(quantity))

    def expect_free_quantity(self, product_code: str, quantity: int) -> None:
        """Sepet satırında kampanyayla bedava verilen adedi doğrular."""
        expect(
            self._page.get_by_test_id(test_id_of(CART["lineFree"], product_code))
        ).to_have_text(str(quantity))

    def expect_line_total(self, product_code: str, amount: str) -> None:
        """Sepet satırının indirim sonrası tutarını doğrular (ör. "150,00 TL")."""
        expect(
            self._page.get_by_test_id(test_id_of(CART["lineTotal"], product_code))
        ).to_have_text(amount)

    def expect_subtotal(self, amount: str) -> None:
        """Ara toplamı doğrular (ör. "175,00 TL")."""
        expect(self._page.get_by_test_id(CART["subtotal"]["testId"])).to_have_text(amount)

    def expect_discount(self, amount: str) -> None:
        """Kampanya indirimi tutarını doğrular (ör. "25,00 TL")."""
        expect(self._page.get_by_test_id(CART["discount"]["testId"])).to_have_text(amount)

    def expect_total(self, amount: str) -> None:
        """İndirim sonrası genel toplamı doğrular (ör. "150,00 TL")."""
        expect(self._page.get_by_test_id(CART["total"]["testId"])).to_have_text(amount)

    def expect_min_order_warning(self, message: str) -> None:
        """Minimum sipariş uyarısının verilen metni içerdiğini doğrular."""
        expect(self._page.get_by_test_id(CART["minOrderWarning"]["testId"])).to_contain_text(
            message
        )

    def expect_no_min_order_warning(self) -> None:
        """Minimum sipariş uyarısının gösterilmediğini doğrular."""
        expect(self._page.get_by_test_id(CART["minOrderWarning"]["testId"])).to_have_count(0)

    def expect_checkout_disabled(self) -> None:
        """"Siparişi onayla" butonunun pasif olduğunu doğrular."""
        expect(self._page.get_by_test_id(CART["checkoutSubmit"]["testId"])).to_be_disabled()

    def expect_checkout_enabled(self) -> None:
        """"Siparişi onayla" butonunun aktif olduğunu doğrular."""
        expect(self._page.get_by_test_id(CART["checkoutSubmit"]["testId"])).to_be_enabled()

    def expect_product_not_in_cart(self, product_code: str) -> None:
        """Sepette ürünün bulunmadığını doğrular."""
        expect(self._page.get_by_test_id(test_id_of(CART["line"], product_code))).to_have_count(0)

    def expect_cart_count(self, count: int) -> None:
        """Üst menüdeki sepet sayacının verilen adet olduğunu doğrular (sepet sayfasında)."""
        expect(self._page.get_by_test_id(NAV["cartCount"]["testId"])).to_have_text(str(count))

    def expect_empty(self) -> None:
        """Sepetin boş olduğunu doğrular."""
        expect(self._page.get_by_test_id(CART["empty"]["testId"])).to_be_visible()
