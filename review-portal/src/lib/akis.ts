// Gereksinim durumundan 14 adımlı akıştaki adımı türetir (TEKNIK-TASARIM §2).
// Durum kümesi core-api'nin REQUIREMENT durum makinesidir (tp_core/workflow/states.py);
// `Record<GereksinimDurumu, …>` sayesinde core'a yeni durum eklenip burada eşlenmezse derleme
// kırılır, lib.test.ts de states.py'yi okuyarak aynı kümeyi doğrular.
import { AKIS_ADIMLARI } from "./etiketler";
import type { GereksinimDurumu } from "../api/types";

/** Durum → akış adımı (1–14). `null`: durumdan çıkarılamaz, ipucuna bakılır. */
export const DURUM_ADIMI: Record<GereksinimDurumu, number | null> = {
  new: 1, // Jira'dan çekildi
  in_review: 2, // Ön inceleme (AI)
  findings_open: 2, // Ön inceleme — insan kararı bekliyor
  doc_final: 2, // Ön inceleme tamam, PO'ya gidecek
  pending_po: 3, // PO teyidi
  po_approved: 4, // Test case
  generating: 4,
  cases_ready: 4,
  done: 5, // Case'ler yayınlandı → kod taslağı ve sonrası
  failed: null, // in_review veya generating'den düşebilir
};

const SON_ADIM = AKIS_ADIMLARI.length;

/**
 * Akış adımının adı. 1. adım Jira story'sinde "Jira"; serbest metin gereksinimde Jira yoktur,
 * o yüzden "Serbest metin" yazılır.
 */
export function adimAdi(no: number, kaynak: "jira" | "free_text" = "jira"): string {
  if (no === 1 && kaynak !== "jira") return "Serbest metin";
  return AKIS_ADIMLARI[no - 1]?.ad ?? "";
}

/**
 * Gösterilecek adım. Gereksinim makinesi `done` ile biter; sonraki adımlar (kod, CI, triage)
 * script/koşu nesnelerinde ilerler, bu yüzden `done` ve `failed` için API'nin verdiği ipucu
 * (varsa) kullanılır. Bilinmeyen durum adı 1. adım sayılır.
 */
export function akisAdimi(durum: string, ipucu?: number | null): number {
  const sinirla = (n: number) => Math.min(SON_ADIM, Math.max(1, Math.round(n)));
  const ipucuGecerli = typeof ipucu === "number" && Number.isFinite(ipucu);
  const temel = DURUM_ADIMI[durum as GereksinimDurumu];
  if (temel === undefined) return 1;
  if (temel === null) return ipucuGecerli ? sinirla(ipucu) : 1;
  if (durum === "done" && ipucuGecerli) return sinirla(Math.max(temel, ipucu));
  return temel;
}

/** Başarısız işin türü → akıştaki adımı (core job.tur; `son_hata.job_tur`). */
export const HATA_ADIMI: Record<string, number> = {
  "requirements.review": 2,
  "requirements.consistency": 2,
  "requirements.apply_doc_fixes": 2,
  "requirements.po_request": 3,
  "requirements.po_poll": 3,
  "cases.generate": 4,
};

/** Denetim (ön inceleme/tutarlılık) aşamasının işleri: yalnızca bunlar düşünce "denetim tamamlanmadı" denir. */
export const DENETIM_ISLERI = new Set(["requirements.review", "requirements.consistency", "requirements.apply_doc_fixes"]);

/** Case üretimi işi (core `cases.generate`). */
export const URETIM_ISI = "cases.generate";

/** `failed` gereksinimde hangi adımın düştüğü: API ipucu yoksa başarısız işin türünden. */
export function hataAdimi(jobTur: string | null | undefined): number | null {
  return jobTur ? (HATA_ADIMI[jobTur] ?? null) : null;
}
