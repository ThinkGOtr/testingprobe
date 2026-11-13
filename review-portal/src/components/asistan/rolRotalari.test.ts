// Rol kısıtlı rotalar iki yerde aynı olmalı (013 inceleme turu 2, BE2-6; 012): core
// `rules/assistant/rotalar.json` (`roller`) ve portal `ROTA_IZINLERI` (sayfa koruması). Biri
// değişip diğeri unutulursa asistan, kullanıcının açamayacağı ekrana "Git" düğmesi gösterir ya da
// açabileceği ekranı gizler. rules/ Docker derleme bağlamında yok → skipIf.
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { IZINLER, ROLLER, ROTA_IZINLERI } from "../../lib/yetki";
import { rolRotasiAcik } from "./rolRotalari";

const KOK = resolve(__dirname, "../../../..");
const ROTALAR_JSON = resolve(KOK, "rules/assistant/rotalar.json");

type Kayit = { kalip: string; roller: string[] | null };

/** Rotayı açabilen roller (rotanın izinlerinden herhangi biri). */
function rotaRolleri(kalip: string): string[] {
  const izinler = ROTA_IZINLERI[kalip] ?? [];
  return [...new Set(izinler.flatMap((i) => [...IZINLER[i]]))].sort();
}

describe("rol kısıtlı rotalar", () => {
  it.skipIf(!existsSync(ROTALAR_JSON))("rotalar.json `roller` alanı ROTA_IZINLERI'nin rolleriyle aynı", () => {
    const veri = JSON.parse(readFileSync(ROTALAR_JSON, "utf8")) as { rotalar: Kayit[] };
    const kisitli = veri.rotalar.filter((r) => r.roller !== null);
    expect(kisitli.length).toBeGreaterThan(0);
    for (const r of kisitli) expect([...(r.roller ?? [])].sort(), r.kalip).toEqual(rotaRolleri(r.kalip));
  });

  it("rol kısıtlı rota yalnız izni olan role açık; korumasız rota herkese", () => {
    for (const kalip of Object.keys(ROTA_IZINLERI)) {
      const rota = kalip.replace(/:[^/]+/g, "x1");
      const acan = rotaRolleri(kalip);
      for (const rol of ROLLER) expect(rolRotasiAcik(rota, rol), `${rota} ${rol}`).toBe(acan.includes(rol));
      expect(rolRotasiAcik(rota, null), rota).toBe(false);
    }
    expect(rolRotasiAcik("/kontrol-kulesi?x=1", "viewer")).toBe(true);
    expect(rolRotasiAcik("/demo", "presenter" as never)).toBe(true); // eski ad → admin
    expect(rolRotasiAcik("/olmayan-ekran", "admin")).toBe(false);
  });
});
