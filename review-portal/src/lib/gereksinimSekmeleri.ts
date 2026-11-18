// Gereksinim detayının sekmeleri (DS-1) ve "Sıradaki adım" satırı. Saf işlevler: sayfa ve testler ortak kullanır.
import type { GereksinimDetay } from "../api/types";

/** Ana sekme kimlikleri (`?sekme=<id>`). */
export const GEREKSINIM_SEKMESI = {
  dokuman: "dokuman",
  model: "tasarim-modeli",
  caseler: "caseler",
  po: "po-teyidi",
  tutarlilik: "tutarlilik",
} as const;
export type GereksinimSekmesi = (typeof GEREKSINIM_SEKMESI)[keyof typeof GEREKSINIM_SEKMESI];

/** Sekme adları (sıra = ekrandaki sıra). */
export const GEREKSINIM_SEKME_ADI: Record<GereksinimSekmesi, string> = {
  dokuman: "Doküman",
  "tasarim-modeli": "Tasarım modeli",
  caseler: "Case'ler",
  "po-teyidi": "PO teyidi",
  tutarlilik: "Tutarlılık",
};

export interface SiradakiAdim {
  metin: string;
  /** Adımın yapıldığı sekme; sayfa ilk açılışta bu sekmeyi gösterir. */
  sekme: GereksinimSekmesi;
}

/**
 * Durumdan "Sıradaki adım" (tek satır) ve ilgili sekme. `uretimHatasi`: düşen iş case/model üretimi;
 * `ajanBagli`: test Agent Probe'da (case akışı kapalı).
 */
export function gereksinimSiradakiAdim(
  g: Pick<GereksinimDetay, "durum" | "kaynak" | "ac_missing">,
  d: { uretimHatasi: boolean; ajanBagli: boolean },
): SiradakiAdim {
  const S = GEREKSINIM_SEKMESI;
  switch (g.durum) {
    case "new":
      return {
        metin: g.ac_missing
          ? "ön incelemeyi başlatın; eksik kabul kriterleri PO'ya soru olarak gider."
          : "ön incelemeyi başlatın; doküman kod ve veriyle karşılaştırılır.",
        sekme: S.dokuman,
      };
    case "in_review":
      return { metin: "ön inceleme ve tutarlılık kontrolü sürüyor; bulgular gelince karar verin.", sekme: S.tutarlilik };
    case "findings_open":
      return { metin: "tutarlılık bulgularına karar verin, ardından düzeltmeleri yazın ya da belgeyi son hâl yapın.", sekme: S.tutarlilik };
    case "doc_final":
      return { metin: "doküman son hâlinde; PO teyidi istenir.", sekme: S.po };
    case "pending_po":
      return {
        metin: g.kaynak === "free_text" ? "PO teyidini portalda verin ya da geri çevirin." : "PO'nun Jira'da soruları yanıtlayıp tp-po-approved etiketini koyması bekleniyor.",
        sekme: S.po,
      };
    case "po_approved":
      return d.ajanBagli
        ? { metin: "test Ürün AI ajanında (Agent Probe) koşar.", sekme: S.caseler }
        : { metin: "üretim kipini seçip case (ya da tasarım modeli) üretin.", sekme: S.caseler };
    case "modeling":
      return { metin: "tasarım modeli üretiliyor; bitince inceleyip onaylayın.", sekme: S.model };
    case "model_ready":
      return { metin: "tasarım modeli kararınızı bekliyor; ayrıntı ve model adımı Tasarım modeli sekmesinde.", sekme: S.model };
    case "generating":
      return { metin: "case'ler üretiliyor; bitince Case review'da inceleyin.", sekme: S.caseler };
    case "cases_ready":
      return { metin: "case'leri Case review'da inceleyip onaylayın.", sekme: S.caseler };
    case "done":
      return { metin: "case'ler yayınlandı; akış otomasyon adımlarıyla sürer.", sekme: S.caseler };
    case "failed":
      return d.uretimHatasi
        ? { metin: "case üretimini yeniden deneyin.", sekme: S.caseler }
        : { metin: "son hatayı inceleyip yeniden kontrol edin.", sekme: S.tutarlilik };
    default:
      return { metin: "durumu inceleyin.", sekme: S.dokuman };
  }
}
