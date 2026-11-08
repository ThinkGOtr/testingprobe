// Bağımlılıksız ekran yığını (web'deki router.ts karşılığı; URL yerine ekran nesnesi).
// Web yolu ↔ mobil ekran: /giris ↔ giriş (oturumsuz), /katalog ↔ katalog, /sepet ↔ sepet,
// /siparisler ↔ siparisler, /siparis/<numara> ↔ siparis.
export type Ekran =
  | { ad: "katalog" }
  | { ad: "sepet" }
  | { ad: "siparisler" }
  | { ad: "siparis"; numara: string };

export function ayniEkran(a: Ekran, b: Ekran): boolean {
  if (a.ad !== b.ad) return false;
  return a.ad !== "siparis" || a.numara === (b as { numara: string }).numara;
}
