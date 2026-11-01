import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Tarayıcısız birim testleri (yardımcılar): `npm run birim`. Prova yapılandırmasını (rapor dizini,
// video) yüklemez; yığın gerekmez.
export default defineConfig({
  testDir: ".",
  testMatch: /birim\.spec\.ts$/,
  reporter: [["list"]],
  outputDir: join(tmpdir(), "tp-rehearsal-ui-birim"),
});
