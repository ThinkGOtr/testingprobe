import { defineConfig, devices } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { yerelZaman } from "./zaman.js";

// Demo provası (arayüz). İki kip (UI_KIP):
// - tur   (varsayılan): salt okuma. Tamamlanmış akışın ekranlarını rol rol gezer; yığını değiştirmez.
//         Sunucunun yedek videosu ve ekran görüntüleri için.
// - canli: sunucunun yapacağı her eylemi portal + jira-sim arayüzünden yapar (temiz `make reset`
//          ister; scripts/demo-prova.sh --ui).
// Çıktı: rehearsal/reports/<zaman>-ui-<kip>[-k<n>]/ — ekranlar/NN-*.png, video/*.webm, rapor.md.
// <zaman> YEREL saattir (scripts/demo-prova.sh özeti ve API raporlarıyla aynı); demo-prova dizini
// kendisi verir (UI_RAPOR_DIZINI), böylece özet her zaman bu koşunun raporunu gösterir.
//
// İz (trace) KAPALI: Playwright izi form doldurma argümanlarını ve giriş POST gövdelerini kaydeder —
// portal ve jira-sim PO parolaları düz metin olarak trace.zip'e girer. Tanı için video + adım ekranları
// yeter; demo-prova her koşudan sonra dizini .env sırlarına karşı tarar (tp_rehearsal.sir_tarama).
const BURASI = dirname(fileURLToPath(import.meta.url));
const KIP = process.env.UI_KIP === "canli" ? "canli" : "tur";
const kosu = process.env.PROVA_KOSU ? `-k${process.env.PROVA_KOSU}` : "";
export const RAPOR_DIZINI =
  process.env.UI_RAPOR_DIZINI ?? resolve(BURASI, "..", "reports", `${yerelZaman(new Date())}-ui-${KIP}${kosu}`);
process.env.UI_RAPOR_DIZINI = RAPOR_DIZINI;
mkdirSync(join(RAPOR_DIZINI, "ekranlar"), { recursive: true, mode: 0o700 });

export default defineConfig({
  testDir: ".",
  testMatch: /prova\.spec\.ts$/,
  outputDir: join(RAPOR_DIZINI, "video"),
  timeout: KIP === "canli" ? 45 * 60_000 : 10 * 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.PORTAL_URL ?? "http://127.0.0.1:8080",
    locale: "tr-TR",
    timezoneId: "Europe/Istanbul",
    actionTimeout: 15_000,
    trace: "off", // parolalar ize düşer (yukarıdaki not); değiştirmeyin
    video: { mode: "on", size: { width: 1440, height: 900 } },
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
});
