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

/** ASCII kolon adlarının sık sözcükleri → Türkçe (u2 N8: "sepet_tutari" → "sepet tutarı"); bilinmeyen sözcük aynen. */
const TR_SOZLUK: Record<string, string> = {
  tutari: "tutarı",
  kampanyali: "kampanyalı",
  uyarisi: "uyarısı",
  siparis: "sipariş",
  siparisi: "siparişi",
  fiyati: "fiyatı",
  sayisi: "sayısı",
  urun: "ürün",
  urunu: "ürünü",
  odeme: "ödeme",
  gun: "gün",
  sure: "süre",
  ucret: "ücret",
  ucreti: "ücreti",
  kisi: "kişi",
  musteri: "müşteri",
};
/** `sepet_tutari` → "sepet tutarı" (alt çizgi boşluk, bilinen sözcükler Türkçe karakterle). */
export const trAd = (x: string) =>
  x
    .trim()
    .split("_")
    .map((w) => TR_SOZLUK[w] ?? w)
    .join(" ");
const ad = trAd;

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
    .replace(/\s*\/\/\s*([A-Za-z0-9_.]+)/g, (_m, b: string) => ` ÷ ${sayi(b)} (tam kısım)`)
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

/** Çıktı kolonunun okunması için gereken tanım (ad, tür, açıklama). */
export interface OkunacakCikti {
  ad: string;
  tur?: string;
  aciklama?: string;
}

/** Bir işleçli, işlevsiz kısa ifade mi ("adet // 7", "ara_toplam * 2")? */
const basitMi = (e: string) => !/\w+\(/.test(e) && (e.match(/(\/\/|[-+*/%])/g) ?? []).length <= 1;

/** Açıklamadan iş cümlesi: baş harf küçük, parantezli ek atılır ("Bedava adetlerin tutarı (kampanya indirimi)" → "bedava adetlerin tutarı"). */
const aciklamaCumlesi = (a: string) => {
  const t = a.replace(/\s*\([^)]*\)\s*$/, "").trim();
  return t.charAt(0).toLocaleLowerCase("tr-TR") + t.slice(1);
};

/**
 * u2 N8: çıktının iş dili. Sabit değer → "bedava adet 0" / "uyarı görünmez"; tek ad → "toplam = ara toplam";
 * kısa ifade → "bedava adet = adet ÷ 7 (tam kısım)"; uzun ifade, açıklama varsa → "indirim = bedava adetlerin tutarı,
 * kuruşa yuvarlanır" (formül yerine anlam); açıklama yoksa formülün okunuşu.
 */
export function ciktiyiOku(c: OkunacakCikti, ifade: string): string {
  const e = ifade.trim();
  if (e === "dogru" || e === "yanlis") return c.tur === "mantiksal" || /uyari/.test(c.ad) ? mantiksalOku(c.ad, e) : `${ad(c.ad)}: ${deger(e)}`;
  if (/^-?\d+(\.\d+)?$/.test(e)) return `${ad(c.ad)} ${sayi(e)}`;
  if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(e)) return `${ad(c.ad)} = ${ad(e)}`;
  if (basitMi(e) || !c.aciklama) return `${ad(c.ad)} = ${ifadeyiOku(e)}`;
  const yuvarla = /yuvarla\([^()]*(?:\([^()]*\)[^()]*)*,\s*2\s*\)/.test(e) ? ", kuruşa yuvarlanır" : "";
  return `${ad(c.ad)} = ${aciklamaCumlesi(c.aciklama)}${yuvarla}`;
}

/** Satırın tek cümlesi: "Eğer adet 7 ya da daha fazla → bedava adet = adet ÷ 7 (tam kısım); indirim = bedava adetlerin tutarı, kuruşa yuvarlanır". */
export function satiriOku(kosul: string, cikti: Record<string, string>, sira: (string | OkunacakCikti)[]): string {
  const sonuclar = sira
    .map((c) => (typeof c === "string" ? { ad: c } : c))
    .filter((c) => cikti[c.ad] !== undefined)
    .map((c) => ciktiyiOku(c, cikti[c.ad]));
  const k = kosuluOku(kosul);
  return `${k === "diğer tüm durumlarda" ? "Diğer tüm durumlarda" : `Eğer ${k}`} → ${sonuclar.join("; ") || "çıktı yok"}`;
}

/** u2 N13: tablo hücresinde ifade, Türkçe sözcüklerle (dogru → doğru, yanlis → yanlış, degil → değil). */
export function ifadeGosterimi(e: string): string {
  return e.replace(/\bdogru\b/g, "doğru").replace(/\byanlis\b/g, "yanlış").replace(/\bdegil\b/g, "değil");
}

/** Mantıksal değer mi (`true`/`false`, `dogru`/`yanlis`)? */
export function mantiksalMi(d: unknown): d is boolean | "dogru" | "yanlis" | "true" | "false" {
  return d === true || d === false || d === "dogru" || d === "yanlis" || d === "true" || d === "false";
}

/**
 * u2 N18: mantıksal çıktının iş dili. `minimum_uyarisi` doğru → "uyarı görünür", yanlış → "uyarı görünmez";
 * tanınmayan adda "evet"/"hayır" yerine düz "doğru"/"yanlış" (anlam uydurulmaz).
 */
export function mantiksalOku(ad: string, d: unknown): string {
  const evet = d === true || d === "dogru" || d === "true";
  if (/uyari/.test(ad)) return evet ? "uyarı görünür" : "uyarı görünmez";
  if (/(^|_)(gorunur|aktif|pasif|var)$/.test(ad)) return `${ad.replace(/_/g, " ")}: ${evet ? "evet" : "hayır"}`;
  return evet ? "doğru" : "yanlış";
}

/** Alıntıyı Türkçe tırnakla sarar; zaten tırnakla başlıyor ya da bitiyorsa sarmaz (çift tırnak olmasın). */
export function alintiMetni(a: string): string {
  return /^["“”'‘’«]|["“”'‘’»]$/.test(a.trim()) ? a : `“${a}”`;
}
