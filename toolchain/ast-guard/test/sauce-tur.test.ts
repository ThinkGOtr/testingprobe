// Sauce Labs elle turu (.github/workflows/sauce-demo.yml) sözleşmesi: yalnız elle tetik, çekirdeğin
// okuduğu `sauce` işi + `sauce-results` artefaktı, scripts/github-sauce-tur-ozeti.py platform özetleri.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import { tmp, writeTree } from "./helpers.js";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");
const wf = readFileSync(join(REPO_ROOT, ".github", "workflows", "sauce-demo.yml"), "utf8");
const ci = readFileSync(join(REPO_ROOT, ".github", "workflows", "ci.yml"), "utf8");
const duman = readFileSync(join(REPO_ROOT, "demo-app", ".sauce", "duman.yml"), "utf8");
const OZET = join(REPO_ROOT, "scripts", "github-sauce-tur-ozeti.py");

const readJson = (p: string): unknown => JSON.parse(readFileSync(p, "utf8"));

function ozet(args: string[], cwd: string, env: Record<string, string> = {}): { status: number | null; summary: string; stderr: string } {
  const summaryFile = join(cwd, "step-summary.md");
  writeFileSync(summaryFile, "");
  const r = spawnSync("python3", ["-I", OZET, ...args], {
    cwd,
    encoding: "utf8",
    env: { PATH: process.env["PATH"] ?? "/usr/bin:/bin", GITHUB_STEP_SUMMARY: summaryFile, ...env },
  });
  return { status: r.status, summary: readFileSync(summaryFile, "utf8"), stderr: r.stderr };
}

