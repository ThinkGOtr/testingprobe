import { expect } from "@playwright/test";
import { signedInTest, test } from "./fixtures";

test.describe("Bayi girişi (TPD-4)", () => {
  test("doğru bilgilerle giriş yapılır ve katalog açılır", async ({ loginPage, catalogPage, dealer }) => {
    await loginPage.goto();
    await loginPage.login(dealer.username, dealer.password);
    await loginPage.expectLoggedIn(dealer.name);
    await catalogPage.expectProductVisible("P-001");
  });

  test("hatalı parolada hata mesajı gösterilir", async ({ loginPage, dealer }) => {
    await loginPage.goto();
    await loginPage.login(dealer.username, "YanlisParola1");
    await loginPage.expectLoginError("Kullanıcı adı veya parola hatalı");
    await loginPage.expectOnLoginPage();
  });

  test("oturumsuz kullanıcı giriş sayfasına yönlendirilir", async ({ page, loginPage }) => {
    await page.goto("/sepet");
    await loginPage.expectOnLoginPage();
  });

  // Ajanın "Ham çıktı"sında "Console: N errors" görünmesin: oturumsuz açılış yoklaması ve giriş
  // akışı tarayıcı konsoluna hata (ör. 401 "Failed to load resource") düşürmemeli.
  test("oturumsuz açılış ve giriş konsola hata yazmaz", async ({ page, loginPage, catalogPage, dealer }) => {
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });
    page.on("pageerror", (err) => errors.push(err.message));
    await loginPage.goto();
    await loginPage.expectOnLoginPage();
    await loginPage.login(dealer.username, dealer.password);
    await loginPage.expectLoggedIn(dealer.name);
    await catalogPage.expectProductVisible("P-001");
    expect(errors).toEqual([]);
  });

  signedInTest("çıkış yapınca giriş sayfasına dönülür", async ({ catalogPage, loginPage }) => {
    await catalogPage.goto();
    await loginPage.logout();
    await loginPage.expectOnLoginPage();
  });
});
