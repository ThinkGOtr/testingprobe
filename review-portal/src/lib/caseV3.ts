// Case şeması v3 (011 §4.1–§4.2) yardımcıları: eski/yeni ayrımı, hazır olma kuralları ve
// sunucunun 422 hata listesinin ayrıştırılması. Saf işlevler: hem düzeltme formu hem örnek veri
// (mock) katmanı kullanır. Nihai doğrulama her zaman sunucudadır (`consistency_problems`).
import type { AcikSoru, CaseHazirlik, CaseUretimOzeti, TestCase, TestCaseIcerik, Varsayim } from "../api/types";
import { CASE_DURUMU, CASE_HAZIRLIK, SORU_SAHIBI } from "./etiketler";

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
    if (!soru.length) s.push('"Soru bekliyor" case en az bir açık soruya atıf yapmalı (ör. Q1).');
    if (beklenenDolu) s.push('"Soru bekliyor" case\'in beklenen sonucu boş olmalı (soru yanıtlanınca yazılır).');
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

// ---------------------------------------------------------------- D5: hazır olmayan case yönlendirmesi, toplu onay

/** Sayının okunuşundaki son sözcük: [son ünlü (4'lü uyum: i, ı, u, ü), ünlüyle bitiyor mu]. */
function sayiSesi(n: number): [string, boolean] {
  const birler: [string, boolean][] = [["ı", false], ["i", false], ["i", true], ["ü", false], ["ü", false], ["i", false], ["ı", true], ["i", true], ["i", false], ["u", false]];
  const onlar: [string, boolean][] = [["ı", false], ["u", false], ["i", true], ["u", false], ["ı", false], ["i", true], ["ı", false], ["i", false], ["i", false], ["ı", false]];
  const m = Math.abs(Math.trunc(n));
  if (m === 0) return birler[0];
  if (m % 10) return birler[m % 10];
  if (m % 100) return onlar[(m % 100) / 10];
  if (m % 1000) return ["ü", false]; // yüz
  if (m % 1_000_000) return ["i", false]; // bin
  return ["u", false]; // milyon
}

/**
 * Sayıya Türkçe hâl eki (kesme işaretiyle): belirtme "3'ü", "6'yı"; tamlayan "2'nin", "3'ün".
 * Ek okunuşa göre seçilir (2 → "iki" → 'yi / 'nin).
 */
export function sayiEki(n: number, hal: "belirtme" | "tamlayan"): string {
  const [unlu, unluyleBiter] = sayiSesi(n);
  if (hal === "belirtme") return `${n}'${unluyleBiter ? "y" : ""}${unlu}`;
  return `${n}'${unluyleBiter ? "n" : ""}${unlu}n`;
}

export interface HazirlikYonlendirmesi {
  /** soru: açık soru bekliyor; varsayim: yalnız varsayıma bağlı; tutarlilik: core onay engeli; genel: diğer. */
  tur: "soru" | "varsayim" | "tutarlilik" | "genel";
  metin: string;
  /** "Varsayım doğrulandı" ile doğrulanabilecek varsayımlar (yalnız `tur === "varsayim"`). */
  dogrulanacak: string[];
}

/**
 * UX-2: taslaktaki case neden onaylanamıyor ve ne yapmalı. Açık soru varsa önce o söylenir (varsayım
 * doğrulaması bu durumda sunulmaz); yalnız varsayım varsa "Varsayım doğrulandı" önerilir; core
 * tutarlılık engeli varsa onun metni. Onaylanabilir case'te ya da taslak olmayan case'te null.
 */