describe("sauce-demo.yml: yalnız elle tur", () => {
  const on = wf.slice(wf.indexOf("\non:\n"), wf.indexOf("\npermissions:\n"));

  it("tek tetik workflow_dispatch (tetik=sauce); PR/push/cron/deploy yok", () => {
    assert.match(on, /workflow_dispatch:/);
    for (const yok of ["pull_request", "push:", "schedule", "repository_dispatch"]) assert.ok(!on.includes(yok), yok);
    assert.match(on, /options: \[sauce\]/);
    assert.match(wf, /run-name: >-\n\s+\$\{\{ format\('sauce-demo \{0\} \[\{1\}\]'/);
  });

  it("SAUCE_TETIKLER 'sauce' içermiyorsa tur atlanır; tek tur aynı anda", () => {
    assert.match(wf, /tetikler=",\$\{SAUCE_TETIKLER:-sauce\},"/);
    assert.match(wf, /concurrency:\n {2}group: sauce-demo\n {2}cancel-in-progress: false/);
  });

  it("çekirdeğin okuduğu iş `sauce` ve artefakt `sauce-results`; platform işleri ayrı", () => {
    for (const j of ["hazirlik", "derle-android", "derle-ios", "sauce-web", "sauce-mobil", "sauce"]) {
      assert.match(wf, new RegExp(`\\n {2}${j}:\\n {4}name: `), j);
    }
    assert.match(wf, /\n {2}sauce:\n {4}name: sauce\n/);
    assert.match(wf, /name: sauce-results\n/);
    assert.match(wf, /--beklenen web,android,ios/);
    assert.match(wf, /if \[ "\$HAZIRLIK" != "success" \]/, "hazırlık düşerse atlandı değil hata");
  });

  it("kimlik komut satırında değil (netrc stdin); artefaktta token ve anahtar maskelenir", () => {
    assert.ok(!/curl[^\n]*-u /.test(wf), "curl -u kullanılmaz");
    assert.match(wf, /--netrc-file \/dev\/stdin/);
    assert.equal((wf.match(/for s in "\$\{DEMOAPP_TEST_TOKEN:-\}" "\$\{SAUCE_ACCESS_KEY:-\}"/g) ?? []).length, 2);
  });

  it("ci.yml Sauce job'u varsayılan olarak hiçbir ci tetiğinde koşmaz", () => {
    assert.match(ci, /tetikler=",\$\{SAUCE_TETIKLER:-sauce\},"/);
    assert.ok(!ci.includes("SAUCE_TETIKLER:-push"), "eski varsayılan kalmadı");
  });

  it("duman.yml: suite adları <OS>-<Tarayıcı>; Edge satırı msedge projesiyle", () => {
    const adlar = [...duman.matchAll(/- name: "([^"]+)"/g)].map((m) => m[1]);
    assert.deepEqual(adlar, ["Windows-11-Chromium", "Windows-11-Edge"]);
    assert.match(duman, /TP_PW_EDGE: "1"[\s\S]*project: msedge/);
    for (const a of adlar) assert.match(wf, new RegExp(`--suite ${a}`));
  });
});

const JOB = "0123456789abcdef0123456789abcdef";
const JOB2 = "fedcba9876543210fedcba9876543210";

describe("github-sauce-tur-ozeti.py", () => {
  it("web: suite başına satır, etiket ve Sauce iş bağlantısı; JUnit test adı platformla", () => {
    const dir = tmp("sauce-tur-");
    writeTree(dir, {
      "r.json": JSON.stringify({
        test_results: [
          { name: "Windows-11-Chromium", status: "passed", url: `https://app.eu-central-1.saucelabs.com/tests/${JOB}` },
          { name: "Windows-11-Edge", status: "failed", url: `https://app.eu-central-1.saucelabs.com/tests/${JOB2}` },
          { name: "kötü", status: "passed", url: "https://evil.example/tests/x" },
        ],
      }),
      "j.xml":
        '<testsuites><testsuite name="Windows-11-Chromium"><testcase name="giriş" classname="login.spec.ts"/>' +
        '<testcase name="sipariş" classname="order.spec.ts"/></testsuite>' +
        '<testsuite name="Windows-11-Edge"><testcase name="sipariş" classname="order.spec.ts"><failure message="x"/></testcase></testsuite></testsuites>',
    });
    const r = ozet(["web", "--out", "o", "--report", "r.json", "--junit", "j.xml", "--exit-code", "1", "--region", "eu-central-1"], dir);
    assert.equal(r.status, 0, r.stderr);
    const p = readJson(join(dir, "o/platformlar.json")) as Record<string, unknown>[];
    assert.equal(p.length, 2);
    assert.deepEqual(
      p.map((x) => [x["etiket"], x["durum"], x["toplam"], x["gecen"]]),
      [
        // saucectl'in tek çıkış kodu (1) Edge'e aittir; Chromium kendi kanıtıyla geçti.
        ["Windows 11 · Chromium", "passed", 2, 2],
        ["Windows 11 · Edge", "failed", 1, 0],
      ],
    );
    assert.equal(((p[1]!["isler"] as Record<string, unknown>[])[0]!)["url"], `https://app.eu-central-1.saucelabs.com/tests/${JOB2}`);
    assert.match(readFileSync(join(dir, "o/junit-1.xml"), "utf8"), /name="\[Windows 11 · Edge\] sipariş"/);
  });

  it("mobil + topla: oturum → Sauce iş bağlantısı; eksik platform 'error'; sauce.json + junit + ci-meta", () => {
    const dir = tmp("sauce-tur-");
    writeTree(dir, {
      "sf/TEST-TestSuite.xml":
        '<testsuite name="TestSuite"><testcase name="dogruBilgilerleGiris" classname="com.x.GirisTesti"/>' +
        '<testcase name="siparisOnayVeGecmis" classname="com.x.SiparisTesti"/></testsuite>',
      "o.jsonl":
        `{"test":"GirisTesti.dogruBilgilerleGiris","oturum":"${JOB}","durum":"passed"}\n` +
        `{"test":"kötü","oturum":"../../x","durum":"passed"}\n`,
    });
    let r = ozet(
      ["mobil", "--out", "p/android", "--platform", "android", "--etiket", "Android · emülatör", "--surefire", "sf", "--oturumlar", "o.jsonl", "--exit-code", "0", "--region", "eu-central-1"],
      dir,
    );
    assert.equal(r.status, 0, r.stderr);
    const a = (readJson(join(dir, "p/android/platformlar.json")) as Record<string, unknown>[])[0]!;
    assert.equal(a["durum"], "passed");
    assert.equal(a["toplam"], 2);
    assert.deepEqual(a["isler"], [
      { ad: "GirisTesti.dogruBilgilerleGiris", url: `https://app.eu-central-1.saucelabs.com/tests/${JOB}`, durum: "passed" },
    ]);
    r = ozet(
      ["topla", "--out", "s", "--girdi", "p/android", "--beklenen", "web,android,ios", "--kota-once", '{"kalan_dk":60,"x":"metin"}'],
      dir,
      { GITHUB_REPOSITORY: "acme/demo", GITHUB_RUN_ID: "77", TP_TRIGGER: "sauce", TP_ISTEK_ID: "ist-1", SAUCE_REGION: "eu-central-1" },
    );
    assert.equal(r.status, 0, r.stderr);
    const s = readJson(join(dir, "s/sauce.json")) as Record<string, unknown>;
    assert.equal(s["durum"], "error");
    assert.equal(s["job_url"], `https://app.eu-central-1.saucelabs.com/tests/${JOB}`);
    const pl = s["platformlar"] as Record<string, unknown>[];
    assert.deepEqual(pl.map((x) => [x["platform"], x["durum"]]), [
      ["web", "error"],
      ["android", "passed"],
      ["ios", "error"],
    ]);
    assert.deepEqual((s["kota"] as Record<string, unknown>)["once"], { kalan_dk: 60 });
    assert.match(readFileSync(join(dir, "s/junit.xml"), "utf8"), /\[Android · emülatör\] dogruBilgilerleGiris/);
    assert.equal((readJson(join(dir, "s/ci-meta.json")) as Record<string, unknown>)["job"], "sauce");
    assert.match(r.summary, /\| Android · emülatör \| passed \| 2\/2 \|/);
  });

  it("atla: durum atlandi, platform yok", () => {
    const dir = tmp("sauce-tur-");
    const r = ozet(["atla", "--out", "s", "--neden", "Sauce kimliği tanımlı değil"], dir);
    assert.equal(r.status, 0, r.stderr);
    const s = readJson(join(dir, "s/sauce.json")) as Record<string, unknown>;
    assert.equal(s["durum"], "atlandi");
    assert.deepEqual(s["platformlar"], []);
  });
});
