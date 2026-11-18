"""Bayi girişi (TPD-4) — TS tests/login.spec.ts karşılığı (temsilî alt küme)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from altyapi.bayiler import Bayi
from pages.catalog_page import CatalogPage
from pages.login_page import LoginPage


def test_dogru_bilgilerle_giris_yapilir_ve_katalog_acilir(page: Page, dealer: Bayi) -> None:
    login_page, catalog_page = LoginPage(page), CatalogPage(page)
    login_page.goto()
    login_page.login(dealer.kullanici_adi, dealer.parola)
    login_page.expect_logged_in(dealer.ad)
    catalog_page.expect_product_visible("P-001")


def test_hatali_parolada_hata_mesaji_gosterilir(page: Page, dealer: Bayi) -> None:
    login_page = LoginPage(page)
    login_page.goto()
    login_page.login(dealer.kullanici_adi, "YanlisParola1")
    login_page.expect_login_error("Kullanıcı adı veya parola hatalı")
    login_page.expect_on_login_page()


def test_oturumsuz_kullanici_giris_sayfasina_yonlendirilir(page: Page) -> None:
    page.goto("/sepet")
    LoginPage(page).expect_on_login_page()


@pytest.mark.oturumlu
def test_cikis_yapinca_giris_sayfasina_donulur(page: Page) -> None:
    catalog_page, login_page = CatalogPage(page), LoginPage(page)
    catalog_page.goto()
    login_page.logout()
    login_page.expect_on_login_page()
