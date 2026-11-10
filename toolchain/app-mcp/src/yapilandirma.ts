/**
 * Ortamdan yapılandırma. Ajan uygulama kimliğini SEÇEMEZ: `app_launch` yalnızca platform alır,
 * uygulama (paket / bundle / yol) burada sabittir.
 *
 *   APPIUM_URL_ANDROID | APPIUM_URL_IOS | APPIUM_URL_WINDOWS   platform başına Appium adresi
 *                                                              (boş = platform kapalı)
 *   APP_ANDROID_PACKAGE (zorunlu), APP_ANDROID_ACTIVITY, APP_ANDROID_APK, APP_ANDROID_UDID
 *   APP_IOS_BUNDLE_ID (zorunlu), APP_IOS_APP, APP_IOS_UDID, APP_IOS_DEVICE_NAME,
 *   APP_IOS_PLATFORM_VERSION
 *   APP_WINDOWS_APP (zorunlu: .exe yolu ya da AUMID), APP_WINDOWS_ARGS (→ appium:appArguments,
 *   ör. `--api-url http://192.168.64.1:18081/api`), APP_WINDOWS_WORKDIR (→ appium:appWorkingDir)
 *   APP_MCP_HOST (127.0.0.1), APP_MCP_PORT (8932), APP_MCP_ALLOWED_HOSTS (virgüllü Host listesi)
 *   APP_MCP_IDLE_S (300), APP_MCP_WAIT_MAX_S (10), APP_MCP_SNAPSHOT_MAX_SATIR (400),
 *   APP_MCP_SNAPSHOT_MAX_KARAKTER (40000), APP_MCP_OTURUM_ACMA_S (300)
 */
import type { Platform } from './agac.js';

export interface PlatformAyari {
  platform: Platform;
  appiumUrl: URL;
  /** Uygulamayı başlatma/sonlandırma kimliği (appPackage / bundleId / exe-AUMID). */
  uygulamaKimligi: string;
  /** Appium oturum yetenekleri (uygulama sabitleri dahil). */
  yetenekler: Record<string, unknown>;
}

export interface Ayarlar {
  host: string;
  port: number;
  izinliHostlar: string[];
  bostaSn: number;
  beklemeMaksSn: number;
  snapshotMaksSatir: number;
  snapshotMaksKarakter: number;
  oturumAcmaSn: number;
  platformlar: Partial<Record<Platform, PlatformAyari>>;
}

type Ortam = Record<string, string | undefined>;

function tamsayi(ortam: Ortam, ad: string, varsayilan: number, min: number, maks: number): number {
  const ham = ortam[ad];
  if (ham === undefined || ham === '') return varsayilan;
  const n = Number(ham);
  if (!Number.isInteger(n) || n < min || n > maks) {
    throw new Error(`${ad} ${min}..${maks} aralığında tamsayı olmalı (verilen: ${ham})`);
  }
  return n;
}

function adres(ortam: Ortam, ad: string): URL | undefined {
  const ham = ortam[ad]?.trim();
  if (!ham) return undefined;
  let u: URL;
  try {
    u = new URL(ham);
  } catch {
    throw new Error(`${ad} geçerli bir URL değil: ${ham}`);
  }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') throw new Error(`${ad} http(s) olmalı`);
  return u;
}

function zorunlu(ortam: Ortam, ad: string, platform: string): string {
  const v = ortam[ad]?.trim();
  if (!v) throw new Error(`${platform} için ${ad} gerekli (uygulama kimliği yapılandırmadan gelir)`);
  return v;
}

/**
 * NovaWindows 1.5.0 `app` ve `appArguments` değerlerini PowerShell'de tek tırnak içine KAÇIŞSIZ
 * gömer (`Start-Process '<app>' -ArgumentList '<appArguments>'`, lib/commands/app.ts). Tek tırnak
 * ya da satır sonu, VM'de keyfi PowerShell çalıştırmaya dönüşür; bu yüzden reddedilir.
 * `appWorkingDir` sürücüde kaçışlanır ama `%DEGISKEN%` genişletilir; aynı kural ona da uygulanır.
 */
