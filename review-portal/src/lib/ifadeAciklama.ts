// 012 review turu 1 (analist/PO 5): karar tablosu satırının düz Türkçe karşılığı. PO ifade dilini değil
// iş kuralını onaylar: "adet >= 7" → "adet 7 ya da daha fazla". Çeviri sözcük düzeyindedir (ayrıştırıcı
// değil); tanınmayan parça olduğu gibi kalır — anlam uydurulmaz.

const KARSILASTIRMA: Record<string, string> = {
  ">=": "ya da daha fazla",
  "<=": "ya da daha az",
  ">": "'den fazla",
  "<": "'den az",
  "==": "",
  "!=": "değil",
};

/** `sepet_tutari` → "sepet tutarı" değil, "sepet tutari": adlar okunur kalsın diye yalnız alt çizgi boşluk olur. */
const ad = (x: string) => x.replace(/_/g, " ");

/** "750" → "750", "25.5" → "25,5" (ondalık virgül). */
const sayi = (x: string) => x.replace(".", ",");

function deger(x: string): string {
  const t = x.trim();
  if (t === "dogru") return "doğru";
  if (t === "yanlis") return "yanlış";
  if (/^-?\d+(\.\d+)?$/.test(t)) return sayi(t);
  if (/^"[^"]*"$/.test(t)) return t;
  return ifadeyiOku(t);
}

/** Tek karşılaştırma: `adet >= 7` → "adet 7 ya da daha fazla"; `sepet_tutari < 750` → "sepet tutari 750'den az". */
function karsilastirmaOku(sol: string, op: string, sag: string): string {
  const s = deger(sag);
  if (op === "==") return `${ad(sol.trim())} = ${s}`;
  if (op === "!=") return `${ad(sol.trim())} ${s} değil`;
  if (op === ">" || op === "<") return `${ad(sol.trim())} ${s}${KARSILASTIRMA[op]}`;
  return `${ad(sol.trim())} ${s} ${KARSILASTIRMA[op]}`;
}

/** Aritmetik ifade: `adet // 7` → "adet ÷ 7 (tam kısım)"; `x * y` → "x × y". */
export function ifadeyiOku(ifade: string): string {
  return ifade
    .replace(/\s*\/\/\s*(\S+)/g, (_m, b: string) => ` ÷ ${sayi(b)} (tam kısım)`)
    .replace(/\s*\*\s*/g, " × ")
    .replace(/(?<![<>=!])\s*\/\s*/g, " ÷ ")
    .replace(/\byuvarla\(/g, "yuvarla(")
    .replace(/\btaban\(/g, "aşağı yuvarla(")
    .replace(/\btavan\(/g, "yukarı yuvarla(")
    .replace(/\b([a-zçğıöşü]+(?:_[a-zçğıöşü0-9]+)+)\b/g, (m) => ad(m))
    .replace(/\b(\d+)\.(\d+)\b/g, "$1,$2")
    .replace(/\bdogru\b/g, "doğru")
    .replace(/\byanlis\b/g, "yanlış");
}

/** Koşulun düz Türkçesi. `dogru` → "diğer tüm durumlarda". */
export function kosuluOku(kosul: string): string {
  const k = kosul.trim();
  if (!k) return "—";
  if (k === "dogru") return "diğer tüm durumlarda";
  const parcalar = k.split(/\s+(ve|veya)\s+/);
  return parcalar
    .map((p) => {
      if (p === "ve") return "ve";
      if (p === "veya") return "ya da";
      const degil = /^degil\s+(.+)$/.exec(p);
      if (degil) return `${ad(degil[1])} değilse`;
      const m = /^(.+?)\s*(>=|<=|==|!=|>|<)\s*(.+)$/.exec(p);
      if (m) return karsilastirmaOku(m[1], m[2], m[3]);
      // Yalın mantıksal girdi: `kampanyali_sepet` → "kampanyali sepet ise".
      if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(p)) return `${ad(p)} ise`;
      return ifadeyiOku(p);
    })
    .join(" ");
}

/** Satırın tek cümlesi: "adet 7 ya da daha fazla → bedava adet: adet ÷ 7 (tam kısım); indirim: …". */
export function satiriOku(kosul: string, cikti: Record<string, string>, sira: string[]): string {
  const sonuclar = sira.filter((c) => cikti[c] !== undefined).map((c) => `${ad(c)}: ${deger(cikti[c])}`);
  const k = kosuluOku(kosul);
  return `${k === "diğer tüm durumlarda" ? "Diğer tüm durumlarda" : `Eğer ${k}`} → ${sonuclar.join("; ") || "çıktı yok"}`;
}
