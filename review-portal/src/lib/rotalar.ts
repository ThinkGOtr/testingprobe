// Uygulama içi rotalar (App.tsx ile aynı). Bağlantı bileşeni bir iç yolun gerçekten bir ekrana
// çıkıp çıkmadığını buradan bilir; fixtures.test.ts örnek verideki her iç bağlantıyı buna karşı
// doğrular ("Sayfa bulunamadı"ya giden ölü bağlantı kalmasın).
const ROTA_KALIPLARI: RegExp[] = [
  /^\/$/,
  /^\/giris$/,
  /^\/gereksinimler$/,
  /^\/gereksinimler\/[^/]+$/,
  /^\/gereksinimler\/[^/]+\/caseler$/,
  /^\/gereksinimler\/[^/]+\/yayin$/,
  /^\/kod$/,
  /^\/kod\/[^/]+$/,
  /^\/kosular$/,
  /^\/kosular\/[^/]+$/,
  /^\/hatalar\/[^/]+$/,
  /^\/bug-taslaklari$/,
  /^\/bug-taslaklari\/[^/]+$/,
  /^\/kontrol-kulesi$/,
  /^\/denetim$/,
  /^\/claude-code$/,
];

export function uygulamaRotasiMi(yol: string): boolean {
  const temiz = yol.split(/[?#]/)[0];
  return ROTA_KALIPLARI.some((k) => k.test(temiz));
}

export type BaglantiTuru = "dis" | "ic" | "metin";

/**
 * - `dis`: http(s) adresi veya core'un /api/ altındaki bir adresi, yeni sekmede açılır.
 * - `ic`: portal ekranı (react-router).
 * - `metin`: adres yok, sayfa içi çapa ya da portalın sunmadığı bir yol (ör. /artifacts, /forge):
 *   tıklanabilir gösterilmez — tıklayınca "Sayfa bulunamadı" açan bağlantı yerine düz metin.
 */
export function baglantiTuru(href: string | null | undefined): BaglantiTuru {
  if (!href) return "metin";
  if (/^https?:\/\//i.test(href)) return "dis";
  // /api/ altı nginx üzerinden core-api'ye gider (ör. core'un sunduğu artifact'lar): gerçek adres.
  if (href.startsWith("/api/")) return "dis";
  if (href.startsWith("/") && uygulamaRotasiMi(href)) return "ic";
  return "metin";
}
