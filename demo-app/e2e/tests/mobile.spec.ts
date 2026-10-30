// Dar ekran (390 px) yerleşimi: sepet satırının tutarı ve "Kaldır" butonu yatay kaydırma
// olmadan görünür; indirim yokken eksi işareti gösterilmez.
import { expect, signedInTest as test } from "./fixtures";

test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

test.describe("Mobil sepet yerleşimi", () => {
  test("satır tutarı ve Kaldır butonu kaydırmadan görünür", async ({ page, catalogPage, cartPage }) => {
    await catalogPage.goto();
    await catalogPage.addToCart("P-004", 24);
    await catalogPage.addToCart("P-001", 7);
    await cartPage.goto();

    const pageOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(pageOverflow, "sayfa yatay kaydırma gerektirmemeli").toBeLessThanOrEqual(0);

    const wrap = page.locator(".table-wrap");
    const wrapOverflow = await wrap.evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(wrapOverflow, "sepet tablosu yatay kaydırma gerektirmemeli").toBeLessThanOrEqual(0);

    for (const code of ["P-004", "P-001"]) {
      const total = page.getByTestId(`cart-line-total-${code}`);
      const remove = page.getByTestId(`cart-line-remove-${code}`);
      await expect(total).toBeInViewport({ ratio: 1 });
      await expect(remove).toBeInViewport({ ratio: 1 });
      // Kart görünümünde sütun başlığı her değerin yanında etiket olarak görünür.
      await expect(total).toHaveAttribute("data-label", "Tutar");
    }
    // Yalnızca yerleşim: kampanya tutarları cart.spec'te (BREAK_CAMPAIGN'da bu test yeşil kalır).
    await cartPage.expectLineTotal("P-004", "720,00 TL");

    await cartPage.removeProduct("P-004");
    await cartPage.expectProductNotInCart("P-004");
  });

  test("indirim yokken eksi işareti gösterilmez", async ({ page, catalogPage, cartPage }) => {
    await catalogPage.goto();
    await catalogPage.addToCart("P-002", 2);
    await cartPage.goto();
    await cartPage.expectDiscount("0,00 TL");
    await expect(page.getByTestId("cart-discount").locator("xpath=..")).toHaveText("0,00 TL");
  });
});
