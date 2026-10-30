import { expect, type Page } from "@playwright/test";
import { nav } from "../common/locators";
import { paths, testIdOf } from "../support";
import { order } from "./locators";

const ORDER_NUMBER = /^SP-\d{6}$/;

/** Sipariş onayı ve sipariş geçmişi. */
export class OrderPage {
  constructor(private readonly page: Page) {}

  /** Sipariş geçmişi sayfasını açar. */
  async gotoHistory(): Promise<void> {
    await this.page.goto(paths.orders);
    await expect(
      this.page.getByTestId(order.ordersTable.testId).or(this.page.getByTestId(order.ordersEmpty.testId)),
    ).toBeVisible();
  }

  /** Üst menüden sipariş geçmişine gider. */
  async openHistory(): Promise<void> {
    await this.page.getByTestId(nav.orders.testId).click();
    await expect(this.page).toHaveURL(new RegExp(`${paths.orders}$`));
  }

  /** Onay sayfasındaki sipariş numarasını okur. */
  async readOrderNumber(): Promise<string> {
    const el = this.page.getByTestId(order.orderNumber.testId);
    await expect(el).toHaveText(ORDER_NUMBER);
    return (await el.innerText()).trim();
  }

  /** Sipariş onayının ve sipariş numarasının gösterildiğini doğrular. */
  async expectConfirmation(): Promise<void> {
    await expect(this.page.getByTestId(order.confirmation.testId)).toBeVisible();
    await expect(this.page.getByTestId(order.orderNumber.testId)).toHaveText(ORDER_NUMBER);
  }

  /** Onaylanan siparişin genel toplamını doğrular (ör. "1.025,00 TL"). */
  async expectConfirmedTotal(amount: string): Promise<void> {
    await expect(this.page.getByTestId(order.orderTotal.testId)).toHaveText(amount);
  }

  /** Onay sayfasında gösterilen siparişin sipariş geçmişinde listelendiğini doğrular. */
  async expectConfirmedOrderInHistory(): Promise<void> {
    const orderNumber = await this.readOrderNumber();
    await this.openHistory();
    await this.expectOrderInHistory(orderNumber);
  }

  /** Verilen sipariş numarasının sipariş geçmişinde listelendiğini doğrular. */
  async expectOrderInHistory(orderNumber: string): Promise<void> {
    await expect(this.page.getByTestId(testIdOf(order.orderRow, orderNumber))).toBeVisible();
  }

  /** Sipariş geçmişindeki siparişin genel toplamını doğrular. */
  async expectOrderTotalInHistory(orderNumber: string, amount: string): Promise<void> {
    await expect(this.page.getByTestId(testIdOf(order.orderRowTotal, orderNumber))).toHaveText(amount);
  }

  /** Sipariş geçmişinin boş olduğunu doğrular. */
  async expectNoOrders(): Promise<void> {
    await expect(this.page.getByTestId(order.ordersEmpty.testId)).toBeVisible();
  }
}
