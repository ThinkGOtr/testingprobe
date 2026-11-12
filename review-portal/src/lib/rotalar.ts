// Uygulama içi rotalar (App.tsx ile aynı). Bağlantı bileşeni bir iç yolun gerçekten bir ekrana
// çıkıp çıkmadığını buradan bilir; fixtures.test.ts örnek verideki her iç bağlantıyı buna karşı
// doğrular ("Sayfa bulunamadı"ya giden ölü bağlantı kalmasın).
//
// `ROTA_DESENLERI` react-router desenleridir (`:id` tek yol parçası); asistan/öneri ekran bağlamı
// (`useEkranBaglami`, `matchPath`) ve core'un `rules/assistant/rotalar.json` listesi bununla
// aynıdır (rotalar.test.ts eşitliği denetler).
export const ROTA_DESENLERI: readonly string[] = [
  "/",
  "/giris",
  // AI Probe rol seçici (yalnız TP_AUTH_MODE=aiprobe|both; oturum öncesi ekran, asistan yok →
  // `rules/assistant/rotalar.json`'da değil, /giris gibi).
  "/rol-sec",
  "/gereksinimler",
  "/gereksinimler/:id",
  "/gereksinimler/:id/caseler",
  "/gereksinimler/:id/yayin",
  "/caseler",
  "/kod",
  "/kod/:id",
  "/kosular",
  "/kosular/:id",
  "/hatalar/:id",
  "/bug-taslaklari",
  "/bug-taslaklari/:id",
  "/kontrol-kulesi",
  "/yol-haritasi",
  "/denetim",
  "/claude-code",
  "/demo",
];

/** `/gereksinimler/:id` → `^/gereksinimler/[^/]+$` (parametre tek yol parçası). */
export function desenKalibi(desen: string): RegExp {
  const govde = desen
    .split("/")
    .map((p) => (p.startsWith(":") ? "[^/]+" : p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))
    .join("/");
  return new RegExp(`^${govde || "/"}$`);
}

const ROTA_KALIPLARI: RegExp[] = ROTA_DESENLERI.map(desenKalibi);

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
