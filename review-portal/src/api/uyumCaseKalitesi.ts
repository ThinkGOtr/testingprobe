// K21 "Case kalitesi" yanıt uyarlayıcısı: eksik ya da bozuk alan uydurulmaz; sayı yoksa 0 (sayım)
// ya da null (oran/ortalama: "ölçülmedi").
import type { CaseKalitesi, CaseKalitesiKarar } from "./types";

type Nesne = Record<string, unknown>;

const nesne = (x: unknown): Nesne => (x && typeof x === "object" && !Array.isArray(x) ? (x as Nesne) : {});
const sayi = (x: unknown): number => (typeof x === "number" && Number.isFinite(x) ? x : 0);
const sayiYaDaNull = (x: unknown): number | null => (typeof x === "number" && Number.isFinite(x) ? x : null);
const metin = (x: unknown, varsayilan = ""): string => (typeof x === "string" ? x : varsayilan);
const dizi = (x: unknown): unknown[] => (Array.isArray(x) ? x : []);

const KARARLAR: CaseKalitesiKarar[] = ["KABUL", "DUZELTME_GEREKLI", "ENGELLE"];

function kararSayilari(x: unknown): Record<CaseKalitesiKarar, number> {
  const o = nesne(x);
  // Eski/ham biçim "DÜZELTME_GEREKLİ" de kabul edilir.
  return {
    KABUL: sayi(o.KABUL),
    DUZELTME_GEREKLI: sayi(o.DUZELTME_GEREKLI ?? o["DÜZELTME_GEREKLİ"]),
    ENGELLE: sayi(o.ENGELLE),
  };
}

function sayiSozlugu(x: unknown): Record<string, number> {
  const s: Record<string, number> = {};
  for (const [k, v] of Object.entries(nesne(x))) if (typeof v === "number" && Number.isFinite(v)) s[k] = v;
  return s;
}

function metinSozlugu(x: unknown): Record<string, string> {
  const s: Record<string, string> = {};
  for (const [k, v] of Object.entries(nesne(x))) if (typeof v === "string") s[k] = v;
  return s;
}

export function caseKalitesiUyarla(ham: unknown): CaseKalitesi {
  const h = nesne(ham);
  const kapsam = nesne(h.kapsam);
  const review = nesne(h.review);
  const denetim = nesne(h.denetim);
  const tekrar = nesne(h.tekrar);
  const readiness = nesne(h.readiness);
  const icerik = nesne(h.icerik_kontrolu);
  return {
    requirement_id: typeof h.requirement_id === "string" ? h.requirement_id : null,
    kapsam: {
      gereksinim: sayiYaDaNull(kapsam.gereksinim),
      oge: sayiYaDaNull(kapsam.oge),
      negatif_karar: sayiYaDaNull(kapsam.negatif_karar),
      hazir_gereksinim: sayiYaDaNull(kapsam.hazir_gereksinim),
      hazir_oge: sayiYaDaNull(kapsam.hazir_oge),
      n_gereksinim: sayi(kapsam.n_gereksinim),
      kapsam_yontemi: metin(kapsam.kapsam_yontemi, "toplam"),
    },
    review: {
      n: sayi(review.n),
      ortalama: sayiYaDaNull(review.ortalama),
      ortalama_skor: sayiYaDaNull(review.ortalama_skor),
      olcek: metin(review.olcek, "yüzde = skor / 12 × 100"),
      bayat: sayi(review.bayat),
      dagilim: dizi(review.dagilim).map((d) => ({ aralik: metin(nesne(d).aralik, "?"), n: sayi(nesne(d).n) })),
    },
    denetim: {
      n: sayi(denetim.n),
      kod: kararSayilari(denetim.kod),
      model: kararSayilari(denetim.model),
      hata: sayi(denetim.hata),
      bekliyor: sayi(denetim.bekliyor),
    },
    tekrar: {
      oneri: sayi(tekrar.oneri),
      case: sayi(tekrar.case),
      etkilenen_case: sayi(tekrar.etkilenen_case),
      oran: sayiYaDaNull(tekrar.oran),
    },
    readiness: {
      ready: sayi(readiness.ready),
      assumption_dependent: sayi(readiness.assumption_dependent),
      blocked: sayi(readiness.blocked),
      legacy: sayi(readiness.legacy),
    },
    teknik: sayiSozlugu(h.teknik),
    icerik_kontrolu: {
      n: sayi(icerik.n),
      gec: sayi(icerik.gec),
      uyar: sayi(icerik.uyar),
      engelle: sayi(icerik.engelle),
      engel_orani: sayiYaDaNull(icerik.engel_orani),
      uyari_orani: sayiYaDaNull(icerik.uyari_orani),
      yon: sayiSozlugu(icerik.yon),
    },
    surumler: dizi(h.surumler).map((x) => {
      const s = nesne(x);
      return {
        surum: metin(s.surum, "bilinmiyor"),
        uretim: sayi(s.uretim),
        case: sayi(s.case),
        review_ortalama: sayiYaDaNull(s.review_ortalama),
        review_n: sayi(s.review_n),
        kabul: sayi(s.kabul),
        duzeltme: sayi(s.duzeltme),
        engel: sayi(s.engel),
        tekrar_orani: sayiYaDaNull(s.tekrar_orani),
      };
    }),
    hedefler: dizi(h.hedefler).flatMap((x) => {
      const t = nesne(x);
      const hedef = typeof t.hedef === "number" || typeof t.hedef === "string" ? t.hedef : null;
      if (hedef === null) return [];
      return [{ ad: metin(t.ad, metin(t.metrik, "Hedef")), metrik: typeof t.metrik === "string" ? t.metrik : undefined, hedef, not: typeof t.not === "string" ? t.not : undefined }];
    }),
    kaynaklar: metinSozlugu(h.kaynaklar),
    uyarilar: dizi(h.uyarilar).filter((u): u is string => typeof u === "string"),
  };
}

export { KARARLAR as CASE_KALITESI_KARARLARI };
