// scripts/github-{ci-results,sauce-summary,break-verify-result}.sh — CI artefakt sözleşmesi.
// Çekirdeğin ci-runs alımı GitHub artefaktlarını bu betiklerin yazdığı düzende okur; yerel koşu
// (test-runner) ile aynı adlar: junit.xml, results.json, allure-results/, playwright-report/.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, symlinkSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import { tmp, writeTree } from "./helpers.js";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");
const script = (name: string): string => join(REPO_ROOT, "scripts", name);

type Run = { status: number | null; stdout: string; stderr: string; summary: string };

function run(name: string, args: string[], cwd: string, env: Record<string, string> = {}): Run {
  const summaryFile = join(cwd, "step-summary.md");
  writeFileSync(summaryFile, "");
  const res = spawnSync("bash", [script(name), ...args], {
    cwd,
    encoding: "utf8",
    // Yalnızca verilen ortam: çağıranın GITHUB_* değişkenleri sızmasın.
    env: { PATH: process.env["PATH"] ?? "/usr/bin:/bin", GITHUB_STEP_SUMMARY: summaryFile, ...env },
  });
  return { status: res.status, stdout: res.stdout, stderr: res.stderr, summary: readFileSync(summaryFile, "utf8") };
}

const readJson = (p: string): Record<string, unknown> => JSON.parse(readFileSync(p, "utf8")) as Record<string, unknown>;

const GH = {
  GITHUB_SHA: "a".repeat(40),
  GITHUB_REF: "refs/heads/main",
  GITHUB_EVENT_NAME: "repository_dispatch",
  GITHUB_REPOSITORY: "acme/testingprobe",
  GITHUB_RUN_ID: "123456",
  GITHUB_RUN_ATTEMPT: "1",
  TP_TRIGGER: "deploy",
  TP_ISTEK_ID: "ist-42",
  PLAYWRIGHT_VERSION: "1.64.1",
};

function pwReport(stats: Record<string, number>, errors: unknown[] = []): string {
  return JSON.stringify({ config: {}, suites: [], errors, stats: { duration: 1234.5, ...stats } });
}

function resultsFixture(dir: string, stats: Record<string, number> | null): void {
  const files: Record<string, string> = {
    "demo-app/e2e/results/junit.xml": "<testsuites/>",
    "demo-app/e2e/results/allure-results/x-result.json": "{}",
    "demo-app/e2e/results/html/index.html": "<html></html>",
    "demo-app/e2e/results/artifacts/cart-kampanya/trace.zip": "zip",
    "demo-app/e2e/tests/generated/tpd-1-kampanya.spec.ts": "// üretildi",
    "demo-app/e2e/tests/generated/tpd-1-sinir.spec.ts": "// üretildi",
    "demo-app/e2e/tests/cart.spec.ts": "// el yazımı",
    "run-checks.log": "==> playwright test\n",
  };
  if (stats) files["demo-app/e2e/results/results.json"] = pwReport(stats);
  writeTree(dir, files);
}

