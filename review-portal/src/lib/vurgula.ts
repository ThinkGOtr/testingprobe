// Hafif TypeScript / Python sözdizimi renklendirme: belirteç listesi üretir (HTML üretmez; React metin
// düğümleriyle basılır, böylece kod içeriği asla HTML olarak yorumlanmaz).

export type BelirtecTuru = "anahtar" | "metin" | "yorum" | "sayi" | "tip" | "fonksiyon" | "duz";
export interface Belirtec {
  tur: BelirtecTuru;
  metin: string;
}

const ANAHTAR = new Set([
  "import", "from", "export", "const", "let", "var", "async", "await", "function", "return", "new", "if", "else",
  "for", "of", "in", "while", "class", "extends", "type", "interface", "as", "true", "false", "null", "undefined",
  "this", "try", "catch", "finally", "throw", "default", "readonly", "void",
]);

const DESEN =
  /(\/\/[^\n]*|\/\*[\s\S]*?\*\/)|("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_$][\w$]*)/g;

// Python: yorum `#`; `//` tam sayı bölmesidir (ör. campaign.py `adet // 6`), yorum değil.
const DESEN_PY =
  /(#[^\n]*)|("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][\w]*)/g;

const ANAHTAR_PY = new Set([
  "import", "from", "def", "return", "if", "elif", "else", "for", "in", "not", "and", "or", "is", "while", "class",
  "try", "except", "finally", "raise", "with", "as", "lambda", "None", "True", "False", "pass", "yield", "async", "await",
]);

export type Dil = "ts" | "py";

/** Dosya adından dil (bilinmiyorsa TypeScript). */
export function dilBul(dosya?: string | null): Dil {
  return dosya && /\.py$/i.test(dosya) ? "py" : "ts";
}

export function belirtecle(kod: string, dil: Dil = "ts"): Belirtec[] {
  const desen = dil === "py" ? DESEN_PY : DESEN;
  const anahtarlar = dil === "py" ? ANAHTAR_PY : ANAHTAR;
  const sonuc: Belirtec[] = [];
  let son = 0;
  const ekle = (tur: BelirtecTuru, metin: string) => {
    if (!metin) return;
    const onceki = sonuc[sonuc.length - 1];
    if (onceki && onceki.tur === tur && tur === "duz") onceki.metin += metin;
    else sonuc.push({ tur, metin });
  };
  for (const m of kod.matchAll(desen)) {
    const i = m.index ?? 0;
    ekle("duz", kod.slice(son, i));
    const [tam, yorum, metin, sayi, kelime] = m;
    if (yorum) ekle("yorum", yorum);
    else if (metin) ekle("metin", metin);
    else if (sayi) ekle("sayi", sayi);
    else if (kelime) {
      const sonraki = kod.slice(i + kelime.length).match(/^\s*\(/);
      if (anahtarlar.has(kelime)) ekle("anahtar", kelime);
      else if (/^[A-Z]/.test(kelime)) ekle("tip", kelime);
      else if (sonraki) ekle("fonksiyon", kelime);
      else ekle("duz", kelime);
    } else ekle("duz", tam);
    son = i + tam.length;
  }
  ekle("duz", kod.slice(son));
  return sonuc;
}

/** Belirteçleri satırlara böler (satır numaralı görünüm için). */
export function satirlaraBol(belirtecler: Belirtec[]): Belirtec[][] {
  const satirlar: Belirtec[][] = [[]];
  for (const b of belirtecler) {
    const parcalar = b.metin.split("\n");
    parcalar.forEach((p, i) => {
      if (i > 0) satirlar.push([]);
      if (p) satirlar[satirlar.length - 1].push({ tur: b.tur, metin: p });
    });
  }
  return satirlar;
}
