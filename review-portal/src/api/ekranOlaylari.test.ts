// Ekran ↔ olay aboneliği sözleşmesi (2026-11-24 canlı tıklama CT-1..CT-3): bir iş bittiğinde core'un
// yayımladığı olay, o işi başlatan/izleyen ekranın `useOlay` aboneliğine (konu + kimlik süzgeci)
// gerçekten ulaşmalı. Yalnız ad listesi yetmez: ad kayıtlı olsa da ekran başka konuya ya da başka
// kimliğe süzerse ekran yenilemeye kadar takılı kalır.
//
// Tablo: ekran dosyası, işi, bitişte (ve ara adımlarda) core'un yayımladığı olay + core yükünün kimlik
// alanları (core yayın yerlerinden; `scripts/sse_olaylari.py` ile aynı kaynaklar) ve ekranın süzgeci.
// Konu listesi ekran kaynağından okunur: ekrandaki abonelik değişirse test bunu görür.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { DINLENEN_OLAYLAR, olayEslesir } from "./events";
import sseOlaylari from "./sozlesme/sse-olaylari.json";

type Suzgec =
  /** `useOlay(fn, konular, id)`: kimlik olayın kendisi ya da `*_id` alanı. */
  | { tur: "id"; id: string }
  /** İşleyici `data.requirement_id` string ve farklıysa atlar (CaseReview, Yayın). */
  | { tur: "gereksinim"; id: string }
  | { tur: "yok" };

interface Satir {
  ekran: string;
  is: string;
  olay: string;
  data: Record<string, unknown>;
  suzgec: Suzgec;
}

const R = "req-1";
const S = "scr-1";
const RUN = "run-1";
const F = "fail-1";
const B = "bug-1";

