import { expect, type Page } from "@playwright/test";
import { nav } from "../common/locators";
import { paths, testIdOf } from "../support";
import { cart } from "./locators";

/** Sepet sayfası: satırlar, kampanya, toplamlar ve sipariş onayı. */
export class CartPage {
  constructor(private readonly page: Page) {}

  /** Sepet sayfasını açar. */
  async goto(): Promise<void> {
    await this.page.goto(paths.cart);
    await expect(
      this.page.getByTestId(cart.table.testId).or(this.page.getByTestId(cart.empty.testId)),
    ).toBeVisible();
  }

  /** Ürünü sepetten kaldırır. */
  async removeProduct(productCode: string): Promise<void> {
    await this.page.getByTestId(testIdOf(cart.lineRemove, productCode)).click();
    await expect(this.page.getByTestId(testIdOf(cart.line, productCode))).toHaveCount(0);
  }

  /** "Siparişi onayla" butonuna basar ve onay sayfasının açılmasını bekler. */
  async checkout(): Promise<void> {
    await this.page.getByTestId(cart.checkoutSubmit.testId).click();
    await expect(this.page).toHaveURL(/\/siparis\/[^/]+$/);
  }

  /** Sepet satırındaki adedi doğrular. */
  async expectLineQuantity(productCode: string, quantity: number): Promise<void> {
    await expect(this.page.getByTestId(testIdOf(cart.lineQuantity, productCode))).toHaveText(
      String(quantity),
    );
  }

  /** Sepet satırında kampanyayla bedava verilen adedi doğrular. */
  async expectFreeQuantity(productCode: string, quantity: number): Promise<void> {
    await expect(this.page.getByTestId(testIdOf(cart.lineFree, productCode))).toHaveText(
      String(quantity),
    );
  }

  /** Sepet satırının indirim sonrası tutarını doğrular (ör. "150,00 TL"). */
  async expectLineTotal(productCode: string, amount: string): Promise<void> {
    await expect(this.page.getByTestId(testIdOf(cart.lineTotal, productCode))).toHaveText(amount);
  }

  /** Ara toplamı doğrular (ör. "175,00 TL"). */
  async expectSubtotal(amount: string): Promise<void> {
    await expect(this.page.getByTestId(cart.subtotal.testId)).toHaveText(amount);
  }

  /** Kampanya indirimi tutarını doğrular (ör. "25,00 TL"). */
  async expectDiscount(amount: string): Promise<void> {
    await expect(this.page.getByTestId(cart.discount.testId)).toHaveText(amount);
  }

  /** İndirim sonrası genel toplamı doğrular (ör. "150,00 TL"). */
  async expectTotal(amount: string): Promise<void> {
    await expect(this.page.getByTestId(cart.total.testId)).toHaveText(amount);
  }

  /** Minimum sipariş uyarısının verilen metni içerdiğini doğrular (ör. "Minimum sipariş tutarı 750,00 TL"). */
  async expectMinOrderWarning(message: string): Promise<void> {
    await expect(this.page.getByTestId(cart.minOrderWarning.testId)).toContainText(message);
  }

  /** Minimum sipariş uyarısının gösterilmediğini doğrular. */
  async expectNoMinOrderWarning(): Promise<void> {
    await expect(this.page.getByTestId(cart.minOrderWarning.testId)).toHaveCount(0);
  }

  /** "Siparişi onayla" butonunun pasif olduğunu doğrular. */
  async expectCheckoutDisabled(): Promise<void> {
    await expect(this.page.getByTestId(cart.checkoutSubmit.testId)).toBeDisabled();
  }

  /** "Siparişi onayla" butonunun aktif olduğunu doğrular. */
  async expectCheckoutEnabled(): Promise<void> {
    await expect(this.page.getByTestId(cart.checkoutSubmit.testId)).toBeEnabled();
  }

  /** Sepette ürünün bulunmadığını doğrular. */
  async expectProductNotInCart(productCode: string): Promise<void> {
    await expect(this.page.getByTestId(testIdOf(cart.line, productCode))).toHaveCount(0);
  }

  /** Üst menüdeki sepet sayacının verilen adet olduğunu doğrular (sepet sayfasında). */
  async expectCartCount(count: number): Promise<void> {
    await expect(this.page.getByTestId(nav.cartCount.testId)).toHaveText(String(count));
  }

  /** Sepetin boş olduğunu doğrular. */
  async expectEmpty(): Promise<void> {
    await expect(this.page.getByTestId(cart.empty.testId)).toBeVisible();
  }
}
