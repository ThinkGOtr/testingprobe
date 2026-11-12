// K21 "Case kalitesi" örnek yanıtı (GET /control-tower/case-quality). Core sözleşmesiyle aynı biçim;
// iki prompt sürümü ve birkaç ekip hedefi (kırılım ve hedef notu görünsün diye). Sayılar örnektir.
const KAYNAKLAR = {
  kapsam: "cases.service._coverage_state → oranlar {gereksinim_kapsami, oge_kapsami, negatif_karar_kapsami}; proje geneli = kapsanan/toplam toplamı",
  hazir_kapsam: "oranlar içinde adı 'hazir' geçen anahtar; yoksa kapsam matrisinin covered_by_ready alanı",
  review: "case_set_review (gereksinim başına en güncel tamamlanmış kayıt); skor 0–12, yüzde = skor/12×100",
  denetim: "case_set_audit (gereksinim başına en güncel tamamlanmış kayıt): kod = karar (deterministik sertleştirme sonrası), model = model_karari",
  tekrar: "review'ların remove_or_merge öneri sayısı / değerlendirilen case sayısı",
  readiness: "güncel case'lerin icerik.readiness alanı; eski (v2) case readiness taşımaz",
  teknik: "güncel case'lerin teknik listesi (bir case birden çok tekniğe sayılır)",
  icerik_kontrolu: "asistan_denetim kararları (gec/uyar/engelle), soru ve cevap ayrı satır; proje geneli",
  surumler: "case_uretim → ai_call.surum (paket@sürüm); REPLAY dahil",
  hedefler: "Prompt Seti v2 başlangıç hedefleri: ekip hedefi, standart değil; eşik ya da kapı uygulanmaz",
};

export function mockCaseKalitesi(requirementId: string | null): unknown {
  const tek = requirementId !== null;
  return {
    requirement_id: requirementId,
    kapsam: tek
      ? { gereksinim: 1.0, oge: 0.8571, negatif_karar: 1.0, hazir_gereksinim: 0.75, hazir_oge: 0.7143, n_gereksinim: 1, kapsam_yontemi: "toplam" }
      : { gereksinim: 0.9167, oge: 0.8421, negatif_karar: 0.8, hazir_gereksinim: 0.6667, hazir_oge: 0.6316, n_gereksinim: 4, kapsam_yontemi: "toplam" },
    review: tek
      ? {
          n: 1,
          ortalama: 91.7,
          ortalama_skor: 11,
          olcek: "yüzde = skor / 12 × 100",
          bayat: 0,
          dagilim: [
            { aralik: "0–49", n: 0 },
            { aralik: "50–69", n: 0 },
            { aralik: "70–84", n: 0 },
            { aralik: "85–100", n: 1 },
          ],
        }
      : {
          n: 6,
          ortalama: 79.2,
          ortalama_skor: 9.5,
          olcek: "yüzde = skor / 12 × 100",
          bayat: 1,
          dagilim: [
            { aralik: "0–49", n: 0 },
            { aralik: "50–69", n: 1 },
            { aralik: "70–84", n: 3 },
            { aralik: "85–100", n: 2 },
          ],
        },
    denetim: tek
      ? { n: 1, kod: { KABUL: 1, DUZELTME_GEREKLI: 0, ENGELLE: 0 }, model: { KABUL: 1, DUZELTME_GEREKLI: 0, ENGELLE: 0 }, hata: 0, bekliyor: 0 }
      : { n: 6, kod: { KABUL: 3, DUZELTME_GEREKLI: 2, ENGELLE: 1 }, model: { KABUL: 4, DUZELTME_GEREKLI: 2, ENGELLE: 0 }, hata: 1, bekliyor: 1 },
    tekrar: tek ? { oneri: 0, case: 7, etkilenen_case: 0, oran: 0 } : { oneri: 3, case: 38, etkilenen_case: 5, oran: 0.0789 },
    readiness: tek ? { ready: 5, assumption_dependent: 1, blocked: 1, legacy: 0 } : { ready: 24, assumption_dependent: 6, blocked: 3, legacy: 5 },
    teknik: tek ? { BVA: 2, EP: 3, UC: 2 } : { BVA: 9, CL: 4, DT: 5, EP: 14, ST: 3, UC: 7 },
    icerik_kontrolu: { n: 40, gec: 34, uyar: 4, engelle: 2, engel_orani: 0.05, uyari_orani: 0.1, yon: { cevap: 20, soru: 20 } },
    surumler: tek
      ? [{ surum: "case-generation@v3", uretim: 1, case: 7, review_ortalama: 91.7, review_n: 1, kabul: 1, duzeltme: 0, engel: 0, tekrar_orani: 0 }]
      : [
          { surum: "case-generation@v2", uretim: 3, case: 21, review_ortalama: 70.8, review_n: 2, kabul: 0, duzeltme: 1, engel: 1, tekrar_orani: 0.1429 },
          { surum: "case-generation@v3", uretim: 4, case: 22, review_ortalama: 83.3, review_n: 4, kabul: 3, duzeltme: 1, engel: 0, tekrar_orani: 0.0455 },
        ],
    hedefler: [
      { ad: "Case seti review ortalaması", metrik: "review.ortalama", hedef: "≥ %80", not: "ekip hedefi, standart değil" },
      { ad: "Tekrar oranı", metrik: "tekrar.oran", hedef: "≤ %5", not: "ekip hedefi, standart değil" },
      { ad: "Gereksinim kapsamı", metrik: "kapsam.gereksinim", hedef: "%100", not: "ekip hedefi, standart değil" },
    ],
    kaynaklar: KAYNAKLAR,
    uyarilar: [
      ...(tek ? ["İçerik kontrolü (asistan denetimi) gereksinime bağlı değildir; proje geneli gösterilir."] : []),
      ...(tek ? [] : ["5 eski (v2) case readiness taşımıyor (K9); review/denetim setine girmez."]),
    ],
  };
}