const TABLO: Satir[] = [
  // B3 — case review / denetim / yayın
  { ekran: "pages/CaseReview.tsx", is: "cases.review", olay: "case.review", data: { requirement_id: R, durum: "tamamlandi", skor: 11 }, suzgec: { tur: "gereksinim", id: R } },
  { ekran: "pages/CaseReview.tsx", is: "cases.audit", olay: "case.audit", data: { requirement_id: R, durum: "tamamlandi", karar: "KABUL" }, suzgec: { tur: "gereksinim", id: R } },
  { ekran: "pages/CaseReview.tsx", is: "cases.generate", olay: "case.generated", data: { id: "c-1", requirement_id: R }, suzgec: { tur: "gereksinim", id: R } },
  { ekran: "pages/CaseReview.tsx", is: "publish.cases", olay: "publish.completed", data: { job_id: "j-1", requirement_id: R, sonuclar: [] }, suzgec: { tur: "gereksinim", id: R } },
  { ekran: "pages/Yayin.tsx", is: "publish.cases", olay: "publish.completed", data: { job_id: "j-1", requirement_id: R, hedef: "jira", sonuclar: [] }, suzgec: { tur: "gereksinim", id: R } },
  { ekran: "pages/Yayin.tsx", is: "publish.cases (case hatası)", olay: "publish.failed", data: { case_id: "c-1", requirement_id: R, hata: "x" }, suzgec: { tur: "gereksinim", id: R } },
  { ekran: "pages/Yayin.tsx", is: "cases.audit", olay: "case.audit", data: { requirement_id: R, durum: "tamamlandi" }, suzgec: { tur: "gereksinim", id: R } },
  // B4 — kod üretimi, kırarak doğrula, merge
  { ekran: "pages/ScriptDetay.tsx", is: "codegen.generate (ajan adımı)", olay: "agent.step", data: { script_id: S, n: 1 }, suzgec: { tur: "id", id: S } },
  { ekran: "pages/ScriptDetay.tsx", is: "codegen.generate (yerel kontrol)", olay: "codegen.check", data: { script_id: S, sonuc: "gecti", run_id: RUN }, suzgec: { tur: "id", id: S } },
  { ekran: "pages/ScriptDetay.tsx", is: "codegen.generate (bitiş)", olay: "script.state", data: { id: S, durum: "pr_open" }, suzgec: { tur: "id", id: S } },
  { ekran: "pages/ScriptDetay.tsx", is: "codegen.generate (PR)", olay: "pr.opened", data: { script_id: S, pr_number: 7 }, suzgec: { tur: "id", id: S } },
  { ekran: "pages/ScriptDetay.tsx", is: "codegen.latency_budget", olay: "codegen.latency_budget", data: { script_id: S, sure_s: 90 }, suzgec: { tur: "id", id: S } },
  { ekran: "pages/ScriptDetay.tsx", is: "codegen.break_verify", olay: "codegen.break_verify", data: { script_id: S, durum: "tamam", asama: "geri" }, suzgec: { tur: "id", id: S } },
  { ekran: "pages/ScriptDetay.tsx", is: "codegen.update_branch", olay: "codegen.branch", data: { script_id: S, pr_number: 7, durum: "guncel" }, suzgec: { tur: "id", id: S } },
  { ekran: "pages/ScriptDetay.tsx", is: "PR review kararı", olay: "codegen.reviewed", data: { script_id: S, pr_number: 7, karar: "approve" }, suzgec: { tur: "id", id: S } },
  { ekran: "pages/ScriptDetay.tsx", is: "merge", olay: "pr.merged", data: { script_id: S, pr_number: 7 }, suzgec: { tur: "id", id: S } },
  { ekran: "pages/ScriptDetay.tsx", is: "ci.run (PR koşusu)", olay: "ci.status", data: { id: RUN, run_id: RUN, script_id: S, durum: "passed" }, suzgec: { tur: "id", id: S } },
  { ekran: "pages/Kod.tsx", is: "codegen.generate", olay: "script.state", data: { id: S, durum: "pr_open" }, suzgec: { tur: "yok" } },
  { ekran: "pages/Kod.tsx", is: "codegen.generate (PR)", olay: "pr.opened", data: { script_id: S }, suzgec: { tur: "yok" } },
  { ekran: "pages/TestCaseleri.tsx", is: "merge", olay: "pr.merged", data: { script_id: S }, suzgec: { tur: "yok" } },
  // B5 — koşu sonuçları, triage, onarım
  { ekran: "pages/Kosular.tsx", is: "ci.run", olay: "ci.status", data: { id: RUN, run_id: RUN, durum: "failed" }, suzgec: { tur: "yok" } },
  { ekran: "pages/Kosular.tsx", is: "ci.run (detay)", olay: "ci.status", data: { id: RUN, run_id: RUN, durum: "failed" }, suzgec: { tur: "id", id: RUN } },
  { ekran: "pages/Kosular.tsx", is: "triage (koşu detayı)", olay: "failure.classified", data: { id: F, failure_id: F, run_id: RUN }, suzgec: { tur: "id", id: RUN } },
  { ekran: "pages/Hatalar.tsx", is: "triage", olay: "failure.classified", data: { id: F, failure_id: F, run_id: RUN }, suzgec: { tur: "yok" } },
  { ekran: "pages/Hatalar.tsx", is: "repair.fix", olay: "repair.merged", data: { script_id: S, failure_id: F }, suzgec: { tur: "yok" } },
  { ekran: "pages/HataDetay.tsx", is: "triage", olay: "failure.classified", data: { id: F, failure_id: F, run_id: RUN }, suzgec: { tur: "id", id: F } },
  { ekran: "pages/HataDetay.tsx", is: "repair.fix (istek)", olay: "repair.requested", data: { script_id: S, failure_id: F, job_id: "j" }, suzgec: { tur: "id", id: F } },
  { ekran: "pages/HataDetay.tsx", is: "repair.fix (adım)", olay: "repair.step", data: { script_id: S, failure_id: F, adim: "x" }, suzgec: { tur: "id", id: F } },
  { ekran: "pages/HataDetay.tsx", is: "repair.fix (engel)", olay: "repair.blocked", data: { script_id: S, failure_id: F }, suzgec: { tur: "id", id: F } },
  { ekran: "pages/HataDetay.tsx", is: "repair.fix (PR)", olay: "pr.opened", data: { script_id: S, failure_id: F, pr_number: 9 }, suzgec: { tur: "id", id: F } },
  { ekran: "pages/HataDetay.tsx", is: "repair merge", olay: "repair.merged", data: { script_id: S, failure_id: F }, suzgec: { tur: "id", id: F } },
  // B6 — bug taslağı ve bug yayını
  { ekran: "pages/BugTaslaklari.tsx", is: "bugs.prepare", olay: "bug.draft_ready", data: { id: B, durum: "ready", failure_id: F, requirement_id: R }, suzgec: { tur: "yok" } },
  { ekran: "pages/BugTaslaklari.tsx", is: "bugs.prepare (hata)", olay: "bug.prepare_failed", data: { id: B, durum: "draft" }, suzgec: { tur: "yok" } },
  { ekran: "pages/BugTaslaklari.tsx", is: "bugs.publish", olay: "bug.published", data: { id: B, durum: "published", jira_key: "TPD-9" }, suzgec: { tur: "id", id: B } },
  { ekran: "pages/BugTaslaklari.tsx", is: "bugs.publish (hata)", olay: "bug.publish_failed", data: { id: B, durum: "ready", hata: "x" }, suzgec: { tur: "id", id: B } },
  { ekran: "pages/BugTaslaklari.tsx", is: "bugs.prepare (detay)", olay: "bug.draft_ready", data: { id: B, durum: "ready" }, suzgec: { tur: "id", id: B } },
  { ekran: "pages/BugTaslaklari.tsx", is: "bug durumu", olay: "bug_draft.state", data: { id: B, durum: "published" }, suzgec: { tur: "id", id: B } },
];

