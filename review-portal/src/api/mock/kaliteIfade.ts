// 012 Ş7 — mock arka uç için sınırlı ifade dili (ANALIZ §4.2).
//
// Gerçek uygulama core'dadır (`tp_core/features/karar_tablosu/ifade.py`); bu dosya yalnız örnek veri
// modunun "örnekle dene", doğrulama ve beklenen sonuç kontrolünü gerçeğe yakın çalıştırması içindir.
// `eval` yok: kendi ayrıştırıcısı var. Sayılar JS sayısıdır (core'da Decimal); sonuçlar 10 haneye
// yuvarlanır ki ikili kayan nokta artığı (0.1 + 0.2) örnek ekranda görünmesin.

export type IfadeDegeri = number | string | boolean;
export type IfadeTuru = "sayi" | "metin" | "mantiksal";

export class IfadeHatasi extends Error {
  readonly konum: number;
  constructor(mesaj: string, konum = 0) {
    super(mesaj);
    this.name = "IfadeHatasi";
    this.konum = konum;
  }
}

export const IFADE_EN_COK = 300;
const DERINLIK_EN_COK = 32;

type Belirtec =
  | { t: "sayi"; d: number; k: number }
  | { t: "metin"; d: string; k: number }
  | { t: "ad"; d: string; k: number }
  | { t: "islec"; d: string; k: number }
  | { t: "son"; k: number };

const ISLECLER = ["//", "==", "!=", "<=", ">=", "+", "-", "*", "/", "%", "<", ">", "(", ")", ","];
const AD_BASI = /[A-Za-z_ğüşıöçĞÜŞİÖÇ]/;
const AD_DEVAMI = /[A-Za-z0-9_ğüşıöçĞÜŞİÖÇ]/;

function belirtecler(metin: string): Belirtec[] {
  const cikti: Belirtec[] = [];
  let i = 0;
  while (i < metin.length) {
    const c = metin[i];
    if (/\s/.test(c)) {
      i++;
      continue;
    }
    if (/[0-9]/.test(c)) {
      const m = /^[0-9]+(\.[0-9]+)?/.exec(metin.slice(i))!;
      cikti.push({ t: "sayi", d: Number(m[0]), k: i });
      i += m[0].length;
      continue;
    }
    if (c === '"') {
      const son = metin.indexOf('"', i + 1);
      if (son < 0) throw new IfadeHatasi("kapanmamış metin", i);
      cikti.push({ t: "metin", d: metin.slice(i + 1, son), k: i });
      i = son + 1;
      continue;
    }
    if (AD_BASI.test(c)) {
      let j = i + 1;
      while (j < metin.length && AD_DEVAMI.test(metin[j])) j++;
      cikti.push({ t: "ad", d: metin.slice(i, j), k: i });
      i = j;
      continue;
    }
    const islec = ISLECLER.find((o) => metin.startsWith(o, i));
    if (!islec) throw new IfadeHatasi(`beklenmeyen karakter '${c}'`, i);
    cikti.push({ t: "islec", d: islec, k: i });
    i += islec.length;
  }
  cikti.push({ t: "son", k: metin.length });
  return cikti;
}

export type Dugum =
  | { tur: "sabit"; deger: IfadeDegeri; k: number }
  | { tur: "ad"; ad: string; k: number }
  | { tur: "tekli"; islec: "-" | "degil"; sag: Dugum; k: number }
  | { tur: "ikili"; islec: string; sol: Dugum; sag: Dugum; k: number }
  | { tur: "cagri"; ad: string; arglar: Dugum[]; k: number };

const ISLEVLER: Record<string, number> = { min: 2, max: 2, yuvarla: 2, taban: 1, tavan: 1, eger: 3 };
const AYRILMIS = new Set(["ve", "veya", "degil", "dogru", "yanlis", ...Object.keys(ISLEVLER)]);

/** Girdi/çıktı kolon adı olarak geçerli mi (ifade dilinde ad olarak yazılabilir, ayrılmış sözcük değil). */
export function adGecerli(ad: string): boolean {
  return /^[A-Za-z_ğüşıöçĞÜŞİÖÇ][A-Za-z0-9_ğüşıöçĞÜŞİÖÇ]*$/.test(ad) && !AYRILMIS.has(ad);
}

