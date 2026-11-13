/**
 * Örnek veri: case seti review'u (P8) ve Agent Probe denetimi (P9) — core
 * `features/cases/review.py` ve `denetim_akisi.py` ile aynı kurallar (011 D şeridi).
 *
 * - Set kimliği: güncel (superseded/ret olmayan) v3 case'lerin `icerik_hash`'leri (sıralı) →
 *   `setImzasi`. Case eklenir, düzeltilir ya da reddedilirse imza değişir; review ve karar bayat olur.
 * - Review üretimden sonra otomatik: üretim golden'ı (`case_generation`) adıyla `case_review`
 *   golden'ı (golden/kaynaklar.json) — set üretimdeki hâliyle aynıysa REPLAY, değilse dürüst
 *   REPLAY-MISS (`hata`; "review çalışmadı, yeniden dene").
 * - Denetim "Agent Probe'a gönder" ile; koşul core'daki gibi: güncel setin review'u tamamlanmış ya da en
 *   az bir onaylı v3 case var. Karar `case_audit` golden'ı (set üretimdeki hâliyle aynıysa).
 * - Yayın kapısı (`yayinEngeli`): v3 case için güncel setin son tamamlanmış kararı KABUL değilse engel.
 *   Engel metinleri core gibi "Yayınlanamaz: " önekiyle gelir (K22); portal öneki ikinci kez yazmaz.
 * - Denetim hatası core gibi ham istisna sınıfı önekiyle gelir (`ReplayNoOutput: …`); portal ayıklar.
 */
import type {
  CaseDenetimGorunumu,
  CaseDenetimKaydi,
  CaseHaritasi,
  CaseReviewGorunumu,
  CaseReviewIcerik,
  CaseReviewKaydi,
  DenetimBulgusu,
  DenetimKarari,
  TestCase,
} from "../types";
import { caseEski } from "../../lib/caseV3";
import { YAYINLANAMAZ } from "../../lib/kalite";
import { KAYNAK } from "./fixtures";

export interface KaliteKaydi {
  /** Üretimin eşleştiği golden adı (`TPD-1`, `f2-kod-hatasi/TPD-1` …); REPLAY-MISS üretiminde yok. */
  golden?: string;
  /** Üretim bittiğindeki set imzası (golden girdi beyanının karşılığı). */
  uretimImzasi?: string | null;
  review?: CaseReviewKaydi;
  denetimler?: CaseDenetimKaydi[];
}

const KAYNAK_K = KAYNAK as unknown as {
  case_review?: Record<string, CaseReviewIcerik>;
  case_audit?: Record<string, { decision: DenetimKarari; decision_rationale: string; findings: DenetimBulgusu[]; missing_scenarios: string[] }>;
};

export function setCaseleri(caseler: TestCase[], rid: string): TestCase[] {
  return caseler.filter((c) => c.requirement_id === rid && c.durum !== "superseded" && c.durum !== "rejected" && !caseEski(c));
}

/** Kısa, kararlı imza (djb2; core'daki sha256'nın örnek veri karşılığı). */
export function setImzasi(caseler: TestCase[], rid: string): string | null {
  const hashler = setCaseleri(caseler, rid)
    .map((c) => c.icerik_hash)
    .sort();
  if (!hashler.length) return null;
  let h = 5381;
  for (const ch of hashler.join("\n")) h = ((h * 33) ^ ch.charCodeAt(0)) >>> 0;
  return `set-${h.toString(16).padStart(8, "0")}`;
}

export function caseHaritasi(caseler: TestCase[], rid: string): CaseHaritasi {
  const out: CaseHaritasi = {};
  setCaseleri(caseler, rid).forEach((c, i) => {
    out[String(i + 1)] = { id: c.id, sira_no: c.sira_no, uretim_no: 1, title: c.icerik.title, durum: c.durum };
  });
  return out;
}

const UYGUN = (i: CaseReviewIcerik) => (i.items ?? []).filter((m) => m.verdict === "UYGUN").length;

