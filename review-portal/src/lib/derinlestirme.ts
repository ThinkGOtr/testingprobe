// Derinleştirme (011 P5/P6, K7): `GET /requirements/{id}/deepen` yanıt uyarlaması ve panelin saf
// kuralları (düğme engeli, sonuç metni). Derinleştirme mevcut sete ek taslak üretir; gereksinim
// `cases_ready`'de kalır.
import type { DerinlestirmeDurumu, DerinlestirmeTuru } from "../api/types";
import { gereksinimDurumu } from "./etiketler";
import { DERINLESTIRME_TEKNIKLERI } from "./uretimSecenekleri";

const DURUMLAR = ["yok", "calisiyor", "tamam", "hata"] as const;

export const DERINLESTIRME_YOK: DerinlestirmeDurumu = {
  durum: "yok",
  tur: null,
  teknik: null,
  uretim_no: null,
  yeni_case_sayisi: null,
  uyarilar: [],
  hata: null,
};

export function derinlestirmeDurumuUyarla(ham: unknown): DerinlestirmeDurumu {
  if (!ham || typeof ham !== "object") return { ...DERINLESTIRME_YOK };
  const h = ham as Record<string, unknown>;
  const durum = DURUMLAR.includes(h.durum as (typeof DURUMLAR)[number]) ? (h.durum as DerinlestirmeDurumu["durum"]) : "yok";
  const sayi = (x: unknown) => (typeof x === "number" && Number.isFinite(x) ? x : null);
  return {
    durum,
    tur: h.tur === "negatif" || h.tur === "teknik" ? h.tur : null,
    teknik: typeof h.teknik === "string" && h.teknik ? h.teknik : null,
    uretim_no: sayi(h.uretim_no),
    yeni_case_sayisi: sayi(h.yeni_case_sayisi),
    uyarilar: Array.isArray(h.uyarilar) ? h.uyarilar.filter((u): u is string => typeof u === "string") : [],
    hata: typeof h.hata === "string" && h.hata ? h.hata : null,
  };
}

export const DERINLESTIRME_SURUYOR = "Derinleştirme sürüyor; bitince yeni taslaklar listeye eklenir.";
/** İki derinleştirme düğmesinden biri sürerken diğerinin pasiflik nedeni (core tek iş tutar: 409). */
export const DIGER_DERINLESTIRME_SURUYOR = "Diğer derinleştirme sürüyor";
/** Yoklama bu kadar ardışık okuma hatasında durur; kullanıcı "Tekrar dene" ile sürdürür. */
export const YOKLAMA_HATA_SINIRI = 3;

/**
 * Düğmeler neden pasif (null: etkin). Rol kontrolü düğmenin kendisinde (`case.generate`, Testçi); burada
 * gereksinim durumu (core: yalnız `cases_ready`, aksi 409) ve süren derinleştirme (409).
 */
export function derinlestirmeEngeli(gereksinimDurumuKodu: string | undefined, d: Pick<DerinlestirmeDurumu, "durum"> | null | undefined): string | null {
  if (!gereksinimDurumuKodu) return "Gereksinim yükleniyor";
  if (gereksinimDurumuKodu !== "cases_ready") {
    return `Derinleştirme yalnız "Case review aşamasında" olan gereksinimde yapılabilir (şu an: ${gereksinimDurumu(gereksinimDurumuKodu).etiket}).`;
  }
  if (d?.durum === "calisiyor") return DERINLESTIRME_SURUYOR;
  return null;
}

export function derinlestirmeAdi(tur: DerinlestirmeTuru | null, teknik: string | null): string {
  if (tur === "negatif") return "Negatif genişletme";
  if (tur === "teknik") {
    const t = DERINLESTIRME_TEKNIKLERI.find((x) => x.kod === teknik);
    return `Teknik derinleştirme${teknik ? ` (${t ? `${t.kod} — ${t.ad}` : teknik})` : ""}`;
  }
  return "Derinleştirme";
}

/** Bitmiş derinleştirmenin tek satırlık sonucu ("N yeni taslak eklendi" / "Yeni taslak eklenmedi"). */
export function derinlestirmeSonucu(d: DerinlestirmeDurumu): string | null {
  if (d.durum !== "tamam") return null;
  const n = d.yeni_case_sayisi ?? 0;
  return n > 0 ? `${n} yeni taslak eklendi${d.uretim_no !== null ? ` (üretim ${d.uretim_no})` : ""}.` : "Yeni taslak eklenmedi.";
}
