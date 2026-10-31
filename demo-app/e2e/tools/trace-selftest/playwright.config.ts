// tools/trace-token-selftest.js için: ana yapılandırmayla aynı fikstür yolu, her testte trace açık,
// kendi çıktı dizini ve SQLite dosyası (aynı anda koşan e2e ile çakışmaz).
import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import base from "../../playwright.config";

// webServer.cwd yapılandırma dosyasına görelidir; ana yapılandırmanın dizinine (e2e/) göre çözülür.
const e2eDir = fileURLToPath(new URL("../../", import.meta.url));

const ownDb = (s: string): string => s.replaceAll("results/demoapp-e2e.db", "results/trace-selftest/demoapp-e2e.db");

export default defineConfig({
  ...base,
  testDir: ".",
  outputDir: "../../results/trace-selftest/artifacts",
  workers: 1,
  reporter: [["json", { outputFile: "../../results/trace-selftest/results.json" }]],
  use: { ...base.use, trace: "on" },
  webServer: Array.isArray(base.webServer)
    ? base.webServer.map((w) => ({
        ...w,
        cwd: w.cwd === undefined ? undefined : resolve(e2eDir, w.cwd),
        command: `mkdir -p "${resolve(e2eDir, "results/trace-selftest")}" && ${ownDb(w.command)}`,
        env: Object.fromEntries(Object.entries(w.env ?? {}).map(([k, v]) => [k, ownDb(v)])),
      }))
    : base.webServer,
});
