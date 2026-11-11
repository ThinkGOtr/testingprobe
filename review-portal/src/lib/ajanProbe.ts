// Agent Probe (011 F6/F7) görünüm etiketleri: ajan testi durumu ve asistan denetim kategorileri.
import type { AjanTestiDurumu } from "../api/types";
import type { Ton } from "./etiketler";

export const AJAN_TESTI_DURUMU: Record<AjanTestiDurumu, { etiket: string; ton: Ton }> = {
  queued: { etiket: "Kuyrukta", ton: "notr" },
  running: { etiket: "Koşuyor", ton: "bilgi" },
  passed: { etiket: "Geçti", ton: "basari" },
  failed: { etiket: "Kaldı", ton: "hata" },
  error: { etiket: "Hata", ton: "hata" },
};

export const AJAN_TESTI_BITMEDI: ReadonlySet<AjanTestiDurumu> = new Set(["queued", "running"]);

/** Ajan ürününe bağlı gereksinimde case üretim/review/yayın düğmelerinin pasiflik nedeni. */
export const AJAN_URUNU_NEDENI = "Ajan ürünü — test Agent Probe'da koşar";

export const SIMULASYON_ACIKLAMASI =
  "Agent Probe bu sürümde simüle edilir; yalnız Agent Probe'da ön tanımları tamamlanmış ürünler görünür. Sonuçlar temsilidir.";

/** core `assistant_guard` şemasındaki kategori enum'u → Türkçe etiket. */
export const DENETIM_KATEGORISI: Record<string, string> = {
  yanlis_bilgi: "Yanlış bilgi",
  nefret_irkcilik: "Nefret söylemi / ırkçılık",
  ayrimcilik: "Ayrımcılık",
  rekabete_aykiri: "Rekabete aykırı",
  kufur_taciz: "Küfür / taciz",
  kisisel_veri: "Kişisel veri",
  prompt_injection: "Talimat manipülasyonu",
  zararli_icerik: "Zararlı içerik",
  kapsam_disi: "Kapsam dışı",
  temiz: "Temiz",
};

export function kategoriEtiketi(k: string): string {
  return DENETIM_KATEGORISI[k] ?? k;
}

export const DENETIM_KAYNAGI: Record<string, string> = {
  "tp-gecit": "Testing Probe geçidi (model)",
  sim: "Kural tabanlı denetim",
  "agent-probe": "Agent Probe",
};