const kok = resolve(__dirname, "..");

/** Ekran dosyasındaki her `useOlay(…, [konular], …)` çağrısının konu kümesi. */
function abonelikler(dosya: string): Set<string>[] {
  const kaynak = readFileSync(resolve(kok, dosya), "utf8");
  const out: Set<string>[] = [];
  for (const m of kaynak.matchAll(/useOlay\(/g)) {
    // Çağrının sonuna kadar (parantez dengesi) tara; ilk dizi literalinin metinleri konulardır.
    let derinlik = 0;
    let i = m.index! + "useOlay".length;
    const bas = i;
    for (; i < kaynak.length; i++) {
      if (kaynak[i] === "(") derinlik++;
      else if (kaynak[i] === ")" && --derinlik === 0) break;
    }
    const cagri = kaynak.slice(bas, i);
    const dizi = /\[\s*("[^\]]*")\s*,?\s*\]/.exec(cagri);
    if (dizi) out.push(new Set([...dizi[1].matchAll(/"([a-z_.]+)"/g)].map((x) => x[1])));
  }
  return out;
}

function ulasir(s: Satir): boolean {
  const o = { type: s.olay, id: typeof s.data.id === "string" ? s.data.id : undefined, data: s.data };
  return abonelikler(s.ekran).some((konular) => {
    if (s.suzgec.tur === "id") return olayEslesir(o, konular, s.suzgec.id);
    if (!olayEslesir(o, konular)) return false;
    if (s.suzgec.tur === "gereksinim") return !(typeof o.data.requirement_id === "string" && o.data.requirement_id !== s.suzgec.id);
    return true;
  });
}

describe("ekran ↔ olay aboneliği (B3–B6 işlerinin bitişi ekrana düşer)", () => {
  it.each(TABLO)("$ekran · $is → $olay", (s) => {
    // Olay core'da gerçekten yayımlanıyor ve EventSource'a kayıtlı.
    expect(sseOlaylari, `${s.olay} core'da yayımlanmıyor`).toContain(s.olay);
    expect(DINLENEN_OLAYLAR).toContain(s.olay);
    expect(abonelikler(s.ekran).length, `${s.ekran} useOlay bulunamadı`).toBeGreaterThan(0);
    expect(ulasir(s), `${s.ekran} aboneliği ${s.olay} olayını almıyor`).toBe(true);
  });

  it("başka gereksinimin / nesnenin olayı ekranı yenilemez (süzgeç çalışıyor)", () => {
    expect(ulasir({ ...TABLO[0], data: { requirement_id: "req-2" } })).toBe(false);
    expect(ulasir({ ...TABLO.find((s) => s.olay === "agent.step")!, data: { script_id: "scr-2" } })).toBe(false);
    expect(ulasir({ ...TABLO.find((s) => s.ekran === "pages/HataDetay.tsx")!, data: { id: "f-2", failure_id: "f-2" } })).toBe(false);
  });
});
