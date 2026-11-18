"""Ürün kataloğu sayfası (TS: pages/catalog/catalog.page.ts `CatalogPage`)."""

from __future__ import annotations

import re

from playwright.sync_api import Locator, Page, expect

from pages.destek import PATHS, scope_test_id_of, test_id_of
from pages.kimlikler import CATALOG, NAV


class CatalogPage:
    """Ürün kataloğu sayfası."""

    def __init__(self, page: Page) -> None:
        self._page = page

    def _card(self, product_code: str) -> Locator:
        return self._page.get_by_test_id(test_id_of(CATALOG["productCard"], product_code))

    def goto(self) -> None:
        """Katalog sayfasını açar."""
        self._page.goto(PATHS["catalog"])
        expect(self._page.get_by_test_id(CATALOG["productList"]["testId"])).to_be_visible()

    def open_from_menu(self) -> None:
        """Üst menüden kataloğa gider."""
        self._page.get_by_test_id(NAV["catalog"]["testId"]).click()
        expect(self._page).to_have_url(re.compile(re.escape(PATHS["catalog"]) + "$"))

    def set_quantity(self, product_code: str, quantity: int) -> None:
        """Ürün kartındaki adet alanına değer yazar."""
        self._card(product_code).get_by_test_id(
            test_id_of(CATALOG["quantityInput"], product_code)
        ).fill(str(quantity))

    def add_to_cart(self, product_code: str, quantity: int) -> None:
        """Ürün kartında adedi girip "Sepete ekle" butonuna basar ve sepetin güncellenmesini
        bekler."""
        self.set_quantity(product_code, quantity)
        # Yanıt beklemesi tıklamadan önce kurulur; tıklama hatası (ör. kırık locator) yanıt
        # beklemesinin zaman aşımından önce görünür: triage tek ve doğru hatayı görür.
        with self._page.expect_response(
            lambda r: r.url.endswith("/api/cart/lines") and r.request.method == "POST",
            timeout=10_000,
        ) as yanit:
            self._page.get_by_test_id(
                scope_test_id_of(CATALOG["addToCart"], product_code)
            ).get_by_test_id(CATALOG["addToCart"]["testId"]).click()
        response = yanit.value
        assert response.ok, f"sepete ekleme isteği başarısız: {response.status}"

    def open_cart(self) -> None:
        """Üst menüden sepete gider."""
        self._page.get_by_test_id(NAV["cart"]["testId"]).click()
        expect(self._page).to_have_url(re.compile(re.escape(PATHS["cart"]) + "$"))

    def expect_product_visible(self, product_code: str) -> None:
        """Ürün kartının katalogda göründüğünü doğrular."""
        expect(self._card(product_code)).to_be_visible()

    def expect_product_price(self, product_code: str, price: str) -> None:
        """Ürün kartındaki fiyatın verilen tutar olduğunu doğrular (ör. "25,00 TL")."""
        expect(
            self._page.get_by_test_id(test_id_of(CATALOG["productPrice"], product_code))
        ).to_have_text(price)

    def expect_campaign(self, product_code: str, campaign_name: str) -> None:
        """Ürün kartında verilen kampanya adının göründüğünü doğrular (ör. "6 al 1 bedava")."""
        expect(self._card(product_code)).to_contain_text(campaign_name)

    def expect_cart_count(self, count: int) -> None:
        """Üst menüdeki sepet sayacının verilen adet olduğunu doğrular."""
        expect(self._page.get_by_test_id(NAV["cartCount"]["testId"])).to_have_text(str(count))
