#!/usr/bin/env node
/** app-mcp giriş noktası: ortamdan ayarları okur, `/mcp` streamable HTTP sunucusunu açar. */
import { sunucuOlustur } from './sunucu.js';
import { wdioFabrikasi } from './surucu.js';
import { ayarlariOku } from './yapilandirma.js';

const log = (m: string) => process.stderr.write(`[app-mcp] ${m}\n`);

let ayar;
try {
  ayar = ayarlariOku();
} catch (e) {
  log(`yapılandırma hatası: ${(e as Error).message}`);
  process.exit(2);
}
const platformlar = Object.values(ayar.platformlar).map((p) => `${p.platform}=${p.appiumUrl.origin}`);
if (platformlar.length === 0) log('uyarı: hiçbir platform yapılandırılmadı (APPIUM_URL_ANDROID|IOS|WINDOWS)');

const s = sunucuOlustur(ayar, wdioFabrikasi, log);
s.http.listen(ayar.port, ayar.host, () => {
  log(`dinleniyor http://${ayar.host}:${ayar.port}/mcp — ${platformlar.join(', ') || 'platform yok'}`);
});

let kapaniyor = false;
for (const sinyal of ['SIGINT', 'SIGTERM'] as const) {
  process.on(sinyal, () => {
    if (kapaniyor) return;
    kapaniyor = true;
    log(`${sinyal}: Appium oturumları kapatılıyor`);
    const zaman = setTimeout(() => process.exit(1), 15_000);
    zaman.unref();
    void s.kapat().then(() => process.exit(0));
  });
}
