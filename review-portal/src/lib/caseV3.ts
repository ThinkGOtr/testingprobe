// Case şeması v3 (011 §4.1–§4.2) yardımcıları: eski/yeni ayrımı, hazır olma kuralları ve
// sunucunun 422 hata listesinin ayrıştırılması. Saf işlevler: hem düzeltme formu hem örnek veri
// (mock) katmanı kullanır. Nihai doğrulama her zaman sunucudadır (`consistency_problems`).
import type { AcikSoru, CaseHazirlik, CaseUretimOzeti, TestCase, TestCaseIcerik, Varsayim } from "../api/types";

/** Eski (v2) içerik: `readiness` anahtarı yok (K9). */
export const eskiIcerik = (i: TestCaseIcerik): boolean => i.readiness === undefined;

/** Case eski şemalı mı: core `legacy` bayrağı varsa o, yoksa içerikten. */
export const caseEski = (tc: Pick<TestCase, "legacy" | "icerik">): boolean => tc.legacy ?? eskiIcerik(tc.icerik);

/** Hazır olma durumu: core alanı > içerik > "ready" (eski case hazır sayılır, K9). */
export const caseHazirlik = (tc: Pick<TestCase, "readiness" | "icerik">): CaseHazirlik => tc.readiness ?? tc.icerik.readiness ?? "ready";

const dolu = (x: string | null | undefined) => !!x && x.trim() !== "";

/**
 * §4.2 kural 4–5 (hazır olma ↔ atıflar ↔ beklenenler; test verisi sentetik). Eski içerikte boş döner.
 * Form bunu göndermeden önce gösterir; sunucu aynı kuralı 422 ile uygular.
 */
export function hazirlikSorunlari(i: TestCaseIcerik): string[] {
  if (eskiIcerik(i)) return [];
  const s: string[] = [];
  const varsayim = i.assumption_refs ?? [];
  const soru = i.open_question_refs ?? [];
  const beklenenDolu = dolu(i.expected_result);
  const bosAdimlar = i.steps.filter((a) => !dolu(a.expected)).map((a) => a.id);
  if (i.readiness === "ready") {
    if (soru.length) s.push(`"Hazır" case açık soruya atıf yapamaz: açık soru atıflarını boşaltın (${soru.join(", ")}).`);
    if (varsayim.length) s.push(`"Hazır" case varsayıma atıf yapamaz: varsayım atıflarını boşaltın (${varsayim.join(", ")}).`);
    if (!beklenenDolu) s.push('"Hazır" case\'in beklenen sonucu dolu olmalı.');
    if (bosAdimlar.length) s.push(`"Hazır" case'te her adımın beklenen sonucu dolu olmalı (boş: ${bosAdimlar.join(", ")}).`);
  } else if (i.readiness === "assumption_dependent") {
    if (!varsayim.length) s.push('"Varsayıma bağlı" case en az bir varsayıma atıf yapmalı (ör. A1).');
    if (!beklenenDolu) s.push('"Varsayıma bağlı" case\'in beklenen sonucu dolu olmalı.');
    if (bosAdimlar.length) s.push(`"Varsayıma bağlı" case'te her adımın beklenen sonucu dolu olmalı (boş: ${bosAdimlar.join(", ")}).`);
  } else if (i.readiness === "blocked") {
    if (!soru.length) s.push('"Engelli" case en az bir açık soruya atıf yapmalı (ör. Q1).');
    if (beklenenDolu) s.push('"Engelli" case\'in beklenen sonucu boş olmalı (soru yanıtlanınca yazılır).');
  }
  for (const v of i.test_data ?? []) {
    if (!v.synthetic) s.push(`Test verisi "${v.name}" sentetik olmalı (gerçek veri kullanılmaz).`);
  }
  return s;
}

const TEKNIK_ONEKI: Record<string, string> = { EP: "EP-", BVA: "BV-", DT: "DT-", ST: "ST-", PW: "PW-", UC: "UC-", EG: "EG-" };

/**
 * §4.2 kural 1–6 (örnek veri katmanı için; core `consistency_problems` karşılığı). `ozet` yoksa
 * (üretim özeti kayıtlı değil) kapsam öğelerinin tanımlılığı denetlenmez; açık soru / varsayım
 * atıfları ise tanımsız sayılır (metni gösterilemeyen atıf kabul edilmez).
 */
