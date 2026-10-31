// Üretilen testler için ESLint kurallarının öz denetimi (npm run lint:generated-selftest).
// Şablona uygun örnek temiz geçmeli; sözleşmeyi çiğneyen her örnek en az bir hata vermelidir.
// Örnekler geçici olarak tests/generated/ altına yazılır (kurallar yola bağlıdır) ve silinir.
import console from "node:console";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import process from "node:process";
import { URL, fileURLToPath } from "node:url";
import { ESLint } from "eslint";

const root = fileURLToPath(new URL("..", import.meta.url));
const dir = join(root, "tests", "generated");

const header = 'import { signedInTest as test } from "../fixtures";\n';
const body = (inner) =>
  `${header}\ntest.describe("TPD-1 · örnek", () => {\n  test("örnek", async ({ catalogPage, cartPage }) => {\n${inner}\n  });\n});\n`;

const good = {
  "sablon-oturumlu": body(
    '    await catalogPage.goto();\n    await catalogPage.addToCart("P-001", 7);\n' +
      '    await catalogPage.openCart();\n    await cartPage.expectFreeQuantity("P-001", 1);',
  ),
  "sablon-giris": [
    'import { test } from "../fixtures";',
    "",
    'test.use({ dealerUsername: "bayi2" });',
    "",
    'test("örnek", async ({ loginPage, catalogPage }) => {',
    "  await loginPage.goto();",
    '  await loginPage.login("bayi2", "Demo123!");',
    '  await loginPage.expectLoggedIn("Sahil Bayi");',
    "  await catalogPage.expectCartCount(0);",
    "});",
    "",
  ].join("\n"),
  // core codegen şablonunun (playwright_test.ts.j2) birebir biçimi: seçenek nesnesi + etiketler.
  "sablon-core": [
    "// AI-generated — AI Testing Probe (CasesToCode).",
    'import { test } from "../fixtures";',
    "",
    'test.use({ dealerUsername: "bayi1" });',
    "",
    'test.describe("TPD-1 · C2", () => {',
    '  test("7 adet @tp-uretilen", { tag: ["@tp-case-x", "@TPD-1"] }, async ({ cartPage, catalogPage, loginPage }) => {',
    "    // S1 — Giriş sayfasını aç",
    "    await loginPage.goto();",
    '    await loginPage.login("bayi1", "Demo123!");',
    '    await catalogPage.addToCart("P-001", 7);',
    "    await catalogPage.openCart();",
    '    await cartPage.expectFreeQuantity("P-001", 1);',
    '    await cartPage.expectTotal("150,00 TL");',
    "  });",
    "});",
    "",
  ].join("\n"),
};

const bad = {
  "playwright-dogrudan": 'import { test, expect } from "@playwright/test";\ntest("x", async ({ page }) => { await expect(page).toHaveTitle("x"); });\n',
  "locators-ice-aktarma": `import { catalog } from "../../pages/catalog/locators";\n${body("    await catalogPage.goto();\n    void catalog;")}`,
  "fixtures-expect": body('    await cartPage.goto();').replace("signedInTest as test", "signedInTest as test, expect"),
  "ham-page": header + 'test("x", async ({ page, cartPage }) => { await page.goto("/"); await cartPage.expectEmpty(); });\n',
  "test-fail": body("    test.fail();\n    await cartPage.expectEmpty();"),
  "kosul": body('    if (Date.now() > 0) await cartPage.expectTotal("1,00 TL");\n    await catalogPage.goto();'),
  "dongu": body('    for (const k of ["P-001"]) await catalogPage.addToCart(k, 1);\n    await cartPage.expectEmpty();'),
  "baseurl-use": `${header}test.use({ baseURL: "http://evil" });\ntest("x", async ({ cartPage }) => { await cartPage.expectEmpty(); });\n`,
  "dinamik-import": body('    await import("node:fs");\n    await cartPage.expectEmpty();'),
  "process-env": body('    await catalogPage.addToCart(process.env.X ?? "P-001", 1);\n    await cartPage.expectEmpty();'),
  // İzin listesi: yasak listesinin kaçırdığı yollar (inceleme bulgusu).
  "hesaplanmis-uye-page": body('    await cartPage["page"].goto("http://evil.example/");'),
  "globalthis-fetch": body('    await globalThis.fetch("http://evil.example/");\n    await cartPage.expectEmpty();'),
  "constructor-zinciri": body('    await cartPage.goto.constructor("return 1")();'),
  "private-page-uyesi": body('    await cartPage.page.goto("http://evil.example/");'),
  "fikstur-olmayan-param": header + 'test("x", async ({ cartPage, baseURL }) => { await cartPage.expectEmpty(); void baseURL; });\n',
  "literal-olmayan-arguman": body('    await catalogPage.addToCart("P-001", Number("7"));'),
  "degisken": body('    const n = 7;\n    await catalogPage.addToCart("P-001", n);'),
  "await-yok": body("    void cartPage.expectEmpty();"),
  "bilinmeyen-metot": body('    await cartPage.evaluate("1");'),
  "ic-ice-islev": body("    await cartPage.expectEmpty();\n    await catalogPage.goto();\n  });\n  test(\"y\", async ({ cartPage }) => {\n    await (async () => { await cartPage.expectEmpty(); })();"),
};

mkdirSync(dir, { recursive: true });
const files = [];
const write = (name, text) => {
  const f = join(dir, `__ozdenetim-${name}.spec.ts`);
  writeFileSync(f, text);
  files.push(f);
  return f;
};

let failed = 0;
try {
  const goodFiles = Object.entries(good).map(([n, t]) => [n, write(n, t)]);
  const badFiles = Object.entries(bad).map(([n, t]) => [n, write(n, t)]);
  const eslint = new ESLint({ cwd: root, allowInlineConfig: false });
  for (const [name, f] of goodFiles) {
    const [r] = await eslint.lintFiles([f]);
    const msgs = r?.messages ?? [];
    if (msgs.length) {
      failed++;
      console.error(`HATA: şablona uygun örnek '${name}' reddedildi:\n${msgs.map((m) => `  ${m.ruleId}: ${m.message}`).join("\n")}`);
    } else console.log(`ok  geçer   ${name}`);
  }
  for (const [name, f] of badFiles) {
    const [r] = await eslint.lintFiles([f]);
    const errors = (r?.messages ?? []).filter((m) => m.severity === 2);
    // Başka bir kural (ör. kullanılmayan değişken) tesadüfen yakalamasın: sözleşme kuralı yakalamalı.
    if (!errors.some((m) => m.ruleId?.startsWith("no-restricted-"))) {
      failed++;
      console.error(`HATA: sözleşmeyi çiğneyen örnek '${name}' geçti`);
    } else console.log(`ok  reddedilir ${name} (${[...new Set(errors.map((m) => m.ruleId))].join(", ")})`);
  }
} finally {
  for (const f of files) rmSync(f, { force: true });
}
if (failed) process.exit(1);
console.log("Üretilen test lint sözleşmesi: tamam");
