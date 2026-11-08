#!/usr/bin/env node
// app-mcp DEMO UYGULAMA dumanı: çalışan cihaz + Appium'a karşı, MCP istemcisiyle Bayi Sipariş
// Portalı'nı (demo-app/mobile) başlatır ve doğrulama ajanının yolunu yürür:
//   app_launch (reset) → snapshot'ta giriş kimlikleri → kullanıcı adı + parola (maskeli) → giriş →
//   katalog metnini bekle → ürün kartındaki "Sepete ekle" için app_generate_locator
//   → {platform, strategy:"id"|"accessibilityId", id:"add-to-cart"} beklenir.
//
//   make cihaz-baslat PLATFORM=android && npm run build && node scripts/duman-demo.mjs android
//   node scripts/duman-demo.mjs ios
//
// Ortam: APPIUM_URL (varsayılan http://127.0.0.1:4723), DUMAN_KANIT (varsayılan
// <repo>/var/cihaz/kanit — gitignore'lu), DUMAN_BAYI / DUMAN_PAROLA (varsayılan demo bayi1),
// APP_ANDROID_APK / APP_IOS_APP (verilirse oturumda kurulur). Parola hiçbir çıktıya yazılmaz.
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';

const burasi = dirname(fileURLToPath(import.meta.url));
const paket = resolve(burasi, '..');
const kok = resolve(paket, '../..');
const platform = process.argv[2] ?? 'android';
const appium = process.env.APPIUM_URL ?? 'http://127.0.0.1:4723';
const port = Number(process.env.DUMAN_PORT ?? 18933);
const kanitDizini = process.env.DUMAN_KANIT ?? join(kok, 'var/cihaz/kanit');
const bayi = process.env.DUMAN_BAYI ?? 'bayi1';
const parola = process.env.DUMAN_PAROLA ?? 'Demo123!'; // demo-app/README.md "Demo bayileri"
const UYGULAMA = 'com.antreklabs.bayisiparis';

const udidDosyasi = join(kok, 'var/cihaz/ios.udid');
const iosUdid = process.env.TP_IOS_UDID ?? (existsSync(udidDosyasi) ? readFileSync(udidDosyasi, 'utf8').trim() : '');

const ORTAM = {
  android: {
    APPIUM_URL_ANDROID: appium,
    APP_ANDROID_PACKAGE: UYGULAMA,
    APP_ANDROID_ACTIVITY: '.MainActivity',
    ...(process.env.APP_ANDROID_APK ? { APP_ANDROID_APK: process.env.APP_ANDROID_APK } : {}),
  },
  ios: {
    APPIUM_URL_IOS: appium,
    APP_IOS_BUNDLE_ID: UYGULAMA,
    APP_IOS_UDID: iosUdid,
    ...(process.env.APP_IOS_APP ? { APP_IOS_APP: process.env.APP_IOS_APP } : {}),
  },
};
const BEKLENEN_STRATEJI = { android: 'id', ios: 'accessibilityId' };
if (!ORTAM[platform]) {
  console.error('kullanım: duman-demo.mjs android|ios');
  process.exit(2);
}

mkdirSync(kanitDizini, { recursive: true });
const zaman = new Date().toISOString().replace(/[:.]/g, '-');
const kanitDosyasi = join(kanitDizini, `duman-demo-${platform}-${zaman}.txt`);
const kayit = [];
const yaz = (s) => {
  // Son savunma: parola hiçbir satıra düşmesin.
  const temiz = s.split(parola).join('***');
  console.log(temiz);
  kayit.push(temiz);
};

let sunucu;
let sunucuLog = '';
sunucu = spawn(process.execPath, [join(paket, 'dist/src/index.js')], {
  env: { ...process.env, ...ORTAM[platform], APP_MCP_PORT: String(port), APP_MCP_HOST: '127.0.0.1' },
  stdio: ['ignore', 'inherit', 'pipe'],
});
sunucu.stderr.on('data', (d) => {
  sunucuLog += d;
});
await new Promise((ok, red) => {
  const t = setTimeout(() => red(new Error(`app-mcp açılmadı:\n${sunucuLog}`)), 15000);
  sunucu.stderr.on('data', () => {
    if (sunucuLog.includes('dinleniyor')) {
      clearTimeout(t);
      ok();
    }
  });
  sunucu.on('exit', (k) => red(new Error(`app-mcp çıktı (${k}):\n${sunucuLog}`)));
});

