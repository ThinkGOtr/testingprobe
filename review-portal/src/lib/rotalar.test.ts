// Rota desenleri: `ROTA_DESENLERI` ↔ App.tsx `<Route path>` ↔ core `rules/assistant/rotalar.json`
// (AI-ASISTAN-PLANI §13). `:id` kalıpları RegExp'e dönüştürülerek karşılaştırılır. rules/ Docker
// derleme bağlamında yok → skipIf.
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { ekranBaglamiCikar, EKRAN_ADLARI } from "./ekranBaglami";
import { desenKalibi, ROTA_DESENLERI, uygulamaRotasiMi } from "./rotalar";

const KOK = resolve(__dirname, "../../..");
const ROTALAR_JSON = resolve(KOK, "rules/assistant/rotalar.json");
const APP = resolve(__dirname, "../App.tsx");

/** JSON içindeki "/..." ya da "^/..." biçimli tüm dizgeler (dosya biçiminden bağımsız). */
function yolDizgeleri(o: unknown): string[] {
  if (typeof o === "string") return /^\^?\//.test(o) ? [o] : [];
  if (Array.isArray(o)) return o.flatMap(yolDizgeleri);
  if (o && typeof o === "object") return Object.values(o).flatMap(yolDizgeleri);
  return [];
}

const kaynak = (d: string) => (d.startsWith("^") ? new RegExp(d).source : desenKalibi(d).source);

describe("ROTA_DESENLERI", () => {
  it("RegExp kalıpları desenlerden türetilir", () => {
    expect(desenKalibi("/").test("/")).toBe(true);
    expect(desenKalibi("/gereksinimler/:id").test("/gereksinimler/abc")).toBe(true);
    expect(desenKalibi("/gereksinimler/:id").test("/gereksinimler/abc/caseler")).toBe(false);
    expect(uygulamaRotasiMi("/gereksinimler/x/caseler?sekme=1")).toBe(true);
    expect(uygulamaRotasiMi("/artifacts/x")).toBe(false);
  });

  it("App.tsx rotalarıyla aynı", () => {
    const metin = readFileSync(APP, "utf8");
    const yollar = [...metin.matchAll(/<Route\s+(?:index\b|path="([^"]+)")/g)]
      .map((m) => (m[1] === undefined ? "/" : m[1]))
      .filter((p) => p !== "*")
      .map((p) => (p.startsWith("/") ? p : `/${p}`));
    expect(new Set(yollar)).toEqual(new Set(ROTA_DESENLERI));
  });

  it("her desenin ekran adı var", () => {
    for (const d of ROTA_DESENLERI) expect(EKRAN_ADLARI[d], d).toBeTruthy();
  });

  it.skipIf(!existsSync(ROTALAR_JSON))("rules/assistant/rotalar.json ile aynı (giriş ve rol seçimi hariç)", () => {
    // /rol-sec (AI Probe rol seçici) asistan bağlamı dışındadır; rotalar.json'a girmez (core
    // test_rules_asistan.ASISTAN_DISI).
    const disarida = ["/giris", "/rol-sec"].map((d) => desenKalibi(d).source);
    const json = yolDizgeleri(JSON.parse(readFileSync(ROTALAR_JSON, "utf8")) as unknown);
    const portal = new Set(ROTA_DESENLERI.map(kaynak).filter((s) => !disarida.includes(s)));
    const core = new Set(json.map(kaynak).filter((s) => !disarida.includes(s)));
    expect(core).toEqual(portal);
  });
});

describe("ekranBaglamiCikar (useEkranBaglami)", () => {
  it("varlık kimliğini matchPath ile desenden çıkarır", () => {
    expect(ekranBaglamiCikar("/gereksinimler/0f3c/caseler")).toEqual({
      rota_kalibi: "/gereksinimler/:id/caseler",
      ekran: "Case inceleme",
      varlik: { tur: "requirement", id: "0f3c" },
    });
    expect(ekranBaglamiCikar("/kod/s-1").varlik).toEqual({ tur: "script", id: "s-1" });
    expect(ekranBaglamiCikar("/kosular/r-9").varlik).toEqual({ tur: "run", id: "r-9" });
    expect(ekranBaglamiCikar("/hatalar/f-2").varlik).toEqual({ tur: "failure", id: "f-2" });
    expect(ekranBaglamiCikar("/bug-taslaklari/b-1").varlik).toEqual({ tur: "bug_draft", id: "b-1" });
    expect(ekranBaglamiCikar("/kosular")).toEqual({ rota_kalibi: "/kosular", ekran: "Koşular", varlik: null });
    expect(ekranBaglamiCikar("/yok/bu")).toEqual({ rota_kalibi: null, ekran: "Bilinmeyen ekran", varlik: null });
  });
});
