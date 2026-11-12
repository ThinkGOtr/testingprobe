// Kontrol Kulesi "Case kalitesi" (011 K21): mock verisiyle görünür değerler, P9 kod/model kararı ayrık,
// null değer "ölçülmedi", hedef notu (ekip hedefi, standart değil), sürüm tablosu, küçük örneklem notu,
// eski core'da (404) bölümün gizlenmesi.
import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import { mockCaseKalitesi } from "../api/mock/caseKalitesi";
import { caseKalitesiUyarla } from "../api/uyumCaseKalitesi";
import { KontrolKulesi } from "../pages/KontrolKulesi";
import { oturumAc, sar } from "../test/yardimci";
import { CaseKalitesiBolumu } from "./CaseKalitesi";

afterEach(() => {
  vi.restoreAllMocks();
});

/** Brief'teki core örnek yanıtı (küçük örneklem, hedef yok, hazır kapsam null). */
const CORE_ORNEGI = {
  requirement_id: null,
  kapsam: { gereksinim: 0.6667, oge: 1.0, negatif_karar: 1.0, hazir_gereksinim: null, hazir_oge: null, n_gereksinim: 2, kapsam_yontemi: "toplam" },
  review: {
    n: 2,
    ortalama: 66.7,
    ortalama_skor: 8.0,
    olcek: "yüzde = skor / 12 × 100",
    bayat: 2,
    dagilim: [
      { aralik: "0–49", n: 1 },
      { aralik: "50–69", n: 0 },
      { aralik: "70–84", n: 0 },
      { aralik: "85–100", n: 1 },
    ],
  },
  denetim: { n: 2, kod: { KABUL: 1, DUZELTME_GEREKLI: 1, ENGELLE: 0 }, model: { KABUL: 2, DUZELTME_GEREKLI: 0, ENGELLE: 0 }, hata: 1, bekliyor: 1 },
  tekrar: { oneri: 1, case: 4, etkilenen_case: 2, oran: 0.25 },
  readiness: { ready: 2, assumption_dependent: 1, blocked: 1, legacy: 1 },
  teknik: { BVA: 1, DT: 1, EP: 2, UC: 1 },
  icerik_kontrolu: { n: 4, gec: 2, uyar: 1, engelle: 1, engel_orani: 0.25, uyari_orani: 0.25, yon: { cevap: 2, soru: 2 } },
  surumler: [{ surum: "case-generation@v3", uretim: 1, case: 5, review_ortalama: 91.7, review_n: 1, kabul: 0, duzeltme: 1, engel: 0, tekrar_orani: 0.3333 }],
  hedefler: [],
  kaynaklar: { kapsam: "k", review: "r" },
  uyarilar: ["Hazır kapsam ölçülmüyor: kapsam matrisinde hazır case bilgisi (covered_by_ready) yok."],
};

