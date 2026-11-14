// .github/workflows/ci.yml sözleşme testleri: workflow'un başka şeritlerin dosyalarıyla uyumu.
// (GitHub Actions burada koşturulamaz; kayma — rapor yolu, betik adı, imaj ön koşulu — yakalanır.)
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
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

describe("ci.yml ↔ yerel koşu ile aynı artefakt düzeni (ci-runs alımı)", () => {
  it("sonuçlar github-ci-results.sh ile e2e/results'tan toplanır; artefakt kökü tp-results/", () => {
    const collect = step("Sonuçları topla (yerel koşu biçimi)");
    assert.match(collect, /if: always\(\) && env\.RUN_TESTS == 'true'/);
    assert.match(collect, /bash scripts\/github-ci-results\.sh --out tp-results/);
    assert.match(collect, /--src "\$E2E_ROOT\/results"/);
    assert.match(collect, /--exit-code "\$\{EXIT_A:-\$\{EXIT_B:-\}\}"/);
    assert.match(ci, /E2E_ROOT: demo-app\/e2e\n/);
    const upload = step("Artefaktlar");
    assert.match(upload, /name: test-local-results/);
    assert.match(upload, /path: tp-results\/\n/);
    assert.match(upload, /if-no-files-found: error/);
    assert.ok(!upload.includes("demo-app/e2e/results"), "ham yol yüklenmez (artefakt kökü düz olmalı)");
    assert.match(step("Playwright HTML raporu"), /name: playwright-report[\s\S]*path: tp-results\/playwright-report\//);
  });

  it("test adımları çıkış kodunu çıktı olarak verir (Yol A ve B)", () => {
    for (const name of ["Testler (toolchain imajında)", "Testler (runner üzerinde)"]) {
      const s = step(name);
      assert.match(s, /tee run-checks\.log \|\| rc=\$\{PIPESTATUS\[0\]\}/, name);
      assert.match(s, /echo "exit_code=\$rc" >> "\$GITHUB_OUTPUT"/, name);
      assert.match(s, /exit "\$rc"/, name);
    }
    assert.match(step("Testler (toolchain imajında)"), /id: tests_a/);
    assert.match(step("Testler (runner üzerinde)"), /id: tests_b/);
  });
});

describe("ci.yml tetikler ve çekirdek bağlantısı", () => {
  const on = ci.slice(ci.indexOf("\non:\n"), ci.indexOf("\npermissions:\n"));

  it("pull_request, push, repository_dispatch[deploy], workflow_dispatch; schedule yok (gece çekirdekten)", () => {
    for (const t of ["pull_request:", "push:", "repository_dispatch:", "workflow_dispatch:"]) {
      assert.ok(on.includes(`\n  ${t}`), t);
    }
    assert.match(on, /repository_dispatch:\n {4}types: \[deploy\]/);
    // Gece koşusunu çekirdek workflow_dispatch(tetik=nightly) ile başlatır: cron çift koşu açardı.
    assert.ok(!on.includes("\n  schedule:"), "ci.yml schedule içermemeli");
    assert.ok(!/- cron:/.test(on), "ci.yml cron içermemeli");
    assert.match(on, /tetik:[\s\S]*options: \[manual, nightly, deploy\]/);
    assert.match(on, /istek_id:/);
  });

  it("istek kimliği koşu adında; biçimi doğrulanır; çekirdek koşuları iptal edilmez", () => {
    assert.match(ci, /run-name: >-[\s\S]*format\('ci deploy \[\{0\}\]', github\.event\.client_payload\.istek_id/);
    assert.match(ci, /format\('ci \{0\} \[\{1\}\]', inputs\.tetik, inputs\.istek_id/);
    assert.match(ci, /TP_ISTEK_ID: \$\{\{ github\.event\.client_payload\.istek_id \|\| github\.event\.client_payload\.tp_run_id \|\| inputs\.istek_id \|\| '' \}\}/);
    assert.match(step("Karar"), /\^\[A-Za-z0-9\._-\]\{1,64\}\$/);
    assert.match(ci, /cancel-in-progress: \$\{\{ github\.event_name == 'pull_request' \}\}/);
  });

  it("deploy tetiğinde client_payload.ref checkout edilir (test-local, sauce)", () => {
    for (const j of ["test-local", "sauce"]) {
      assert.match(job(j), /ref: \$\{\{ github\.event\.client_payload\.ref \|\| '' \}\}/, j);
    }
  });

  it("üretilen testler (e2e/tests/generated) değişiklik tespitinde ve özette", () => {
    assert.match(ci, /GENERATED_TESTS: demo-app\/e2e\/tests\/generated\n/);
    assert.match(job("changes"), /generated:\n\s+- 'demo-app\/e2e\/tests\/generated\/\*\*'/);
    assert.match(job("changes"), /- 'demo-app\/\*\*'/, "demo-app/** test-local'i tetikler (generated dahil)");
  });

  it("CI'da model/ajan yok (anayasa II)", () => {
    const code = ci.replace(/^\s*#.*$/gm, "");
    assert.doesNotMatch(code, /ANTHROPIC_API_KEY|TP_MODEL_MODE|playwright-mcp|PLAYWRIGHT_MCP_URL/);
  });
});

describe("ci.yml Sauce → sauce.json", () => {
  const j = job("sauce");

  it("kimlik yoksa da checkout + sauce.json (atlandi) + artefakt", () => {
    const co = j.slice(j.indexOf("- name: Checkout"));
    assert.doesNotMatch(co.slice(0, co.indexOf("\n      - name: ", 1)), /if:/, "checkout koşulsuz");
    const s = step("Sauce özeti ve sauce.json");
    assert.match(s, /if: always\(\)/);
    assert.match(s, /bash scripts\/github-sauce-summary\.sh --out tp-sauce/);
    assert.match(s, /--skipped "Sauce kimliği/);
    assert.match(s, /--report demo-app\/results\/sauce\/saucectl-report\.json/);
    assert.match(s, /--exit-code "\$\{SAUCE_EXIT:-\}"/);
    const up = step("Sauce artefaktları");
    assert.match(up, /if: always\(\)/);
    assert.match(up, /name: sauce-results/);
    assert.match(up, /path: tp-sauce\/\n/);
  });

  it("saucectl raporu config'teki yola yazılır; üretilen testler testMatch'te", () => {
    const sc = readFileSync(join(REPO_ROOT, "demo-app", ".sauce", "config.yml"), "utf8");
    assert.match(sc, /filename: results\/sauce\/saucectl-report\.json/);
    assert.match(sc, /filename: results\/sauce\/saucectl-junit\.xml/);
    assert.match(sc, /directory: results\/sauce\/artifacts/);
    assert.match(sc, /testMatch: \[[^\]]*"tests\/generated\/\.\*\\\\\.spec\\\\\.ts"/);
    assert.match(step("Sauce'ta Playwright (Chromium)"), /working-directory: demo-app/);
    assert.match(step("Sauce'ta Playwright (Chromium)"), /echo "exit_code=\$rc" >> "\$GITHUB_OUTPUT"/);
  });
});

describe("break-verify.yml (GitHub modunda kırarak doğrula)", () => {
  const bv = readFileSync(join(REPO_ROOT, ".github", "workflows", "break-verify.yml"), "utf8");

  it("yalnızca workflow_dispatch; aynı betik; break-verify.json artefaktı; yazma yetkisi yok", () => {
    const on = bv.slice(bv.indexOf("\non:\n"), bv.indexOf("\npermissions:\n"));
    assert.deepEqual([...on.matchAll(/\n {2}([a-z_]+):/g)].map((m) => m[1]), ["workflow_dispatch"]);
    assert.match(bv, /bash demo-app\/ci\/break-verify\.sh/);
    assert.match(bv, /bash scripts\/github-break-verify-result\.sh --out tp-break/);
    assert.match(bv, /name: break-verify-results/);
    assert.match(bv, /permissions:\n {2}contents: read\n\n/);
    assert.doesNotMatch(bv.replace(/^\s*#.*$/gm, ""), /secrets\.|ANTHROPIC/);
  });

  // Belge gerçek kod yolunu anlatmalı: çekirdek bu workflow'u tetiklemez; GitHub modunda kırarak
  // doğrulama toolchain /check + TP_FORGE_REMOTE_URL aynasıyla yapılır. Biri çekirdeği bu
  // workflow'a bağlarsa ikinci test kırılır ve başlık/CI.md birlikte güncellenmelidir.
  it("başlık ve CI.md çekirdeğin bu workflow'u tetiklemediğini ve ayna şartını söyler", () => {
    const header = bv.slice(0, bv.indexOf("\nname: break-verify\n"));
    assert.match(header, /ÇEKİRDEK BU WORKFLOW'U TETİKLEMEZ/);
    assert.match(header, /TP_FORGE_REMOTE_URL/);
    assert.doesNotMatch(header, /çekirdek bu workflow'u `?workflow_dispatch`? ile/i);
    const doc = readFileSync(join(REPO_ROOT, ".github", "CI.md"), "utf8");
    const row = doc.split("\n").find((l) => l.startsWith("| `workflows/break-verify.yml`"));
    assert.ok(row, "CI.md break-verify satırı yok");
    assert.match(row, /elle/);
    assert.match(row, /çekirdek tetiklemez/);
    assert.match(doc, /### Kırarak doğrula ve GitHub modu[\s\S]*TP_FORGE_REMOTE_URL/);
  });

  it("çekirdek kodu break-verify.yml'yi dispatch etmez / artefaktını almaz (belge ile tutarlı)", () => {
    const src = join(REPO_ROOT, "core", "src", "tp_core");
    const hits: string[] = [];
    const walk = (dir: string): void => {
      for (const e of readdirSync(dir, { withFileTypes: true })) {
        const p = join(dir, e.name);
        if (e.isDirectory()) walk(p);
        else if (e.name.endsWith(".py") && !p.endsWith(join("integrations", "forge_github.py"))) {
          const t = readFileSync(p, "utf8");
          if (/BREAK_VERIFY_WORKFLOW|ARTIFACT_BREAK_VERIFY|break-verify\.yml|break-verify-results/.test(t)) {
            hits.push(p.slice(REPO_ROOT.length + 1));
          }
        }
      }
    };
    walk(src);
    assert.deepEqual(hits, [], "çekirdek break-verify.yml'ye bağlandı: başlığı ve CI.md'yi güncelle");
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

describe("tsc --strict kapısının yapılandırması korunur (Constitution IV)", () => {
  it("ast-guard tsconfig.json değişiminde de koşar (changes.pages filtresi)", () => {
    const changes = job("changes");
    const start = changes.indexOf("\n            pages:\n");
    assert.ok(start >= 0, "paths-filter pages girdisi yok");
    const pages = changes.slice(start, changes.indexOf("\n            generated:\n", start));
    assert.match(pages, /- 'demo-app\/e2e\/pages\/\*\*'/);
    assert.match(pages, /- 'demo-app\/e2e\/tsconfig\.json'/);
  });

  it("CODEOWNERS kalite kapısı yapılandırma dosyalarını kapsar", () => {
    const owners = readFileSync(join(REPO_ROOT, ".github", "CODEOWNERS"), "utf8")
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith("#"))
      .map((l) => l.split(/\s+/));
    const paths = new Set(owners.map((p) => p[0]));
    for (const p of [
      "/demo-app/e2e/tsconfig.json",
      "/demo-app/e2e/eslint.config.js",
      "/demo-app/e2e/playwright.config.ts",
      "/demo-app/ci/",
    ]) {
      assert.ok(paths.has(p), `CODEOWNERS kapsamıyor: ${p}`);
      const rel = p.replace(/^\//, "").replace(/\/$/, "");
      assert.ok(existsSync(join(REPO_ROOT, rel)), `CODEOWNERS yolu repoda yok: ${p}`);
    }
    for (const o of owners) assert.ok(o.length >= 2 && o.slice(1).every((x) => x.startsWith("@")), `sahipsiz satır: ${o.join(" ")}`);
  });
});
