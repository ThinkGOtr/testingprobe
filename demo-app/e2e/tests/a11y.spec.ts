import AxeBuilder from "@axe-core/playwright";
import type { Page, TestInfo } from "@playwright/test";
import { expect, signedInTest, test } from "./fixtures";

// Erişilebilirlik denetimi (WCAG 2.x A/AA). Tüm ihlaller ek olarak raporlanır (Kontrol Kulesi sayar);
// test yalnızca "critical" etkili ihlalde kırmızı olur.
async function audit(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  const byImpact: Record<string, number> = {};
  for (const v of results.violations) {
    const impact = v.impact ?? "unknown";
    byImpact[impact] = (byImpact[impact] ?? 0) + v.nodes.length;
  }
  const summary = {
    page: name,
    url: page.url(),
    violations: results.violations.length,
    nodes: results.violations.reduce((n, v) => n + v.nodes.length, 0),
    byImpact,
    details: results.violations.map((v) => ({
      id: v.id,
      impact: v.impact,
      help: v.help,
      nodes: v.nodes.map((n) => n.target.join(" ")),
    })),
  };
  await testInfo.attach(`axe-${name}.json`, {
    body: JSON.stringify(summary, null, 2),
    contentType: "application/json",
  });
  testInfo.annotations.push({ type: "axe-violations", description: `${name}: ${summary.violations}` });
  const critical = results.violations.filter((v) => v.impact === "critical");
  expect(critical, `kritik erişilebilirlik ihlali: ${critical.map((v) => v.id).join(", ")}`).toEqual([]);
}

test.describe("Erişilebilirlik @a11y", () => {
  signedInTest("katalog sayfası", async ({ page, catalogPage }, testInfo) => {
    await catalogPage.goto();
    await audit(page, testInfo, "katalog");
  });

  signedInTest("sepet sayfası (uyarı ve satırlarla)", async ({ page, catalogPage, cartPage }, testInfo) => {
    await catalogPage.goto();
    await catalogPage.addToCart("P-002", 10);
    await catalogPage.addToCart("P-003", 2);
    await cartPage.goto();
    await cartPage.expectMinOrderWarning("Minimum sipariş tutarı 750,00 TL");
    await audit(page, testInfo, "sepet");
  });

  test("giriş sayfası (hata mesajıyla)", async ({ page, loginPage, dealer }, testInfo) => {
    await loginPage.goto();
    await loginPage.login(dealer.username, "YanlisParola1");
    await loginPage.expectLoginError("Kullanıcı adı veya parola hatalı");
    await audit(page, testInfo, "giris");
  });
});
