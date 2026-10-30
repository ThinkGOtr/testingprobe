import { defineConfig, devices } from "@playwright/test";

// Ekran duman testi: portal örnek veri modunda (vite build --mode mock) vite preview ile açılır.
const PORT = Number(process.env.PORTAL_E2E_PORT ?? 4173);

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./e2e/sonuclar",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    actionTimeout: 10_000,
    locale: "tr-TR",
    timezoneId: "Europe/Istanbul",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: {
    command: `npm run build:mock && npx vite preview --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: `http://127.0.0.1:${PORT}/giris`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
