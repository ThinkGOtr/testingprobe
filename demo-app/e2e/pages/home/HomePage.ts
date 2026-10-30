import { expect, type Locator, type Page } from "@playwright/test";
import * as L from "./locators";

export class HomePage {
  readonly root: Locator;
  readonly title: Locator;
  readonly checkApiButton: Locator;
  readonly apiStatus: Locator;

  constructor(private readonly page: Page) {
    this.root = page.getByTestId(L.HOME_PAGE);
    this.title = page.getByTestId(L.HOME_TITLE);
    this.checkApiButton = page.getByTestId(L.HOME_CHECK_API);
    this.apiStatus = page.getByTestId(L.HOME_API_STATUS);
  }

  async goto(): Promise<void> {
    await this.page.goto("/");
  }

  async checkApi(): Promise<void> {
    await this.checkApiButton.click();
  }

  async expectLoaded(): Promise<void> {
    await expect(this.root).toBeVisible();
    await expect(this.title).toHaveText("Bayi Sipariş Portalı");
  }
}
