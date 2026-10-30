import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { isLocatorPath, normalizeRoot, runGuard, type Mode, type Report } from "../src/guard.js";
import { DirSource, GitSource, openSource } from "../src/sources.js";
import { BASE_TREE, CART_LOCATORS, commit, git, initRepo, makePair, tmp, writeTree } from "./helpers.js";

function guard(changes: Record<string, string | null>, mode: Mode = "repair", base = BASE_TREE): Report {
  const p = makePair(base, changes);
  return runGuard(new DirSource(p.base), new DirSource(p.head), { mode, root: "." });
}

function codes(r: Report): string[] {
  return r.violations.map((v) => v.code);
}

const cartWith = (from: string, to: string): string => {
  assert.ok(CART_LOCATORS.includes(from), `fixture içinde yok: ${from}`);
  return CART_LOCATORS.replace(from, to);
};

describe("repair modu", () => {
  it("0 değişiklik: geçer, testId değişikliği yok", () => {
    const r = guard({});
    assert.equal(r.ok, true);
    assert.deepEqual(r.changed_files, []);
    assert.deepEqual(r.testid_changes, []);
    assert.deepEqual(r.violations, []);
  });

  it("yalnızca testId değeri değişti: geçer ve değişikliği raporlar", () => {
    const r = guard({ "pages/cart/locators.ts": cartWith('testId: "add-to-cart"', 'testId: "cart-add"') });
    assert.equal(r.ok, true, JSON.stringify(r.violations));
    assert.deepEqual(r.testid_changes, [
      { file: "pages/cart/locators.ts", entry: "cart.addToCart", before: "add-to-cart", after: "cart-add" },
    ]);
    assert.deepEqual(r.changed_files, [{ path: "pages/cart/locators.ts", status: "modified", locator: true }]);
  });

  it("birden çok dosyada testId değişikliği geçer", () => {
    const r = guard({
      "pages/cart/locators.ts": cartWith('"cart-subtotal"', '"cart-sub-total"'),
      "pages/login/locators.ts": BASE_TREE["pages/login/locators.ts"]!.replace('"login-submit"', '"login-btn"'),
    });
    assert.equal(r.ok, true, JSON.stringify(r.violations));
    assert.equal(r.testid_changes.length, 2);
  });

  it("anahtar eklendi: key_added", () => {
    const r = guard({
      "pages/cart/locators.ts": cartWith(
        "} as const;\n\nexport const cartLines",
        '  extra: { testId: "extra", role: "button", name: "Ek", intent: "Ek" },\n} as const;\n\nexport const cartLines',
      ),
    });
    assert.equal(r.ok, false);
    assert.deepEqual(codes(r), ["key_added"]);
    assert.equal(r.violations[0]?.entry, "cart.extra");
  });

  it("anahtar kaldırıldı: key_removed", () => {
    const r = guard({
      "pages/cart/locators.ts": cartWith(
        '  cartCount: { testId: "cart-count", role: "status", name: "Sepet", intent: "Sepetteki ürün sayısı" },\n',
        "",
      ),
    });
    assert.deepEqual(codes(r), ["key_removed"]);
  });

  it("anahtar yeniden adlandırıldı: key_added + key_removed", () => {
    const r = guard({ "pages/cart/locators.ts": cartWith("cartCount:", "cartCounter:") });
    assert.deepEqual(codes(r).sort(), ["key_added", "key_removed"]);
  });

  it("niyet (intent) değişti: field_changed", () => {
    const r = guard({
      "pages/cart/locators.ts": cartWith(
        'intent: "Ürün kartında sepete ekleme butonu"',
        'intent: "Sepeti boşaltma butonu"',
      ),
    });
    assert.equal(r.ok, false);
    assert.deepEqual(codes(r), ["field_changed"]);
    assert.equal(r.violations[0]?.field, "intent");
    assert.equal(r.violations[0]?.before, "Ürün kartında sepete ekleme butonu");
    assert.equal(r.violations[0]?.after, "Sepeti boşaltma butonu");
  });

  it("rol ve ad değişti: her biri ayrı field_changed", () => {
    const r = guard({
      "pages/cart/locators.ts": cartWith('role: "button",\n    name: "Sepete ekle"', 'role: "link",\n    name: "Sepet"'),
    });
    assert.deepEqual(
      r.violations.map((v) => `${v.code}:${v.field}`).sort(),
      ["field_changed:name", "field_changed:role"],
    );
  });

  it("testId ile birlikte intent değişti: ihlal ve testId değişikliği birlikte raporlanır", () => {
    const r = guard({
      "pages/cart/locators.ts": cartWith('testId: "cart-count"', 'testId: "count"').replace(
        "Sepetteki ürün sayısı",
        "Başka",
      ),
    });
    assert.equal(r.ok, false);
    assert.deepEqual(codes(r), ["field_changed"]);
    assert.equal(r.testid_changes.length, 1);
  });

  it("alan eklendi / kaldırıldı", () => {
    const added = guard({ "pages/cart/locators.ts": cartWith('name: "Sepet",', 'name: "Sepet", extra: "x",') });
    assert.deepEqual(codes(added), ["field_added"]);
    const removed = guard({ "pages/cart/locators.ts": cartWith(' role: "status",', "") });
    assert.deepEqual(codes(removed), ["field_removed"]);
  });

  it("export eklendi / kaldırıldı", () => {
    const added = guard({
      "pages/cart/locators.ts": `${CART_LOCATORS}\nexport const more = {} as const;\n`,
    });
    assert.deepEqual(codes(added), ["export_added"]);
    const removed = guard({
      "pages/cart/locators.ts": CART_LOCATORS.slice(0, CART_LOCATORS.indexOf("export const cartLines")),
    });
    assert.deepEqual(codes(removed).sort(), ["export_removed", "key_removed"]);
  });

  it("locator olmayan dosya değişti: non_locator_file_changed", () => {
    const r = guard({
      "pages/cart/locators.ts": cartWith('"add-to-cart"', '"cart-add"'),
      "tests/cart.spec.ts": 'import { test } from "@playwright/test";\ntest("x", async () => { /* assertion silindi */ });\n',
    });
    assert.equal(r.ok, false);
    assert.deepEqual(codes(r), ["non_locator_file_changed"]);
    assert.equal(r.violations[0]?.file, "tests/cart.spec.ts");
  });

  it("page object dosyası değişti: non_locator_file_changed", () => {
    const r = guard({ "pages/cart/CartPage.ts": "export class CartPage {}\n" });
    assert.deepEqual(codes(r), ["non_locator_file_changed"]);
  });

  it("yeni dosya eklendi veya silindi", () => {
    assert.deepEqual(codes(guard({ "tests/new.spec.ts": "x" })), ["non_locator_file_changed"]);
    assert.deepEqual(codes(guard({ "tests/cart.spec.ts": null })), ["non_locator_file_changed"]);
    assert.deepEqual(codes(guard({ "pages/new/locators.ts": "export const n = {} as const;\n" })), [
      "locator_file_added",
    ]);
    assert.deepEqual(codes(guard({ "pages/login/locators.ts": null })), ["locator_file_deleted"]);
  });

  it("hesaplanan değer enjekte edildi: non_literal_value", () => {
    const r = guard({
      "pages/cart/locators.ts": cartWith('testId: "add-to-cart"', "testId: `add-${globalThis.location}`"),
    });
    assert.equal(r.ok, false);
    assert.deepEqual(codes(r), ["non_literal_value"]);
  });

  it("çağrı enjekte edildi (IIFE): non_literal_value", () => {
    const r = guard({
      "pages/cart/locators.ts": cartWith('testId: "add-to-cart"', 'testId: (() => { fetch("http://x"); return "a"; })()'),
    });
    assert.deepEqual(codes(r), ["non_literal_value"]);
  });

  it("import enjekte edildi: forbidden_statement", () => {
    const r = guard({ "pages/cart/locators.ts": `import "node:child_process";\n${CART_LOCATORS}` });
    assert.ok(codes(r).includes("forbidden_statement"));
  });

  it("yalnızca yorum değişti: non_testid_change", () => {
    const r = guard({ "pages/cart/locators.ts": cartWith("saf veri.", "saf veri (değişti).") });
    assert.deepEqual(codes(r), ["non_testid_change"]);
  });

  it("testId dışı alanın tırnak biçimi değişti: non_testid_change", () => {
    const r = guard({ "pages/cart/locators.ts": cartWith('role: "status"', "role: 'status'") });
    assert.deepEqual(codes(r), ["non_testid_change"]);
  });

  it("testId literal'inin yalnızca tırnağı değişti: değer aynı, geçer", () => {
    const r = guard({ "pages/cart/locators.ts": cartWith('testId: "cart-count"', "testId: 'cart-count'") });
    assert.equal(r.ok, true);
    assert.deepEqual(r.testid_changes, []);
  });

  it("anahtar sırası değişti: non_testid_change", () => {
    const r = guard({
      "pages/cart/locators.ts": cartWith(
        'role: "status", name: "Sepet"',
        'name: "Sepet", role: "status"',
      ),
    });
    assert.deepEqual(codes(r), ["non_testid_change"]);
  });

  it("geçersiz yeni testId: invalid_testid", () => {
    const r = guard({ "pages/cart/locators.ts": cartWith('"add-to-cart"', '"cart add"') });
    assert.deepEqual(codes(r), ["invalid_testid"]);
  });

  it("taban saf değilse: base_not_pure", () => {
    const base = { ...BASE_TREE, "pages/home/locators.ts": 'export const HOME_PAGE = "home-page";\n' };
    const p = makePair(base, { "pages/home/locators.ts": 'export const HOME_PAGE = "home";\n' });
    const r = runGuard(new DirSource(p.base), new DirSource(p.head), { mode: "repair", root: "." });
    assert.ok(codes(r).includes("base_not_pure"));
    assert.equal(r.ok, false);
  });

  it("node_modules ve results dizinleri dizin modunda yok sayılır", () => {
    const r = guard({ "node_modules/x/index.js": "x", "results/junit.xml": "<x/>" });
    assert.equal(r.ok, true);
    assert.deepEqual(r.changed_files, []);
  });
});

