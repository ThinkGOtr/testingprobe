// AI-generated — AI Testing Probe (CasesToCode). Elle düzenlemeyin; değişiklik case'in yeniden
// onayı ve yeniden üretimle yapılır.
// Case: TPD-1-C8 (3f9b1c2e-0000-5000-8000-0000000000c2) · Story: TPD-1 · Jira Test: TPD-12
// Onaylı case hash: 2fc379c5df7649b09a3b2714ff1741a2e737dcfa2fc1c86d6aa6ec20f456d8ea
// Eşleme: verify_and_map · mod: replay · bundle: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
// Eşleme hash: 8dc6a6c380c6e9cb46deedf753811911e83a9098bcadacc769fd7661513aae4e · şablon: 27d7a7d397b6f70fe448639790e56991ed28ed83a025acad14ba76ad00a7f55d
import { test } from "../fixtures";

test.use({ dealerUsername: "bayi1" });

test.describe("TPD-1 · C8", () => {
  test("Onaylanan siparişin numarası gösterilir ve sipariş geçmişinde listelenir @tp-uretilen", { tag: ["@tp-case-3f9b1c2e-0000-5000-8000-0000000000c2", "@TPD-1"] }, async ({ cartPage, catalogPage, loginPage, orderPage }) => {
    // S1 — Giriş sayfasını aç
    await loginPage.goto();
    // S2 — Bayi kullanıcısıyla giriş yap
    await loginPage.login("bayi1", "Demo123!");
    // S3 — "Şeftalili Soğuk Çay 1L" (P-004) kartında adedi 25 yapıp "Sepete ekle" butonuna bas
    await catalogPage.addToCart("P-004", 25);
    // S4 — Üst menüden sepete git
    await catalogPage.openCart();
    // S5 — "Siparişi onayla" butonuna bas
    await cartPage.checkout();
    // Beklenen sonuç (değerler onaylı case metninden)
    await orderPage.expectConfirmation();
    await orderPage.expectConfirmedTotal("750,00 TL");
    await orderPage.expectConfirmedOrderInHistory();
  });
});
