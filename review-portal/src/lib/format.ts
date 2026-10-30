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
