import { expect, signedInTest as test } from "./fixtures";

test.describe("Sepet (TPD-1)", () => {
  test.beforeEach(async ({ catalogPage }) => {
    await catalogPage.goto();
  });

  test("katalog ürünleri ve fiyatları tr-TR biçiminde gösterir", async ({ catalogPage }) => {
    await catalogPage.expectProductPrice("P-001", "25,00 TL");
    await catalogPage.expectProductPrice("P-002", "15,00 TL");
    await catalogPage.expectProductPrice("P-003", "8,00 TL");
    await catalogPage.expectProductPrice("P-004", "30,00 TL");
    await catalogPage.expectCampaign("P-001", "6 al 1 bedava");
  });

  test("AC1: Sepete ekle ürünü sepete ekler ve sepet sayacı artar", async ({ catalogPage }) => {
    await catalogPage.expectCartCount(0);
    await catalogPage.addToCart("P-002", 1);
    await catalogPage.expectCartCount(1);
    await catalogPage.addToCart("P-003", 2);
    await catalogPage.expectCartCount(3);
  });

  test("kampanya: 7 adet P-001 → 1 bedava, toplam 150,00 TL", async ({ page, catalogPage, cartPage }) => {
    await catalogPage.addToCart("P-001", 7);
    await catalogPage.openCart();
    await cartPage.expectLineQuantity("P-001", 7);
    await cartPage.expectFreeQuantity("P-001", 1);
    await cartPage.expectSubtotal("175,00 TL");
    await cartPage.expectDiscount("25,00 TL");
    // İndirim varsa özet satırı eksi işaretiyle gösterilir.
    await expect(page.getByTestId("cart-discount").locator("xpath=..")).toHaveText("−25,00 TL");
    await cartPage.expectTotal("150,00 TL");
  });

  // 6 adet sınırı burada bilerek doğrulanmaz: "6 adette bedava var mı?" demo senaryosuna bağlıdır
  // (DEMO-VERISI Demo-B: ana yolda C3 "6 → 1 bedava", `f2-kod-hatasi`'nda "6 → bedava yok" ve
  // defect adayı). El yazımı testler yalnızca iki senaryoda da doğru olan davranışı (7 → 1) doğrular;
  // tools/scenario-neutral-check.js bunu denetler.

  test("kampanyasız üründe bedava adet verilmez", async ({ catalogPage, cartPage }) => {
    await catalogPage.addToCart("P-002", 12);
    await catalogPage.openCart();
    await cartPage.expectFreeQuantity("P-002", 0);
    await cartPage.expectDiscount("0,00 TL");
  });

  test("kampanyasız siparişte minimum tutar altında uyarı gösterilir ve onay pasif olur", async ({
    catalogPage,
    cartPage,
  }) => {
    await catalogPage.addToCart("P-002", 10);
    await catalogPage.openCart();
    await cartPage.expectTotal("150,00 TL");
    await cartPage.expectMinOrderWarning("Minimum sipariş tutarı 750,00 TL");
    await cartPage.expectCheckoutDisabled();
  });

  test("kampanyalı siparişte minimum tutar aranmaz", async ({ catalogPage, cartPage }) => {
    // 7 x P-001: toplam minimum tutarın (750,00 TL) çok altında; indirim tutarından bağımsız.
    await catalogPage.addToCart("P-001", 7);
    await catalogPage.openCart();
    await cartPage.expectLineQuantity("P-001", 7);
    await cartPage.expectNoMinOrderWarning();
    await cartPage.expectCheckoutEnabled();
  });

  test("minimum tutara ulaşınca uyarı kalkar ve onay aktif olur", async ({ catalogPage, cartPage }) => {
    await catalogPage.addToCart("P-004", 25);
    await catalogPage.openCart();
    await cartPage.expectTotal("750,00 TL");
    await cartPage.expectNoMinOrderWarning();
    await cartPage.expectCheckoutEnabled();
  });

  test("ürün sepetten kaldırılabilir", async ({ catalogPage, cartPage }) => {
    await catalogPage.addToCart("P-002", 1);
    await catalogPage.addToCart("P-003", 1);
    await catalogPage.openCart();
    await cartPage.removeProduct("P-002");
    await cartPage.expectProductNotInCart("P-002");
    await cartPage.expectLineQuantity("P-003", 1);
    await cartPage.removeProduct("P-003");
    await cartPage.expectEmpty();
  });
});
