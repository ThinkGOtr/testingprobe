// locators.ts sözleşmesi: role + name meta verisi uygulamayla tutarlı olmalı.
// Locator onarımı (TEKNIK-TASARIM §8.7) kırılan testId'nin adayını getByRole(role, { name }) ile
// bulur; bu test, adı olan her locator'ın rol + adla bulunan elemanlarının o testId'yi
// (önek locator'larda o önekle başlayan testId'yi) taşıdığını doğrular. Rol + ad sayfada birden
// fazla elemana uyuyorsa locator `within` (kapsayıcı testId öneki) taşımalıdır ve her kapsayıcının
// içinde rol + ad TAM OLARAK bir elemana uymalıdır; onarım adayı o kapsayıcıda aranır.
import type { Locator, Page, TestInfo } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { cart } from "../pages/cart/locators";
import { catalog } from "../pages/catalog/locators";
import { nav } from "../pages/common/locators";
import { login } from "../pages/login/locators";
import { order } from "../pages/order/locators";
import { testIdOf, type LocatorSpec } from "../pages/support";
import { expect, signedInTest, test } from "./fixtures";

type AriaRole = Parameters<Page["getByRole"]>[0];

/**
 * testId'nin kendisi sayfada var mı. Kırık bir testId (ör. uygulamada değişmiş) burada rol/ad
 * karşılaştırmasından (assertion) ÖNCE, page object'lerle aynı biçimde bir locator hatası
 * ("element(s) not found", `getByTestId('…')`) olarak görünür: triage bunu test bakımı sayar.
 */
async function expectTestIdPresent(page: Page, key: string, spec: LocatorSpec): Promise<void> {
  const isPrefix = spec.testId.endsWith("-");
  let target: Locator;
  if (spec.within) {
    const firstScope = await page.locator(`[data-testid^="${spec.within}"]`).first().getAttribute("data-testid");
    const suffix = (firstScope ?? "").slice(spec.within.length);
    target = page.getByTestId(firstScope ?? spec.within).getByTestId(testIdOf(spec, isPrefix ? suffix : undefined));
  } else {
    target = isPrefix ? page.locator(`[data-testid^="${spec.testId}"]`).first() : page.getByTestId(spec.testId);
  }
  await expect(target.first(), `${key}: testId '${spec.testId}' sayfada bulunamadı`).toBeAttached();
}

async function expectRoleNameMatchesTestId(page: Page, group: Record<string, LocatorSpec>): Promise<void> {
  for (const [key, spec] of Object.entries(group)) {
    if (!spec.name) continue;
    await expectTestIdPresent(page, key, spec);
    const matches = page.getByRole(spec.role as AriaRole, { name: spec.name });
    await expect(matches.first(), `${key}: rol '${spec.role}' + ad '${spec.name}' bulunamadı`).toBeVisible();
    const ids = await matches.evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
    const ok = ids.every((id) =>
      spec.testId.endsWith("-") ? (id ?? "").startsWith(spec.testId) : id === spec.testId,
    );
    expect(ok, `${key}: rol + ad ile bulunan testId'ler ${JSON.stringify(ids)} ≠ '${spec.testId}'`).toBe(true);
    if (ids.length > 1 || spec.within) {
      expect(spec.within, `${key}: rol + ad ${ids.length} elemana uyuyor; 'within' kapsamı gerekli`).toBeTruthy();
      await expectUniqueWithinScope(page, key, spec);
    }
  }
}

/** Her kapsayıcıda (within önekiyle başlayan testId) rol + ad tam olarak bir elemana uyar. */
async function expectUniqueWithinScope(page: Page, key: string, spec: LocatorSpec): Promise<void> {
  const within = spec.within ?? "";
  const scopes = page.locator(`[data-testid^="${within}"]`);
  const scopeIds = await scopes.evaluateAll((els) => els.map((e) => e.getAttribute("data-testid") ?? ""));
  expect(scopeIds.length, `${key}: '${within}' kapsayıcısı bulunamadı`).toBeGreaterThan(0);
  for (const scopeId of scopeIds) {
    const inScope = page.getByTestId(scopeId).getByRole(spec.role as AriaRole, { name: spec.name });
    await expect(inScope, `${key}: ${scopeId} içinde rol + ad tek elemana uymalı`).toHaveCount(1);
    // Önek locator'da beklenen testId kapsayıcının soneğini taşır: product-card-P-001 → qty-input-P-001.
    const suffix = scopeId.slice(within.length);
    await expect(inScope).toHaveAttribute("data-testid", testIdOf(spec, spec.testId.endsWith("-") ? suffix : undefined));
  }
}

