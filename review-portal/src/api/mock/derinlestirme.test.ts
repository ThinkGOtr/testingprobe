// Örnek veri: generation-options, seçenekli generate-cases (platform golden / REPLAY-MISS) ve
// derinleştirme uçları (011 §4.4, K5, K7).
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { api } from "../client";
import type { TestCaseIcerik } from "../types";
import { oturumAc } from "../../test/yardimci";
import { REPLAY_MISS_DERINLESTIRME } from "./derinlestirme";
import { KAYNAK } from "./fixtures";
import { ayar, bekleyenMockIs, mockVerisi } from "./handlers";
import { V3_GEREKSINIM_ID, V3_ICERIKLER } from "./caseV3";

const bekleIsler = async () => {
  const son = Date.now() + 5000;
  do await new Promise((r) => setTimeout(r, 10));
  while (bekleyenMockIs() > 0 && Date.now() < son);
};

const gereksinim = (id: string) => mockVerisi().gereksinimler.find((g) => g.id === id)!;

/** TPD-4'ü PO onaylı (case üretilebilir) yapar. */
function tpd4Hazir() {
  const g = gereksinim("req-tpd-4");
  g.durum = "po_approved";
  g.po = { durum: "approved", onaylayan: "po@sim.local", zaman: "2026-11-01T10:00:00Z", kanal: "jira" };
  return g;
}

const ICERIK = (baslik: string): TestCaseIcerik => ({ ...JSON.parse(JSON.stringify(V3_ICERIKLER[0])), title: baslik });

let eskiDeepening: typeof KAYNAK.case_deepening;
beforeEach(() => {
  ayar.isAdimiMs = 0;
  eskiDeepening = KAYNAK.case_deepening;
});
afterEach(() => {
  KAYNAK.case_deepening = eskiDeepening;
  for (const k of Object.keys(KAYNAK.case_generation)) if (k.startsWith("platform-test")) delete KAYNAK.case_generation[k];
});

describe("GET generation-options", () => {
  it("kayıt yokken secenekler null, varsayılan ve katalog döner", async () => {
    await oturumAc("testci");
    const y = await api.uretimSecenekleri("req-tpd-4");
    expect(y.secenekler).toBeNull();
    expect(y.varsayilan).toMatchObject({ platformlar: [], test_seviyesi: "SYSTEM" });
    expect(y.platformlar).toEqual(["Web", "Mobil-iOS", "Mobil-Android", "Desktop-Win", "Desktop-macOS", "Desktop-Linux", "API", "Data"]);
    expect(y.test_seviyeleri).toContain("UAT");
    expect(y.ek_bilgi_alanlari.tarayicilar).toMatchObject({ etiket: "Tarayıcılar", tur: "metin", platformlar: ["Web"] });
    await expect(api.uretimSecenekleri("yok")).rejects.toMatchObject({ status: 404 });
  });

  it("gönderilen seçenekler gereksinimde saklanır ve sonraki okumada `secenekler` olur", async () => {
    await oturumAc("testci");
    tpd4Hazir();
    const govde = { platformlar: ["API"], test_seviyesi: "INTEGRATION", benimsenen_standartlar: ["OWASP API Top 10"], kapsam_disi: "Ödeme", roller: "bayi", ek_bilgi: { auth_tipi: "OAuth2" } };
    await api.caseUret("req-tpd-4", "tek_tur", govde);
    await bekleIsler();
    expect((await api.uretimSecenekleri("req-tpd-4")).secenekler).toEqual(govde);
  });
});

