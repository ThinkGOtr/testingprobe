import { describe, expect, it } from "vitest";
import { hatalariGrupla, sinirliKonum } from "./ScriptDetay";

describe("Demo-B ekran ayrıntıları", () => {
  it("assertion değeri sayı sınırında vurgulanır (0,00 TL, 150,00 TL'nin içinde değil)", () => {
    const m = "ara toplam 150,00 tl, indirim 0,00 tl, toplam 150,00 tl";
    expect(m.slice(sinirliKonum(m, "0,00 tl"), sinirliKonum(m, "0,00 tl") + 7)).toBe("0,00 tl");
    expect(sinirliKonum(m, "0,00 tl")).toBe(m.indexOf("indirim") + 8);
    expect(sinirliKonum(m, "150,00 tl")).toBe(11);
    expect(sinirliKonum("adet 6, bedava 0", "6")).toBe(5);
  });
  it("core'un topladığı tekrar sayısı korunur (3/3, 1/3 değil)", () => {
    const g = hatalariGrupla([{ test_adi: "t", hata_mesaji: "e", beklenen: '"0"', gerceklesen: '"1"', adim: null, tekrar: 3 }]);
    expect(g[0].adet).toBe(3);
  });
});
