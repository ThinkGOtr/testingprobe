// locators.ts sözleşmesi: role + name meta verisi uygulamayla tutarlı olmalı.
// Locator onarımı (TEKNIK-TASARIM §8.7) kırılan testId'nin adayını getByRole(role, { name }) ile
// bulur; bu test, adı olan her locator'ın rol + adla bulunan elemanlarının o testId'yi
// (önek locator'larda o önekle başlayan testId'yi) taşıdığını doğrular. Rol + ad sayfada birden
// fazla elemana uyuyorsa locator `within` (kapsayıcı testId öneki) taşımalıdır ve her kapsayıcının
// içinde rol + ad TAM OLARAK bir elemana uymalıdır; onarım adayı o kapsayıcıda aranır.
import type { Page } from "@playwright/test";
import { cart } from "../pages/cart/locators";
import { catalog } from "../pages/catalog/locators";
import { nav } from "../pages/common/locators";
import { login } from "../pages/login/locators";
import { order } from "../pages/order/locators";
import { testIdOf, type LocatorSpec } from "../pages/support";
import { expect, signedInTest, test } from "./fixtures";

type AriaRole = Parameters<Page["getByRole"]>[0];

async function expectRoleNameMatchesTestId(page: Page, group: Record<string, LocatorSpec>): Promise<void> {
  for (const [key, spec] of Object.entries(group)) {
    if (!spec.name) continue;
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

test.describe("locators.ts rol/ad sözleşmesi", () => {
  test("giriş sayfası", async ({ page, loginPage, dealer }) => {
    await loginPage.goto();
    await loginPage.login(dealer.username, "YanlisParola1");
    await loginPage.expectLoginError("Kullanıcı adı veya parola hatalı");
    await expectRoleNameMatchesTestId(page, login);
  });

  signedInTest("menü, katalog, sepet ve sipariş sayfaları", async ({ page, catalogPage, cartPage, orderPage }) => {
    await catalogPage.goto();
    await expectRoleNameMatchesTestId(page, nav);
    await expectRoleNameMatchesTestId(page, catalog);
    await catalogPage.addToCart("P-004", 30);
    await cartPage.goto();
    await expectRoleNameMatchesTestId(page, cart);
    await cartPage.checkout();
    await orderPage.expectConfirmation();
    const { confirmation, orderNumber, orderTotal } = order;
    await expectRoleNameMatchesTestId(page, { confirmation, orderNumber, orderTotal });
    await orderPage.openHistory();
    const { ordersTable, orderRow, orderRowTotal } = order;
    await expectRoleNameMatchesTestId(page, { ordersTable, orderRow, orderRowTotal });
  });
});
