// Rol kısıtlı rotalar üç yerde aynı olmalı (013 inceleme turu 2, BE2-6): core
// `rules/assistant/rotalar.json` (`roller`), portal `ROL_GEREKLI_ROTALAR` ve App.tsx `<RolGerekli>`.
// Biri değişip diğeri unutulursa asistan, kullanıcının açamayacağı ekrana "Git" düğmesi gösterir
// ya da açabileceği ekranı gizler. rules/ Docker derleme bağlamında yok → skipIf.
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { ROL_GEREKLI_ROTALAR, rolRotasiAcik } from "./rolRotalari";

const KOK = resolve(__dirname, "../../../..");
const ROTALAR_JSON = resolve(KOK, "rules/assistant/rotalar.json");
const APP = resolve(__dirname, "../../App.tsx");

type Kayit = { kalip: string; roller: string[] | null };

function sirali(harita: Readonly<Record<string, readonly string[]>>): Record<string, string[]> {
  return Object.fromEntries(
    Object.entries(harita)
      .map(([k, v]) => [k, [...v].sort()] as const)
      .sort(([a], [b]) => a.localeCompare(b)),
  );
}

describe("rol kısıtlı rotalar", () => {
  it.skipIf(!existsSync(ROTALAR_JSON))("rotalar.json `roller` alanı ile ROL_GEREKLI_ROTALAR aynı", () => {
    const veri = JSON.parse(readFileSync(ROTALAR_JSON, "utf8")) as { rotalar: Kayit[] };
    const json: Record<string, string[]> = {};
    for (const r of veri.rotalar) if (r.roller !== null) json[r.kalip] = r.roller;
    expect(Object.keys(json).length).toBeGreaterThan(0);
    expect(sirali(ROL_GEREKLI_ROTALAR)).toEqual(sirali(json));
  });

  it("App.tsx `<RolGerekli>` sarmalayıcıları ile ROL_GEREKLI_ROTALAR aynı", () => {
    const app = readFileSync(APP, "utf8");
    const desen = /path="([^"]+)"\s*element=\{\s*<RolGerekli roller=\{\[([^\]]*)\]\}/g;
    const portal: Record<string, string[]> = {};
    for (const m of app.matchAll(desen)) {
      portal[`/${m[1].replace(/^\/+/, "")}`] = [...m[2].matchAll(/"([^"]+)"/g)].map((r) => r[1]);
    }
    expect(Object.keys(portal).length).toBe((app.match(/<RolGerekli roller=/g) ?? []).length);
    expect(sirali(ROL_GEREKLI_ROTALAR)).toEqual(sirali(portal));
  });

  it("rol kısıtlı rota yalnız listedeki role açık", () => {
    for (const [rota, roller] of Object.entries(ROL_GEREKLI_ROTALAR)) {
      for (const rol of roller) expect(rolRotasiAcik(rota, rol), `${rota} ${rol}`).toBe(true);
      expect(rolRotasiAcik(rota, null), rota).toBe(false);
    }
  });
});
