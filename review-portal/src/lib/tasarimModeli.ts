// Tasarım modelinin portal tarafı yardımcıları: Türkçe etiketler ve model içi tutarlılık önizlemesi.
// Yetkili kontrol core'dadır (`features/cases/model.py`; yanıttaki `sorunlar`). Buradaki kopya
// yalnızca düzenleme sırasında anında geri bildirim ve örnek veri (mock) içindir.
import type { DesignModel, SinirBeklenen, SinirTarafi, Teknik } from "../api/tasarimModeliTipleri";
import type { Ton } from "./etiketler";

export const TEKNIK_ADI: Record<Teknik, string> = {
  EP: "Eşdeğerlik bölümleme",
  BVA: "Sınır değer analizi",
  DT: "Karar tablosu",
  ST: "Durum geçişi",
  PW: "Pairwise",
  UC: "Kullanım senaryosu",
  EG: "Hata tahmini",
  CL: "Kontrol listesi",
};

/** Teknik → kapsam öğesi kimliği öneki (case-generation v3 ile aynı). */
export const TEKNIK_ONEKI: Record<Teknik, string> = { EP: "EP-", BVA: "BV-", DT: "DT-", ST: "ST-", PW: "PW-", UC: "UC-", EG: "EG-", CL: "CL-" };

export const RISK_ETIKETI: Record<string, { etiket: string; ton: Ton }> = {
  high: { etiket: "yüksek", ton: "hata" },
  medium: { etiket: "orta", ton: "uyari" },
  low: { etiket: "düşük", ton: "notr" },
};

export const SINIR_TARAFI: Record<SinirTarafi, string> = { on: "sınırda", below: "altında", above: "üstünde" };
export const SINIR_BEKLENEN: Record<SinirBeklenen, { etiket: string; ton: Ton }> = {
  accept: { etiket: "kabul", ton: "basari" },
  reject: { etiket: "ret", ton: "hata" },
  open_question: { etiket: "açık soru", ton: "uyari" },
};

export const MODEL_SORUNU: Record<string, string> = {
  overlap: "Çakışan bölüm",
  missing_boundary: "Eksik sınır",
  unreachable: "Ulaşılamayan düğüm",
  undefined_combination: "Tanımsız kombinasyon",
  other: "Diğer",
};

export const MODEL_DURUMU: Record<string, { etiket: string; ton: Ton }> = {
  draft: { etiket: "Onay bekliyor", ton: "uyari" },
  approved: { etiket: "Onaylı", ton: "basari" },
  rejected: { etiket: "Reddedildi", ton: "hata" },
  superseded: { etiket: "Geçersiz (yenisi var)", ton: "notr" },
};

export const SAHIP: Record<string, string> = { PO: "PO", analyst: "Analist", developer: "Geliştirici", "": "—" };

export const OGE_KIMLIGI = /^(EP-[VI][0-9]+|BV-[0-9]+|DT-R[0-9]+|ST-[TX][0-9]+|PW-[0-9]+|UC-(MF|AF[0-9]+|EF[0-9]+)|EG-[0-9]+|CL-[0-9]+)$/;

const cift = (liste: string[]) => [...new Set(liste.filter((x, i) => liste.indexOf(x) !== i))].sort();

/**
 * Model içi tutarlılık (önizleme): kimlik deseni ve tekilliği, ayrıntılı öğelerin coverage_items'ta
 * tanımlılığı, koşul ↔ teknik bağı, geçersiz bölüm/ret beklenen sınırın `valid:false` ile tutarlılığı.
 */
export function modelSorunlari(m: DesignModel): string[] {
  const s: string[] = [];
  const ogeler = new Map(m.coverage_items.map((o) => [o.id, o]));
  const kimlikler = m.coverage_items.map((o) => o.id);
  const hatali = kimlikler.filter((k) => !OGE_KIMLIGI.test(k));
  if (hatali.length) s.push(`geçersiz kapsam öğesi kimliği: ${hatali.join(", ")}`);
  for (const [ad, liste] of [
    ["kapsam öğesi", kimlikler],
    ["koşul", m.conditions.map((c) => c.id)],
    ["açık soru", m.open_questions.map((q) => q.id)],
    ["varsayım", m.assumptions.map((a) => a.id)],
  ] as const) {
    const c = cift([...liste]);
    if (c.length) s.push(`yinelenen ${ad} kimliği: ${c.join(", ")}`);
  }
  const kosullar = new Set(m.conditions.map((c) => c.id));
  for (const t of m.techniques) if (!kosullar.has(t.condition_id)) s.push(`teknik tanımsız koşula bağlı: ${t.condition_id}`);
  const teknikli = new Set(m.techniques.map((t) => t.condition_id));
  for (const c of m.conditions) if (!teknikli.has(c.id)) s.push(`${c.id}: teknik seçilmemiş`);
  const bagli: string[] = [
    ...m.partitions.map((p) => p.item_id),
    ...m.boundaries.map((b) => b.item_id),
    ...m.decision_tables.flatMap((d) => d.rules.map((r) => r.item_id)),
    ...m.state_models.flatMap((sm) => [...sm.valid_transitions.map((t) => t.item_id), ...sm.invalid_transitions.map((t) => t.item_id)]),
    ...m.flows.map((f) => f.item_id),
  ];
  const tanimsiz = [...new Set(bagli.filter((k) => !ogeler.has(k)))].sort();
  if (tanimsiz.length) s.push(`ayrıntılı modelde coverage_items'ta olmayan öğe: ${tanimsiz.join(", ")}`);
  for (const p of m.partitions) {
    const o = ogeler.get(p.item_id);
    if (o && o.valid !== p.valid) s.push(`${p.item_id}: bölümün geçerliliği kapsam öğesiyle çelişiyor`);
  }
  for (const b of m.boundaries) {
    const o = ogeler.get(b.item_id);
    if (o && b.expected === "reject" && o.valid) s.push(`${b.item_id}: reddedilen sınır değer valid:true`);
    if (o && b.expected === "accept" && !o.valid) s.push(`${b.item_id}: kabul edilen sınır değer valid:false`);
  }
  const teknikler = new Set(m.techniques.map((t) => t.technique));
  for (const o of m.coverage_items) {
    const teknik = (Object.keys(TEKNIK_ONEKI) as Teknik[]).find((t) => o.id.startsWith(TEKNIK_ONEKI[t]));
    if (teknik && !teknikler.has(teknik)) s.push(`${o.id}: tekniği (${teknik}) hiçbir koşul için seçilmemiş`);
  }
  return s;
}

