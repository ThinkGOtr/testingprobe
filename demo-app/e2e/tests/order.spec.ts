import { expect, signedInTest as test } from "./fixtures";

test.describe("Sipariş onayı ve geçmiş (TPD-1 AC5)", () => {
  // Sıfırlanmış veri gerektirir; TP_E2E_NO_RESET=1 (yalnızca sepet yalıtımı) modunda dışlanır.
  test("siparişi olmayan bayide boş geçmiş bilgisi gösterilir @sifir-veri", async ({ orderPage }) => {
    await orderPage.gotoHistory();
    await orderPage.expectNoOrders();
  });

  test("onaylanan sipariş numarasıyla gösterilir ve geçmişte listelenir", async ({
    catalogPage,
    cartPage,
    orderPage,
  }) => {
    await catalogPage.goto();
    await catalogPage.addToCart("P-004", 30);
    await catalogPage.addToCart("P-001", 7);
    await catalogPage.openCart();
    await cartPage.expectTotal("1.050,00 TL");
    await cartPage.checkout();
    await orderPage.expectConfirmation();
    await orderPage.expectConfirmedTotal("1.050,00 TL");
    await catalogPage.expectCartCount(0);
    const orderNumber = await orderPage.readOrderNumber();
    await orderPage.expectConfirmedOrderInHistory();
    await orderPage.expectOrderTotalInHistory(orderNumber, "1.050,00 TL");
  });

  test("minimum tutarın altındaki sepet API'de de reddedilir", async ({ page, catalogPage }) => {
    await catalogPage.goto();
    await catalogPage.addToCart("P-003", 1);
    const resp = await page.request.post("/api/orders");
    expect(resp.status()).toBe(422);
    expect(await resp.json()).toEqual({ detail: "Minimum sipariş tutarı 750,00 TL" });
  });
});
