// Story açıklaması (core `parse_description` çıktısı) → görüntülenecek bloklar.
//
// Çekirdek açıklamayı düz metin verir: bloklar boş satırla ayrılır, ardışık maddeler tek satır
// sonuyla gelir ("- x" madde, "1. x" numaralı madde), şablon bölüm başlıkları kendi satırındadır
// ("🎯 Objective (Amaç)"). AC'ler açıklamada yoktur (ayrı alan); şablonlu story'de Jira'daki gibi
// QA Checklist'ten önce gösterilsinler diye AC bölümünün yeri işaretlenir.

export type DokumanBlogu =
  | { tur: "baslik"; metin: string }
  | { tur: "paragraf"; satirlar: string[] }
  | { tur: "liste"; numarali: boolean; maddeler: string[] }
  | { tur: "ac" };

// core/src/tp_core/integrations/jira_adf.py TEMPLATE_SECTIONS ile aynı adlar.
const BOLUM_ADLARI: Record<string, string[]> = {
  objective: ["objective", "amaç"],
  scope: ["scope", "kapsam"],
  user_flow: ["user flow", "kullanıcı akışı"],
  dependencies: ["dependencies & integration", "dependencies", "bağımlılıklar & entegrasyon"],
  other: ["other information & assets", "other information", "diğer bilgiler & kaynaklar"],
  acceptance_criteria: ["acceptance criteria", "kabul kriterleri"],
  qa_checklist: ["qa checklist", "qa kontrol listesi"],
};
const AC_SONRASI = new Set(["qa_checklist"]);
const ON_EK = /^(?::[a-z0-9_+-]+:|[^A-Za-zÇĞİÖŞÜçğıöşü])*/;
const MADDE = /^\s*[-*•]\s+(.*)$/;
const NUMARALI = /^\s*\d{1,9}[.)]\s+(.*)$/;

function adAnahtarlari(ad: string): string[] {
  const sade = (s: string) =>
    s
      .split(/\s+/)
      .filter(Boolean)
      .map((w) => (w === "and" || w === "ve" ? "&" : w))
      .join(" ");
  return [sade(ad.toLowerCase()), sade(ad.replace(/I/g, "ı").replace(/İ/g, "i").toLowerCase())];
}

/** Satır bir şablon bölüm başlığıysa bölüm anahtarı. */
export function sablonBolumu(satir: string): string | null {
  if (satir.includes("\n") || satir.length > 120) return null;
  const ad = satir
    .trim()
    .replace(ON_EK, "")
    .replace(/\s*\([^)]*\)\s*:?\s*$/, "")
    .replace(/\s*:\s*$/, "");
  if (!ad) return null;
  const adaylar = adAnahtarlari(ad);
  for (const [anahtar, adlar] of Object.entries(BOLUM_ADLARI)) {
    if (adlar.some((a) => adaylar.includes(adAnahtarlari(a)[0]))) return anahtar;
  }
  return null;
}

/** Açıklamayı bloklara ayırır. Şablonda (en az iki bölüm başlığı) AC yeri `{tur: "ac"}` olur. */
export function dokumanBloklari(metin: string): { bloklar: DokumanBlogu[]; sablon: boolean } {
  const bloklar: DokumanBlogu[] = [];
  const bolumler = new Set<string>();
  for (const parca of metin.replace(/\r\n/g, "\n").split(/\n\s*\n/)) {
    const satirlar = parca.split("\n").filter((s) => s.trim());
    if (!satirlar.length) continue;
    const bolum = satirlar.length === 1 ? sablonBolumu(satirlar[0]) : null;
    if (bolum) {
      bolumler.add(bolum);
      bloklar.push({ tur: "baslik", metin: satirlar[0].trim() });
      continue;
    }
    const madde = satirlar.every((s) => MADDE.test(s));
    const numarali = !madde && satirlar.every((s) => NUMARALI.test(s));
    if (madde || numarali) {
      const re = madde ? MADDE : NUMARALI;
      bloklar.push({ tur: "liste", numarali, maddeler: satirlar.map((s) => s.replace(re, "$1").trim()) });
    } else {
      bloklar.push({ tur: "paragraf", satirlar });
    }
  }
  const sablon = bolumler.size >= 2;
  if (sablon) {
    const i = bloklar.findIndex((b) => b.tur === "baslik" && AC_SONRASI.has(sablonBolumu(b.metin) ?? ""));
    bloklar.splice(i === -1 ? bloklar.length : i, 0, { tur: "ac" });
  }
  return { bloklar, sablon };
}