/** Ayrıntılı modelde geçmeyen kapsam öğeleri (yalnız EG öğeleri ayrıntılı model gerektirmez). */
export function bagliOgeler(m: DesignModel): Set<string> {
  return new Set([
    ...m.partitions.map((p) => p.item_id),
    ...m.boundaries.map((b) => b.item_id),
    ...m.decision_tables.flatMap((d) => d.rules.map((r) => r.item_id)),
    ...m.state_models.flatMap((sm) => [...sm.valid_transitions.map((t) => t.item_id), ...sm.invalid_transitions.map((t) => t.item_id)]),
    ...m.flows.map((f) => f.item_id),
  ]);
}

/**
 * D1/K20: model onayı (approve/edit) tur 2'yi (case üretimi) otomatik başlatır; onay yanıtı bunu
 * `tur2: {basladi, job_id?, uretim_no?, mesaj?}` ya da düz `tur2_basladi: boolean` ile bildirir.
 * Alan yoksa (eski core) null: panel eski "Case'leri üret" düğmesini gösterir.
 */
export interface Tur2Bilgisi {
  basladi: boolean;
  job_id: string | null;
  uretim_no: number | null;
  mesaj: string | null;
}

export function tur2Uyarla(ham: unknown): Tur2Bilgisi | null {
  if (!ham || typeof ham !== "object") return null;
  const h = ham as Record<string, unknown>;
  const t = h.tur2 && typeof h.tur2 === "object" && !Array.isArray(h.tur2) ? (h.tur2 as Record<string, unknown>) : null;
  const engel = typeof h.tur2_engeli === "string" && h.tur2_engeli.trim() ? h.tur2_engeli : null;
  // D1 kesin sözleşme: `tur2_baslatildi: bool`, `tur2: {job_id, workflow_id, uretim_no, kip, asama} | null`,
  // `tur2_engeli: str | null`. Önceki taslak biçimler (`tur2.basladi`, `tur2_basladi`) de okunur.
  const bayrak =
    typeof h.tur2_baslatildi === "boolean" ? h.tur2_baslatildi : typeof h.tur2_basladi === "boolean" ? h.tur2_basladi : t && typeof t.basladi === "boolean" ? t.basladi : null;
  if (bayrak === null && !t && engel === null) return null;
  return {
    basladi: bayrak ?? !!t,
    job_id: t && typeof t.job_id === "string" ? t.job_id : null,
    uretim_no: t && typeof t.uretim_no === "number" ? t.uretim_no : null,
    mesaj: engel ?? (t && typeof t.mesaj === "string" ? t.mesaj : null),
  };
}

/** Onaydan sonra tur 2 başladıysa gösterilen bildirim. */
export function tur2Bildirimi(t: Tur2Bilgisi): string {
  return t.uretim_no !== null ? `Case üretimi otomatik başladı (üretim ${t.uretim_no}).` : "Case üretimi otomatik başladı.";
}

/**
 * REPLAY-MISS modeli yer tutucudur: kayıtlı model çıktısı yoktu, kabul kriterlerinden asgari bir
 * iskelet yazıldı. Gerçek bir tasarım modeli değildir; onaylanamaz (case üretiminin girdisi olamaz).
 */
export function yerTutucuModelMi(m: { uretim_modu: string | null } | null | undefined): boolean {
  return m?.uretim_modu === "replay_miss";
}

export const YER_TUTUCU_NEDENI =
  "Yer tutucu model (REPLAY-MISS): bu girdi için kayıtlı model çıktısı yok; kabul kriterlerinden kurulan iskelet onaylanamaz. Modeli canlı modelle yeniden üretin.";
