// Test ortamları uyum katmanı: `GET /environments` ve koşuların `test_ortami` alanı. Eksik/bozuk alan
// null'a iner (eski core, ortamsız koşu); hiçbir değer uydurulmaz.
import { ORTAM_TURLERI, type Ortam, type Ortamlar, type OrtamTuru, type TestOrtami } from "./types";
import { nesneMi } from "./uyum";

const TURLER = new Set<string>(ORTAM_TURLERI);

export function testOrtamiUyarla(x: unknown): TestOrtami | null {
  if (!nesneMi(x)) return null;
  const eid = typeof x.eid === "string" ? x.eid : "";
  if (!eid) return null;
  const tur: OrtamTuru = typeof x.tur === "string" && TURLER.has(x.tur) ? (x.tur as OrtamTuru) : "test";
  return {
    eid,
    ad: typeof x.ad === "string" && x.ad ? x.ad : eid,
    tur,
    // prod her zaman canlıdır (sözleşme); alan yoksa türden.
    canli: x.canli === true || tur === "prod",
  };
}

export function ortamlarUyarla(govde: unknown): Ortamlar {
  const g = nesneMi(govde) ? govde : {};
  const ham = Array.isArray(g.ortamlar) ? g.ortamlar : [];
  const vid = typeof g.varsayilan_eid === "string" && g.varsayilan_eid ? g.varsayilan_eid : null;
  const ortamlar: Ortam[] = [];
  for (const o of ham) {
    const t = testOrtamiUyarla(o);
    if (t) ortamlar.push({ ...t, varsayilan: (nesneMi(o) && o.varsayilan === true) || t.eid === vid });
  }
  return { ortamlar, varsayilan_eid: vid ?? ortamlar.find((o) => o.varsayilan)?.eid ?? null };
}

/** Projenin varsayılan ortamı (yoksa null). */
export function varsayilanOrtam(o: Ortamlar | null | undefined): Ortam | null {
  if (!o) return null;
  return o.ortamlar.find((x) => x.eid === o.varsayilan_eid) ?? o.ortamlar.find((x) => x.varsayilan) ?? null;
}
