import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import { EXIT_ERROR, EXIT_OK, EXIT_VIOLATIONS, main } from "../src/cli.js";
import { BASE_TREE, CART_LOCATORS, commit, initRepo, makePair, tmp } from "./helpers.js";

const CLI = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "cli.js");

function run(args: string[], cwd?: string): { code: number; json: Record<string, unknown>; stderr: string } {
  const res = spawnSync(process.execPath, [CLI, ...args], { cwd, encoding: "utf8" });
  let json: Record<string, unknown> = {};
  try {
    json = JSON.parse(res.stdout) as Record<string, unknown>;
  } catch {
    json = {};
  }
  return { code: res.status ?? -1, json, stderr: res.stderr };
}

function capture(argv: string[], cwd?: string): { code: number; out: string; err: string } {
  let out = "";
  let err = "";
  const code = main(argv, { stdout: (s) => (out += s), stderr: (s) => (err += s) }, cwd);
  return { code, out, err };
}

describe("CLI (alt süreç)", () => {
  it("geçen onarım: çıkış 0, JSON rapor stdout'ta", () => {
    const p = makePair(BASE_TREE, { "pages/cart/locators.ts": CART_LOCATORS.replace('"add-to-cart"', '"cart-add"') });
    const r = run(["--base", p.base, "--head", p.head, "--mode", "repair"]);
    assert.equal(r.code, EXIT_OK, r.stderr);
    assert.equal(r.json["ok"], true);
    assert.equal(r.json["tool"], "ast-guard");
    assert.equal((r.json["testid_changes"] as unknown[]).length, 1);
    assert.match(r.stderr, /add-to-cart → cart-add/);
  });

  it("ihlal: çıkış 1", () => {
    const p = makePair(BASE_TREE, { "tests/cart.spec.ts": "x" });
    const r = run(["--base", p.base, "--head", p.head]);
    assert.equal(r.code, EXIT_VIOLATIONS);
    assert.equal(r.json["ok"], false);
    assert.equal(r.json["mode"], "repair", "varsayılan mod repair olmalı");
    assert.match(r.stderr, /non_locator_file_changed/);
  });

  it("git ref'leri ve --root ile monorepo", () => {
    const mono = Object.fromEntries(Object.entries(BASE_TREE).map(([k, v]) => [`demo-app/e2e/${k}`, v]));
    const repo = initRepo(mono);
    commit(repo, { "demo-app/e2e/pages/cart/locators.ts": CART_LOCATORS.replace('"cart-count"', '"cart-counter"') });
    const r = run(["--base", "HEAD~1", "--head", "HEAD", "--root", "demo-app/e2e", "--mode", "repair"], repo);
    assert.equal(r.code, EXIT_OK, r.stderr);
    assert.equal(r.json["root"], "demo-app/e2e");
    const pr = run(["--base", "HEAD~1", "--head", "HEAD", "--root", "demo-app/e2e", "--mode", "pr", "--repo", repo]);
    assert.equal(pr.code, EXIT_OK, pr.stderr);
    assert.equal(pr.json["noop"], false);
  });

  it("--out dosyaya yazar, --quiet stdout'u bastırır", () => {
    const p = makePair(BASE_TREE, {});
    const out = join(tmp(), "report.json");
    const r = spawnSync(process.execPath, [CLI, "--base", p.base, "--head", p.head, "--out", out, "--quiet"], {
      encoding: "utf8",
    });
    assert.equal(r.status, 0);
    assert.equal(r.stdout, "");
    assert.equal((JSON.parse(readFileSync(out, "utf8")) as { ok: boolean }).ok, true);
  });

  it("çözülemeyen ref: çıkış 2 ve JSON hata", () => {
    const repo = initRepo(BASE_TREE);
    const r = run(["--base", "nope", "--head", "HEAD", "--repo", repo]);
    assert.equal(r.code, EXIT_ERROR);
    assert.equal(r.json["ok"], false);
    assert.match(String(r.json["error"]), /çözülemedi/);
  });
});

describe("CLI (süreç içi)", () => {
  it("eksik argüman, geçersiz mod, bilinmeyen bayrak: çıkış 2", () => {
    assert.equal(capture(["--base", "a"]).code, EXIT_ERROR);
    assert.equal(capture(["--base", "a", "--head", "b", "--mode", "yolo"]).code, EXIT_ERROR);
    assert.equal(capture(["--bogus"]).code, EXIT_ERROR);
    assert.equal(capture(["--base", ".", "--head", ".", "--root", "../dışarı"]).code, EXIT_ERROR);
  });

  it("--help: çıkış 0", () => {
    const r = capture(["--help"]);
    assert.equal(r.code, EXIT_OK);
    assert.match(r.out, /Kullanım/);
  });
});
