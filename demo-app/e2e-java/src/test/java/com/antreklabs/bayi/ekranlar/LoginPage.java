package com.antreklabs.bayi.ekranlar;

import static com.microsoft.playwright.assertions.PlaywrightAssertions.assertThat;

import com.antreklabs.bayi.ekranlar.Kimlikler.Login;
import com.antreklabs.bayi.ekranlar.Kimlikler.Nav;
import com.microsoft.playwright.Page;

/** Bayi giriş sayfası. */
public class LoginPage extends Ekran {

  public LoginPage(Page page) {
    super(page);
  }

  /** Giriş sayfasını açar. */
  public void goTo() {
    git(LOGIN_YOLU);
    assertThat(kimlik(Login.USERNAME)).isVisible();
  }

  /** Kullanıcı adı ve parolayı girip giriş yapar. */
  public void login(String username, String password) {
    kimlik(Login.USERNAME).fill(username);
    kimlik(Login.PASSWORD).fill(password);
    kimlik(Login.SUBMIT).click();
  }

  /** Oturumu kapatır. */
  public void logout() {
    kimlik(Nav.LOGOUT).click();
  }

  /** Giriş hatası mesajının verilen metin olduğunu doğrular. */
  public void expectLoginError(String message) {
    assertThat(kimlik(Login.ERROR)).hasText(message);
  }

  /** Verilen bayi adıyla oturum açıldığını ve kataloğun açıldığını doğrular. */
  public void expectLoggedIn(String dealerName) {
    assertThat(kimlik(Nav.CURRENT_DEALER)).hasText(dealerName);
    dogrulaYol(CATALOG_YOLU);
  }

  /** Giriş sayfasında olunduğunu doğrular. */
  public void expectOnLoginPage() {
    dogrulaYol(LOGIN_YOLU);
    assertThat(kimlik(Login.SUBMIT)).isVisible();
  }
}