/** Üretimden sonra (otomatik) ya da "Yeniden çalıştır" ile review. */
export function reviewCalistir(k: KaliteKaydi, caseler: TestCase[], rid: string, simdi: string, isteyen = "system"): CaseReviewKaydi {
  const imza = setImzasi(caseler, rid) ?? "";
  const golden = k.golden ? KAYNAK_K.case_review?.[k.golden] : undefined;
  const eslesir = golden !== undefined && imza === k.uretimImzasi;
  const kayit: CaseReviewKaydi = eslesir
    ? {
        id: `rv-${rid}-${simdi}`,
        durum: "tamamlandi",
        set_hash: imza,
        uretim_no: 1,
        skor: UYGUN(golden),
        icerik: { ...golden, score: UYGUN(golden), case_haritasi: caseHaritasi(caseler, rid), mode: "replay" },
        hata: null,
        isteyen,
        mode: "replay",
        olusturma: simdi,
        guncelleme: simdi,
        bayat: false,
      }
    : {
        id: `rv-${rid}-${simdi}`,
        durum: "hata",
        set_hash: imza,
        uretim_no: 1,
        skor: null,
        icerik: {},
        hata: "REPLAY-MISS: bu set için kayıtlı review çıktısı yok (ReplayNoOutput)",
        isteyen,
        mode: null,
        olusturma: simdi,
        guncelleme: simdi,
        bayat: false,
      };
  k.review = kayit;
  return kayit;
}

export function reviewGorunumu(k: KaliteKaydi | undefined, caseler: TestCase[], rid: string, gereksinimDurumu: string): CaseReviewGorunumu {
  const imza = setImzasi(caseler, rid);
  const r = k?.review ? { ...k.review, bayat: k.review.set_hash !== imza } : null;
  return {
    requirement_id: rid,
    set_hash: imza,
    review: r,
    bayat: r?.bayat ?? false,
    calisiyor: r?.durum === "bekliyor",
    yeniden_calistirilabilir: imza !== null && ["cases_ready", "done"].includes(gereksinimDurumu),
  };
}

const sonTamamlanan = (k: KaliteKaydi | undefined, imza: string | null) =>
  imza ? [...(k?.denetimler ?? [])].reverse().find((d) => d.set_hash === imza && d.durum === "tamamlandi") ?? null : null;

/** "Agent Probe'a gönder" neden kapalı (null = gönderilebilir); core `submit_block`. */
export function gonderEngeli(k: KaliteKaydi | undefined, caseler: TestCase[], rid: string, gereksinimDurumu: string): string | null {
  if (!["cases_ready", "done"].includes(gereksinimDurumu)) return `Agent Probe denetimi yalnız "Case review aşamasında" olan gereksinimde istenir (durum: ${gereksinimDurumu})`;
  const imza = setImzasi(caseler, rid);
  if (!imza) return "Gereksinimin güncel v3 case'i yok; denetlenecek set boş";
  if (k?.review?.set_hash === imza && k.review.durum === "bekliyor") return "Bu set için review sürüyor; review bitince Agent Probe'a gönderin";
  if (k?.review?.set_hash === imza && k.review.durum === "tamamlandi") return null;
  if (setCaseleri(caseler, rid).some((c) => c.durum === "approved" || c.durum === "published")) return null;
  return "Bu setin review'u tamamlanmadı ve onaylı case yok: review'u yeniden çalıştırın ya da en az bir case'i inceleyip onaylayın";
}

/** Denetim kaydı (bekliyor) → `denetimTamamla` arka planda kararı yazar. */
export function denetimBaslat(k: KaliteKaydi, caseler: TestCase[], rid: string, simdi: string, isteyen: string): CaseDenetimKaydi {
  const kayit: CaseDenetimKaydi = {
    id: `ap-${rid}-${(k.denetimler?.length ?? 0) + 1}`,
    durum: "bekliyor",
    set_hash: setImzasi(caseler, rid) ?? "",
    karar: null,
    model_karari: null,
    icerik: {},
    kaynak: "tp-gecit",
    talep_no: null,
    hata: null,
    isteyen,
    olusturma: simdi,
    guncelleme: simdi,
    guncel: true,
  };
  (k.denetimler ??= []).push(kayit);
  return kayit;
}

