#!/usr/bin/env node
// app-mcp entegrasyon dumanı: çalışan cihaz + Appium'a karşı, MCP istemcisiyle stok bir uygulamayı
// (Android Ayarlar / iOS Ayarlar) başlatır, snapshot alır, bir öğeye tıklar, sonuçları yazar.
//
//   make cihaz-baslat PLATFORM=android && npm run build && node scripts/duman.mjs android
//   node scripts/duman.mjs ios
//
// Ortam: APPIUM_URL (varsayılan http://127.0.0.1:4723), DUMAN_KANIT (varsayılan
// <repo>/var/cihaz/kanit). app-mcp ayrı süreç olarak başlatılır (gerçek HTTP yolu).
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
const port = Number(process.env.DUMAN_PORT ?? 18932);
const kanitDizini = process.env.DUMAN_KANIT ?? join(kok, 'var/cihaz/kanit');

// iOS: simülatör UDID'i (make cihaz-baslat PLATFORM=ios yazar); ad ile seçim xcuitest'te yeni
// simülatör oluşturmaya kalkar.
const udidDosyasi = join(kok, 'var/cihaz/ios.udid');
const iosUdid = process.env.TP_IOS_UDID ?? (existsSync(udidDosyasi) ? readFileSync(udidDosyasi, 'utf8').trim() : '');

const STOK = {
  android: {
    env: { APPIUM_URL_ANDROID: appium, APP_ANDROID_PACKAGE: 'com.android.settings', APP_ANDROID_ACTIVITY: '.Settings' },
    // Tıklanacak öğe: adı bu desene uyan ilk düğme.
    hedef: /^- button "(Network|Ağ|Connected|Bağlı|Display|Ekran)/,
  },
  ios: {
    env: { APPIUM_URL_IOS: appium, APP_IOS_BUNDLE_ID: 'com.apple.Preferences', APP_IOS_UDID: iosUdid },
    hedef: /^- (button|listitem) "(General|Genel)/,
  },
};
const stok = STOK[platform];
if (!stok) {
  console.error('kullanım: duman.mjs android|ios');
  process.exit(2);
}

mkdirSync(kanitDizini, { recursive: true });
const zaman = new Date().toISOString().replace(/[:.]/g, '-');
const kanitDosyasi = join(kanitDizini, `duman-${platform}${process.env.DUMAN_MCP_URL ? '-konteyner' : ''}-${zaman}.txt`);
const kayit = [];
const yaz = (s) => {
  console.log(s);
  kayit.push(s);
};

// DUMAN_MCP_URL verilirse çalışan bir app-mcp'ye (ör. konteyner) bağlanılır; yoksa yerel süreç açılır.
const disUrl = process.env.DUMAN_MCP_URL;
let sunucu;
let sunucuLog = '';
if (!disUrl) {
  sunucu = spawn(process.execPath, [join(paket, 'dist/src/index.js')], {
    env: { ...process.env, ...stok.env, APP_MCP_PORT: String(port), APP_MCP_HOST: '127.0.0.1' },
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
}

const istemci = new Client({ name: 'tp-duman', version: '0.1.0' });
const tasima = new StreamableHTTPClientTransport(new URL(disUrl ?? `http://127.0.0.1:${port}/mcp`));
let basarili = false;
try {
  await istemci.connect(tasima);
  const { tools } = await istemci.listTools();
  yaz(`# app-mcp duman — ${platform} — ${new Date().toISOString()} — ${disUrl ? `harici app-mcp ${disUrl}` : 'yerel app-mcp süreci'}`);
  yaz(`araçlar: ${tools.map((t) => t.name).join(', ')}`);

  const cagir = async (ad, arg) => {
    const t0 = Date.now();
    const r = await istemci.callTool({ name: ad, arguments: arg }, undefined, { timeout: 600_000 });
    const metin = r.content.filter((c) => c.type === 'text').map((c) => c.text).join('\n');
    const resim = r.content.find((c) => c.type === 'image');
    yaz(`\n## ${ad} ${JSON.stringify(arg)} — ${Date.now() - t0} ms${r.isError ? ' — HATA' : ''}`);
    yaz(metin + (resim ? `\n(resim: ${resim.mimeType}, ${Math.round((resim.data.length * 3) / 4 / 1024)} KiB)` : ''));
    if (r.isError) throw new Error(`${ad} hata döndürdü`);
    return { metin, resim };
  };

  const ilk = await cagir('app_launch', { platform });
  await cagir('app_wait_for', { time: 2 });
  const snap = await cagir('app_snapshot', {});
  const satirlar = snap.metin.split('\n');
  const satir = satirlar.find((s) => stok.hedef.test(s.trimStart())) ?? satirlar.find((s) => /^\s*- button ".+" .*\[ref=e\d+\]/.test(s));
  if (!satir) throw new Error('tıklanacak düğme bulunamadı');
  const ref = /\[ref=(e\d+)\]/.exec(satir)[1];
  const tarif = /"([^"]*)"/.exec(satir)?.[1] ?? ref;
  await cagir('app_generate_locator', { ref, element: tarif });
  await cagir('app_click', { ref, element: tarif });
  const ekran = await cagir('app_screenshot', {});
  if (ekran.resim) writeFileSync(kanitDosyasi.replace(/\.txt$/, '.png'), Buffer.from(ekran.resim.data, 'base64'));
  // Hata yolu: var olmayan ref → isError beklenir.
  const yok = await istemci.callTool({ name: 'app_click', arguments: { ref: 'e99999' } });
  yaz(`\n## app_click {"ref":"e99999"} — isError=${yok.isError === true}\n${yok.content[0].text}`);
  void ilk;
  basarili = true;
} catch (e) {
  yaz(`\nDUMAN BAŞARISIZ: ${e.message}`);
} finally {
  await tasima.terminateSession().catch(() => {});
  await istemci.close().catch(() => {});
  if (sunucu) {
    sunucu.kill('SIGTERM');
    await new Promise((r) => sunucu.on('exit', r));
    yaz(`\n## app-mcp günlüğü\n${sunucuLog.trim()}`);
  }
  yaz(`\nSONUÇ: ${basarili ? 'BAŞARILI' : 'BAŞARISIZ'}`);
  writeFileSync(kanitDosyasi, kayit.join('\n') + '\n');
  console.log(`kanıt: ${kanitDosyasi}`);
}
process.exit(basarili ? 0 : 1);
