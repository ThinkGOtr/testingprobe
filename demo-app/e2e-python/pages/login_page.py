"""Bayi giriş sayfası (TS: pages/login/login.page.ts `LoginPage`)."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from pages.destek import PATHS
from pages.kimlikler import LOGIN, NAV


class LoginPage:
    """Bayi giriş sayfası."""

    def __init__(self, page: Page) -> None:
        self._page = page

    def goto(self) -> None:
        """Giriş sayfasını açar."""
        self._page.goto(PATHS["login"])
        expect(self._page.get_by_test_id(LOGIN["username"]["testId"])).to_be_visible()

    def login(self, username: str, password: str) -> None:
        """Kullanıcı adı ve parolayı girip giriş yapar."""
        self._page.get_by_test_id(LOGIN["username"]["testId"]).fill(username)
        self._page.get_by_test_id(LOGIN["password"]["testId"]).fill(password)
        self._page.get_by_test_id(LOGIN["submit"]["testId"]).click()

    def logout(self) -> None:
        """Oturumu kapatır."""
        self._page.get_by_test_id(NAV["logout"]["testId"]).click()

    def expect_login_error(self, message: str) -> None:
        """Giriş hatası mesajının verilen metin olduğunu doğrular."""
        expect(self._page.get_by_test_id(LOGIN["error"]["testId"])).to_have_text(message)

    def expect_logged_in(self, dealer_name: str) -> None:
        """Verilen bayi adıyla oturum açıldığını ve kataloğun açıldığını doğrular."""
        expect(self._page.get_by_test_id(NAV["currentDealer"]["testId"])).to_have_text(dealer_name)
        expect(self._page).to_have_url(re.compile(re.escape(PATHS["catalog"]) + "$"))

    def expect_on_login_page(self) -> None:
        """Giriş sayfasında olunduğunu doğrular."""
        expect(self._page).to_have_url(re.compile(re.escape(PATHS["login"]) + "$"))
        expect(self._page.get_by_test_id(LOGIN["submit"]["testId"])).to_be_visible()
