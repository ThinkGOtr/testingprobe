/** Çok proje (TP-COK-PROJE-PLANI §4.4): MCP oturumu başına uygulama (`x-tp-app` başlığı). */
import assert from 'node:assert/strict';
import type { AddressInfo } from 'node:net';
import { after, before, describe, it } from 'node:test';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { sunucuOlustur, type AppMcpSunucusu } from '../src/sunucu.js';
import { ayarlariOku, oturumAyari } from '../src/yapilandirma.js';
import { fikstur, sahteFabrika, testAyarlari } from './sahte.js';

const kodla = (v: unknown): string => Buffer.from(JSON.stringify(v), 'utf8').toString('base64url');

describe('oturumAyari', () => {
  it('başlık yoksa ayar aynen', () => {
    const a = testAyarlari();
    assert.equal(oturumAyari(a, undefined), a);
    assert.equal(oturumAyari(a, ''), a);
  });

  it('android: paket/aktivite/apk bloktan; Appium adresi ve udid ortamdan', () => {
    const a = testAyarlari({ APP_ANDROID_UDID: 'emulator-5554', APP_ANDROID_ACTIVITY: '.Eski' });
    const o = oturumAyari(a, kodla({ android: { app_id: 'com.ornek.b', path: '/apk/b.apk' } }));
    const p = o.platformlar.android!;
    assert.equal(p.uygulamaKimligi, 'com.ornek.b');
    assert.equal(p.appiumUrl.href, a.platformlar.android!.appiumUrl.href);
    assert.equal(p.yetenekler['appium:appPackage'], 'com.ornek.b');
    assert.equal(p.yetenekler['appium:app'], '/apk/b.apk');
    assert.equal(p.yetenekler['appium:enforceAppInstall'], true);
    assert.equal(p.yetenekler['appium:appActivity'], undefined, 'ortamın aktivitesi karışmaz');
    assert.equal(p.yetenekler['appium:udid'], 'emulator-5554');
    // Başlıkta olmayan platform ve sunucu ayarı değişmez.
    assert.equal(o.platformlar.ios, a.platformlar.ios);
    assert.equal(a.platformlar.android!.uygulamaKimligi, 'com.antreklabs.bayi');
  });

  it('windows: yol/argüman/çalışma dizini; PowerShell tırnağı reddedilir', () => {
    const a = testAyarlari();
    const o = oturumAyari(a, kodla({ windows: { path: 'C:\\B\\B.exe', args: '--x 1', workdir: 'C:\\B' } }));
    const y = o.platformlar.windows!.yetenekler;
    assert.equal(o.platformlar.windows!.uygulamaKimligi, 'C:\\B\\B.exe');
    assert.equal(y['appium:appArguments'], '--x 1');
    assert.equal(y['appium:appWorkingDir'], 'C:\\B');
    assert.throws(() => oturumAyari(a, kodla({ windows: { path: "C:\\a'; kotu" } })), /tek tırnak/);
  });

  it('boş platform bloğu oturumda platformu kapatır (ortamın uygulaması açılmaz)', () => {
    const a = testAyarlari();
    const o = oturumAyari(a, kodla({ android: {}, ios: { app_id: 'com.ornek.i' } }));
    assert.equal(o.platformlar.android, undefined);
    assert.equal(o.platformlar.ios?.uygulamaKimligi, 'com.ornek.i');
    assert.ok(a.platformlar.android, 'taban ayar değişmez');
  });

  it('ortamda kapalı platform başlıkla açılmaz', () => {
    const a = ayarlariOku({ APPIUM_URL_ANDROID: 'http://h:4723', APP_ANDROID_PACKAGE: 'p' });
    const o = oturumAyari(a, kodla({ ios: { app_id: 'com.ornek.b' } }));
    assert.equal(o.platformlar.ios, undefined);
  });

  it('geçersiz başlıklar reddedilir', () => {
    const a = testAyarlari();
    assert.throws(() => oturumAyari(a, '%%%'), /x-tp-app/);
    assert.throws(() => oturumAyari(a, kodla([1])), /nesne/);
    assert.throws(() => oturumAyari(a, kodla({ symbian: {} })), /bilinmeyen platform/);
    assert.throws(() => oturumAyari(a, kodla({ android: { fazla: 'x' } })), /bilinmeyen alan/);
    assert.throws(() => oturumAyari(a, kodla({ android: { app_id: 1 } })), /dize/);
    assert.throws(() => oturumAyari(a, kodla({ android: { app_id: 'a\nb' } })), /denetim/);
    assert.throws(() => oturumAyari(a, kodla({ android: { activity: '.X' } })), /app_id gerekli/);
  });
});

describe('x-tp-app başlığı (HTTP)', () => {
  const f = sahteFabrika({ android: () => [fikstur('android-bayi-giris.xml')] });
  const ayar = testAyarlari();
  let s: AppMcpSunucusu;
  let taban: string;

  before(async () => {
    s = sunucuOlustur(ayar, f.fabrika);
    await new Promise<void>((r) => s.http.listen(0, '127.0.0.1', r));
    const port = (s.http.address() as AddressInfo).port;
    taban = `http://127.0.0.1:${port}`;
    ayar.izinliHostlar.splice(0, ayar.izinliHostlar.length, `127.0.0.1:${port}`);
  });
  after(async () => {
    await s.kapat();
  });

  it('oturumun Appium sürücüsü başlıktaki uygulamayla açılır', async () => {
    const tasima = new StreamableHTTPClientTransport(new URL(`${taban}/mcp`), {
      requestInit: { headers: { 'x-tp-app': kodla({ android: { app_id: 'com.ornek.b' } }) } },
    });
    const istemci = new Client({ name: 'test', version: '0' });
    await istemci.connect(tasima);
    const r = await istemci.callTool({ name: 'app_launch', arguments: { platform: 'android' } });
    assert.equal(r.isError, undefined);
    assert.equal(f.acilanlar.at(-1)!.ayar.uygulamaKimligi, 'com.ornek.b');
    await tasima.terminateSession();
    await istemci.close();
  });

  it('geçersiz başlık 400', async () => {
    const govde = JSON.stringify({
      jsonrpc: '2.0',
      id: 1,
      method: 'initialize',
      params: { protocolVersion: '2025-03-26', capabilities: {}, clientInfo: { name: 't', version: '0' } },
    });
    const r = await fetch(`${taban}/mcp`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'application/json, text/event-stream', 'x-tp-app': '%%%' },
      body: govde,
    });
    assert.equal(r.status, 400);
    assert.equal(s.oturumlar.size, 0);
  });
});
