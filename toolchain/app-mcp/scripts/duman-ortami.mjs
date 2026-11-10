// Duman betiklerinin (duman.mjs, duman-demo.mjs) platform başına app-mcp ortamı. Ayrı modüldür ki
// cihazsız birim testi (test/duman.test.ts) Windows dahil her platformun ortamını doğrulayabilsin.
//
// Appium adresi: APPIUM_URL verilirse o; yoksa android/ios için hosttaki Appium
// (http://127.0.0.1:4723), windows için UTM sanal makinesi (http://$TP_WINDOWS_VM_APPIUM,
// varsayılan 192.168.64.2:4723; docs/WINDOWS-VM.md).

export const PLATFORMLAR = ['android', 'ios', 'windows'];
export const VARSAYILAN_WINDOWS_VM_APPIUM = '192.168.64.2:4723';
/** Demo uygulamasının VM'deki yolu (docs/WINDOWS-VM.md §4.1). */
export const DEMO_WINDOWS_APP = 'C:\\tp\\bayi\\win-arm64\\BayiSiparis.exe';
export const DEMO_UYGULAMA = 'com.antreklabs.bayisiparis';
/** `app_generate_locator`'ın "Sepete ekle" için beklenen stratejisi (Windows: UIA AutomationId). */
export const BEKLENEN_STRATEJI = { android: 'id', ios: 'accessibilityId', windows: 'accessibilityId' };

const dolu = (v) => (typeof v === 'string' && v.trim() ? v.trim() : undefined);

export function appiumAdresi(platform, ortam) {
  const acik = dolu(ortam.APPIUM_URL);
  if (acik) return acik;
  if (platform === 'windows') return `http://${dolu(ortam.TP_WINDOWS_VM_APPIUM) ?? VARSAYILAN_WINDOWS_VM_APPIUM}`;
  return 'http://127.0.0.1:4723';
}

/** Windows: uygulama + isteğe bağlı argüman / çalışma dizini (yapilandirma.ts doğrular). */
function windowsOrtami(ortam, varsayilanUygulama, zorunlu = true) {
  const uygulama = dolu(ortam.APP_WINDOWS_APP) ?? varsayilanUygulama;
  if (!uygulama && zorunlu) {
    throw new Error('windows dumanı için APP_WINDOWS_APP gerekli (VM\'deki .exe yolu ya da AUMID)');
  }
  const env = { APPIUM_URL_WINDOWS: appiumAdresi('windows', ortam) };
  if (uygulama) env.APP_WINDOWS_APP = uygulama;
  for (const ad of ['APP_WINDOWS_ARGS', 'APP_WINDOWS_WORKDIR']) {
    const v = dolu(ortam[ad]);
    if (v) env[ad] = v;
  }
  return env;
}

/**
 * duman.mjs: stok uygulama (Android/iOS Ayarlar) ya da Windows'ta yapılandırılmış uygulama.
 * `hedef`: tıklanacak düğmenin deseni; Windows'ta `null` (uygulama bilinmediği için tıklanmaz,
 * yalnızca başlat + snapshot + locator + ekran görüntüsü).
 * Bilinmeyen platformda `undefined`. `harici`: çalışan bir app-mcp'ye bağlanılacak (DUMAN_MCP_URL);
 * uygulama orada yapılandırılmıştır, APP_WINDOWS_APP zorunlu değildir.
 */
export function stokOrtami(platform, ortam, iosUdid = '', harici = false) {
  switch (platform) {
    case 'android':
      return {
        env: {
          APPIUM_URL_ANDROID: appiumAdresi(platform, ortam),
          APP_ANDROID_PACKAGE: 'com.android.settings',
          APP_ANDROID_ACTIVITY: '.Settings',
        },
        hedef: /^- button "(Network|Ağ|Connected|Bağlı|Display|Ekran)/,
      };
    case 'ios':
      return {
        env: { APPIUM_URL_IOS: appiumAdresi(platform, ortam), APP_IOS_BUNDLE_ID: 'com.apple.Preferences', APP_IOS_UDID: iosUdid },
        hedef: /^- (button|listitem) "(General|Genel)/,
      };
    case 'windows':
      return { env: windowsOrtami(ortam, undefined, !harici), hedef: null };
    default:
      return undefined;
  }
}

/** duman-demo.mjs: Bayi Sipariş Portalı (mobil: demo-app/mobile; Windows: demo-app/desktop WPF). */
export function demoOrtami(platform, ortam, iosUdid = '') {
  switch (platform) {
    case 'android':
      return {
        APPIUM_URL_ANDROID: appiumAdresi(platform, ortam),
        APP_ANDROID_PACKAGE: DEMO_UYGULAMA,
        APP_ANDROID_ACTIVITY: '.MainActivity',
        ...(dolu(ortam.APP_ANDROID_APK) ? { APP_ANDROID_APK: dolu(ortam.APP_ANDROID_APK) } : {}),
      };
    case 'ios':
      return {
        APPIUM_URL_IOS: appiumAdresi(platform, ortam),
        APP_IOS_BUNDLE_ID: DEMO_UYGULAMA,
        APP_IOS_UDID: iosUdid,
        ...(dolu(ortam.APP_IOS_APP) ? { APP_IOS_APP: dolu(ortam.APP_IOS_APP) } : {}),
      };
    case 'windows':
      return windowsOrtami(ortam, DEMO_WINDOWS_APP);
    default:
      return undefined;
  }
}

/** Kanıt başlığındaki uygulama kimliği. */
export function uygulamaKimligi(platform, env) {
  return env.APP_ANDROID_PACKAGE ?? env.APP_IOS_BUNDLE_ID ?? env.APP_WINDOWS_APP ?? platform;
}