function powershellGuvenli(ad: string, deger: string | undefined): string | undefined {
  const v = deger?.trim();
  if (!v) return undefined;
  if (/['\u2018\u2019\u201a\u201b\x00-\x1f\x7f]/.test(v)) {
    throw new Error(`${ad} tek tırnak ya da denetim karakteri içeremez (NovaWindows PowerShell'e kaçışsız geçirir)`);
  }
  return v;
}

function ekle(hedef: Record<string, unknown>, anahtar: string, deger: string | undefined): void {
  if (deger?.trim()) hedef[anahtar] = deger.trim();
}

export function ayarlariOku(ortam: Ortam = process.env): Ayarlar {
  const bostaSn = tamsayi(ortam, 'APP_MCP_IDLE_S', 300, 30, 3600);
  const ortak = { 'appium:newCommandTimeout': bostaSn + 60 };
  const platformlar: Partial<Record<Platform, PlatformAyari>> = {};

  const a = adres(ortam, 'APPIUM_URL_ANDROID');
  if (a) {
    const paket = zorunlu(ortam, 'APP_ANDROID_PACKAGE', 'android');
    const y: Record<string, unknown> = {
      platformName: 'Android',
      'appium:automationName': 'UiAutomator2',
      'appium:appPackage': paket,
      'appium:autoGrantPermissions': true,
      'appium:disableWindowAnimation': true,
      'appium:forceAppLaunch': true,
      'appium:shouldTerminateApp': true,
      // RN testID resource-id'ye paket öneki olmadan yazılır; sürücü `id` aramasına
      // "<paket>:id/" eklemesin (Java testleri AppiumBy.id ile aynı kimliği arar).
      'appium:disableIdLocatorAutocompletion': true,
      ...ortak,
    };
    ekle(y, 'appium:appActivity', ortam.APP_ANDROID_ACTIVITY);
    ekle(y, 'appium:app', ortam.APP_ANDROID_APK);
    // APK verildiyse cihazdaki eski derleme (aynı sürüm kodu) yerine her oturumda bu kurulur.
    if (y['appium:app']) y['appium:enforceAppInstall'] = true;
    ekle(y, 'appium:udid', ortam.APP_ANDROID_UDID);
    platformlar.android = { platform: 'android', appiumUrl: a, uygulamaKimligi: paket, yetenekler: y };
  }

  const i = adres(ortam, 'APPIUM_URL_IOS');
  if (i) {
    const bundle = zorunlu(ortam, 'APP_IOS_BUNDLE_ID', 'ios');
    const y: Record<string, unknown> = {
      platformName: 'iOS',
      'appium:automationName': 'XCUITest',
      'appium:bundleId': bundle,
      'appium:forceAppLaunch': true,
      'appium:shouldTerminateApp': true,
      'appium:wdaLaunchTimeout': 240000,
      ...ortak,
    };
    ekle(y, 'appium:app', ortam.APP_IOS_APP);
    ekle(y, 'appium:udid', ortam.APP_IOS_UDID);
    ekle(y, 'appium:deviceName', ortam.APP_IOS_DEVICE_NAME);
    ekle(y, 'appium:platformVersion', ortam.APP_IOS_PLATFORM_VERSION);
    platformlar.ios = { platform: 'ios', appiumUrl: i, uygulamaKimligi: bundle, yetenekler: y };
  }

  const w = adres(ortam, 'APPIUM_URL_WINDOWS');
  if (w) {
    const uygulama = powershellGuvenli('APP_WINDOWS_APP', zorunlu(ortam, 'APP_WINDOWS_APP', 'windows'))!;
    const y: Record<string, unknown> = {
      platformName: 'Windows',
      'appium:automationName': 'NovaWindows',
      'appium:app': uygulama,
      ...ortak,
    };
    // Yetenek adları sabit sürücü sürümünün (appium-novawindows-driver 1.5.0) README'si ve
    // lib/constraints.ts'iyle doğrulandı: appArguments (dize), appWorkingDir (dize).
    ekle(y, 'appium:appArguments', powershellGuvenli('APP_WINDOWS_ARGS', ortam.APP_WINDOWS_ARGS));
    ekle(y, 'appium:appWorkingDir', powershellGuvenli('APP_WINDOWS_WORKDIR', ortam.APP_WINDOWS_WORKDIR));
    platformlar.windows = { platform: 'windows', appiumUrl: w, uygulamaKimligi: uygulama, yetenekler: y };
  }

  const port = tamsayi(ortam, 'APP_MCP_PORT', 8932, 1, 65535);
  const izinliHostlar = (ortam.APP_MCP_ALLOWED_HOSTS ?? '')
    .split(',')
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
  return {
    host: ortam.APP_MCP_HOST?.trim() || '127.0.0.1',
    port,
    izinliHostlar: izinliHostlar.length ? izinliHostlar : [`127.0.0.1:${port}`, `localhost:${port}`],
    bostaSn,
    beklemeMaksSn: tamsayi(ortam, 'APP_MCP_WAIT_MAX_S', 10, 1, 30),
    snapshotMaksSatir: tamsayi(ortam, 'APP_MCP_SNAPSHOT_MAX_SATIR', 400, 20, 5000),
    snapshotMaksKarakter: tamsayi(ortam, 'APP_MCP_SNAPSHOT_MAX_KARAKTER', 40000, 1000, 500000),
    oturumAcmaSn: tamsayi(ortam, 'APP_MCP_OTURUM_ACMA_S', 300, 10, 1800),
    platformlar,
  };
}
