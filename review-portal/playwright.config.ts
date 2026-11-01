import { defineConfig, devices } from "@playwright/test";

// İki mod:
// - Varsayılan (duman): portal örnek veri modunda (vite build --mode mock) vite preview ile açılır;
//   arka uç gerekmez. `canli.spec.ts` atlanır.
// - PORTAL_LIVE=1 (canlı yığın): yalnızca `canli.spec.ts` koşar, çalışan portala bağlanır
//   (PORTAL_URL, varsayılan compose'daki http://127.0.0.1:8080). Sunucu başlatılmaz; `make up`
//   ile ayağa kalkmış yığın gerekir. Giriş parolası SEED_USER_PASSWORD (ya da PORTAL_PASSWORD).
const CANLI = process.env.PORTAL_LIVE === "1";
const PORT = Number(process.env.PORTAL_E2E_PORT ?? 4173);
const BASE_URL = CANLI ? (process.env.PORTAL_URL ?? "http://127.0.0.1:8080") : `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./e2e/sonuclar",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  reporter: [["list"]],
  ...(CANLI ? { testMatch: /canli\.spec\.ts$/ } : { testIgnore: /canli\.spec\.ts$/ }),
  use: {
    baseURL: BASE_URL,
    // Canlı modda iz (trace) KAPALI: iz dosyası doldurulan parolayı düz metin taşır (sır sızıntısı).
    trace: CANLI ? "off" : "retain-on-failure",
    actionTimeout: 10_000,
    locale: "tr-TR",
    timezoneId: "Europe/Istanbul",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  ...(CANLI
    ? {}
    : {
        webServer: {
          command: `npm run build:mock && npx vite preview --host 127.0.0.1 --port ${PORT} --strictPort`,
          url: `http://127.0.0.1:${PORT}/giris`,
          reuseExistingServer: false,
          timeout: 120_000,
        },
      }),
});
