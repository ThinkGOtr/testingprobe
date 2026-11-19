// Sözleşme: core'un denetim zincirine yazdığı HER olay kodunun (audit_event.eylem) Denetim ekranında
// okunur etiketi var. Kod listesi core kaynağından toplanır (`npm run sozlesme:denetim`;
// güncelliğini core `tests/unit/test_cross_lane_contracts.py` denetler).
import { describe, expect, it } from "vitest";
import kodlar from "../api/sozlesme/denetim-olaylari.json";
import { OLAY_ETIKETI_KODLARI, olayEtiketi } from "./kullaniciMetni";

describe("denetim olay kodu etiketleri", () => {
  it("core'un yazdığı tüm olay kodları etiket haritasında", () => {
    const harita = new Set(OLAY_ETIKETI_KODLARI);
    const eksik = (kodlar as string[]).filter((k) => !harita.has(k));
    expect(eksik).toEqual([]);
    expect((kodlar as string[]).length).toBeGreaterThan(150);
  });

  it("etiketler iç kod içermez", () => {
    for (const k of kodlar as string[]) {
      const e = olayEtiketi(k);
      expect(e, k).not.toMatch(/[a-z]+_[a-z]+|\w+\.\w+/);
    }
  });
});
