// Tutar biçimi her yerde tr-TR: "1.250,00 TL" (web: demo-app/web/src/format.ts).
// Intl'e güvenmeden elle biçimlenir: Hermes'in Intl desteği platforma/ICU verisine göre değişebilir;
// testler metni birebir karşılaştırdığı için çıktı her cihazda aynı olmalı.

export function formatTL(value: string | number): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return `${String(value)} TL`;
  const isaret = n < 0 ? "-" : "";
  const [tam, kesir] = Math.abs(n).toFixed(2).split(".");
  const gruplu = tam.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `${isaret}${gruplu},${kesir} TL`;
}

const AYLAR = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"];

/** tr-TR `dateStyle: "medium", timeStyle: "short"` karşılığı: "8 Kas 2026 14:05" (cihaz saat dilimi). */
export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const ss = String(d.getHours()).padStart(2, "0");
  const dd = String(d.getMinutes()).padStart(2, "0");
  return `${d.getDate()} ${AYLAR[d.getMonth()]} ${d.getFullYear()} ${ss}:${dd}`;
}
