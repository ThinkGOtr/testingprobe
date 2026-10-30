import { expect, type Locator, type Page } from "@playwright/test";
import { nav } from "../common/locators";
import { paths, scopeTestIdOf, testIdOf } from "../support";
import { catalog } from "./locators";

/** Ürün kataloğu sayfası. */
export class CatalogPage {
  constructor(private readonly page: Page) {}

  private card(productCode: string): Locator {
    return this.page.getByTestId(testIdOf(catalog.productCard, productCode));
  }

  /** Katalog sayfasını açar. */
  async goto(): Promise<void> {
    await this.page.goto(paths.catalog);
    await expect(this.page.getByTestId(catalog.productList.testId)).toBeVisible();
  }

  /** Üst menüden kataloğa gider. */
  async openFromMenu(): Promise<void> {
    await this.page.getByTestId(nav.catalog.testId).click();
    await expect(this.page).toHaveURL(new RegExp(`${paths.catalog}$`));
  }

  /** Ürün kartındaki adet alanına değer yazar. */
  async setQuantity(productCode: string, quantity: number): Promise<void> {
    await this.card(productCode)
      .getByTestId(testIdOf(catalog.quantityInput, productCode))
      .fill(String(quantity));
  }

  /** Ürün kartında adedi girip "Sepete ekle" butonuna basar ve sepetin güncellenmesini bekler. */
  async addToCart(productCode: string, quantity: number): Promise<void> {
    await this.setQuantity(productCode, quantity);
    // Yanıt beklemesi tıklamadan önce kurulur; hatası yutulmaz ama tıklama hatasının
    // (ör. kırık locator) önüne geçmez: triage tek ve doğru hatayı görür.
    const updated = this.page
      .waitForResponse((r) => r.url().endsWith("/api/cart/lines") && r.request().method() === "POST", {
        timeout: 10_000,
      })
      .catch((err: unknown) => (err instanceof Error ? err : new Error(String(err))));
    await this.page
      .getByTestId(scopeTestIdOf(catalog.addToCart, productCode))
      .getByTestId(catalog.addToCart.testId)
      .click();
    const response = await updated;
    if (response instanceof Error) throw response;
    expect(response.ok(), `sepete ekleme isteği başarısız: ${response.status()}`).toBe(true);
  }

  /** Üst menüden sepete gider. */
  async openCart(): Promise<void> {
    await this.page.getByTestId(nav.cart.testId).click();
    await expect(this.page).toHaveURL(new RegExp(`${paths.cart}$`));
  }

  /** Ürün kartının katalogda göründüğünü doğrular. */
  async expectProductVisible(productCode: string): Promise<void> {
    await expect(this.card(productCode)).toBeVisible();
  }

  /** Ürün kartındaki fiyatın verilen tutar olduğunu doğrular (ör. "25,00 TL"). */
  async expectProductPrice(productCode: string, price: string): Promise<void> {
    await expect(this.page.getByTestId(testIdOf(catalog.productPrice, productCode))).toHaveText(price);
  }

  /** Ürün kartında verilen kampanya adının göründüğünü doğrular (ör. "6 al 1 bedava"). */
  async expectCampaign(productCode: string, campaignName: string): Promise<void> {
    await expect(this.card(productCode)).toContainText(campaignName);
  }

  /** Üst menüdeki sepet sayacının verilen adet olduğunu doğrular. */
  async expectCartCount(count: number): Promise<void> {
    await expect(this.page.getByTestId(nav.cartCount.testId)).toHaveText(String(count));
  }
}
