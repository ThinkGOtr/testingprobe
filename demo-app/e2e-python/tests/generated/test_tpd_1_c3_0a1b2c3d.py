# AI-generated — AI Testing Probe (CasesToCode). Elle düzenlemeyin; değişiklik case'in yeniden
# onayı ve yeniden üretimle yapılır.
# Case: TPD-1 C3 (0a1b2c3d-0000-4000-8000-000000000003) · Story: TPD-1 · Jira Test: TPD-T3
# Onaylı case hash: ornek-referans-dosyasi
# Eşleme: verify_and_map · platform: web · dil: python · mod: ornek · bundle: ornek
# Eşleme hash: ornek · şablon: ornek
import pytest
from playwright.sync_api import Page

from pages.cart_page import CartPage
from pages.catalog_page import CatalogPage
from pages.login_page import LoginPage


@pytest.mark.uretilen
@pytest.mark.web
@pytest.mark.tp_case("0a1b2c3d-0000-4000-8000-000000000003")
@pytest.mark.story("TPD-1")
@pytest.mark.dealer("bayi2")
def test_tpd_1_c3_0a1b2c3d(page: Page) -> None:
    cart_page = CartPage(page)
    catalog_page = CatalogPage(page)
    login_page = LoginPage(page)

    # 1 — bayi2 / Demo123! ile giriş yapılır
    login_page.goto()
    login_page.login("bayi2", "Demo123!")
    # 2 — Katalogda P-001 ürününden 7 adet sepete eklenir
    catalog_page.add_to_cart("P-001", 7)
    # 3 — Sepet açılır
    catalog_page.open_cart()
    # Beklenen sonuç (değerler onaylı case metninden)
    cart_page.expect_free_quantity("P-001", 1)
    cart_page.expect_discount("25,00 TL")
    cart_page.expect_total("150,00 TL")