export function ayristir(metin: string): Dugum {
  if (metin.length > IFADE_EN_COK) throw new IfadeHatasi(`ifade en çok ${IFADE_EN_COK} karakter olabilir`, IFADE_EN_COK);
  if (!metin.trim()) throw new IfadeHatasi("ifade boş", 0);
  const b = belirtecler(metin);
  let i = 0;
  const bak = () => b[i];
  const islecMi = (d: string) => b[i].t === "islec" && (b[i] as { d: string }).d === d;
  const adMi = (d: string) => b[i].t === "ad" && (b[i] as { d: string }).d === d;
  const derin = (n: number, k: number) => {
    if (n > DERINLIK_EN_COK) throw new IfadeHatasi(`ifade çok derin (en çok ${DERINLIK_EN_COK} düzey)`, k);
  };

  function veya(n: number): Dugum {
    derin(n, bak().k);
    let sol = ve(n + 1);
    while (adMi("veya")) {
      const k = b[i++].k;
      sol = { tur: "ikili", islec: "veya", sol, sag: ve(n + 1), k };
    }
    return sol;
  }
  function ve(n: number): Dugum {
    let sol = degil(n + 1);
    while (adMi("ve")) {
      const k = b[i++].k;
      sol = { tur: "ikili", islec: "ve", sol, sag: degil(n + 1), k };
    }
    return sol;
  }
  function degil(n: number): Dugum {
    derin(n, bak().k);
    if (adMi("degil")) {
      const k = b[i++].k;
      return { tur: "tekli", islec: "degil", sag: degil(n + 1), k };
    }
    return karsilastirma(n + 1);
  }
  function karsilastirma(n: number): Dugum {
    const sol = toplama(n + 1);
    for (const o of ["==", "!=", "<=", ">=", "<", ">"]) {
      if (islecMi(o)) {
        const k = b[i++].k;
        return { tur: "ikili", islec: o, sol, sag: toplama(n + 1), k };
      }
    }
    return sol;
  }
  function toplama(n: number): Dugum {
    let sol = carpma(n + 1);
    while (islecMi("+") || islecMi("-")) {
      const t = b[i++] as { d: string; k: number };
      sol = { tur: "ikili", islec: t.d, sol, sag: carpma(n + 1), k: t.k };
    }
    return sol;
  }
  function carpma(n: number): Dugum {
    let sol = tekli(n + 1);
    while (islecMi("*") || islecMi("/") || islecMi("//") || islecMi("%")) {
      const t = b[i++] as { d: string; k: number };
      sol = { tur: "ikili", islec: t.d, sol, sag: tekli(n + 1), k: t.k };
    }
    return sol;
  }
  function tekli(n: number): Dugum {
    derin(n, bak().k);
    if (islecMi("-")) {
      const k = b[i++].k;
      return { tur: "tekli", islec: "-", sag: tekli(n + 1), k };
    }
    return birincil(n + 1);
  }
  function birincil(n: number): Dugum {
    const t = b[i];
    if (t.t === "sayi" || t.t === "metin") {
      i++;
      return { tur: "sabit", deger: t.d, k: t.k };
    }
    if (t.t === "ad") {
      i++;
      if (t.d === "dogru" || t.d === "yanlis") return { tur: "sabit", deger: t.d === "dogru", k: t.k };
      if (t.d in ISLEVLER) {
        if (!islecMi("(")) throw new IfadeHatasi(`'${t.d}' işlevinden sonra '(' bekleniyor`, bak().k);
        i++;
        const arglar: Dugum[] = [];
        if (!islecMi(")")) {
          arglar.push(veya(n + 1));
          while (islecMi(",")) {
            i++;
            arglar.push(veya(n + 1));
          }
        }
        if (!islecMi(")")) throw new IfadeHatasi("')' bekleniyor", bak().k);
        i++;
        if (arglar.length !== ISLEVLER[t.d]) throw new IfadeHatasi(`'${t.d}' ${ISLEVLER[t.d]} değer alır`, t.k);
        return { tur: "cagri", ad: t.d, arglar, k: t.k };
      }
      if (t.d === "ve" || t.d === "veya" || t.d === "degil") throw new IfadeHatasi(`beklenmeyen '${t.d}'`, t.k);
      return { tur: "ad", ad: t.d, k: t.k };
    }
    if (t.t === "islec" && t.d === "(") {
      i++;
      const ic = veya(n + 1);
      if (!islecMi(")")) throw new IfadeHatasi("')' bekleniyor", bak().k);
      i++;
      return ic;
    }
    throw new IfadeHatasi(t.t === "son" ? "ifade eksik" : `beklenmeyen '${(t as { d: string }).d}'`, t.k);
  }

  const kok = veya(0);
  if (b[i].t !== "son") throw new IfadeHatasi(`beklenmeyen '${(b[i] as { d: unknown }).d}'`, b[i].k);
  return kok;
}

