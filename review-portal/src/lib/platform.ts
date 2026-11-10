// 009 mobil-masaüstü: test platformu boyutu (web | android | ios | windows) için yardımcılar.
// Çekirdek sözleşmesi: specs/009-mobil-masaustu/plan.md §2.9 (POST /code/generate `platform`,
// script/SSE `platform`, `local-ci-<platform>` check'leri, triage `page_source` kanıtı).

export const PLATFORMLAR = ["web", "android", "ios", "windows"] as const;
export type Platform = (typeof PLATFORMLAR)[number];

/** Uygulama (Java + Appium) platformları; web Playwright + TypeScript'tir. */
export const UYGULAMA_PLATFORMLARI: readonly Platform[] = ["android", "ios", "windows"];

export const PLATFORM_ETIKETI: Record<Platform, string> = {
  web: "Web",
  android: "Android",
  ios: "iOS",
  windows: "Windows",
};

/** Seçicide platformun altında görünen kısa açıklama (ne üretileceği). */
export const PLATFORM_ACIKLAMASI: Record<Platform, string> = {
  web: "Tarayıcı · Playwright + TypeScript",
  android: "Emülatör · Appium + Java",
  ios: "Simülatör · Appium + Java",
  windows: "Masaüstü · Appium + Java",
};

const PLATFORM_KUMESI = new Set<string>(PLATFORMLAR);

export function platformMi(x: unknown): x is Platform {
  return typeof x === "string" && PLATFORM_KUMESI.has(x);
}

/** Ham değeri platforma çevirir (büyük/küçük harf ve boşluk duyarsız); tanınmazsa null (uydurulmaz). */
export function platformUyarla(x: unknown): Platform | null {
  if (typeof x !== "string") return null;
  const k = x.trim().toLowerCase();
  return platformMi(k) ? k : null;
}

export function uygulamaPlatformuMu(p: Platform | null | undefined): boolean {
  return !!p && p !== "web";
}

/** Ekran görüntüsü dikey mi (telefon): canlı görünüm çerçevesi uzun görüntüyü sığdırır. */
export function dikeyEkranMi(p: Platform | null | undefined): boolean {
  return p === "android" || p === "ios";
}

/**
 * Check adının dostu etiketi: `local-ci` → "Yerel CI · Web", `local-ci-android` → "Yerel CI · Android".
 * Tanınmayan ad (ör. GitHub `test-local`, `semgrep`) null döner: ham ad gösterilir.
 */
export function checkEtiketi(ad: string): string | null {
  if (ad === "local-ci") return `Yerel CI · ${PLATFORM_ETIKETI.web}`;
  const m = /^local-ci-([a-z]+)$/.exec(ad);
  const p = m ? platformUyarla(m[1]) : null;
  return p ? `Yerel CI · ${PLATFORM_ETIKETI[p]}` : null;
}

/** Check adından platform (`local-ci` = web, `local-ci-<platform>`); başka check'te null. */
export function checkPlatformu(ad: string): Platform | null {
  if (ad === "local-ci") return "web";
  const m = /^local-ci-([a-z]+)$/.exec(ad);
  return m ? platformUyarla(m[1]) : null;
}

/** Uygulama ajanı araçlarının (app-mcp) insan için Türkçe adları (009 §2.6). */
export const UYGULAMA_ARACI: Record<string, string> = {
  app_launch: "Uygulamayı başlat",
  app_snapshot: "Ekranı oku",
  app_click: "Dokun",
  app_type: "Yaz",
  app_select_option: "Seç",
  app_wait_for: "Bekle",
  app_generate_locator: "Locator üret",
  app_screenshot: "Ekran görüntüsü",
};

/** Ajan aracının görünen adı: bilinen `app_*` araçları Türkçe, diğerleri (browser_*) ham ad. */
export function aracEtiketi(arac: string): string {
  return UYGULAMA_ARACI[arac] ?? arac;
}

/** Süzgeç seçimi: "tumu" ya da bir platform. Adres çubuğunda `?platform=`. */
export type PlatformSecimi = Platform | "tumu";

export function platformSecimiOku(x: string | null | undefined): PlatformSecimi {
  return platformUyarla(x) ?? "tumu";
}

/**
 * Platform süzgeci. Seçim "tumu" ise liste aynen döner; bir platform seçiliyse yalnız o platformu
 * TAŞIYAN öğeler kalır — platformu bilinmeyen (null) öğe hiçbir platforma yazılmaz (uydurulmaz).
 */
export function platformaGoreSuz<T>(liste: readonly T[], secim: PlatformSecimi, al: (x: T) => Platform | null | undefined): T[] {
  if (secim === "tumu") return [...liste];
  return liste.filter((x) => al(x) === secim);
}
