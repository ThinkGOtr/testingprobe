#!/usr/bin/env node
// Geliştirici aracı (ajana açık DEĞİL): çalışan Appium'dan ham sayfa kaynağını test fikstürü olarak
// kaydeder. Birim testlerindeki gerçek Android/iOS fikstürleri bununla yakalandı.
//   node scripts/kaynak-yakala.mjs android com.android.settings .Settings test/fixtures/android-ayarlar.xml
//   node scripts/kaynak-yakala.mjs ios com.apple.Preferences - test/fixtures/ios-ayarlar.xml
import { readFileSync, writeFileSync } from 'node:fs';
import { remote } from 'webdriverio';

const [platform, uygulama, etkinlik, cikti] = process.argv.slice(2);
if (!platform || !uygulama || !cikti) {
  console.error('kullanım: kaynak-yakala.mjs android|ios <paket|bundle> <etkinlik|-> <çıktı.xml>');
  process.exit(2);
}
const yetenek =
  platform === 'android'
    ? { platformName: 'Android', 'appium:automationName': 'UiAutomator2', 'appium:appPackage': uygulama, ...(etkinlik !== '-' ? { 'appium:appActivity': etkinlik } : {}), 'appium:noReset': true }
    : { platformName: 'iOS', 'appium:automationName': 'XCUITest', 'appium:bundleId': uygulama, 'appium:udid': process.env.TP_IOS_UDID ?? readFileSync(new URL('../../../var/cihaz/ios.udid', import.meta.url), 'utf8').trim(), 'appium:noReset': true, 'appium:wdaLaunchTimeout': 240000 };
const b = await remote({ hostname: '127.0.0.1', port: 4723, path: '/', capabilities: yetenek, logLevel: 'error', connectionRetryTimeout: 600000 });
try {
  await new Promise((r) => setTimeout(r, Number(process.env.BEKLE_MS ?? 2000)));
  writeFileSync(cikti, await b.getPageSource());
  console.log(`yazıldı: ${cikti}`);
} finally {
  await b.deleteSession();
}