const TUR_ADI: Record<IfadeTuru, string> = { sayi: "sayı", metin: "metin", mantiksal: "mantıksal" };
const turu = (d: IfadeDegeri): IfadeTuru => (typeof d === "number" ? "sayi" : typeof d === "string" ? "metin" : "mantiksal");

/** İfadenin sonuç türü (değer olmadan): bilinmeyen ad ve tür uyuşmazlığı burada yakalanır. */
export function turCikar(d: Dugum, adlar: Record<string, IfadeTuru>): IfadeTuru {
  const bekle = (x: Dugum, t: IfadeTuru, ne: string): void => {
    const g = turCikar(x, adlar);
    if (g !== t) throw new IfadeHatasi(`tür uyuşmazlığı: ${ne} ${TUR_ADI[t]} olmalı (${TUR_ADI[g]} verildi)`, x.k);
  };
  switch (d.tur) {
    case "sabit":
      return turu(d.deger);
    case "ad": {
      const t = adlar[d.ad];
      if (!t) throw new IfadeHatasi(`bilinmeyen ad '${d.ad}'`, d.k);
      return t;
    }
    case "tekli":
      bekle(d.sag, d.islec === "-" ? "sayi" : "mantiksal", d.islec === "-" ? "'-' işlenen" : "'degil' işlenen");
      return d.islec === "-" ? "sayi" : "mantiksal";
    case "ikili": {
      if (d.islec === "ve" || d.islec === "veya") {
        bekle(d.sol, "mantiksal", `'${d.islec}' sol tarafı`);
        bekle(d.sag, "mantiksal", `'${d.islec}' sağ tarafı`);
        return "mantiksal";
      }
      if (d.islec === "==" || d.islec === "!=") {
        const a = turCikar(d.sol, adlar);
        const b = turCikar(d.sag, adlar);
        if (a !== b) throw new IfadeHatasi(`tür uyuşmazlığı: ${TUR_ADI[a]} ile ${TUR_ADI[b]} karşılaştırılamaz`, d.k);
        return "mantiksal";
      }
      bekle(d.sol, "sayi", `'${d.islec}' sol tarafı`);
      bekle(d.sag, "sayi", `'${d.islec}' sağ tarafı`);
      return ["<", "<=", ">", ">="].includes(d.islec) ? "mantiksal" : "sayi";
    }
    case "cagri": {
      if (d.ad === "eger") {
        bekle(d.arglar[0], "mantiksal", "'eger' koşulu");
        const a = turCikar(d.arglar[1], adlar);
        const b = turCikar(d.arglar[2], adlar);
        if (a !== b) throw new IfadeHatasi(`tür uyuşmazlığı: 'eger' dalları aynı türde olmalı (${TUR_ADI[a]}, ${TUR_ADI[b]})`, d.k);
        return a;
      }
      d.arglar.forEach((a) => bekle(a, "sayi", `'${d.ad}' değeri`));
      return "sayi";
    }
  }
}

const temiz = (x: number) => Number(x.toFixed(10));

/** HALF_UP (sıfırdan uzağa) yuvarlama. */
export function yuvarla(x: number, hane: number): number {
  const c = 10 ** hane;
  const y = Math.round(Math.abs(x) * c + 1e-9) / c;
  return temiz(x < 0 ? -y : y);
}

