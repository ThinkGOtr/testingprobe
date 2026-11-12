// D5: diğer şeritlerin kesin sözleşmelerine dayanıklılık (D1 tur 2 alanları, model ret nedenleri).
import { describe, expect, it } from "vitest";
import { MODEL_RET_NEDENI } from "./etiketler";
import { tur2Uyarla } from "./tasarimModeli";

describe("D1: model onay yanıtındaki tur 2 bilgisi", () => {
  it("kesin biçim: tur2_baslatildi + tur2 iş bilgisi", () => {
    expect(tur2Uyarla({ tur2_baslatildi: true, tur2: { job_id: "j1", workflow_id: "w1", uretim_no: 3, kip: "iki_tur", asama: "case" }, tur2_engeli: null })).toEqual({
      basladi: true,
      job_id: "j1",
      uretim_no: 3,
      mesaj: null,
    });
  });
  it("başlatılamadı: tur2_engeli mesaj olur", () => {
    expect(tur2Uyarla({ tur2_baslatildi: false, tur2: null, tur2_engeli: "Kabul kriteri yok" })).toEqual({ basladi: false, job_id: null, uretim_no: null, mesaj: "Kabul kriteri yok" });
  });
  it("eski taslak biçimler ve alan yokluğu", () => {
    expect(tur2Uyarla({ tur2: { basladi: true, uretim_no: 2 } })?.uretim_no).toBe(2);
    expect(tur2Uyarla({ tur2_basladi: false })?.basladi).toBe(false);
    expect(tur2Uyarla({ id: "m1" })).toBeNull();
  });
});

describe("D1: model ret nedenleri modele özgü", () => {
  it("yedi neden Türkçe etiketli; case nedenleri yok", () => {
    expect(Object.keys(MODEL_RET_NEDENI).sort()).toEqual(
      ["invented_rule", "missing_ac", "missing_condition", "out_of_scope", "wrong_boundary", "wrong_coverage_item", "wrong_technique"].sort(),
    );
    expect(MODEL_RET_NEDENI.wrong_technique).toBe("Yanlış teknik");
  });
});
