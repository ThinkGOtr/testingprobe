// Portal nginx proxy süreleri ↔ core bekleme süreleri. POST /publish core'da iş bitene kadar
// `BEKLEME_S` bekleyip 202 döner; proxy okuma süresi bundan kısaysa 202 portala ulaşmaz (504).
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const kok = resolve(__dirname, "../..");
const nginx = readFileSync(resolve(kok, "nginx.conf"), "utf8");

/** `location <eşleşme> { … }` bloğundaki `proxy_read_timeout` (saniye); yoksa null. */
function okumaSuresi(eslesme: string): number | null {
  const bas = nginx.indexOf(`location ${eslesme} {`);
  if (bas < 0) return null;
  const blok = nginx.slice(bas, nginx.indexOf("}", bas));
  const m = /proxy_read_timeout\s+(\d+)(s|m|h)?;/.exec(blok);
  if (!m) return null;
  const n = Number(m[1]);
  return m[2] === "m" ? n * 60 : m[2] === "h" ? n * 3600 : n;
}

describe("nginx: POST /publish proxy okuma süresi core beklemesinden uzun", () => {
  // Varsayılan değer core'daki publish.service.BEKLEME_S ile aynı; dosya varsa oradan okunur.
  const servis = resolve(kok, "../core/src/tp_core/features/publish/service.py");
  const beklemeS = existsSync(servis) ? Number(/^BEKLEME_S\s*=\s*([\d.]+)/m.exec(readFileSync(servis, "utf8"))?.[1]) : 45;

  it("core BEKLEME_S okunur", () => {
    expect(beklemeS).toBeGreaterThan(0);
  });

  it("/api/publish kendi location'ında, okuma süresi ≥ BEKLEME_S + 15 sn pay", () => {
    const sure = okumaSuresi("= /api/publish");
    expect(sure).not.toBeNull();
    expect(sure!).toBeGreaterThanOrEqual(beklemeS + 15);
  });

  it("genel /api/ bloğu yayın beklemesini taşımaz (ayrı blok zorunlu)", () => {
    const genel = okumaSuresi("/api/");
    expect(genel).not.toBeNull();
    // Genel blok kısa kalabilir; ama kısaysa yayın ayrı blokta olmalı (yukarıdaki test).
    if (genel! < beklemeS) expect(nginx).toContain("location = /api/publish {");
  });
});