export function hesapla(d: Dugum, ortam: Record<string, IfadeDegeri>): IfadeDegeri {
  const sayi = (x: Dugum): number => {
    const v = hesapla(x, ortam);
    if (typeof v !== "number") throw new IfadeHatasi(`tür uyuşmazlığı: sayı bekleniyor (${TUR_ADI[turu(v)]} verildi)`, x.k);
    return v;
  };
  const mantik = (x: Dugum): boolean => {
    const v = hesapla(x, ortam);
    if (typeof v !== "boolean") throw new IfadeHatasi(`tür uyuşmazlığı: mantıksal bekleniyor (${TUR_ADI[turu(v)]} verildi)`, x.k);
    return v;
  };
  switch (d.tur) {
    case "sabit":
      return d.deger;
    case "ad": {
      if (!(d.ad in ortam)) throw new IfadeHatasi(`bilinmeyen ad '${d.ad}'`, d.k);
      return ortam[d.ad];
    }
    case "tekli":
      return d.islec === "-" ? temiz(-sayi(d.sag)) : !mantik(d.sag);
    case "ikili": {
      if (d.islec === "ve") return mantik(d.sol) && mantik(d.sag);
      if (d.islec === "veya") return mantik(d.sol) || mantik(d.sag);
      if (d.islec === "==" || d.islec === "!=") {
        const a = hesapla(d.sol, ortam);
        const b = hesapla(d.sag, ortam);
        if (turu(a) !== turu(b)) throw new IfadeHatasi(`tür uyuşmazlığı: ${TUR_ADI[turu(a)]} ile ${TUR_ADI[turu(b)]} karşılaştırılamaz`, d.k);
        return d.islec === "==" ? a === b : a !== b;
      }
      const a = sayi(d.sol);
      const b = sayi(d.sag);
      switch (d.islec) {
        case "+":
          return temiz(a + b);
        case "-":
          return temiz(a - b);
        case "*":
          return temiz(a * b);
        case "<":
          return a < b;
        case "<=":
          return a <= b;
        case ">":
          return a > b;
        case ">=":
          return a >= b;
      }
      if (b === 0) throw new IfadeHatasi("sıfıra bölme", d.k);
      if (d.islec === "/") return temiz(a / b);
      if (d.islec === "//") return Math.floor(a / b);
      return temiz(a - b * Math.floor(a / b));
    }
    case "cagri": {
      if (d.ad === "eger") return mantik(d.arglar[0]) ? hesapla(d.arglar[1], ortam) : hesapla(d.arglar[2], ortam);
      const [a, b] = d.arglar.map(sayi);
      if (d.ad === "min") return Math.min(a, b);
      if (d.ad === "max") return Math.max(a, b);
      if (d.ad === "taban") return Math.floor(a);
      if (d.ad === "tavan") return Math.ceil(a);
      if (!Number.isInteger(b) || b < 0 || b > 10) throw new IfadeHatasi("'yuvarla' hanesi 0–10 arası tam sayı olmalı", d.k);
      return yuvarla(a, b);
    }
  }
}

/** "1.250,00 TL" → 1250; "−25,00 TL" → -25; "7" → 7; sayı değilse null. */
export function sayiAyristir(metin: string): number | null {
  let m = metin
    .trim()
    .replace(/[−–]/g, "-")
    .replace(/\s*(TL|₺|adet|%)\s*$/i, "")
    .replace(/\s/g, "");
  if (!/^-?[0-9][0-9.,]*$/.test(m)) return null;
  if (m.includes(",")) {
    if (!/^-?[0-9]{1,3}(\.[0-9]{3})*,[0-9]+$/.test(m) && !/^-?[0-9]+,[0-9]+$/.test(m)) return null;
    m = m.replace(/\./g, "").replace(",", ".");
  } else if (/^-?[0-9]{1,3}(\.[0-9]{3})+$/.test(m)) {
    m = m.replace(/\./g, "");
  } else if (!/^-?[0-9]+(\.[0-9]+)?$/.test(m)) {
    return null;
  }
  const n = Number(m);
  return Number.isFinite(n) ? n : null;
}

/** Değeri örneğin biçiminde yazar: (300, "150,00 TL") → "300,00 TL"; (14, "7") → "14". */
export function sayiBicimle(deger: number, ornek: string): string {
  const m = /^(\s*[−–-]?)([0-9][0-9.]*)(?:,([0-9]+))?(.*)$/.exec(ornek.trim());
  if (!m) return String(deger);
  const hane = m[3]?.length ?? 0;
  const binlik = /^[0-9]{1,3}(\.[0-9]{3})+$/.test(m[2]) || (hane > 0 && Math.abs(deger) >= 1000);
  const [tam, kesir] = yuvarla(Math.abs(deger), hane).toFixed(hane).split(".");
  const tamMetin = binlik ? tam.replace(/\B(?=(\d{3})+(?!\d))/g, ".") : tam;
  return `${deger < 0 ? "-" : ""}${tamMetin}${kesir ? `,${kesir}` : ""}${m[4]}`;
}

export function esitMi(a: IfadeDegeri, b: IfadeDegeri, tolerans = 0): boolean {
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) <= tolerans + 1e-9;
  return a === b;
}

/** Sayıyı yanıt gövdesinde core gibi (Decimal → metin) taşır: 25 → "25", 0.5 → "0.5". */
export function degerYaz(d: IfadeDegeri): string | boolean {
  return typeof d === "number" ? String(temiz(d)) : d;
}
