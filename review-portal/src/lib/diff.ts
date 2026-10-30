// Kelime düzeyinde fark (LCS). Önerilen doküman metni ↔ mevcut metin için.

export type FarkParcasi = { tur: "ayni" | "eklendi" | "silindi"; metin: string };

function parcala(s: string): string[] {
  // Boşlukları ayrı belirteç olarak tut, böylece birleştirince metin aynen geri gelir.
  return s.match(/\s+|[^\s]+/g) ?? [];
}

export function kelimeFarki(eski: string, yeni: string): FarkParcasi[] {
  const a = parcala(eski);
  const b = parcala(yeni);
  const n = a.length;
  const m = b.length;
  // LCS tablosu (demo metinleri kısa: birkaç yüz belirteç)
  const tablo: Uint16Array[] = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      tablo[i][j] = a[i] === b[j] ? tablo[i + 1][j + 1] + 1 : Math.max(tablo[i + 1][j], tablo[i][j + 1]);
    }
  }
  const sonuc: FarkParcasi[] = [];
  const ekle = (tur: FarkParcasi["tur"], metin: string) => {
    const son = sonuc[sonuc.length - 1];
    if (son && son.tur === tur) son.metin += metin;
    else sonuc.push({ tur, metin });
  };
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      ekle("ayni", a[i]);
      i++;
      j++;
    } else if (tablo[i + 1][j] >= tablo[i][j + 1]) {
      ekle("silindi", a[i++]);
    } else {
      ekle("eklendi", b[j++]);
    }
  }
  while (i < n) ekle("silindi", a[i++]);
  while (j < m) ekle("eklendi", b[j++]);
  return sonuc;
}

/** Normalize edilmiş Levenshtein mesafesi (0 = aynı, 1 = tamamen farklı). §12 "küçük düzeltme". */
export function duzeltmeOlcusu(eski: string, yeni: string): number {
  const a = eski.trim().replace(/\s+/g, " ").toLocaleLowerCase("tr-TR");
  const b = yeni.trim().replace(/\s+/g, " ").toLocaleLowerCase("tr-TR");
  if (a === b) return 0;
  const uzun = Math.max(a.length, b.length);
  if (uzun === 0) return 0;
  let onceki = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const simdiki = [i];
    for (let j = 1; j <= b.length; j++) {
      simdiki[j] = Math.min(onceki[j] + 1, simdiki[j - 1] + 1, onceki[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    onceki = simdiki;
  }
  return onceki[b.length] / uzun;
}
