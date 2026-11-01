/** YYYYMMDD-HHMMSS, süreç saat diliminde (demo-prova.sh `date +%Y%m%d-%H%M%S` ile aynı). */
export function yerelZaman(d: Date): string {
  const iki = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}${iki(d.getMonth() + 1)}${iki(d.getDate())}-` +
    `${iki(d.getHours())}${iki(d.getMinutes())}${iki(d.getSeconds())}`
  );
}

/** Metindeki tüm sır değerlerini (her geçişi) maskeler; boş değerler yok sayılır. */
export function maskele(metin: string, sirlar: readonly string[]): string {
  let m = metin;
  for (const s of [...sirlar].filter((x) => x.length > 0).sort((a, b) => b.length - a.length)) {
    m = m.split(s).join("***");
  }
  return m;
}
