// Portal nginx proxy süreleri ↔ core bekleme süreleri. POST /publish core'da iş bitene kadar
// `BEKLEME_S` bekleyip 202 döner; proxy okuma süresi bundan kısaysa 202 portala ulaşmaz (504).
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
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

/** `location <eşleşme> { … }` bloğunun gövdesi (iç içe süslü parantez yok). */
function blok(eslesme: string): string | null {
  const bas = nginx.indexOf(`location ${eslesme} {`);
  if (bas < 0) return null;
  return nginx.slice(bas, nginx.indexOf("}", bas));
}

describe("nginx: koşu artefaktları tek CSP ile sunulur (Playwright HTML raporu boş açılmaz)", () => {
  it("/api/artifacts/ kendi location'ında; portal CSP'si eklemez, kendi add_header'ı ile mirası keser", () => {
    const b = blok("/api/artifacts/");
    expect(b).not.toBeNull();
    expect(b!).toContain("proxy_pass http://$upstream;");
    expect(b!).toMatch(/rewrite \^\/api\/\(\.\*\)\$ \/\$1 break;/);
    // add_header içeren location sunucu düzeyindeki başlıkları miras almaz: en az bir add_header şart.
    expect(b!).toMatch(/add_header\s+/);
    // Core sandbox CSP'si gönderir; ikinci (portal) CSP raporun satır içi betiklerini engeller.
    expect(b!).not.toMatch(/Content-Security-Policy/);
  });

  it("genel /api/ bloğu add_header tanımlamaz (sunucu CSP'sini miras alır) — artefakt bloğu bu yüzden ayrı", () => {
    expect(blok("/api/")!).not.toMatch(/add_header/);
    expect(nginx).toMatch(/server \{[\s\S]*add_header Content-Security-Policy "default-src 'self'/);
  });
});

describe("nginx: Playwright HTML raporu opak kökende çalışır (localStorage yedeği)", () => {
  const bas = nginx.indexOf("location ~ ^/api/artifacts/runs/");
  const b = bas >= 0 ? nginx.slice(bas, nginx.indexOf("\n    }", bas)) : "";
  it("rapor index.html'i ayrı regex location'da; CSP eklemez, gövdeye Storage yedeği enjekte eder", () => {
    expect(b).not.toBe("");
    expect("/api/artifacts/runs/396f7376-108e-4706-b2b3-c15e67071894/src/e2e/results/html/index.html").toMatch(
      new RegExp(/location ~ (\S+) \{/.exec(b)![1]),
    );
    expect(b).not.toMatch(/Content-Security-Policy/);
    expect(b).toMatch(/proxy_set_header Accept-Encoding "";/);
    expect(b).toMatch(/sub_filter '<head>' '<head><script>/);
    // Köken gevşetilmez: yedek yalnızca erişim hata verirse tanımlanır, allow-same-origin eklenmez.
    const direktifler = nginx.split("\n").filter((l) => !l.trim().startsWith("#")).join("\n");
    expect(direktifler).not.toMatch(/allow-same-origin/);
  });
});

describe("nginx: /api/health core-api hazırlığını yansıtır (AI Probe on-demand yoklaması)", () => {
  it("kendi location'ında core /health'e gider (statik portal /health değil), kısa süreli", () => {
    const b = blok("= /api/health");
    expect(b).not.toBeNull();
    expect(b!).toContain("proxy_pass http://$upstream;");
    expect(b!).toMatch(/rewrite \^\/api\/\(\.\*\)\$ \/\$1 break;/);
    expect(b!).not.toMatch(/return 200/);
    expect(okumaSuresi("= /api/health")!).toBeLessThanOrEqual(10);
  });
});

describe("nginx CSP kimlik kipine göre (docker/40-tp-kimlik-csp.sh)", () => {
  const betik = resolve(kok, "docker/40-tp-kimlik-csp.sh");
  const dockerfile = readFileSync(resolve(kok, "Dockerfile"), "utf8");

  function calistir(env: Record<string, string>): { kod: number; cikti: string; hata: string } {
    const dizin = mkdtempSync(join(tmpdir(), "tp-csp-"));
    const hedef = join(dizin, "nginx.conf");
    const r = spawnSync("sh", [betik], {
      env: { PATH: process.env.PATH ?? "/usr/bin:/bin", TP_NGINX_SABLON: resolve(kok, "nginx.conf"), TP_NGINX_CONF: hedef, ...env },
      encoding: "utf8",
    });
    const cikti = existsSync(hedef) ? readFileSync(hedef, "utf8") : "";
    rmSync(dizin, { recursive: true, force: true });
    return { kod: r.status ?? -1, cikti, hata: r.stderr };
  }
  const csp = (conf: string) => [...conf.matchAll(/add_header\s+Content-Security-Policy\s+"([^"]+)"/g)].map((m) => m[1]!);

  it("local (varsayılan): yapılandırma şablonla bayt bayt aynı, dış köken yok", () => {
    const { kod, cikti } = calistir({});
    expect(kod).toBe(0);
    expect(cikti).toBe(nginx);
    for (const c of csp(cikti)) expect(c).not.toMatch(/https:/);
  });

  it.each(["aiprobe", "both"])("%s: connect-src ve img-src'ye yalnız home kökeni; script-src değişmez", (kip) => {
    const { kod, cikti } = calistir({ TP_AUTH_MODE: kip });
    expect(kod).toBe(0);
    const basliklar = csp(cikti);
    expect(basliklar).toHaveLength(csp(nginx).length);
    for (const c of basliklar) {
      expect(c).toContain("connect-src 'self' https://home.aiprobe.antreklabs.com;");
      expect(c).toContain("img-src 'self' data: https://home.aiprobe.antreklabs.com;");
      expect(c).toMatch(/^default-src 'self';/);
      expect(c).not.toMatch(/script-src/);
    }
    // CSP dışında hiçbir satır değişmez.
    expect(cikti.replaceAll(" https://home.aiprobe.antreklabs.com", "")).toBe(nginx);
  });

  it("AIPROBE_HOME_ORIGIN ile köken değişir; geçersiz köken/kip kabı başlatmaz (fail-closed)", () => {
    expect(csp(calistir({ TP_AUTH_MODE: "aiprobe", AIPROBE_HOME_ORIGIN: "https://home.test:8443" }).cikti)[0]).toContain(
      "connect-src 'self' https://home.test:8443;",
    );
    for (const koken of ["http://home.test", "https://home.test/yol", "https://x.test; script-src *", "*"]) {
      expect(calistir({ TP_AUTH_MODE: "aiprobe", AIPROBE_HOME_ORIGIN: koken }).kod, koken).not.toBe(0);
    }
    expect(calistir({ TP_AUTH_MODE: "acik" }).kod).not.toBe(0);
  });

  it("Dockerfile betiği entrypoint dizinine, değişmez şablonu ayrı yola koyar", () => {
    expect(dockerfile).toContain("COPY nginx.conf /etc/nginx/tp/nginx.conf.sablon");
    expect(dockerfile).toContain("COPY --chown=nginx:nginx nginx.conf /etc/nginx/nginx.conf");
    expect(dockerfile).toMatch(/COPY --chmod=0755 docker\/40-tp-kimlik-csp\.sh \/docker-entrypoint\.d\//);
  });
});