describe("Case kalitesi bölümü", () => {
  it("Kontrol Kulesi'nde mock verisiyle: KPI, P8 dağılımı, P9 kod/model ayrık, hazır olma etiketleri, teknik, içerik kontrolü", async () => {
    await oturumAc("sunucu");
    sar(<KontrolKulesi />);
    const bolum = await screen.findByRole("region", { name: "Case kalitesi" });
    const kpi = within(bolum).getByTestId("case-kalitesi-kpi");
    expect(kpi).toHaveTextContent("Gereksinim kapsamı");
    expect(kpi).toHaveTextContent("%92");
    expect(within(kpi).getByTestId("hazir-kapsam")).toHaveTextContent("%67");
    expect(within(kpi).getByTestId("tekrar-orani")).toHaveTextContent("%7,9");
    expect(within(kpi).getByTestId("yetim-soru")).toHaveTextContent("2/9");

    const review = within(bolum).getByRole("region", { name: /Case seti review \(P8\)/ });
    expect(within(review).getByTestId("review-ortalama")).toHaveTextContent("%79,2");
    const dagilim = within(review).getByRole("list", { name: "Review skor dağılımı (yüzde aralıkları)" });
    expect(within(dagilim).getAllByRole("listitem")).toHaveLength(4);
    expect(within(dagilim).getByText("70–84").closest("li")).toHaveTextContent("3 (%50)");

    const denetim = within(bolum).getByRole("region", { name: /Agent Probe denetimi \(P9\)/ });
    expect(within(denetim).getByTestId("denetim-kod").textContent).toContain("Engelle1");
    expect(within(denetim).getByTestId("denetim-model").textContent).toContain("Engelle0");
    expect(denetim).toHaveTextContent("1 bekliyor · 1 hata");

    const hazirlik = within(bolum).getByRole("region", { name: /Hazır olma/ });
    for (const e of ["Hazır", "Varsayıma bağlı", "Soru bekliyor", "Eski biçim"]) expect(within(hazirlik).getByText(e)).toBeInTheDocument();
    expect(hazirlik).not.toHaveTextContent("Engelli");

    const teknik = within(bolum).getByRole("region", { name: /Teknik dağılımı/ });
    expect(teknik).toHaveTextContent("Kontrol listesi");
    expect(teknik).toHaveTextContent("Sınır değer analizi");

    const icerik = within(bolum).getByRole("region", { name: /İçerik kontrolü/ });
    expect(within(icerik).getByTestId("icerik-engel-orani")).toHaveTextContent("%5");
    expect(within(icerik).getByTestId("icerik-uyari-orani")).toHaveTextContent("%10");
  });

  it("sürüm tablosu: caption'lı erişilebilir tablo, iki prompt sürümü satırı", async () => {
    await oturumAc("sunucu");
    sar(<CaseKalitesiBolumu />);
    const tablo = await screen.findByRole("table", { name: "Prompt sürümüne göre case kalitesi" });
    const satirlar = within(tablo).getAllByRole("row").slice(1);
    expect(satirlar).toHaveLength(2);
    expect(within(satirlar[0]).getByRole("rowheader")).toHaveTextContent("case-generation@v2");
    expect(satirlar[1]).toHaveTextContent("%83,3");
    expect(satirlar[1]).toHaveTextContent("(n=4)");
  });

  it("hedefler 'ekip hedefi, standart değil' notuyla listelenir; kapı gibi davranılmaz", async () => {
    await oturumAc("sunucu");
    sar(<CaseKalitesiBolumu />);
    const hedefler = await screen.findByTestId("case-kalitesi-hedefler");
    expect(hedefler).toHaveTextContent("Ekip hedefi, standart değil");
    // B12: not yalnız başlıkta (maddelerde tekrarlanmaz); her maddede renksiz güncel değer.
    const maddeler = within(hedefler).getAllByTestId("hedef-maddesi");
    expect(maddeler[0]).toHaveTextContent(/^Case seti review ortalaması: hedef ≥ %80 · şu an (%[\d,]+|ölçülmedi)$/);
    for (const m of maddeler) expect(m).not.toHaveTextContent("standart değil");
    // Eşik/kapı dili ve tutturdu/tutmadı işareti yok.
    expect(hedefler).not.toHaveTextContent(/hedef tuttu|hedefin altında|✓|✗/);
  });

  it("core örnek yanıtı: hazır kapsam null → 'ölçülmedi', hedef satırı yok, küçük örneklem notu, uyarılar", async () => {
    vi.spyOn(api, "caseKalitesi").mockResolvedValue(caseKalitesiUyarla(CORE_ORNEGI));
    sar(<CaseKalitesiBolumu />);
    const bolum = await screen.findByTestId("case-kalitesi");
    expect(within(bolum).getByTestId("hazir-kapsam")).toHaveTextContent("ölçülmedi");
    expect(within(bolum).queryByTestId("case-kalitesi-hedefler")).toBeNull();
    expect(within(bolum).getAllByTestId("kucuk-orneklem").length).toBeGreaterThanOrEqual(2);
    expect(within(bolum).getByTestId("case-kalitesi-uyarilar")).toHaveTextContent("Hazır kapsam ölçülmüyor");
    expect(bolum).toHaveTextContent("2 review case seti değiştikten sonra kaldı");
  });

  it("kapsam alanları null: her biri 'ölçülmedi' (uydurma %0 yok)", async () => {
    vi.spyOn(api, "caseKalitesi").mockResolvedValue(caseKalitesiUyarla({ ...CORE_ORNEGI, kapsam: { n_gereksinim: 0 }, tekrar: {}, review: { n: 0 } }));
    sar(<CaseKalitesiBolumu />);
    const kpi = await screen.findByTestId("case-kalitesi-kpi");
    expect(within(kpi).getAllByText("ölçülmedi")).toHaveLength(5);
    expect(kpi).not.toHaveTextContent("%0");
    expect(screen.getByTestId("review-ortalama")).toHaveTextContent("ölçülmedi");
  });

  it("eski core (404): bölüm sessizce gizlenir, hata kutusu yok", async () => {
    const cagri = vi.spyOn(api, "caseKalitesi").mockRejectedValue(new ApiError(404, "Not Found"));
    sar(<CaseKalitesiBolumu />);
    await waitFor(() => expect(cagri).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByRole("heading", { name: "Case kalitesi" })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("başka hata (500): bölüm başlığıyla mevcut HataKutusu deseni", async () => {
    vi.spyOn(api, "caseKalitesi").mockRejectedValue(new ApiError(500, "Sunucu hatası"));
    sar(<CaseKalitesiBolumu />);
    const bolum = await screen.findByRole("region", { name: "Case kalitesi" });
    expect(await within(bolum).findByRole("button", { name: "Tekrar dene" })).toBeInTheDocument();
  });

  it("mock: requirement_id ile tek gereksinim kırılımı", async () => {
    await oturumAc("sunucu");
    const k = await api.caseKalitesi("req-tpd-1");
    expect(k.requirement_id).toBe("req-tpd-1");
    expect(k.kapsam.n_gereksinim).toBe(1);
    expect(caseKalitesiUyarla(mockCaseKalitesi(null)).surumler).toHaveLength(2);
  });

  it("uyarlayıcı: ham 'DÜZELTME_GEREKLİ' anahtarını ve eksik alanları tolere eder", () => {
    const k = caseKalitesiUyarla({ denetim: { n: 1, kod: { "DÜZELTME_GEREKLİ": 1 } } });
    expect(k.denetim.kod.DUZELTME_GEREKLI).toBe(1);
    expect(k.kapsam.gereksinim).toBeNull();
    expect(k.surumler).toEqual([]);
    expect(k.hedefler).toEqual([]);
  });
});