describe("pr modu", () => {
  it("pages/** değişmediyse no-op başarılı", () => {
    const r = guard({ "tests/cart.spec.ts": "değişti", "playwright.config.ts": "x" }, "pr");
    assert.equal(r.ok, true);
    assert.equal(r.noop, true);
    assert.match(r.summary, /no-op/);
  });

  it("testId değişikliğini raporlar, yapı değişikliğine izin verir", () => {
    const r = guard(
      {
        "pages/cart/locators.ts": cartWith('"add-to-cart"', '"cart-add"').replace("cartCount:", "counter:"),
        "pages/cart/CartPage.ts": "export class CartPage {}\n",
        "tests/cart.spec.ts": "değişti",
      },
      "pr",
    );
    assert.equal(r.ok, true, JSON.stringify(r.violations));
    assert.equal(r.noop, false);
    assert.deepEqual(r.testid_changes, [
      { file: "pages/cart/locators.ts", entry: "cart.addToCart", before: "add-to-cart", after: "cart-add" },
    ]);
    assert.deepEqual(r.added_entries, ["pages/cart/locators.ts#cart.counter"]);
    assert.deepEqual(r.removed_entries, ["pages/cart/locators.ts#cart.cartCount"]);
  });

  it("yeni locator dosyası saf olmalı", () => {
    const ok = guard({ "pages/orders/locators.ts": 'export const orders = { table: { testId: "orders-table" } } as const;\n' }, "pr");
    assert.equal(ok.ok, true);
    assert.deepEqual(ok.added_entries, ["pages/orders/locators.ts#orders.table"]);
    const bad = guard({ "pages/orders/locators.ts": 'export const orders = { table: { testId: process.env.X } } as const;\n' }, "pr");
    assert.equal(bad.ok, false);
    assert.deepEqual(codes(bad), ["non_literal_value"]);
  });

  it("değişen locators.ts'e hesaplanan değer enjekte edildiyse başarısız", () => {
    const r = guard({ "pages/cart/locators.ts": cartWith('"cart-count"', "`c-${1}`") }, "pr");
    assert.deepEqual(codes(r), ["non_literal_value"]);
  });

  it("değişmeyen saf olmayan eski dosya PR'ı kilitlemez; değiştirilirse saf hale gelmeli", () => {
    const base = { ...BASE_TREE, "pages/home/locators.ts": 'export const HOME_PAGE = "home-page";\n' };
    const p1 = makePair(base, { "pages/cart/locators.ts": cartWith('"add-to-cart"', '"cart-add"') });
    assert.equal(runGuard(new DirSource(p1.base), new DirSource(p1.head), { mode: "pr", root: "." }).ok, true);
    const p2 = makePair(base, { "pages/home/locators.ts": 'export const home = { page: { testId: "home-page" } } as const;\n' });
    const r2 = runGuard(new DirSource(p2.base), new DirSource(p2.head), { mode: "pr", root: "." });
    assert.equal(r2.ok, true, JSON.stringify(r2.violations));
    assert.deepEqual(r2.added_entries, ["pages/home/locators.ts#home.page"]);
  });

  it("silinen locator dosyası pr modunda ihlal değildir", () => {
    const r = guard({ "pages/login/locators.ts": null }, "pr");
    assert.equal(r.ok, true);
  });
});

