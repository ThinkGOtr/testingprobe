// .github/workflows/ci.yml sözleşme testleri: workflow'un başka şeritlerin dosyalarıyla uyumu.
// (GitHub Actions burada koşturulamaz; kayma — rapor yolu, betik adı, imaj ön koşulu — yakalanır.)
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");
const ci = readFileSync(join(REPO_ROOT, ".github", "workflows", "ci.yml"), "utf8");

/** `- name: <ad>` ile başlayan adımın metni (bir sonraki adıma kadar). */
function step(name: string): string {
  const start = ci.indexOf(`- name: ${name}`);
  assert.ok(start >= 0, `adım bulunamadı: ${name}`);
  const next = ci.indexOf("\n      - name: ", start + 1);
  return ci.slice(start, next < 0 ? undefined : next);
}

/** `<job>:` ile başlayan job'un metni. */
function job(name: string): string {
  const start = ci.indexOf(`\n  ${name}:\n`);
  assert.ok(start >= 0, `job bulunamadı: ${name}`);
  const next = ci.slice(start + 1).search(/\n {2}[a-z][a-z0-9-]*:\n/);
  return ci.slice(start, next < 0 ? undefined : start + 1 + next);
}

describe("ci.yml ↔ Playwright raporlayıcı yolları", () => {
  it("HTML raporu, playwright.config.ts'teki outputFolder ile aynı yoldan yüklenir", () => {
    const cfg = readFileSync(join(REPO_ROOT, "demo-app", "e2e", "playwright.config.ts"), "utf8");
    const m = /\["html",\s*\{\s*outputFolder:\s*"([^"]+)"/.exec(cfg);
    assert.ok(m?.[1], "playwright.config.ts html raporlayıcısı outputFolder tanımlamalı");
    const folder = m[1].replace(/^\.\//, "").replace(/\/$/, "");
    const upload = step("Artefaktlar");
    assert.ok(upload.includes(`demo-app/e2e/${folder}/`), `artefakt yolları demo-app/e2e/${folder}/ içermeli`);
    assert.ok(!upload.includes("playwright-report/"), "eski (yanlış) playwright-report/ yolu kalmamalı");
  });

  it("junit ve json çıktıları da aynı adlarla yüklenir", () => {
    const cfg = readFileSync(join(REPO_ROOT, "demo-app", "e2e", "playwright.config.ts"), "utf8");
    const upload = step("Artefaktlar");
    for (const re of [/\["junit",\s*\{\s*outputFile:\s*"([^"]+)"/, /\["json",\s*\{\s*outputFile:\s*"([^"]+)"/]) {
      const out = re.exec(cfg)?.[1];
      assert.ok(out, re.source);
      assert.ok(upload.includes(`demo-app/e2e/${out}`), out);
    }
  });
});

describe("ci.yml test-local Yol A (toolchain imajı)", () => {
  const a = step("Testler (toolchain imajında)");

  it("imajda uv olmadığı için runner'daki uv salt-okunur bağlanır", () => {
    assert.match(a, /-v "\$uv_bin:\/usr\/local\/bin\/uv:ro"/);
    assert.match(step("uv kurulumu (toolchain imajına bağlanacak)"), /env\.TOOLCHAIN_IMAGE != ''/);
  });

  it("toolchain venv'i ezilmez: UV_PROJECT_ENVIRONMENT demo-app API .venv'ine yönlenir", () => {
    assert.match(a, /-e UV_PROJECT_ENVIRONMENT=\/work\/demo-app\/api\/\.venv/);
  });

  it("ön kontrol başarısızsa açık hata ile durur", () => {
    assert.match(a, /uv --version && "\$UV_PYTHON" --version && node --version/);
    assert.match(a, /::error::Toolchain imajında uv\/Python\/node çalışmıyor/);
  });

  it("imaj digest ile sabitlenmiş olmalı", () => {
    assert.match(a, /\*@sha256:\*\) ;;/);
  });
});

describe("ci.yml Sauce uygulama başlatma", () => {
  it("var olan betik kullanılır (demo-app/ci/serve.sh değil)", () => {
    assert.ok(existsSync(join(REPO_ROOT, "scripts", "github-demo-serve.sh")));
    const s = step("Uygulamayı runner'da başlat (QA ortamı)");
    assert.match(s, /bash scripts\/github-demo-serve\.sh/);
    assert.ok(!ci.includes("ci/serve.sh"), "ci.yml artık demo-app/ci/serve.sh'e bağlı olmamalı");
  });

  it("hazırlık /api/health ile (SPA geri dönüşüne düşen /health ile değil) ölçülür", () => {
    const s = step("Uygulamayı runner'da başlat (QA ortamı)");
    assert.match(s, /\$APP_PORT\/api\/health/);
    assert.ok(!/\$APP_PORT\/health/.test(s));
  });

  it("test token'ı maskelenir ve hem uygulamaya hem Sauce testlerine geçer", () => {
    const s = step("Uygulamayı runner'da başlat (QA ortamı)");
    assert.match(s, /::add-mask::\$token/);
    assert.match(step("Sauce'ta Playwright (Chromium)"), /-e "DEMOAPP_TEST_TOKEN=\$DEMOAPP_TEST_TOKEN"/);
  });

  it("duman testi job'u betiği --smoke ile koşar ve betik değişince tetiklenir", () => {
    assert.match(job("demo-serve-smoke"), /bash scripts\/github-demo-serve\.sh --smoke/);
    assert.match(job("changes"), /- 'scripts\/github-demo-serve\.sh'/);
  });
});

describe("ci.yml ast-guard modu", () => {
  it("mod betiği taban daldan çalışır ve değişince araç testleri koşar", () => {
    assert.match(step("Checkout (taban daldaki ast-guard + mod betiği)"), /\/scripts\/github-ast-guard-mode\.sh/);
    assert.match(job("changes"), /- 'scripts\/github-ast-guard-mode\.sh'/);
  });

  it("bot bilgisi (user.login, user.type, TP_BOT_LOGINS) mod betiğine geçer", () => {
    const j = job("ast-guard");
    assert.match(j, /PR_AUTHOR: \$\{\{ github\.event\.pull_request\.user\.login \}\}/);
    assert.match(j, /TP_BOT_LOGINS: \$\{\{ vars\.TP_BOT_LOGINS \}\}/);
  });
});

describe("ci.yml golden-drift (anayasa II: ajan bağımlılığı yok)", () => {
  const j = job("golden-drift");
  const req = readFileSync(join(REPO_ROOT, ".github", "golden-drift", "requirements.txt"), "utf8");

  it("core venv'ini kurmaz; yalnızca .github/golden-drift ortamında koşar", () => {
    assert.match(j, /working-directory: \.github\/golden-drift/);
    assert.match(j, /uv run --no-project --with-requirements requirements\.txt pytest -q/);
    assert.doesNotMatch(j, /working-directory: core\b/);
    assert.doesNotMatch(j, /uv (run|sync) --frozen/);
    assert.doesNotMatch(j, /core\/uv\.lock/);
    const code = j.replace(/^\s*#.*$/gm, "");
    assert.doesNotMatch(code, /test_consistency_flow\.py|tests\/unit\/gateway/);
  });

  it("ajan SDK'sı içe aktarılabiliyorsa job'u kıran adım var", () => {
    const s = step("Ajan bağımlılığı yok (anayasa II)");
    for (const mod of ["anthropic", "mcp", "tp_core"]) {
      assert.match(s, new RegExp(`"${mod}"`));
    }
    assert.match(s, /sys\.exit\(/);
  });

  it("requirements yalnızca sabit sürümlü pytest/jsonschema/pyyaml içerir", () => {
    const names = req
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith("#"));
    assert.deepEqual(names.map((l) => l.split("==")[0]).sort(), ["jsonschema", "pytest", "pyyaml"]);
    for (const l of names) assert.match(l, /^[a-z]+==\d+\.\d+\.\d+$/);
    assert.doesNotMatch(req.replace(/^#.*$/gm, ""), /anthropic|mcp|tp[-_]core/);
  });

  it("drift paketi değişince job tetiklenir; model anahtarı/secret görmez", () => {
    assert.match(job("changes"), /- '\.github\/golden-drift\/\*\*'/);
    assert.doesNotMatch(j, /secrets\./);
    assert.doesNotMatch(j, /ANTHROPIC/);
  });
});