describe("POST generate-cases (seçenekli)", () => {
  it("gövdesiz çağrı eski davranış: golden TPD-4, hiçbir seçenek saklanmaz", async () => {
    await oturumAc("testci");
    tpd4Hazir();
    await api.caseUret("req-tpd-4");
    await bekleIsler();
    expect(gereksinim("req-tpd-4").durum).toBe("cases_ready");
    expect(mockVerisi().uretimSecenekleri?.["req-tpd-4"]).toBeUndefined();
  });

  it("sınır aşımı 422; durum değişmez", async () => {
    await oturumAc("testci");
    tpd4Hazir();
    await expect(api.caseUret("req-tpd-4", "tek_tur", { benimsenen_standartlar: Array.from({ length: 11 }, (_, i) => `S${i}`) })).rejects.toMatchObject({ status: 422 });
    await expect(api.caseUret("req-tpd-4", "tek_tur", { platformlar: ["Tablet"] })).rejects.toMatchObject({ status: 422 });
    await expect(api.caseUret("req-tpd-4", "tek_tur", { kapsam_disi: "x".repeat(2001) })).rejects.toMatchObject({ status: 422 });
    expect(gereksinim("req-tpd-4").durum).toBe("po_approved");
  });

  it("platform seçili ama golden yok: REPLAY-MISS, gereksinim failed (yeniden denenebilir), case eklenmez", async () => {
    await oturumAc("testci");
    tpd4Hazir();
    const once = mockVerisi().caseler.length;
    await api.caseUret("req-tpd-4", "tek_tur", { platformlar: ["Desktop-Win", "Mobil-iOS"] });
    await bekleIsler();
    const g = gereksinim("req-tpd-4");
    expect(g.durum).toBe("failed");
    expect(g.son_hata).toMatchObject({ job_tur: "cases.generate" });
    expect(g.son_hata!.neden).toContain("REPLAY-MISS");
    expect(g.son_hata!.neden).toContain("platform-desktop-mobile/TPD-4");
    expect(mockVerisi().caseler.length).toBe(once);
  });

  it("platform golden'ı varsa (`platform-<ek>/<kök>`) onun case'leri REPLAY taslak olur", async () => {
    await oturumAc("testci");
    const g = tpd4Hazir();
    // Golden henüz depoda yoksa testte örnek kayıt eklenir (golden gelince `platform-web/TPD-4` aynı yoldan seçilir).
    const ad = "platform-web/TPD-4";
    const vardi = ad in KAYNAK.case_generation;
    if (!vardi) KAYNAK.case_generation[ad] = { girdi_ac: g.kabul_kriterleri.map((a) => `${a.ref}: ${a.metin}`), cases: [ICERIK("Web: tarayıcı matrisi")] };
    try {
      await api.caseUret("req-tpd-4", "tek_tur", { platformlar: ["Web"] });
      await bekleIsler();
      expect(gereksinim("req-tpd-4").durum).toBe("cases_ready");
      const caseler = mockVerisi().caseler.filter((c) => c.requirement_id === "req-tpd-4");
      expect(caseler.map((c) => c.icerik.title)).toEqual(KAYNAK.case_generation[ad].cases.map((c) => c.title));
      expect(caseler.every((c) => c.mode === "replay")).toBe(true);
    } finally {
      if (!vardi) delete KAYNAK.case_generation[ad];
    }
  });
});

