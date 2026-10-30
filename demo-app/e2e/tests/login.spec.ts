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

  signedInTest("çıkış yapınca giriş sayfasına dönülür", async ({ catalogPage, loginPage }) => {
    await catalogPage.goto();
    await loginPage.logout();
    await loginPage.expectOnLoginPage();
  });
});
