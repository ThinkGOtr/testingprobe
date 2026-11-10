// Vendor'lanmış <aiprobe-switcher>: platformdaki sürümlü dağıtım dosyasıyla bayt bayt aynı (SRI sabit).
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { DEGISTIRICI_SURUMU } from "./degistirici";

const VENDOR = resolve(__dirname, `../vendor/aiprobe-switcher/switcher-${DEGISTIRICI_SURUMU}.js`);
// aiprobe-platform/packages/switcher/dist/switcher-1.0.1.js.sri (= web/home/sdk/switcher-1.0.1.js) (sürüm yükseltme = bu değer + dosya).
const SRI = "sha384-IG7/pMHXzbcLypcW9j+ETg/Lz8HdEEJ1xxDsbp27x2qqElyLMHhBjol/3mwssogP";
const PLATFORM = resolve(__dirname, "../../../../aiprobe-platform");
const PLATFORM_DIST = resolve(PLATFORM, `web/home/sdk/switcher-${DEGISTIRICI_SURUMU}.js`);

describe("vendor <aiprobe-switcher>", () => {
  const kaynak = readFileSync(VENDOR);

  it("sha384 platform dağıtımının SRI'sıyla aynı", () => {
    expect(`sha384-${createHash("sha384").update(kaynak).digest("base64")}`).toBe(SRI);
  });

  it("dosyadaki VERSION dosya adıyla aynı", () => {
    expect(kaynak.toString("utf8")).toContain(`export const VERSION = '${DEGISTIRICI_SURUMU}';`);
  });

  it.skipIf(!existsSync(PLATFORM_DIST))("aiprobe-platform web/home/sdk dosyasıyla bayt bayt aynı (repo yanındaysa)", () => {
    expect(kaynak.equals(readFileSync(PLATFORM_DIST))).toBe(true);
  });

  it("dış köken betiği yok: yalnız kataloğu/durumu fetch eder (CSP connect-src home)", () => {
    const metin = kaynak.toString("utf8");
    expect(metin).not.toMatch(/import\s*\(|document\.write|eval\(|new Function/);
  });
});
