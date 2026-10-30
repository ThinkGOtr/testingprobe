import { expect, type Page } from "@playwright/test";
import { nav } from "../common/locators";
import { paths } from "../support";
import { login } from "./locators";

/** Bayi giriş sayfası. */
export class LoginPage {
  constructor(private readonly page: Page) {}

  /** Giriş sayfasını açar. */
  async goto(): Promise<void> {
    await this.page.goto(paths.login);
    await expect(this.page.getByTestId(login.username.testId)).toBeVisible();
  }

  /** Kullanıcı adı ve parolayı girip giriş yapar. */
  async login(username: string, password: string): Promise<void> {
    await this.page.getByTestId(login.username.testId).fill(username);
    await this.page.getByTestId(login.password.testId).fill(password);
    await this.page.getByTestId(login.submit.testId).click();
  }

  /** Oturumu kapatır. */
  async logout(): Promise<void> {
    await this.page.getByTestId(nav.logout.testId).click();
  }

  /** Giriş hatası mesajının verilen metin olduğunu doğrular. */
  async expectLoginError(message: string): Promise<void> {
    await expect(this.page.getByTestId(login.error.testId)).toHaveText(message);
  }

  /** Verilen bayi adıyla oturum açıldığını ve kataloğun açıldığını doğrular. */
  async expectLoggedIn(dealerName: string): Promise<void> {
    await expect(this.page.getByTestId(nav.currentDealer.testId)).toHaveText(dealerName);
    await expect(this.page).toHaveURL(new RegExp(`${paths.catalog}$`));
  }

  /** Giriş sayfasında olunduğunu doğrular. */
  async expectOnLoginPage(): Promise<void> {
    await expect(this.page).toHaveURL(new RegExp(`${paths.login}$`));
    await expect(this.page.getByTestId(login.submit.testId)).toBeVisible();
  }
}