describe("kök (root) ve git kaynakları", () => {
  const MONO = Object.fromEntries(Object.entries(BASE_TREE).map(([k, v]) => [`demo-app/e2e/${k}`, v]));
  MONO["README.md"] = "# mono\n";
  MONO["core/app.py"] = "print(1)\n";

  it("normalizeRoot ve isLocatorPath", () => {
    assert.equal(normalizeRoot("./demo-app/e2e/"), "demo-app/e2e");
    assert.equal(normalizeRoot("."), "");
    assert.throws(() => normalizeRoot("../x"));
    assert.throws(() => normalizeRoot("/abs"));
    assert.equal(isLocatorPath("demo-app/e2e/pages/cart/locators.ts", "demo-app/e2e"), true);
    assert.equal(isLocatorPath("demo-app/e2e/pages/locators.ts", "demo-app/e2e"), true);
    assert.equal(isLocatorPath("demo-app/e2e/pages/a/b/locators.ts", "demo-app/e2e"), true);
    assert.equal(isLocatorPath("demo-app/e2e/tests/locators.ts", "demo-app/e2e"), false);
    assert.equal(isLocatorPath("other/pages/cart/locators.ts", "demo-app/e2e"), false);
    assert.equal(isLocatorPath("demo-app/e2e/pages/cart/locators.tsx", "demo-app/e2e"), false);
    assert.equal(isLocatorPath("demo-app/e2e/pages/cart/xlocators.ts", "demo-app/e2e"), false);
  });

  it("git ref'leri: testId onarımı geçer", () => {
    const repo = initRepo(MONO);
    const baseSha = initialSha(repo);
    const headSha = commit(repo, {
      "demo-app/e2e/pages/cart/locators.ts": cartWith('"add-to-cart"', '"cart-add"'),
    });
    const r = runGuard(new GitSource(repo, baseSha), new GitSource(repo, headSha), { mode: "repair", root: "demo-app/e2e" });
    assert.equal(r.ok, true, JSON.stringify(r.violations));
    assert.equal(r.testid_changes[0]?.after, "cart-add");
    assert.match(r.base, /@[0-9a-f]{12}$/);
  });

  it("git ref'leri: kök dışındaki dosya değişikliği repair modunda ihlal", () => {
    const repo = initRepo(MONO);
    const baseSha = initialSha(repo);
    commit(repo, { "core/app.py": "print(2)\n" });
    const r = runGuard(new GitSource(repo, baseSha), new GitSource(repo, "HEAD"), { mode: "repair", root: "demo-app/e2e" });
    assert.deepEqual(codes(r), ["non_locator_file_changed"]);
    assert.equal(r.violations[0]?.file, "core/app.py");
  });

  it("git ref'leri: pr modunda kök dışı değişiklik no-op", () => {
    const repo = initRepo(MONO);
    const baseSha = initialSha(repo);
    commit(repo, { "core/app.py": "print(2)\n", "demo-app/e2e/tests/cart.spec.ts": "x" });
    const r = runGuard(new GitSource(repo, baseSha), new GitSource(repo, "HEAD"), { mode: "pr", root: "demo-app/e2e" });
    assert.equal(r.noop, true);
    assert.equal(r.ok, true);
  });

  it("karışık: dizin taban ↔ git head", () => {
    const repo = initRepo(BASE_TREE);
    const dir = writeTree(tmp(), BASE_TREE);
    commit(repo, { "pages/login/locators.ts": BASE_TREE["pages/login/locators.ts"]!.replace('"login-submit"', '"login-go"') });
    const r = runGuard(new DirSource(dir), new GitSource(repo, "HEAD"), { mode: "repair", root: "." });
    assert.equal(r.ok, true, JSON.stringify(r.violations));
    assert.deepEqual(r.changed_files.map((c) => c.path), ["pages/login/locators.ts"]);
  });

  it("çözülemeyen ref hata fırlatır; openSource dizini tanır", () => {
    const repo = initRepo(BASE_TREE);
    assert.throws(() => new GitSource(repo, "yok-boyle-bir-ref"), /çözülemedi/);
    assert.equal(openSource(repo, repo).kind, "dir");
    assert.equal(openSource("HEAD", repo).kind, "git");
  });
});

function initialSha(repo: string): string {
  return git(repo, "rev-list", "--max-parents=0", "HEAD");
}