/**
 * Son yeşil durumun aria snapshot'ı (TEKNIK-TASARIM §8.7 doğrulama girdisi).
 *
 * Sözleşme bu sayfada geçtikten SONRA sayfanın (`body`) aria snapshot'ı koşu çıktısına
 * `<sayfa>.aria.yml` olarak yazılır ve rapora eklenir. Locator onarımı kırık koşudan önceki son
 * yeşil koşunun artefaktlarında bu dosyayı bulur (`*aria*.yml`) ve aday rol + adı ona karşı
 * doğrular. Yalnızca sözleşme geçince yazıldığı için dosya, rol + adın doğru testId'ye karşılık
 * geldiği bir durumu kanıtlar; kırık koşuda yazılmaz.
 */
async function writeAriaSnapshot(
  page: Page,
  testInfo: TestInfo,
  pageName: string,
  group: Record<string, LocatorSpec>,
): Promise<void> {
  const snapshot = await page.locator("body").ariaSnapshot();
  // Öz-denetim: adı olan her locator'ın rol + adı snapshot'ta görünmeli (onarım bunu arayacak).
  // getByRole adı alt dizgi olarak eşler ("Sepet" → link "Sepet 0 ürün"); burada da ad önek olarak
  // aranır. Onarımın aria doğrulaması ise adı birebir eşler.
  for (const [key, spec] of Object.entries(group)) {
    if (!spec.name) continue;
    expect(snapshot, `${key}: aria snapshot'ta ${spec.role} "${spec.name}" yok`).toContain(
      `- ${spec.role} "${spec.name}`,
    );
  }
  // Tek dosya: testInfo.attach kopyası (attachments/) aynı kalıba uyup kanıtı çoğaltmasın diye eklenmez.
  writeFileSync(testInfo.outputPath(`${pageName}.aria.yml`), `${snapshot}\n`, "utf-8");
}

test.describe("locators.ts rol/ad sözleşmesi", () => {
  test("giriş sayfası", async ({ page, loginPage, dealer }, testInfo) => {
    await loginPage.goto();
    await loginPage.login(dealer.username, "YanlisParola1");
    await loginPage.expectLoginError("Kullanıcı adı veya parola hatalı");
    await expectRoleNameMatchesTestId(page, login);
    await writeAriaSnapshot(page, testInfo, "giris", login);
  });

  signedInTest(
    "menü, katalog, sepet ve sipariş sayfaları",
    async ({ page, catalogPage, cartPage, orderPage }, testInfo) => {
      await catalogPage.goto();
      await expectRoleNameMatchesTestId(page, nav);
      await expectRoleNameMatchesTestId(page, catalog);
      await writeAriaSnapshot(page, testInfo, "katalog", { ...nav, ...catalog });
      await catalogPage.addToCart("P-004", 30);
      await cartPage.goto();
      await expectRoleNameMatchesTestId(page, cart);
      await writeAriaSnapshot(page, testInfo, "sepet", cart);
      await cartPage.checkout();
      await orderPage.expectConfirmation();
      const { confirmation, orderNumber, orderTotal } = order;
      await expectRoleNameMatchesTestId(page, { confirmation, orderNumber, orderTotal });
      await writeAriaSnapshot(page, testInfo, "siparis", { confirmation, orderNumber, orderTotal });
      await orderPage.openHistory();
      const { ordersTable, orderRow, orderRowTotal } = order;
      await expectRoleNameMatchesTestId(page, { ordersTable, orderRow, orderRowTotal });
      await writeAriaSnapshot(page, testInfo, "siparis-gecmisi", { ordersTable, orderRow, orderRowTotal });
    },
  );
});
