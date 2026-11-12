// Case kalite metin kuralları: ham sınıf adı ayıklama, "Yayınlanamaz: " öneki, yönlendirme (011 D5, K22, UX-7).
import { describe, expect, it } from "vitest";
import { denetimYonlendirmesi, hataMetniniAyikla, yayinlanamaz, yayinlanamazOnekiz } from "./kalite";

describe("hataMetniniAyikla", () => {
  it.each([
    ["ReplayNoOutput: bu set için kayıtlı denetim çıktısı yok (REPLAY-MISS)", "Bu set için kayıtlı denetim çıktısı yok (REPLAY-MISS)"],
    ["REPLAY-MISS: bu set için kayıtlı review çıktısı yok (ReplayNoOutput)", "REPLAY-MISS: bu set için kayıtlı review çıktısı yok"],
    ["TimeoutError: Agent Probe 30 sn içinde yanıt vermedi", "Agent Probe 30 sn içinde yanıt vermedi"],
    ["httpx.ReadTimeout: zaman aşımı", "Zaman aşımı"],
    ["RuntimeError: ReplayMiss: kayıt yok", "Kayıt yok"],
    ["Denetim başarısız [ValueError]", "Denetim başarısız"],
    ["denetim yapılamadı: ReplayMiss", "Denetim yapılamadı"],
    ["Yayınlanamaz: Agent Probe denetimi yapılamadı (ReplayNoOutput: kayıt yok); yeniden gönderin", "Yayınlanamaz: Agent Probe denetimi yapılamadı (kayıt yok); yeniden gönderin"],
  ])("%s", (ham, beklenen) => {
    expect(hataMetniniAyikla(ham)).toBe(beklenen);
  });

  it("Türkçe tek sözcük önekine dokunmaz; boşsa yedek metin", () => {
    expect(hataMetniniAyikla("Denetim: kapı kapalı")).toBe("Denetim: kapı kapalı");
    expect(hataMetniniAyikla("ReplayNoOutput")).toBe("Ayrıntı bildirilmedi.");
    expect(hataMetniniAyikla(null, "yok")).toBe("yok");
  });
});

describe("yayinlanamaz", () => {
  it("önek bir kez", () => {
    expect(yayinlanamaz("karar yok")).toBe("Yayınlanamaz: karar yok");
    expect(yayinlanamaz("Yayınlanamaz: karar yok")).toBe("Yayınlanamaz: karar yok");
    expect(yayinlanamazOnekiz("Yayınlanamaz: karar yok")).toBe("karar yok");
    expect(yayinlanamazOnekiz("karar yok")).toBe("karar yok");
  });
});

describe("denetimYonlendirmesi", () => {
  const d = (karar: "KABUL" | "DÜZELTME_GEREKLİ" | "ENGELLE", guncel = true) => ({ durum: "tamamlandi" as const, karar, guncel });
  it("karar başına sonraki adım", () => {
    expect(denetimYonlendirmesi(d("KABUL"))?.tur).toBe("yayin");
    expect(denetimYonlendirmesi(d("DÜZELTME_GEREKLİ"))?.metin).toMatch(/^Bulgulardaki case'leri düzeltin/);
    expect(denetimYonlendirmesi(d("ENGELLE"))?.metin).toMatch(/^Set yayınlanamaz/);
    expect(denetimYonlendirmesi(d("KABUL", false))?.tur).toBe("bayat");
    expect(denetimYonlendirmesi({ durum: "hata", karar: null, guncel: true })).toBeNull();
    expect(denetimYonlendirmesi(null)).toBeNull();
  });
});
