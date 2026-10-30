// core durum makineleri (tp_core.workflow.states.MACHINES) — portal tarafı geçiş denetimi.
//
// Kaynak `durum-makineleri.json` (core'dan üretilir, `sozlesme.test.ts` güncelliğini denetler).
// Hem mock arka uç hem de karar düğmeleri buradan okur: mock, gerçek core'un 409 vereceği bir
// geçişi asla göstermez; ekran da core'un reddedeceği kararı önermez.
import makineler from "./durum-makineleri.json";
import type { CaseDurumu, CaseKararGirdisi } from "../types";

type Makine = { initial: string; states: string[]; transitions: Record<string, string[]> };
const M = makineler as Record<string, Makine>;

export type MakineAdi = "requirement" | "requirement_review" | "consistency_finding" | "test_case" | "script" | "bug_draft" | "workflow_instance";

export function gecisVar(makine: MakineAdi, mevcut: string, hedef: string): boolean {
  return M[makine]?.transitions[mevcut]?.includes(hedef) ?? false;
}

/** `mevcut`'tan başlayıp `yol`daki her adımın izinli olup olmadığı. */
export function yolGecerli(makine: MakineAdi, mevcut: string, yol: readonly string[]): boolean {
  let d = mevcut;
  for (const h of yol) {
    if (!gecisVar(makine, d, h)) return false;
    d = h;
  }
  return true;
}

export type CaseKarari = CaseKararGirdisi["karar"];

/** core: approve | edit → approved kapısı, reject → rejected kapısı (yalnızca `draft`'tan). */
export const CASE_KARAR_HEDEFI: Record<CaseKarari, CaseDurumu> = {
  approve: "approved",
  edit: "approved",
  reject: "rejected",
};

export const GECIS_YOK = "Bu durumdan bu karara geçilemez.";

export function caseKarariVerilebilir(durum: CaseDurumu, karar: CaseKarari): boolean {
  return gecisVar("test_case", durum, CASE_KARAR_HEDEFI[karar]);
}
