import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { parseLocators } from "../src/locators.js";
import { CART_LOCATORS } from "./helpers.js";

function codes(text: string): string[] {
  return parseLocators("pages/x/locators.ts", text).violations.map((v) => v.code);
}

describe("parseLocators — saf veri", () => {
  it("geçerli dosyadan girişleri çıkarır", () => {
    const p = parseLocators("pages/cart/locators.ts", CART_LOCATORS);
    assert.deepEqual(p.violations, []);
    assert.deepEqual(p.exports, ["cart", "cartLines"]);
    assert.deepEqual([...p.entries.keys()], ["cart.addToCart", "cart.cartCount", "cartLines.subtotal"]);
    assert.deepEqual(p.entries.get("cart.addToCart")?.fields, {
      testId: "add-to-cart",
      role: "button",
      name: "Sepete ekle",
      intent: "Ürün kartında sepete ekleme butonu",
    });
  });

  it("iç içe grupları ve tırnaklı anahtarları kabul eder", () => {
    const p = parseLocators(
      "f",
      `export const a = { "grp-1": { inner: { testId: 'x-1', role: \`button\` } } } as const;`,
    );
    assert.deepEqual(p.violations, []);
    assert.deepEqual(p.entries.get("a.grp-1.inner")?.fields, { testId: "x-1", role: "button" });
  });

  it("boş dosya ve yalnızca yorum geçerlidir", () => {
    assert.deepEqual(codes(""), []);
    assert.deepEqual(codes("// yalnızca yorum\n/* blok */\n"), []);
  });

  const bad: Array<[string, string, string]> = [
    ["şablon ifadesi (hesaplanan değer)", "export const a = { k: { testId: `add-${'x'}` } } as const;", "non_literal_value"],
    ["fonksiyon çağrısı", 'export const a = { k: { testId: String("x") } } as const;', "non_literal_value"],
    ["tanımlayıcı başvurusu", 'const v = "x";\nexport const a = { k: { testId: v } } as const;', "forbidden_statement"],
    ["string birleştirme", 'export const a = { k: { testId: "a" + "b" } } as const;', "non_literal_value"],
    ["sayı değeri", "export const a = { k: { testId: 'x', n: 1 } } as const;", "non_literal_value"],
    ["hesaplanan anahtar", 'export const a = { ["k"]: { testId: "x" } } as const;', "computed_key"],
    ["spread", 'const o = {};\nexport const a = { ...o } as const;', "forbidden_statement"],
    ["spread (tek başına)", "export const a = { ...{ k: { testId: 'x' } } } as const;", "spread"],
    ["shorthand", "export const a = { k } as const;", "shorthand_property"],
    ["metot", "export const a = { k() { return 1; } } as const;", "method"],
    ["getter", "export const a = { get k() { return 'x'; } } as const;", "method"],
    ["as const eksik", 'export const a = { k: { testId: "x" } };', "missing_as_const"],
    ["satisfies", 'export const a = { k: { testId: "x" } } satisfies object;', "missing_as_const"],
    ["let", 'export let a = { k: { testId: "x" } } as const;', "forbidden_statement"],
    ["export edilmemiş const", 'const a = { k: { testId: "x" } } as const;', "forbidden_statement"],
    ["import", 'import x from "fs";\nexport const a = {} as const;', "forbidden_statement"],
    ["export default", "export default {};", "forbidden_statement"],
    ["fonksiyon", "export function f() {}", "forbidden_statement"],
    ["ifade deyimi", 'console.log("x");', "forbidden_statement"],
    ["tip takma adı", "export type T = string;", "forbidden_statement"],
    ["çoklu bildirim", "export const a = {} as const, b = {} as const;", "forbidden_statement"],
    ["tip ek açıklaması", "export const a: object = {} as const;", "forbidden_statement"],
    ["düz string export (eski biçim)", 'export const HOME = "home";', "missing_as_const"],
    ["nesne olmayan as const", 'export const a = "x" as const;', "non_literal_value"],
    ["parantezli nesne", 'export const a = ({ k: { testId: "x" } }) as const;', "non_literal_value"],
    ["testId eksik", 'export const a = { k: { role: "button" } } as const;', "entry_missing_testid"],
    ["karışık nesne", 'export const a = { k: { testId: "x", sub: { testId: "y" } } } as const;', "mixed_object"],
    ["yinelenen anahtar", 'export const a = { k: { testId: "x" }, k: { testId: "y" } } as const;', "duplicate_key"],
    ["yinelenen export", 'export const a = {} as const;\nexport const a = {} as const;', "duplicate_key"],
    ["geçersiz testId (boş)", 'export const a = { k: { testId: "" } } as const;', "invalid_testid"],
    ["geçersiz testId (boşluk/tırnak)", "export const a = { k: { testId: \"x\\\" onclick\" } } as const;", "invalid_testid"],
    ["sözdizimi hatası", "export const a = { k: { testId: 'x' } as const;", "parse_error"],
  ];
  for (const [name, text, code] of bad) {
    it(`reddeder: ${name}`, () => {
      assert.ok(codes(text).includes(code), `${code} bekleniyordu, bulundu: ${JSON.stringify(codes(text))}`);
    });
  }

  it("ihlallere satır numarası ekler", () => {
    const p = parseLocators("f", 'export const a = {\n  k: { testId: String("x") },\n} as const;');
    assert.equal(p.violations[0]?.line, 2);
    assert.equal(p.violations[0]?.field, "testId");
  });
});
