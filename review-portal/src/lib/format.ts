// tr-TR biçimlendirme yardımcıları.

const tarihSaat = new Intl.DateTimeFormat("tr-TR", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});
const saatBicim = new Intl.DateTimeFormat("tr-TR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const para = new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const usd = new Intl.NumberFormat("tr-TR", { style: "currency", currency: "USD", maximumFractionDigits: 3 });

function gecerliTarih(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function tarih(iso: string | null | undefined): string {
  const d = gecerliTarih(iso);
  return d ? tarihSaat.format(d) : "—";
}

export function saat(iso: string | null | undefined): string {
  const d = gecerliTarih(iso);
  return d ? saatBicim.format(d) : "—";
}

/** 1250 → "1.250,00 TL" (DEMO-VERISI tutar biçimi). */
export function tl(tutar: number): string {
  return `${para.format(tutar)} TL`;
}

/**
 * Metindeki tutar alanlarını TL biçimine çevirir: "min_siparis_tutari = 750.00" →
 * "min_siparis_tutari = 750,00 TL". Yalnız adı "tutar" içeren anahtarın sayısal değeri değişir
 * (ham sorgu ve kod metnine uygulanmaz; yalnız gösterilen özet/bulgu cümlesi içindir).
 */
export function tutarlariBicimle(metin: string): string {
  return metin.replace(/(\b[\p{L}_]*tutar[\p{L}_]*\s*[=:]\s*)(\d+(?:[.,]\d{1,2})?)(?![\d.,]|\s*TL)/giu, (_t, anahtar: string, sayi: string) => {
    const n = Number(sayi.replace(",", "."));
    return Number.isFinite(n) ? `${anahtar}${tl(n)}` : `${anahtar}${sayi}`;
  });
}

export function dolar(tutar: number): string {
  return usd.format(tutar);
}

/** 0.734 → "%73" */
export function yuzde(oran: number, basamak = 0): string {
  if (!Number.isFinite(oran)) return "—";
  return `%${(oran * 100).toLocaleString("tr-TR", { maximumFractionDigits: basamak, minimumFractionDigits: basamak })}`;
}

/** ms → "1 dk 05 sn" / "6,8 sn" */
export function sure(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const sn = ms / 1000;
  if (sn < 60) return `${sn.toLocaleString("tr-TR", { maximumFractionDigits: 1 })} sn`;
  const dk = Math.floor(sn / 60);
  const kalan = Math.round(sn - dk * 60);
  if (dk < 60) return `${dk} dk ${String(kalan).padStart(2, "0")} sn`;
  const sa = Math.floor(dk / 60);
  return `${sa} sa ${String(dk - sa * 60).padStart(2, "0")} dk`;
}

export function kisaHash(h: string | null | undefined, n = 10): string {
  if (!h) return "—";
  const temiz = h.replace(/^sha256:/, "");
  return temiz.length > n ? `${temiz.slice(0, n)}…` : temiz;
}

/**
 * "2 gün önce" biçiminde göreli zaman (asistan cevap kartı, öneri kartı "yaptım dedi").
 * Tarih yoksa ya da geçersizse null; gelecekteki tarih "az önce" sayılır.
 */
export function goreliZaman(iso: string | null | undefined, simdi = Date.now()): string | null {
  const d = gecerliTarih(iso);
  if (!d) return null;
  const sn = Math.max(0, Math.floor((simdi - d.getTime()) / 1000));
  if (sn < 60) return "az önce";
  const dk = Math.floor(sn / 60);
  if (dk < 60) return `${dk} dk önce`;
  const sa = Math.floor(dk / 60);
  if (sa < 24) return `${sa} sa önce`;
  return `${Math.floor(sa / 24)} gün önce`;
}

/**
 * Yeni sekmede açılacak dış adres yalnız http(s) ise döner; `javascript:`, `data:` vb. null.
 * Sunucu adresleri zaten sınırlar; bu istemci tarafındaki derinlemesine savunmadır.
 */
export function guvenliDisAdres(adres: string | null | undefined): string | null {
  if (!adres) return null;
  const a = adres.trim();
  return /^https?:\/\//i.test(a) ? a : null;
}
