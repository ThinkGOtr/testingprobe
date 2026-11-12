// AI-generated — AI Testing Probe (CasesToCode). Elle düzenlemeyin; değişiklik case'in yeniden
// onayı ve yeniden üretimle yapılır.
// Case: TPD-1-C5 (3f9b1c2e-0000-5000-8000-0000000000c2) · Story: TPD-1 · Jira Test: TPD-12
// Onaylı case hash: 3e66acd59590b2ce958925015275de88a1632e0c781dcd402cad8bae282ab314
// Eşleme: verify_and_map · mod: replay · bundle: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
// Eşleme hash: 18be7e17169d01382b9beb24030ccb95b9183844da0508044aea8ac9155073a6 · şablon: 27d7a7d397b6f70fe448639790e56991ed28ed83a025acad14ba76ad00a7f55d
import { test } from "../fixtures";

test.use({ dealerUsername: "bayi1" });

test.describe("TPD-1 · C5", () => {
  test("Kampanyasız siparişte minimum tutarın altında uyarı gösterilir ve onay pasif olur @tp-uretilen", { tag: ["@tp-case-3f9b1c2e-0000-5000-8000-0000000000c2", "@TPD-1"] }, async ({ cartPage, catalogPage, loginPage }) => {
    // S1 — Giriş sayfasını aç
    await loginPage.goto();
    // S2 — Bayi kullanıcısıyla giriş yap
    await loginPage.login("bayi1", "Demo123!");
    // S3 — "Limonata 330ml" (P-002) kartında adedi 10 yapıp "Sepete ekle" butonuna bas
    await catalogPage.addToCart("P-002", 10);
    // S4 — Üst menüden sepete git
    await catalogPage.openCart();
    // Beklenen sonuç (değerler onaylı case metninden)
    await cartPage.expectTotal("150,00 TL");
    await cartPage.expectMinOrderWarning("Minimum sipariş tutarı 750,00 TL");
    await cartPage.expectCheckoutDisabled();
  });
});
