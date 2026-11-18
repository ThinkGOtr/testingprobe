// Platform başına depo çipi (ANALIZ §7 Şerit T3).
//
// Proje uygulama platformları (Android, iOS, Windows) için ayrı GitHub deposu seçebilir. Çip yalnız
// varsayılan DIŞI depoda çizilir (`depo !== ''`): tek depolu projede ekran bugünküyle birebir aynı
// kalır. Rozet kategorik bilgidir: nötr hap (K4 renk disiplini).

/** Varsayılan dışı depoda gösterim adı (sahip/ad); varsayılan depoda ya da alan yoksa null. */
export function depoGosterimi(x: { depo?: string | null; depo_adi?: string | null } | null | undefined): string | null {
  const depo = (x?.depo ?? "").trim();
  if (!depo) return null;
  return (x?.depo_adi ?? "").trim() || depo;
}

export const DEPO_ACIKLAMASI = "Bu platformun ayrı test deposu (projenin varsayılan deposu değil).";

export function DepoCipi({ kaynak }: { kaynak: { depo?: string | null; depo_adi?: string | null } | null | undefined }) {
  const ad = depoGosterimi(kaynak);
  if (!ad) return null;
  return (
    <span className="cip cip-notr depo-cipi mono" data-testid="depo-cipi" title={DEPO_ACIKLAMASI}>
      <span className="gorunmez">Depo: </span>
      {ad}
    </span>
  );
}