export function hazirlikYonlendirmesi(
  tc: Pick<TestCase, "durum" | "readiness" | "icerik" | "onay_engeli" | "acik_sorular" | "legacy" | "po_sorulari">,
): HazirlikYonlendirmesi | null {
  if (tc.durum !== "draft") return null;
  const eski = caseEski(tc);
  const sorular = eski ? [] : (tc.icerik.open_question_refs ?? []);
  const varsayimlar = eski ? [] : (tc.icerik.assumption_refs ?? []);
  if (sorular.length) {
    const ek = varsayimlar.length
      ? ` Case ayrıca ${varsayimlar.join(", ")} ${varsayimlar.length > 1 ? "varsayımlarına" : "varsayımına"} bağlı; yanıtla birlikte ${varsayimlar.length > 1 ? "onları" : "onu"} da doğrulayıp 'Düzelt' ile hazır yapın.`
      : "";
    // D6 (K16): soru PO'ya gönderildi mi / yanıtlandı mı — `po_sorulari` varsa metin duruma göre.
    const po = tc.po_sorulari;
    if (po && sorular.some((q) => po[q])) {
      const grup = (d: string) => sorular.filter((q) => (po[q]?.po_durumu ?? "gonderilmedi") === d);
      const parcalar: string[] = [];
      const yanitli = grup("yanitlandi");
      const gonderildi = grup("gonderildi");
      const gonderilmedi = grup("gonderilmedi");
      const etiket = (q: string) => (po[q]?.po_etiketi ? `${q} (${po[q]!.po_etiketi})` : q);
      if (yanitli.length) parcalar.push(`${yanitli.map(etiket).join(", ")} PO tarafından yanıtlandı; beklenen sonucu 'Düzelt' ile bu yanıta göre yazın ya da case'i yeniden üretin.`);
      if (gonderildi.length) parcalar.push(`${gonderildi.map(etiket).join(", ")} PO'ya gönderildi, yanıt bekleniyor; yanıt gelince 'Düzelt' ile beklenen sonucu yazın.`);
      if (gonderilmedi.length) parcalar.push(`${gonderilmedi.join(", ")} PO'nun yanıtını bekliyor ve henüz gönderilmedi; 'Açık soruları PO'ya gönder' ile gönderin, yanıt gelince 'Düzelt' ile beklenen sonucu yazın.`);
      return { tur: "soru", metin: parcalar.join(" ") + ek, dogrulanacak: [] };
    }
    const sahipler = [...new Set((tc.acik_sorular ?? []).filter((q) => sorular.includes(q.id)).map((q) => q.owner))];
    const bekleyen = sahipler.length === 0 || (sahipler.length === 1 && sahipler[0] === "PO") ? "PO'nun yanıtını bekliyor" : `yanıt bekliyor (sahibi: ${sahipler.map((x) => SORU_SAHIBI[x] ?? x).join(", ")})`;
    return { tur: "soru", metin: `${sorular.join(", ")} ${bekleyen}. Henüz gönderilmediyse 'Açık soruları PO'ya gönder' ile gönderin; yanıt gelince 'Düzelt' ile beklenen sonucu yazın.${ek}`, dogrulanacak: [] };
  }
  if (varsayimlar.length) {
    const cok = varsayimlar.length > 1;
    return {
      tur: "varsayim",
      metin: `${varsayimlar.join(", ")} ${cok ? "varsayımları" : "varsayımı"} doğrulanmadı. Doğruladıysanız '${cok ? "Varsayımlar doğrulandı" : "Varsayım doğrulandı"}' ile onaylayın; değilse 'Düzelt' ile beklenen sonucu güncelleyin ya da reddedin.`,
      dogrulanacak: varsayimlar,
    };
  }
  if (tc.onay_engeli) return { tur: "tutarlilik", metin: `${tc.onay_engeli}. 'Düzelt' ile giderin ya da reddedin.`, dogrulanacak: [] };
  const hazirlik = caseHazirlik(tc);
  if (hazirlik !== "ready") {
    return { tur: "genel", metin: `Hazır değil (${CASE_HAZIRLIK[hazirlik]?.etiket ?? hazirlik}): 'Düzelt' ile hazır yapın ya da reddedin.`, dogrulanacak: [] };
  }
  return null;
}

/**
 * K20 toplu onay: case seçilebilir mi. Yalnız taslak, hazır ve tutarlı (core `onay_engeli` null)
 * case seçilir; değilse görünür neden döner. Core alanı yoksa (eski core) içerikten türetilir.
 */
export function topluOnayEngeli(tc: Pick<TestCase, "durum" | "readiness" | "icerik" | "onay_engeli" | "uyarilar" | "legacy">): string | null {
  if (tc.durum !== "draft") return `Taslak değil (${CASE_DURUMU[tc.durum]?.etiket ?? tc.durum})`;
  const hazirlik = caseHazirlik(tc);
  if (hazirlik !== "ready") return `Hazır değil (${CASE_HAZIRLIK[hazirlik]?.etiket ?? hazirlik})`;
  if (tc.onay_engeli) return "Tutarlılık ihlali var";
  if (tc.onay_engeli === undefined && !caseEski(tc) && (tc.uyarilar?.length ?? 0) > 0) return "İçerik uyarısı var";
  return null;
}

/**
 * UX-6 "Hazır değil" süzgeci: güncel (reddedilmemiş, yerini yenisi almamış) case'in hazır olma durumu
 * "ready" değil ya da core onay engeli var. Durum şeridinin (A1) sayacıyla aynı kural.
 */
export function onayaHazirDegil(c: Pick<TestCase, "durum" | "readiness" | "icerik" | "onay_engeli">): boolean {
  if (c.durum === "rejected" || c.durum === "superseded") return false;
  return caseHazirlik(c) !== "ready" || !!c.onay_engeli;
}