describe("github-ci-results.sh (test-local artefaktı)", () => {
  it("yerel koşu adlarıyla düz düzen + ci-meta.json yazar", () => {
    const dir = tmp("ci-res-");
    resultsFixture(dir, { expected: 5, unexpected: 0, flaky: 1, skipped: 0 });
    // sembolik bağ artefakta girmez
    symlinkSync("/etc/hosts", join(dir, "demo-app/e2e/results/allure-results/sizinti.json"));
    const r = run(
      "github-ci-results.sh",
      ["--out", "tp-results", "--src", "results", "--src", "demo-app/e2e/results", "--app-root", "demo-app",
        "--exit-code", "0", "--log", "run-checks.log"],
      dir,
      GH,
    );
    assert.equal(r.status, 0, r.stderr);
    const out = join(dir, "tp-results");
    for (const f of ["junit.xml", "results.json", "allure-results/x-result.json", "playwright-report/index.html",
      "artifacts/cart-kampanya/trace.zip", "run-checks.log", "ci-meta.json"]) {
      assert.ok(existsSync(join(out, f)), f);
    }
    assert.ok(!existsSync(join(out, "html")), "html/ → playwright-report/ olarak yeniden adlandırılır");
    assert.ok(!existsSync(join(out, "allure-results/sizinti.json")), "sembolik bağ kopyalanmaz");
    const meta = readJson(join(out, "ci-meta.json"));
    assert.equal(meta["schema_version"], 1);
    assert.equal(meta["kaynak"], "github");
    assert.equal(meta["job"], "test-local");
    assert.equal(meta["durum"], "passed");
    assert.equal(meta["tetik"], "deploy");
    assert.equal(meta["istek_id"], "ist-42");
    assert.equal(meta["sha"], GH.GITHUB_SHA); // git deposu değil → GITHUB_SHA
    assert.equal(meta["run_url"], "https://github.com/acme/testingprobe/actions/runs/123456");
    assert.equal(meta["exit_code"], 0);
    assert.deepEqual(meta["stats"], { expected: 5, unexpected: 0, flaky: 1, skipped: 0, duration_ms: 1234 });
    assert.deepEqual(meta["dosyalar"], {
      junit: "junit.xml", json: "results.json", allure: "allure-results", html: "playwright-report",
      artifacts: "artifacts", log: "run-checks.log",
    });
    assert.deepEqual(meta["generated_tests"], [
      "e2e/tests/generated/tpd-1-kampanya.spec.ts",
      "e2e/tests/generated/tpd-1-sinir.spec.ts",
    ]);
    assert.ok(String(meta["results_kok"]).endsWith("demo-app/e2e/results"));
  });

  it("beklenmeyen sonuç → failed (defect adayı / kırık locator ayrımı triage'ın işi)", () => {
    const dir = tmp("ci-res-");
    resultsFixture(dir, { expected: 4, unexpected: 1, flaky: 0, skipped: 0 });
    const r = run("github-ci-results.sh", ["--out", "o", "--src", "demo-app/e2e/results", "--exit-code", "1"], dir, GH);
    assert.equal(r.status, 0, r.stderr);
    assert.equal(readJson(join(dir, "o/ci-meta.json"))["durum"], "failed");
  });

  it("rapor yoksa (tsc/eslint kırmızı) → error + açıklama; dosyalar null", () => {
    const dir = tmp("ci-res-");
    resultsFixture(dir, null);
    const r = run("github-ci-results.sh", ["--out", "o", "--src", "demo-app/e2e/results", "--exit-code", "2"], dir, GH);
    assert.equal(r.status, 0, r.stderr);
    const meta = readJson(join(dir, "o/ci-meta.json"));
    assert.equal(meta["durum"], "error");
    assert.match(String(meta["hata"]), /JSON raporu üretilmedi/);
    assert.equal((meta["dosyalar"] as Record<string, unknown>)["json"], null);
    assert.equal(meta["stats"], null);
  });

  it("hiç test koşmadıysa error; rapor düzeyinde hata error; çıkış ≠0 ve yeşil sayılar error", () => {
    const cases: [Record<string, number>, unknown[], string, string][] = [
      [{ expected: 0, unexpected: 0, flaky: 0, skipped: 3 }, [], "0", "error"],
      [{ expected: 3, unexpected: 0, flaky: 0, skipped: 0 }, [{ message: "config hatası" }], "1", "error"],
      [{ expected: 3, unexpected: 0, flaky: 0, skipped: 0 }, [], "1", "error"],
    ];
    for (const [stats, errors, code, want] of cases) {
      const dir = tmp("ci-res-");
      writeTree(dir, { "r/results.json": pwReport(stats, errors) });
      const r = run("github-ci-results.sh", ["--out", "o", "--src", "r", "--exit-code", code], dir, GH);
      assert.equal(r.status, 0, r.stderr);
      assert.equal(readJson(join(dir, "o/ci-meta.json"))["durum"], want, JSON.stringify({ stats, errors, code }));
    }
  });

  it("kullanım hatası: --out/--src yok veya çıkış kodu sayı değil → 2", () => {
    const dir = tmp("ci-res-");
    assert.equal(run("github-ci-results.sh", ["--src", "x"], dir).status, 2);
    assert.equal(run("github-ci-results.sh", ["--out", "o"], dir).status, 2);
    assert.equal(run("github-ci-results.sh", ["--out", "o", "--src", "x", "--exit-code", "a;b"], dir).status, 2);
  });

  it("Playwright raporlayıcı yolları betiğin beklediği adlarla aynı (results/junit.xml, results.json, html, allure-results)", () => {
    const cfg = readFileSync(join(REPO_ROOT, "demo-app", "e2e", "playwright.config.ts"), "utf8");
    assert.match(cfg, /\["junit",\s*\{\s*outputFile:\s*"results\/junit\.xml"/);
    assert.match(cfg, /\["json",\s*\{\s*outputFile:\s*"results\/results\.json"/);
    assert.match(cfg, /\["html",\s*\{\s*outputFolder:\s*"results\/html"/);
    assert.match(cfg, /resultsDir:\s*"results\/allure-results"/);
    assert.match(cfg, /outputDir:\s*"\.\/results\/artifacts"/);
    assert.match(cfg, /testDir:\s*"\.\/tests"/, "tests/generated testDir altında kalmalı");
  });
});

describe("github-sauce-summary.sh (sauce.json)", () => {
  const SAUCE_URL = "https://app.saucelabs.com/tests/0123456789abcdef0123456789abcdef";
  const EU_URL = "https://app.eu-central-1.saucelabs.com/tests/fedcba9876543210fedcba9876543210";

  it("kimlik yoksa: atlandi + neden; özet yazılır", () => {
    const dir = tmp("sauce-");
    const r = run("github-sauce-summary.sh", ["--out", "s", "--region", "us-west-1", "--skipped", "kimlik yok"], dir, GH);
    assert.equal(r.status, 0, r.stderr);
    const j = readJson(join(dir, "s/sauce.json"));
    assert.equal(j["kaynak"], "sauce");
    assert.equal(j["durum"], "atlandi");
    assert.equal(j["neden"], "kimlik yok");
    assert.equal(j["job_url"], null);
    assert.equal(j["istek_id"], "ist-42");
    assert.match(r.summary, /Atlandı: kimlik yok/);
  });

  it("saucectl raporundan job linkleri; VM'deki Playwright raporları köke alınır; özet linkleri içerir", () => {
    const dir = tmp("sauce-");
    writeTree(dir, {
      "demo-app/results/sauce/saucectl-report.json": JSON.stringify({
        testResults: [
          { name: "Chromium — Windows 11", status: "passed", url: SAUCE_URL, browser: "chromium", platform: "Windows 11" },
          { name: "kötü | ad", status: "passed", url: "https://evil.example.com/tests/abc" },
        ],
      }),
      "demo-app/results/sauce/saucectl-junit.xml": "<testsuites name='saucectl'/>",
      "demo-app/results/sauce/artifacts/Chromium — Windows 11/results/junit.xml": "<testsuites name='pw'/>",
      "demo-app/results/sauce/artifacts/Chromium — Windows 11/results/results.json": pwReport({ expected: 1 }),
      "demo-app/results/sauce/artifacts/Chromium — Windows 11/video.mp4": "mp4",
      "results/sauce/saucectl.log": "log",
    });
    const r = run(
      "github-sauce-summary.sh",
      ["--out", "s", "--report", "demo-app/results/sauce/saucectl-report.json",
        "--junit", "demo-app/results/sauce/saucectl-junit.xml", "--artifacts", "demo-app/results/sauce/artifacts",
        "--log", "results/sauce/saucectl.log", "--exit-code", "0", "--region", "us-west-1", "--tunnel", "tp-1-1"],
      dir,
      GH,
    );
    assert.equal(r.status, 0, r.stderr);
    const j = readJson(join(dir, "s/sauce.json"));
    assert.equal(j["durum"], "passed");
    assert.equal(j["job_url"], SAUCE_URL);
    assert.deepEqual(j["jobs"], [
      { id: "0123456789abcdef0123456789abcdef", url: SAUCE_URL, ad: "Chromium — Windows 11", durum: "passed",
        tarayici: "chromium", platform: "Windows 11" },
    ]);
    assert.equal(j["saucectl_exit"], 0);
    assert.equal(j["tunel"], "tp-1-1");
    const files = j["dosyalar"] as Record<string, unknown>;
    assert.equal(files["junit_turu"], "playwright");
    assert.equal(readFileSync(join(dir, "s/junit.xml"), "utf8"), "<testsuites name='pw'/>");
    assert.ok(existsSync(join(dir, "s/results.json")));
    assert.ok(existsSync(join(dir, "s/artifacts/Chromium — Windows 11/video.mp4")));
    assert.match(r.summary, new RegExp(SAUCE_URL.replace(/[.]/g, "\\.")));
    assert.doesNotMatch(r.summary, /evil\.example/);
  });

  it("rapor yoksa log'dan link (AB bölgesi); kırmızı job → failed; saucectl JUnit'i yedek", () => {
    const dir = tmp("sauce-");
    writeTree(dir, {
      "log.txt": `Suite finished. passed=false url=${EU_URL}\nagain ${EU_URL}\n`,
      "sc.xml": "<testsuites name='saucectl'/>",
    });
    const r = run("github-sauce-summary.sh", ["--out", "s", "--log", "log.txt", "--junit", "sc.xml", "--exit-code", "1"], dir, GH);
    assert.equal(r.status, 0, r.stderr);
    const j = readJson(join(dir, "s/sauce.json"));
    assert.equal(j["durum"], "failed");
    assert.equal(j["job_url"], EU_URL);
    assert.equal((j["jobs"] as unknown[]).length, 1);
    assert.equal((j["dosyalar"] as Record<string, unknown>)["junit_turu"], "saucectl");

    const dir2 = tmp("sauce-");
    writeTree(dir2, {
      "rep.json": JSON.stringify([{ name: "s", status: "failed", url: SAUCE_URL }]),
    });
    const r2 = run("github-sauce-summary.sh", ["--out", "s", "--report", "rep.json", "--exit-code", "1"], dir2, GH);
    assert.equal(r2.status, 0, r2.stderr);
    assert.equal(readJson(join(dir2, "s/sauce.json"))["durum"], "failed");
  });

  it("saucectl ≠0 ve job yok → error (tünel/kimlik); saucectl hiç koşmadı → error", () => {
    const dir = tmp("sauce-");
    const r = run("github-sauce-summary.sh", ["--out", "s", "--exit-code", "2"], dir, GH);
    assert.equal(r.status, 0, r.stderr);
    const j = readJson(join(dir, "s/sauce.json"));
    assert.equal(j["durum"], "error");
    assert.match(String(j["neden"]), /Sauce job'u oluşmadı/);
    const dir2 = tmp("sauce-");
    const r2 = run("github-sauce-summary.sh", ["--out", "s", "--exit-code", ""], dir2, GH);
    assert.equal(r2.status, 0, r2.stderr);
    assert.equal(readJson(join(dir2, "s/sauce.json"))["durum"], "error");
  });
});

describe("github-break-verify-result.sh (break-verify.json)", () => {
  const BV = join(REPO_ROOT, "demo-app", "ci", "break-verify.sh");

  it("break-verify.sh'in adım ve hata satırları sınıflandırmanın dayandığı metinle aynı", () => {
    const src = readFileSync(BV, "utf8");
    assert.match(src, /step "1\/3 /);
    assert.match(src, /step "2\/3 /);
    assert.match(src, /step "3\/3 /);
    assert.match(src, /printf '\\n==> %s\\n'/);
    assert.match(src, /HATA: kampanya kuralı bozukken testler yeşil — testler kuralı yakalamıyor/);
  });

  const cases: [string, string, string, number | null][] = [
    ["==> 1/3 normal\n==> 2/3 BREAK\n==> 3/3 normal\nKırarak doğrulama ✓\n", "0", "kanitlandi", 3],
    ["==> 1/3 normal\n==> 2/3 BREAK\nHATA: kampanya kuralı bozukken testler yeşil — testler kuralı yakalamıyor\n", "1", "zayif_test", 2],
    ["==> 1/3 normal\nHATA: kırılma olmadan kampanya testleri kırmızı\n", "1", "hata", 1],
    ["", "", "hata", null],
  ];
  for (const [log, code, want, adim] of cases) {
    it(`${want} (adım ${adim ?? "-"})`, () => {
      const dir = tmp("bv-");
      writeTree(dir, { "bv.log": log });
      mkdirSync(join(dir, "r"));
      const r = run("github-break-verify-result.sh", ["--out", "o", "--log", "bv.log", "--exit-code", code, "--grep", "kampanya"], dir, GH);
      assert.equal(r.status, 0, r.stderr);
      const j = readJson(join(dir, "o/break-verify.json"));
      assert.equal(j["sonuc"], want);
      assert.equal(j["adim"], adim);
      assert.equal(j["grep"], "kampanya");
      if (want === "kanitlandi") assert.equal(j["neden"], null);
      else assert.ok(j["neden"]);
      assert.match(r.summary, /Kırarak doğrula/);
    });
  }
});
