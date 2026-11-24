// repair modu: web testlerinin diğer dillerdeki kimlik bağları (Kimlikler.java / .cs / kimlikler.py)
// yalnız aynı diff'teki locators.ts testId değişikliğiyle eşli literal olarak değişebilir.
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { isBindingPath, runGuard, type Report } from "../src/guard.js";
import { DirSource } from "../src/sources.js";
import { BASE_TREE, makePair, type Tree } from "./helpers.js";

const ROOT = "demo-app/e2e";
const JAVA = "demo-app/e2e-java/src/test/java/com/antreklabs/bayi/ekranlar/Kimlikler.java";
const APP_JAVA = "demo-app/e2e-app/src/test/java/com/antreklabs/bayi/ekranlar/Kimlikler.java";
const CS = "demo-app/e2e-csharp/Pages/Kimlikler.cs";
const PY = "demo-app/e2e-python/pages/kimlikler.py";
const LOC = `${ROOT}/pages/cart/locators.ts`;

const JAVA_METIN = `package x;\n\n/** "yorum" */\npublic final class Kimlikler {\n  public static final class Sepet {\n    public static final String ADD_TO_CART = "add-to-cart";\n    public static final String SUBTOTAL = "cart-subtotal";\n  }\n}\n`;
const CS_METIN = `public static class Kimlikler\n{\n    public const string ADD_TO_CART = "add-to-cart";\n}\n`;
const PY_METIN = `CART = {\n    "addToCart": {"testId": "add-to-cart", "intent": "Sepete ekle"},\n}\n`;

const TABAN: Tree = {
  ...Object.fromEntries(Object.entries(BASE_TREE).map(([k, v]) => [`${ROOT}/${k}`, v])),
  [JAVA]: JAVA_METIN,
  [APP_JAVA]: JAVA_METIN,
  [CS]: CS_METIN,
  [PY]: PY_METIN,
};
const LOC_ONARIM = TABAN[LOC]!.replace('testId: "add-to-cart"', 'testId: "cart-add"');

function guard(changes: Record<string, string | null>): Report {
  const p = makePair(TABAN, changes);
  return runGuard(new DirSource(p.base), new DirSource(p.head), { mode: "repair", root: ROOT });
}
const codes = (r: Report): string[] => r.violations.map((v) => v.code);

describe("repair modu: kimlik bağları", () => {
  it("yol tanıma: yalnız web e2e kökünün kardeşi; uygulama (e2e-app) ve kök '.' hariç", () => {
    assert.equal(isBindingPath(JAVA, ROOT), true);
    assert.equal(isBindingPath(CS, ROOT), true);
    assert.equal(isBindingPath(PY, ROOT), true);
    assert.equal(isBindingPath(APP_JAVA, ROOT), false);
    assert.equal(isBindingPath("demo-app/e2e-java/src/test/java/x/Diger.java", ROOT), false);
    assert.equal(isBindingPath("e2e-java/src/test/java/ekranlar/Kimlikler.java", "."), false);
    assert.equal(isBindingPath("e2e-java/src/test/java/ekranlar/Kimlikler.java", "e2e"), true);
  });

  it("locators.ts + Java + C# + Python eşli değişiklik: geçer", () => {
    const r = guard({
      [LOC]: LOC_ONARIM,
      [JAVA]: JAVA_METIN.replace('"add-to-cart"', '"cart-add"'),
      [CS]: CS_METIN.replace('"add-to-cart"', '"cart-add"'),
      [PY]: PY_METIN.replace('"add-to-cart"', '"cart-add"'),
    });
    assert.equal(r.ok, true, JSON.stringify(r.violations));
    assert.equal(r.testid_changes.length, 4);
    assert.equal(r.changed_files.filter((c) => c.binding).length, 3);
  });

  it("locators.ts değişmeden yalnız Java: eşsiz değişiklik", () => {
    const r = guard({ [JAVA]: JAVA_METIN.replace('"add-to-cart"', '"cart-add"') });
    assert.equal(r.ok, false);
    assert.ok(codes(r).includes("binding_change_unpaired"));
  });

  it("Java'da eşi olmayan başka kimlik değişti: ihlal", () => {
    const r = guard({ [LOC]: LOC_ONARIM, [JAVA]: JAVA_METIN.replace('"add-to-cart"', '"cart-add"').replace('"cart-subtotal"', '"x"') });
    assert.equal(r.ok, false);
    assert.deepEqual(codes(r), ["binding_change_unpaired"]);
  });

  it("Java'da literal dışı değişiklik (yorum/kod): ihlal", () => {
    const r = guard({ [LOC]: LOC_ONARIM, [JAVA]: JAVA_METIN.replace('"add-to-cart"', '"cart-add"').replace("package x;", "package y;") });
    assert.deepEqual(codes(r), ["non_testid_change"]);
  });

  it("Java'da sabit eklendi: yapı değişti", () => {
    const r = guard({ [LOC]: LOC_ONARIM, [JAVA]: JAVA_METIN.replace("  }\n}", '    public static final String X = "add-to-cart";\n  }\n}') });
    assert.deepEqual(codes(r), ["binding_structure_changed"]);
  });

  it("uygulama testlerinin Kimlikler.java'sı onarımda değişemez", () => {
    const r = guard({ [LOC]: LOC_ONARIM, [APP_JAVA]: JAVA_METIN.replace('"add-to-cart"', '"cart-add"') });
    assert.deepEqual(codes(r), ["non_locator_file_changed"]);
  });
});
