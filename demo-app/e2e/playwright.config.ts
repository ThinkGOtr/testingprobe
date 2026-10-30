import { defineConfig, devices } from "@playwright/test";
import { randomBytes } from "node:crypto";
import { fileURLToPath } from "node:url";

// BASE_URL verilirse (compose / test-runner hedefi) çalışan uygulamaya karşı koşar.
// Verilmezse uygulama CI ile aynı yolla `webServer` dizisiyle başlar:
//   API: uvicorn + SQLite (DEMOAPP_TEST_MODE=1)
//   Web: vite build && vite preview (/api → API proxy)
// Veri yalıtımı ve BREAK_CAMPAIGN: tests/fixtures.ts. Kırılma her iki modda da AYNI yolla,
// bayi kapsamında POST /test/break ile açılır; API sürecine BREAK_CAMPAIGN geçirilmez.
const here = fileURLToPath(new URL(".", import.meta.url));
const apiPort = Number(process.env.DEMO_API_PORT ?? 18000);
const webPort = Number(process.env.DEMO_WEB_PREVIEW_PORT ?? 18081);
const sqlitePath = `${here}results/demoapp-e2e.db`;
const apiCommand =
  process.env.DEMO_API_COMMAND ??
  `uv run --frozen --no-dev uvicorn demoapp_api.main:app --host 127.0.0.1 --port ${apiPort}`;

const baseURL = process.env.BASE_URL ?? `http://127.0.0.1:${webPort}`;
// Uygulama dışarıda çalışıyorsa (BASE_URL ya da TP_EXTERNAL_SERVER=1: Sauce/CI) webServer başlatılmaz.
const externalServer = !!process.env.BASE_URL || process.env.TP_EXTERNAL_SERVER === "1";

// /test/reset paylaşılan token'ı. webServer modunda her koşu için rastgele üretilir ve hem
// başlatılan API'ye hem işçilere (process.env kalıtımı) geçer. Dış sunucu modunda dışarıdan verilir.
if (!externalServer && !process.env.DEMOAPP_TEST_TOKEN) {
  process.env.DEMOAPP_TEST_TOKEN = randomBytes(24).toString("hex");
}

// Token yokken TP_E2E_NO_RESET=1: yalnızca sepet yalıtımı; sipariş geçmişi silinemediği için
// boş veri varsayan @sifir-veri testleri koşmaz.
const cartOnlyIsolation = !process.env.DEMOAPP_TEST_TOKEN && process.env.TP_E2E_NO_RESET === "1";

export default defineConfig({
  testDir: "./tests",
  grepInvert: cartOnlyIsolation ? /@sifir-veri/ : undefined,
  outputDir: "./results/artifacts",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  // Paralel işçi başına bir bayi kullanıcısı (bayi1, bayi2); bkz. tests/fixtures.ts.
  workers: 2,
  // Yeniden deneme CLI'dan verilir (CI: --retries=1).
  retries: 0,
  timeout: 20_000,
  expect: { timeout: 5_000 },
  reporter: [
    ["list"],
    ["junit", { outputFile: "results/junit.xml" }],
    ["json", { outputFile: "results/results.json" }],
    ["allure-playwright", { resultsDir: "results/allure-results" }],
    ["html", { outputFolder: "results/html", open: "never" }],
  ],
  use: {
    baseURL,
    locale: "tr-TR",
    timezoneId: "Europe/Istanbul",
    testIdAttribute: "data-testid",
    actionTimeout: 5_000,
    navigationTimeout: 10_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: externalServer
    ? undefined
    : [
        {
          name: "demo-app-api",
          command: `rm -f "${sqlitePath}" "${sqlitePath}-wal" "${sqlitePath}-shm" && mkdir -p "${here}results" && ${apiCommand}`,
          cwd: "../api",
          url: `http://127.0.0.1:${apiPort}/health`,
          env: {
            DEMOAPP_DATABASE_URL: `sqlite:///${sqlitePath}`,
            DEMOAPP_TEST_MODE: "1",
            DEMOAPP_TEST_TOKEN: process.env.DEMOAPP_TEST_TOKEN ?? "",
            // Süreç geneli kırılma kapalı; kırılma bayi kapsamında fixture'dan açılır.
            BREAK_CAMPAIGN: "",
          },
          reuseExistingServer: false,
          timeout: 120_000,
          stdout: "ignore",
          stderr: "pipe",
        },
        {
          name: "demo-app-web",
          command: `npm run build && npx vite preview --host 127.0.0.1 --port ${webPort} --strictPort`,
          cwd: "../web",
          url: `http://127.0.0.1:${webPort}/`,
          env: { DEMOAPP_API_URL: `http://127.0.0.1:${apiPort}` },
          reuseExistingServer: false,
          timeout: 120_000,
          stdout: "ignore",
          stderr: "pipe",
        },
      ],
});