export function tutarlilikSorunlari(i: TestCaseIcerik, ozet?: Pick<CaseUretimOzeti, "coverage_items" | "open_questions" | "assumptions"> | null): string[] {
  if (eskiIcerik(i)) return [];
  const s: string[] = [];
  const covers = i.covers ?? [];
  const teknikler = i.technique ?? [];
  if (ozet) {
    const ogeler = new Set(ozet.coverage_items.map((o) => o.id));
    for (const c of covers) if (!ogeler.has(c)) s.push(`Kapsam öğesi tanımlı değil: ${c}`);
  }
  const sorular = new Set((ozet?.open_questions ?? []).map((q) => q.id));
  for (const q of i.open_question_refs ?? []) if (!sorular.has(q)) s.push(`Açık soru tanımlı değil: ${q}`);
  const varsayimlar = new Set((ozet?.assumptions ?? []).map((a) => a.id));
  for (const a of i.assumption_refs ?? []) if (!varsayimlar.has(a)) s.push(`Varsayım tanımlı değil: ${a}`);
  for (const t of teknikler) {
    const onek = TEKNIK_ONEKI[t];
    if (onek && !covers.some((c) => c.startsWith(onek))) s.push(`Teknik ${t} için kapsam öğesi yok (${onek}… bekleniyor).`);
  }
  s.push(...hazirlikSorunlari(i));
  const digerMetin = [i.title, ...i.preconditions, ...i.steps.flatMap((a) => [a.action, a.data ?? "", a.expected]), i.expected_result, ...(i.teardown ?? [])].join("\n");
  for (const v of i.test_data ?? []) {
    if (v.is_attack_payload && dolu(v.value) && digerMetin.includes(v.value)) {
      s.push(`Güvenlik testi girdisi "${v.name}" değeri başka alanda geçemez; adımlarda verinin adıyla anılmalı.`);
    }
  }
  return s;
}

/**
 * Sunucu hata metnini listeye ayırır. core `InvalidCaseContent`: "mesaj — [\"hata 1\", \"hata 2\"]";
 * FastAPI doğrulama listesi `http.detayOku`'da "; " ile birleşir. Tek maddelik hata tek öğe döner.
 */
export function hataListesi(metin: string | null | undefined): { baslik: string; maddeler: string[] } {
  const m = (metin ?? "").trim();
  if (!m) return { baslik: "", maddeler: [] };
  const ayrac = m.indexOf(" — ");
  if (ayrac > 0) {
    const kuyruk = m.slice(ayrac + 3).trim();
    try {
      const j = JSON.parse(kuyruk) as unknown;
      if (Array.isArray(j)) return { baslik: m.slice(0, ayrac), maddeler: j.map((x) => (typeof x === "string" ? x : JSON.stringify(x))) };
      if (j && typeof j === "object") {
        return { baslik: m.slice(0, ayrac), maddeler: Object.entries(j).map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`) };
      }
    } catch {
      /* JSON değil: düz metin olarak ele alınır */
    }
  }
  const parcalar = m.split("; ").map((x) => x.trim()).filter(Boolean);
  return parcalar.length > 1 ? { baslik: "", maddeler: parcalar } : { baslik: m, maddeler: [] };
}

/** Atıf listesi (ör. ["Q1"]) → çözülmüş kayıtlar; metni gelmeyen atıf yalnız kimliğiyle döner. */
export function atiflariCoz<T extends AcikSoru | Varsayim>(refler: string[] | undefined, cozulmus: T[] | undefined): (T | { id: string })[] {
  const harita = new Map((cozulmus ?? []).map((x) => [x.id, x]));
  const idler = refler && refler.length ? refler : [...harita.keys()];
  return idler.map((id) => harita.get(id) ?? { id });
}

/** Virgül/boşlukla ayrılmış kimlik metni → tekilleştirilmiş liste (ör. "ep-v1, BV-3"). */
export const kimlikListesi = (m: string): string[] => [
  ...new Set(
    m
      .split(/[,\s]+/)
      .map((x) => x.trim())
      .filter(Boolean),
  ),
];