describe("derinleştirme", () => {
  it("rol, durum ve gövde kuralları (403 / 409 / 422)", async () => {
    await oturumAc("muhendis");
    await expect(api.derinlestir(V3_GEREKSINIM_ID, { tur: "negatif" })).rejects.toMatchObject({ status: 403 });
    await api.logout();
    await oturumAc("testci");
    await expect(api.derinlestir("req-tpd-4", { tur: "negatif" })).rejects.toMatchObject({ status: 409 });
    await expect(api.derinlestir(V3_GEREKSINIM_ID, { tur: "teknik" })).rejects.toMatchObject({ status: 422 });
    await expect(api.derinlestir(V3_GEREKSINIM_ID, { tur: "teknik", teknik: "XX" as never })).rejects.toMatchObject({ status: 422 });
    await expect(api.derinlestir(V3_GEREKSINIM_ID, { tur: "negatif", teknik: "EP" })).rejects.toMatchObject({ status: 422 });
    await expect(api.derinlestir(V3_GEREKSINIM_ID, { tur: "baska" as never })).rejects.toMatchObject({ status: 422 });
  });

  it("durum 'yok' → başlat (202) → çalışırken ikinci istek 409 → golden yoksa REPLAY-MISS hata, gereksinim cases_ready'de kalır", async () => {
    await oturumAc("testci");
    KAYNAK.case_deepening = {};
    expect(await api.derinlestirmeDurumu(V3_GEREKSINIM_ID)).toMatchObject({ durum: "yok", tur: null });
    ayar.isAdimiMs = 50;
    const once = mockVerisi().caseler.length;
    const y = await api.derinlestir(V3_GEREKSINIM_ID, { tur: "teknik", teknik: "BVA" });
    expect(y).toMatchObject({ durum: "started", uretim_no: 2, mesaj: "Derinleştirme başlatıldı." });
    expect(y.job_id).toBeTruthy();
    expect(y.workflow_id).toBeTruthy();
    expect(await api.derinlestirmeDurumu(V3_GEREKSINIM_ID)).toMatchObject({ durum: "calisiyor", tur: "teknik", teknik: "BVA" });
    await expect(api.derinlestir(V3_GEREKSINIM_ID, { tur: "negatif" })).rejects.toMatchObject({ status: 409 });
    expect(gereksinim(V3_GEREKSINIM_ID).durum).toBe("cases_ready");
    await bekleIsler();
    const d = await api.derinlestirmeDurumu(V3_GEREKSINIM_ID);
    expect(d).toMatchObject({ durum: "hata", yeni_case_sayisi: 0, hata: REPLAY_MISS_DERINLESTIRME, uyarilar: [REPLAY_MISS_DERINLESTIRME] });
    expect(gereksinim(V3_GEREKSINIM_ID).durum).toBe("cases_ready");
    expect(mockVerisi().caseler.length).toBe(once);
  });

  it("golden varsa (`negatif/<kök>`) case'ler yeni üretim numarasıyla taslak eklenir; mevcutlar korunur; özet tur=negatif", async () => {
    await oturumAc("testci");
    // TPD-1'i case'leri hazır duruma getir (golden kökü Jira anahtarı).
    const g = gereksinim("req-tpd-1");
    g.durum = "cases_ready";
    KAYNAK.case_deepening = {
      "negatif/TPD-1": {
        girdi_ac: [],
        cases: [ICERIK("Geçersiz adet reddedilir"), ICERIK("Stok dışı ürün sepete eklenmez")],
        ozet: { observations: [{ standard_ref: "", note: "Hata mesajı dili" }] },
      },
    };
    const onceki = mockVerisi().caseler.filter((c) => c.requirement_id === "req-tpd-1").map((c) => ({ id: c.id, durum: c.durum }));
    const y = await api.derinlestir("req-tpd-1", { tur: "negatif" });
    await bekleIsler();
    const d = await api.derinlestirmeDurumu("req-tpd-1");
    expect(d).toMatchObject({ durum: "tamam", tur: "negatif", yeni_case_sayisi: 2, uretim_no: y.uretim_no, hata: null });
    const simdi = mockVerisi().caseler.filter((c) => c.requirement_id === "req-tpd-1");
    // Mevcut case'ler ve kararları korunur.
    for (const o of onceki) expect(simdi.find((c) => c.id === o.id)?.durum).toBe(o.durum);
    const yeni = simdi.filter((c) => !onceki.some((o) => o.id === c.id));
    expect(yeni.map((c) => [c.icerik.title, c.durum, c.uretim_no, c.mode])).toEqual([
      ["Geçersiz adet reddedilir", "draft", y.uretim_no, "replay"],
      ["Stok dışı ürün sepete eklenmez", "draft", y.uretim_no, "replay"],
    ]);
    expect(gereksinim("req-tpd-1").durum).toBe("cases_ready");
    const ozet = await api.caseSummary("req-tpd-1");
    expect(ozet!.uretimler.find((u) => u.uretim_no === y.uretim_no)).toMatchObject({ tur: "negatif", observations: [{ standard_ref: "", note: "Hata mesajı dili" }] });
  });

  it("teknik anahtarı küçük harf: `teknik-bva/<kök>`; kaynaklar.json'da case_deepening anahtarı hiç yoksa da çalışır", async () => {
    await oturumAc("testci");
    const g = gereksinim("req-tpd-1");
    g.durum = "cases_ready";
    KAYNAK.case_deepening = undefined;
    await api.derinlestir("req-tpd-1", { tur: "teknik", teknik: "BVA" });
    await bekleIsler();
    expect((await api.derinlestirmeDurumu("req-tpd-1")).durum).toBe("hata");
    KAYNAK.case_deepening = { "teknik-bva/TPD-1": { girdi_ac: [], cases: [ICERIK("Adet üst sınırı 99")] } };
    await api.derinlestir("req-tpd-1", { tur: "teknik", teknik: "BVA" });
    await bekleIsler();
    expect(await api.derinlestirmeDurumu("req-tpd-1")).toMatchObject({ durum: "tamam", teknik: "BVA", yeni_case_sayisi: 1 });
  });
});
