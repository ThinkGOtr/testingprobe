// scripts/github-ast-guard-mode.sh — CI'da ast-guard modunu seçen betik (Constitution VI).
// Betik bash ile alt süreçte koşturulur; çıktı satırları (mode/run/reason) doğrulanır.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

// dist/test/mode-script.test.js → repo kökü
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");
const SCRIPT = join(REPO_ROOT, "scripts", "github-ast-guard-mode.sh");
const CI_YML = join(REPO_ROOT, ".github", "workflows", "ci.yml");

type Result = { mode: string; run: string; reason: string; ghOutput: string };

function decide(env: Record<string, string>): Result {
  const outFile = join(mkdtempSync(join(tmpdir(), "astg-mode-")), "out");
  const res = spawnSync("bash", [SCRIPT], {
    encoding: "utf8",
    // Yalnızca verilen ortam: çağıranın değişkenleri (ör. HEAD_REF) sızmasın.
    env: { PATH: process.env["PATH"] ?? "/usr/bin:/bin", GITHUB_OUTPUT: outFile, ...env },
  });
  assert.equal(res.status, 0, res.stderr);
  const kv = Object.fromEntries(
    res.stdout
      .trim()
      .split("\n")
      .map((l) => [l.slice(0, l.indexOf("=")), l.slice(l.indexOf("=") + 1)]),
  ) as Record<string, string>;
  return {
    mode: kv["mode"] ?? "",
    run: kv["run"] ?? "",
    reason: kv["reason"] ?? "",
    ghOutput: readFileSync(outFile, "utf8"),
  };
}

const PR = { IS_PR: "true", PAGES_CHANGED: "false", HAS_REPAIR_LABEL: "false" };

describe("github-ast-guard-mode.sh", () => {
  it("betik repoda var", () => {
    assert.ok(existsSync(SCRIPT), SCRIPT);
  });

  it("PR değilse: pr modu, koşmaz", () => {
    const r = decide({ IS_PR: "false", HEAD_REF: "tp/repair-x", HAS_REPAIR_LABEL: "true", PR_AUTHOR_TYPE: "Bot" });
    assert.deepEqual([r.mode, r.run], ["pr", "false"]);
  });

  it("insan PR'ı, pages değişmedi: no-op", () => {
    const r = decide({ ...PR, HEAD_REF: "feature/x", PR_AUTHOR: "hakan", PR_AUTHOR_TYPE: "User" });
    assert.deepEqual([r.mode, r.run], ["pr", "false"]);
  });

  it("insan PR'ı, pages değişti: pr modunda koşar", () => {
    const r = decide({ ...PR, PAGES_CHANGED: "true", HEAD_REF: "feature/x", PR_AUTHOR_TYPE: "User" });
    assert.deepEqual([r.mode, r.run], ["pr", "true"]);
  });

  it("tp/repair-* dalı: repair (pages değişmese bile koşar)", () => {
    const r = decide({ ...PR, HEAD_REF: "tp/repair-TPD-12", PR_AUTHOR_TYPE: "User" });
    assert.deepEqual([r.mode, r.run], ["repair", "true"]);
  });

  it("REPAIR_BRANCH_PREFIX ortamdan alınır", () => {
    const r = decide({ ...PR, HEAD_REF: "fix/loc-1", REPAIR_BRANCH_PREFIX: "fix/loc-" });
    assert.equal(r.mode, "repair");
  });

  it("tp-repair etiketi: repair", () => {
    const r = decide({ ...PR, HEAD_REF: "feature/x", HAS_REPAIR_LABEL: "true", PR_AUTHOR_TYPE: "User" });
    assert.deepEqual([r.mode, r.run], ["repair", "true"]);
  });

  it("bot PR'ı, farklı adlı dal, etiket yok: yine repair", () => {
    const r = decide({ ...PR, HEAD_REF: "tp/fix-TPD-3", PR_AUTHOR: "tp-bot[bot]", PR_AUTHOR_TYPE: "Bot" });
    assert.deepEqual([r.mode, r.run], ["repair", "true"]);
    assert.match(r.reason, /bot/);
  });

  it("bot PR'ı, etiket kaldırılmış (yeniden koşu): repair modunda kalır", () => {
    const r = decide({ ...PR, HEAD_REF: "onarim-123", HAS_REPAIR_LABEL: "false", PR_AUTHOR: "tp-bot[bot]", PR_AUTHOR_TYPE: "Bot" });
    assert.equal(r.mode, "repair");
  });

  it("bot PR'ı, tp/case-* dalı: pr modu (yeni test)", () => {
    const r = decide({ ...PR, PAGES_CHANGED: "true", HEAD_REF: "tp/case-3f2a9c1e", PR_AUTHOR_TYPE: "Bot" });
    assert.deepEqual([r.mode, r.run], ["pr", "true"]);
  });

  it("bot PR'ı, tp/case-* dalı ama tp-repair etiketi: repair (etiket her zaman sıkılaştırır)", () => {
    const r = decide({ ...PR, HEAD_REF: "tp/case-3f2a9c1e", HAS_REPAIR_LABEL: "true", PR_AUTHOR_TYPE: "Bot" });
    assert.equal(r.mode, "repair");
  });

  it("TP_BOT_LOGINS: tür User olsa bile listedeki giriş bot sayılır (büyük/küçük harf, boşluk, [bot] eki)", () => {
    for (const author of ["svc-probe", "SVC-Probe", "svc-probe[bot]"]) {
      const r = decide({ ...PR, HEAD_REF: "x", PR_AUTHOR: author, PR_AUTHOR_TYPE: "User", TP_BOT_LOGINS: "other, svc-probe " });
      assert.equal(r.mode, "repair", author);
    }
  });

  it("TP_BOT_LOGINS'te olmayan kullanıcı ve boş liste girdileri bot sayılmaz", () => {
    const r = decide({ ...PR, HEAD_REF: "x", PR_AUTHOR: "svc-probe-2", PR_AUTHOR_TYPE: "User", TP_BOT_LOGINS: ",,svc-probe," });
    assert.equal(r.mode, "pr");
  });

  it("boş önek hiçbir dalla eşleşmez", () => {
    const r = decide({ ...PR, HEAD_REF: "feature/x", REPAIR_BRANCH_PREFIX: "", PR_AUTHOR_TYPE: "User" });
    assert.equal(r.mode, "pr");
  });

  it("çıktı GITHUB_OUTPUT'a da yazılır", () => {
    const r = decide({ ...PR, HEAD_REF: "tp/repair-1" });
    assert.match(r.ghOutput, /^mode=repair$/m);
    assert.match(r.ghOutput, /^run=true$/m);
    assert.match(r.ghOutput, /^reason=.+$/m);
  });

  it("ci.yml önekleri betiğin varsayılanlarıyla aynı ve job betiği çağırıyor", () => {
    const yml = readFileSync(CI_YML, "utf8");
    assert.match(yml, /^\s+REPAIR_BRANCH_PREFIX: tp\/repair-$/m);
    assert.match(yml, /^\s+CASE_BRANCH_PREFIX: tp\/case-$/m);
    assert.match(yml, /PR_AUTHOR_TYPE: \$\{\{ github\.event\.pull_request\.user\.type \}\}/);
    assert.match(yml, /scripts\/github-ast-guard-mode\.sh/);
  });
});
