import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import { main } from "../src/cli.js";
import { extractSymbols, type PageObjectSymbol, type SymbolTable } from "../src/extract.js";

// dist/test/extract.test.js → repo kökü: ../../../..
const here = dirname(fileURLToPath(import.meta.url));
const DEMO_E2E = resolve(here, "../../../../demo-app/e2e");

function po(table: SymbolTable, cls: string): PageObjectSymbol {
  const found = table.page_objects.find((p) => p.class === cls);
  assert.ok(found, `${cls} sembol tablosunda yok`);
  return found;
}

function fixture(files: Record<string, string>): string {
  const dir = mkdtempSync(join(tmpdir(), "tp-symbols-"));
  for (const [rel, text] of Object.entries(files)) {
    const abs = join(dir, rel);
    mkdirSync(dirname(abs), { recursive: true });
    writeFileSync(abs, text);
  }
  return dir;
}

describe("demo-app/e2e/pages", () => {
  const table = extractSymbols(DEMO_E2E);

  it("dört page object sınıfını hatasız bulur", () => {
    assert.deepEqual(table.errors, []);
    assert.deepEqual(
      table.page_objects.map((p) => [p.class, p.file]),
      [
        ["CartPage", "pages/cart/cart.page.ts"],
        ["CatalogPage", "pages/catalog/catalog.page.ts"],
        ["LoginPage", "pages/login/login.page.ts"],
        ["OrderPage", "pages/order/order.page.ts"],
      ],
    );
  });

  it("CatalogPage.addToCart imzası, türleri, JSDoc ve kind=action", () => {
    const catalog = po(table, "CatalogPage");
    const m = catalog.methods.find((x) => x.name === "addToCart");
    assert.ok(m);
    assert.deepEqual(m.params, [
      { name: "productCode", type: "string", optional: false },
      { name: "quantity", type: "number", optional: false },
    ]);
    assert.equal(m.returns, "Promise<void>");
    assert.equal(m.kind, "action");
    assert.equal(m.async, true);
    assert.match(m.doc, /Sepete ekle/);
  });

  it("expect* metotları kind=expect; private yardımcılar ve constructor dışarıda", () => {
    const catalog = po(table, "CatalogPage");
    const names = catalog.methods.map((m) => m.name);
    assert.ok(!names.includes("card"), "private card() sızmamalı");
    assert.ok(!names.includes("constructor"));
    const price = catalog.methods.find((m) => m.name === "expectProductPrice");
    assert.equal(price?.kind, "expect");
    assert.deepEqual(
      price?.params.map((p) => [p.name, p.type]),
      [
        ["productCode", "string"],
        ["price", "string"],
      ],
    );
    for (const m of catalog.methods) {
      assert.equal(m.kind, m.name.startsWith("expect") ? "expect" : "action", m.name);
    }
  });

  it("OrderPage.readOrderNumber dönüş türü Promise<string>", () => {
    const m = po(table, "OrderPage").methods.find((x) => x.name === "readOrderNumber");
    assert.equal(m?.returns, "Promise<string>");
    assert.deepEqual(m?.params, []);
  });

  it("locator'lar: içe aktarılan export'ların girişleri, within ve önek bilgisi", () => {
    const catalog = po(table, "CatalogPage");
    assert.deepEqual(catalog.locators["catalog.addToCart"], {
      testId: "add-to-cart",
      role: "button",
      name: "Sepete ekle",
      intent: "Ürün kartında sepete ekleme butonu",
      within: "product-card-",
      prefix: false,
      file: "pages/catalog/locators.ts",
      line: catalog.locators["catalog.addToCart"]?.line ?? -1,
    });
    assert.equal(catalog.locators["catalog.productCard"]?.prefix, true);
    // CatalogPage nav'ı da içe aktarır (common/locators.ts).
    assert.equal(catalog.locators["nav.cart"]?.testId, "nav-cart");
    // CartPage nav'ı içe aktarmaz.
    assert.equal(po(table, "CartPage").locators["nav.cart"], undefined);
    assert.equal(po(table, "CartPage").locators["cart.checkoutSubmit"]?.name, "Siparişi onayla");
  });

  it("locator dosyaları ve export'ları listelenir", () => {
    assert.deepEqual(table.locator_files, [
      { file: "pages/cart/locators.ts", exports: ["cart"] },
      { file: "pages/catalog/locators.ts", exports: ["catalog"] },
      { file: "pages/common/locators.ts", exports: ["nav"] },
      { file: "pages/login/locators.ts", exports: ["login"] },
      { file: "pages/order/locators.ts", exports: ["order"] },
    ]);
  });
});

describe("güvenilmeyen / saf olmayan girdi", () => {
  it("saf olmayan locator değeri girişi atlar ve hata listeler; çıkarım çökmez", () => {
    const dir = fixture({
      "pages/x/locators.ts":
        'const p = "a";\nexport const x = {\n  ok: { testId: "ok-id", role: "button", name: "Tamam", intent: "i" },\n  bad: { testId: p, role: "button", name: "Kötü", intent: "i" },\n} as const;\n',
      "pages/x/x.page.ts":
        'import { x } from "./locators";\nexport class XPage {\n  /** Tamam. */\n  async ok(a: string, b = 3): Promise<void> { void x; void a; void b; }\n  protected hidden(): void {}\n  static make(): void {}\n}\n',
    });
    try {
      const t = extractSymbols(dir);
      const xp = po(t, "XPage");
      assert.deepEqual(Object.keys(xp.locators), ["x.ok"]);
      assert.ok(t.errors.some((e) => e.file === "pages/x/locators.ts" && /string literal/.test(e.message)));
      assert.deepEqual(xp.methods.map((m) => m.name), ["ok"]);
      assert.deepEqual(xp.methods[0]?.params[1], { name: "b", type: "number", optional: true, default: "3" });
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("iç içe locator nesneleri nokta ile adlandırılır", () => {
    const dir = fixture({
      "pages/c/locators.ts":
        'export const cart = {\n  lines: {\n    subtotal: { testId: "cart-subtotal", role: "cell", name: "Ara toplam", intent: "i" },\n  },\n} as const;\n',
      "pages/c/c.page.ts": 'import { cart as c } from "./locators";\nexport class CPage { go(): void { void c; } }\n',
    });
    try {
      const t = extractSymbols(dir);
      assert.equal(po(t, "CPage").locators["cart.lines.subtotal"]?.testId, "cart-subtotal");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("CLI: --root yoksa 2; pages yoksa 2 + JSON hata", () => {
    const out: string[] = [];
    const io = { stdout: (s: string) => out.push(s), stderr: () => undefined };
    assert.equal(main([], io), 2);
    const dir = mkdtempSync(join(tmpdir(), "tp-symbols-empty-"));
    try {
      assert.equal(main(["--root", dir], io), 2);
      assert.equal(JSON.parse(out.at(-1) ?? "{}").ok, false);
      assert.equal(main(["--root", DEMO_E2E], io), 0);
      assert.equal(JSON.parse(out.at(-1) ?? "{}").page_objects.length, 4);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