export function denetimTamamla(k: KaliteKaydi, kayit: CaseDenetimKaydi, caseler: TestCase[], rid: string, simdi: string): void {
  const golden = k.golden ? KAYNAK_K.case_audit?.[k.golden] : undefined;
  kayit.guncelleme = simdi;
  if (!golden || kayit.set_hash !== k.uretimImzasi) {
    kayit.durum = "hata";
    // Core hata metni ham istisna sınıfıyla başlar (`f"{type(e).__name__}: {e}"`); portal ayıklar.
    kayit.hata = "ReplayNoOutput: bu set için kayıtlı denetim çıktısı yok (REPLAY-MISS)";
    return;
  }
  kayit.durum = "tamamlandi";
  kayit.karar = golden.decision;
  kayit.model_karari = golden.decision;
  kayit.talep_no = `AP-2026-${kayit.set_hash.slice(-8).toUpperCase()}`;
  kayit.icerik = {
    ...golden,
    deterministik_bulgular: [],
    sertlestirildi: false,
    case_haritasi: caseHaritasi(caseler, rid),
    mode: "replay",
  };
}

const kisa = (m: string | null | undefined, n = 240) => {
  const t = (m ?? "").split(/\s+/).join(" ").trim();
  return t.length <= n ? t : `${t.slice(0, n - 1)}…`;
};

/** Yayın kapısı (core `gate_reason`): null = engel yok. */
export function yayinEngeli(k: KaliteKaydi | undefined, caseler: TestCase[], rid: string): string | null {
  const imza = setImzasi(caseler, rid);
  const karar = sonTamamlanan(k, imza);
  if (!karar) {
    const son = k?.denetimler?.at(-1);
    if (!son) return `${YAYINLANAMAZ}Agent Probe denetimi kararı yok; seti "Agent Probe'a gönder" ile denetletin`;
    if (son.set_hash === imza && son.durum === "bekliyor") return `${YAYINLANAMAZ}Agent Probe denetimi sürüyor; bu set için karar henüz gelmedi`;
    if (son.set_hash === imza && son.durum === "hata") return `${YAYINLANAMAZ}Agent Probe denetimi yapılamadı (${kisa(son.hata, 160)}); yeniden gönderin`;
    return `${YAYINLANAMAZ}Agent Probe denetimi kararı bayat — set son denetimden sonra değişti (case eklendi, düzeltildi ya da reddedildi); yeniden gönderin`;
  }
  if (karar.karar === "KABUL") return null;
  const g = kisa(karar.icerik.decision_rationale);
  return `${YAYINLANAMAZ}${g ? `${karar.karar} — ${g}` : String(karar.karar)}`;
}

export function denetimGorunumu(k: KaliteKaydi | undefined, caseler: TestCase[], rid: string, gereksinimDurumu: string): CaseDenetimGorunumu {
  const imza = setImzasi(caseler, rid);
  const isaretle = (d: CaseDenetimKaydi | null | undefined) => (d ? { ...d, guncel: d.set_hash === imza } : null);
  const son = k?.denetimler?.at(-1);
  const calisiyor = son?.durum === "bekliyor" && son.set_hash === imza;
  return {
    requirement_id: rid,
    set_hash: imza,
    denetim: isaretle(son),
    guncel_karar: isaretle(sonTamamlanan(k, imza)),
    calisiyor,
    gonder_engeli: calisiyor ? null : gonderEngeli(k, caseler, rid, gereksinimDurumu),
    kapi_acik: true,
    yayin_engeli: imza ? yayinEngeli(k, caseler, rid) : null,
  };
}