const istemci = new Client({ name: 'tp-duman-demo', version: '0.1.0' });
const tasima = new StreamableHTTPClientTransport(new URL(`http://127.0.0.1:${port}/mcp`));
let basarili = false;

const satirBul = (snap, kimlik) => {
  const s = snap.split('\n').find((l) => l.includes(`[id=${kimlik}]`) && /\[ref=e\d+\]/.test(l));
  if (!s) throw new Error(`snapshot'ta [id=${kimlik}] yok`);
  return { satir: s.trim(), ref: /\[ref=(e\d+)\]/.exec(s)[1] };
};

try {
  await istemci.connect(tasima);
  yaz(`# app-mcp demo uygulama dumanı — ${platform} — ${new Date().toISOString()} — ${UYGULAMA}`);

  const cagir = async (ad, arg, gizli = false) => {
    const t0 = Date.now();
    const r = await istemci.callTool({ name: ad, arguments: arg }, undefined, { timeout: 600_000 });
    const metin = r.content.filter((c) => c.type === 'text').map((c) => c.text).join('\n');
    const gosterilen = gizli ? { ...arg, text: '***' } : arg;
    yaz(`\n## ${ad} ${JSON.stringify(gosterilen)} — ${Date.now() - t0} ms${r.isError ? ' — HATA' : ''}`);
    yaz(metin);
    if (r.isError) throw new Error(`${ad} hata döndürdü`);
    return metin;
  };

  const ilk = await cagir('app_launch', { platform, reset: true });
  const kullanici = satirBul(ilk, 'login-username');
  const sifre = satirBul(ilk, 'login-password');
  const gonder = satirBul(ilk, 'login-submit');
  yaz(`\n✓ giriş kimlikleri: ${[kullanici, sifre, gonder].map((x) => x.satir).join(' | ')}`);

  await cagir('app_type', { element: 'Kullanıcı adı', ref: kullanici.ref, text: bayi });
  const parolaSonuc = await cagir('app_type', { element: 'Parola', ref: sifre.ref, text: parola }, true);
  if (parolaSonuc.includes(parola)) throw new Error('parola çıktıda göründü');
  await cagir('app_click', { element: 'Giriş yap', ref: gonder.ref });
  await cagir('app_wait_for', { text: 'Sepete ekle' });
  const katalog = await cagir('app_snapshot', {});
  const dugme = satirBul(katalog, 'add-to-cart');
  const loc = await cagir('app_generate_locator', { element: 'Sepete ekle', ref: dugme.ref });
  const json = JSON.parse(/\{[\s\S]*\}/.exec(loc)[0]);
  if (json.platform !== platform || json.strategy !== BEKLENEN_STRATEJI[platform] || json.id !== 'add-to-cart') {
    throw new Error(`beklenmeyen locator: ${JSON.stringify(json)}`);
  }
  yaz(`\n✓ locator: ${JSON.stringify(json)}`);
  basarili = true;
} catch (e) {
  yaz(`\nDUMAN BAŞARISIZ: ${e.message}`);
} finally {
  await tasima.terminateSession().catch(() => {});
  await istemci.close().catch(() => {});
  sunucu.kill('SIGTERM');
  await new Promise((r) => sunucu.on('exit', r));
  yaz(`\n## app-mcp günlüğü\n${sunucuLog.trim()}`);
  yaz(`\nSONUÇ: ${basarili ? 'BAŞARILI' : 'BAŞARISIZ'}`);
  writeFileSync(kanitDosyasi, kayit.join('\n') + '\n');
  console.log(`kanıt: ${kanitDosyasi}`);
}
process.exit(basarili ? 0 : 1);
