// AI-generated — AI Testing Probe (CasesToCode). Elle düzenlemeyin; değişiklik case'in yeniden
// onayı ve yeniden üretimle yapılır.
// Case: TPD-1-C2 (3f9b1c2e-0000-5000-8000-0000000000c2) · Story: TPD-1 · Jira Test: TPD-12
// Onaylı case hash: f7a67a7af02b8a418cef1ecd99f091def093ea2e4dc866d50dec36cf3c004573
// Eşleme: verify_and_map · mod: replay · bundle: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
// Eşleme hash: cf31f88a3e9573641b0cbbbbbedc4af4af58f8eee0c9432845c6a88b9611c17f · şablon: 27d7a7d397b6f70fe448639790e56991ed28ed83a025acad14ba76ad00a7f55d
import { test } from "../fixtures";

test.use({ dealerUsername: "bayi1" });

test.describe("TPD-1 · C2", () => {
  test("7 adet kampanyalı üründe 1 adet bedava verilir @tp-uretilen", { tag: ["@tp-case-3f9b1c2e-0000-5000-8000-0000000000c2", "@TPD-1"] }, async ({ cartPage, catalogPage, loginPage }) => {
    // S1 — Giriş sayfasını aç
    await loginPage.goto();
    // S2 — Bayi kullanıcısıyla giriş yap
    await loginPage.login("bayi1", "Demo123!");
    // S3 — "Portakal Gazozu 1L" (P-001) kartında adedi 7 yapıp "Sepete ekle" butonuna bas
    await catalogPage.addToCart("P-001", 7);
    // S4 — Üst menüden sepete git
    await catalogPage.openCart();
    // Beklenen sonuç (değerler onaylı case metninden)
    await cartPage.expectLineQuantity("P-001", 7);
    await cartPage.expectFreeQuantity("P-001", 1);
    await cartPage.expectSubtotal("175,00 TL");
    await cartPage.expectDiscount("25,00 TL");
    await cartPage.expectTotal("150,00 TL");
  });
});
