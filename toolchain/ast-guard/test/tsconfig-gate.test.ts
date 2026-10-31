import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it } from "node:test";
import { runGuard, type Report } from "../src/guard.js";
import { DirSource, GitSource } from "../src/sources.js";
import { checkTsconfig } from "../src/tsconfig-gate.js";
import { BASE_TREE, commit, initRepo, makePair } from "./helpers.js";

const STRICT = `{
  // JSONC: yorum ve sondaki virgül serbest
  "compilerOptions": { "target": "ES2022", "strict": true, "noEmit": true, },
  "include": ["playwright.config.ts", "pages/**/*.ts", "tests/**/*.ts"]
}
`;
const TREE = { ...BASE_TREE, "tsconfig.json": STRICT };

function pr(changes: Record<string, string | null>, base = TREE): Report {
  const p = makePair(base, changes);
  return runGuard(new DirSource(p.base), new DirSource(p.head), { mode: "pr", root: "." });
}
const codes = (r: Report): string[] => r.violations.map((v) => v.code);

describe("tsconfig kapısı (tsc --strict, Constitution IV)", () => {
  it("strict korunarak yapılan değişiklik geçer ve no-op sayılmaz", () => {
    const r = pr({ "tsconfig.json": STRICT.replace('"ES2022"', '"ES2023"') });
    assert.equal(r.ok, true, JSON.stringify(r.violations));
    assert.equal(r.noop, false);
  });

  it('"strict": false reddedilir', () => {
    const r = pr({ "tsconfig.json": STRICT.replace('"strict": true', '"strict": false') });
    assert.deepEqual(codes(r), ["tsconfig_not_strict"]);
    assert.equal(r.ok, false);
  });

  it("strict kaldırılırsa reddedilir", () => {
    const r = pr({ "tsconfig.json": STRICT.replace('"strict": true, ', "") });
    assert.deepEqual(codes(r), ["tsconfig_not_strict"]);
  });

  it("strict ailesinden bayrak kapatılamaz", () => {
    const r = pr({ "tsconfig.json": STRICT.replace('"strict": true', '"strict": true, "strictNullChecks": false, "noImplicitAny": false') });
    assert.deepEqual(codes(r).sort(), ["tsconfig_strict_weakened", "tsconfig_strict_weakened"]);
  });

  it("extends ve kapsam daraltma reddedilir", () => {
    const r = pr({
      "tsconfig.json": STRICT.replace("{\n", '{\n  "extends": "./loose.json",\n').replace(', "tests/**/*.ts"', ""),
    });
    assert.deepEqual(codes(r).sort(), ["tsconfig_extends", "tsconfig_scope_changed"]);
  });

  it("silme ve bozuk JSON reddedilir", () => {
    assert.deepEqual(codes(pr({ "tsconfig.json": null })), ["tsconfig_deleted"]);
    assert.deepEqual(codes(pr({ "tsconfig.json": "{ nope" })), ["tsconfig_invalid"]);
  });

  it("repair modunda tsconfig değişikliği zaten ihlaldir", () => {
    const p = makePair(TREE, { "tsconfig.json": STRICT.replace("ES2022", "ES2023") });
    const r = runGuard(new DirSource(p.base), new DirSource(p.head), { mode: "repair", root: "." });
    assert.deepEqual(codes(r), ["non_locator_file_changed"]);
  });

  it("monorepo kökü: demo-app/e2e/tsconfig.json git ref'lerinde denetlenir", () => {
    const mono = Object.fromEntries(Object.entries(TREE).map(([k, v]) => [`demo-app/e2e/${k}`, v]));
    const repo = initRepo(mono);
    const head = commit(repo, { "demo-app/e2e/tsconfig.json": STRICT.replace('"strict": true', '"strict": false') });
    const r = runGuard(new GitSource(repo, `${head}~1`), new GitSource(repo, head), { mode: "pr", root: "demo-app/e2e" });
    assert.deepEqual(codes(r), ["tsconfig_not_strict"]);
    assert.equal(r.violations[0]?.file, "demo-app/e2e/tsconfig.json");
  });

  // dist/test → toolchain/ast-guard → repo kökü (imaj içinde demo-app yoksa atlanır)
  const realPath = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..", "demo-app", "e2e", "tsconfig.json");
  it("depodaki gerçek demo-app/e2e/tsconfig.json kapıdan geçer", { skip: !existsSync(realPath) }, () => {
    const real = readFileSync(realPath, "utf8");
    assert.deepEqual(checkTsconfig("demo-app/e2e/tsconfig.json", real, real), []);
  });
});
