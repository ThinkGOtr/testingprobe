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

/**
 * 011: dil ayrı seçildiğinde platformun yalnız ortam/araç açıklaması (dil adı yok: "Playwright +
 * TypeScript" Java seçiliyken yanlış olurdu). Dil seçici yokken (011 öncesi core) `PLATFORM_ACIKLAMASI` kalır.
 */
export const PLATFORM_ORTAMI: Record<Platform, string> = {
  web: "Tarayıcı · Playwright",
  android: "Emülatör · Appium",
  ios: "Simülatör · Appium",
  windows: "Masaüstü · Appium",
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
 * Yerel CI check adları (011 K-T1; core `platform.check_adi(platform, dil)` ile aynı): web + TypeScript
 * `local-ci`, web + Java `local-ci-web-java` (GitHub karşılığı `web-java`), uygulama
 * `local-ci-<android|ios|windows>`. `web-java` bir platform DEĞİLDİR: ad tam eşleşmeyle tanınır.
 */
const WEB_CHECKLERI: Record<string, string> = {
  "local-ci": `Yerel CI · ${PLATFORM_ETIKETI.web}`,
  "local-ci-web-java": `Yerel CI · ${PLATFORM_ETIKETI.web} · Java`,
};

/** `local-ci-<uygulama platformu>` (web soneki yok: web'in adları yukarıda tam eşleşmeyle). */
function uygulamaCheckPlatformu(ad: string): Platform | null {
  const m = /^local-ci-([a-z]+)$/.exec(ad);
  const p = m ? platformUyarla(m[1]) : null;
  return p && p !== "web" ? p : null;
}

/**
 * Check adının dostu etiketi: `local-ci` → "Yerel CI · Web", `local-ci-web-java` → "Yerel CI · Web · Java",
 * `local-ci-android` → "Yerel CI · Android". Tanınmayan ad (ör. GitHub `test-local`, `semgrep`) null
 * döner: ham ad gösterilir.
 */
export function checkEtiketi(ad: string): string | null {
  if (ad in WEB_CHECKLERI) return WEB_CHECKLERI[ad];
  const p = uygulamaCheckPlatformu(ad);
  return p ? `Yerel CI · ${PLATFORM_ETIKETI[p]}` : null;
}

/** Check adından platform (`local-ci` ve `local-ci-web-java` = web, `local-ci-<platform>`); başka check'te null. */
export function checkPlatformu(ad: string): Platform | null {
  if (ad in WEB_CHECKLERI) return "web";
  return uygulamaCheckPlatformu(ad);
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

/** Playwright MCP tarayıcı araçlarının (`browser_*`) okunur adları (Script › Ajan adımları). */
export const TARAYICI_ARACI: Record<string, string> = {
  browser_navigate: "Sayfaya git",
  browser_navigate_back: "Geri git",
  browser_snapshot: "Sayfayı oku",
  browser_click: "Tıkla",
  browser_type: "Yaz",
  browser_fill_form: "Formu doldur",
  browser_select_option: "Seç",
  browser_press_key: "Tuşa bas",
  browser_hover: "Üzerine gel",
  browser_drag: "Sürükle",
  browser_drop: "Bırak",
  browser_file_upload: "Dosya yükle",
  browser_handle_dialog: "İletişim kutusunu yanıtla",
  browser_wait_for: "Bekle",
  browser_generate_locator: "Locator üret",
  browser_find: "Öğe bul",
  browser_take_screenshot: "Ekran görüntüsü",
  browser_evaluate: "Sayfada betik çalıştır",
  browser_run_code: "Kod çalıştır",
  browser_run_code_unsafe: "Kod çalıştır",
  browser_verify_element_visible: "Öğe görünür mü doğrula",
  browser_verify_text_visible: "Metin görünür mü doğrula",
  browser_verify_list_visible: "Liste görünür mü doğrula",
  browser_verify_value: "Değeri doğrula",
  browser_console_messages: "Konsol iletilerini oku",
  browser_network_requests: "Ağ isteklerini oku",
  browser_network_request: "Ağ isteğini oku",
  browser_tabs: "Sekmeler",
  browser_resize: "Pencereyi boyutlandır",
  browser_emulate_media: "Ortam öykünmesi",
  browser_pdf_save: "PDF kaydet",
  browser_close: "Tarayıcıyı kapat",
  browser_install: "Tarayıcıyı kur",
};

/**
 * Ajan aracının görünen adı: bilinen `app_*` / `browser_*` araçları Türkçe; tanınmayan araç ham ad yerine
 * genel bir etiketle gösterilir (ham ad çağıranın ipucunda, `title`).
 */
export function aracEtiketi(arac: string): string {
  const ad = UYGULAMA_ARACI[arac] ?? TARAYICI_ARACI[arac];
  if (ad) return ad;
  if (arac.startsWith("browser_")) return "Tarayıcı işlemi";
  if (arac.startsWith("app_")) return "Uygulama işlemi";
  return arac;
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
