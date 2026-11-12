// Hafif TypeScript / Python / Java / C# sözdizimi renklendirme: belirteç listesi üretir (HTML üretmez; React metin
// düğümleriyle basılır, böylece kod içeriği asla HTML olarak yorumlanmaz).

/** `ek`: Java `@Annotation`, C# `[Attribute]`, Python `@decorator`. */
export type BelirtecTuru = "anahtar" | "metin" | "yorum" | "sayi" | "tip" | "fonksiyon" | "ek" | "duz";
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
  /(#[^\n]*)|("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][\w]*)|((?<=^[ \t]*)@[A-Za-z_][\w.]*)/gm;

const ANAHTAR_PY = new Set([
  "import", "from", "def", "return", "if", "elif", "else", "for", "in", "not", "and", "or", "is", "while", "class",
  "try", "except", "finally", "raise", "with", "as", "lambda", "None", "True", "False", "pass", "yield", "async", "await",
]);

// Java: `//` ve `/* */` yorum, `"…"` / `"""…"""` (metin bloğu) / `'c'`, `@Annotation`.
const DESEN_JAVA =
  /(\/\/[^\n]*|\/\*[\s\S]*?\*\/)|("""[\s\S]*?"""|"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')|(\b\d+(?:\.\d+)?[LlFfDd]?\b)|([A-Za-z_$][\w$]*)|(@[A-Za-z_][\w.]*)/g;

const ANAHTAR_JAVA = new Set([
  "package", "import", "public", "private", "protected", "static", "final", "abstract", "class", "interface", "enum",
  "record", "extends", "implements", "new", "return", "if", "else", "for", "while", "do", "switch", "case", "default",
  "break", "continue", "try", "catch", "finally", "throw", "throws", "this", "super", "void", "int", "long", "double",
  "float", "boolean", "char", "byte", "short", "var", "true", "false", "null", "instanceof", "synchronized",
]);

// C#: `//`, `/* */`; `"…"`, `@"…"` (kaçışsız), `$"…"`, `'c'`; satır başındaki `[Attribute]` / `[Attribute(...)]`.
const DESEN_CS =
  /(\/\/[^\n]*|\/\*[\s\S]*?\*\/)|(\$?@"(?:[^"]|"")*"|@?\$?"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')|(\b\d+(?:\.\d+)?[mMfFdDlLuU]?\b)|([A-Za-z_][\w]*)|((?<=^[ \t]*)\[[A-Za-z_][\w.]*(?:\([^\]\n]*\))?(?:\s*,\s*[A-Za-z_][\w.]*(?:\([^\]\n]*\))?)*\])/gm;

const ANAHTAR_CS = new Set([
  "using", "namespace", "public", "private", "protected", "internal", "static", "readonly", "const", "sealed", "abstract",
  "virtual", "override", "partial", "class", "interface", "struct", "enum", "record", "new", "return", "if", "else",
  "for", "foreach", "in", "while", "do", "switch", "case", "default", "break", "continue", "try", "catch", "finally",
  "throw", "this", "base", "void", "int", "long", "double", "float", "decimal", "bool", "char", "string", "object",
  "var", "true", "false", "null", "async", "await", "is", "as", "get", "set",
]);

/** Renklendirilen sözdizimleri (üretim dili `python` burada `py`dir; bkz. `vurguDili`). */
export type VurguDili = "ts" | "py" | "java" | "csharp";

const SOZDIZIMI: Record<VurguDili, { desen: RegExp; anahtarlar: Set<string> }> = {
  ts: { desen: DESEN, anahtarlar: ANAHTAR },
  py: { desen: DESEN_PY, anahtarlar: ANAHTAR_PY },
  java: { desen: DESEN_JAVA, anahtarlar: ANAHTAR_JAVA },
  csharp: { desen: DESEN_CS, anahtarlar: ANAHTAR_CS },
};

/** Dosya uzantısından sözdizimi: `.java`, `.cs`, `.py`, `.ts` (bilinmiyorsa TypeScript). */
export function dilBul(dosya?: string | null): VurguDili {
  if (!dosya) return "ts";
  if (/\.java$/i.test(dosya)) return "java";
  if (/\.cs$/i.test(dosya)) return "csharp";
  if (/\.py$/i.test(dosya)) return "py";
  return "ts";
}

/** Üretim dilinden (ts | java | csharp | python) sözdizimi; bilinmiyorsa null (çağıran dosya adına düşer). */
export function vurguDili(dil: string | null | undefined): VurguDili | null {
  if (dil === "python" || dil === "py") return "py";
  return dil === "ts" || dil === "java" || dil === "csharp" ? dil : null;
}

export function belirtecle(kod: string, dil: VurguDili = "ts"): Belirtec[] {
  const { desen, anahtarlar } = SOZDIZIMI[dil];
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
    const [tam, yorum, metin, sayi, kelime, ek] = m;
    if (yorum) ekle("yorum", yorum);
    else if (metin) ekle("metin", metin);
    else if (sayi) ekle("sayi", sayi);
    else if (ek) ekle("ek", ek);
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
