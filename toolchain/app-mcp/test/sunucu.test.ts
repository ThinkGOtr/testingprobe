/** HTTP katmanı (streamable HTTP `/mcp`) ve yapılandırma. */
import assert from 'node:assert/strict';
import type { AddressInfo } from 'node:net';
import { after, before, describe, it } from 'node:test';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { sunucuOlustur, type AppMcpSunucusu } from '../src/sunucu.js';
import { ayarlariOku } from '../src/yapilandirma.js';
import { fikstur, sahteFabrika, testAyarlari } from './sahte.js';

describe('HTTP sunucusu', () => {
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

  it('izinsiz Host başlığı 403 (DNS rebinding)', async () => {
    const r = await new Promise<number>((ok, red) => {
      const u = new URL(`${taban}/health`);
      import('node:http').then(({ request }) => {
        const q = request({ host: u.hostname, port: u.port, path: u.pathname, headers: { host: 'kotu.example' } }, (res) => {
          res.resume();
          ok(res.statusCode ?? 0);
        });
        q.on('error', red);
        q.end();
      }, red);
    });
    assert.equal(r, 403);
  });

  it('sağlık ucu', async () => {
    const r = await fetch(`${taban}/health`);
    assert.equal(r.status, 200);
    assert.deepEqual(await r.json(), { durum: 'ok', oturum: 0, platformlar: ['android', 'ios', 'windows'] });
  });

  it('MCP oturumu: initialize → araç → DELETE Appium oturumunu kapatır', async () => {
    const tasima = new StreamableHTTPClientTransport(new URL(`${taban}/mcp`));
    const istemci = new Client({ name: 'test', version: '0' });
    await istemci.connect(tasima);
    assert.equal(s.oturumlar.size, 1);
    const r = await istemci.callTool({ name: 'app_launch', arguments: { platform: 'android' } });
    assert.equal(r.isError, undefined);
    await tasima.terminateSession();
    await istemci.close();
    await new Promise((ok) => setTimeout(ok, 50));
    assert.equal(s.oturumlar.size, 0);
    assert.equal(f.acilanlar.at(-1)!.surucu.kapali, true);
  });

  it('boşta zaman aşımı: Appium oturumu ve MCP oturumu kapanır', async () => {
    const tasima = new StreamableHTTPClientTransport(new URL(`${taban}/mcp`));
    const istemci = new Client({ name: 'test', version: '0' });
    await istemci.connect(tasima);
    await istemci.callTool({ name: 'app_launch', arguments: { platform: 'android' } });
    const [kayit] = [...s.oturumlar.values()];
    await s.bostaDenetle();
    assert.equal(s.oturumlar.size, 1, 'süre dolmadan kapanmamalı');
    kayit!.oturum.sonEtkinlik = Date.now() - (ayar.bostaSn + 1) * 1000;
    await s.bostaDenetle();
    assert.equal(s.oturumlar.size, 0);
    assert.equal(f.acilanlar.at(-1)!.surucu.kapali, true);
    await istemci.close();
  });

  it('bilinmeyen oturum 404, initialize olmadan 400', async () => {
    const baslik = { 'content-type': 'application/json', accept: 'application/json, text/event-stream' };
    const govde = JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' });
    const yok = await fetch(`${taban}/mcp`, { method: 'POST', headers: { ...baslik, 'mcp-session-id': 'yok' }, body: govde });
    assert.equal(yok.status, 404);
    const ilksiz = await fetch(`${taban}/mcp`, { method: 'POST', headers: baslik, body: govde });
    assert.equal(ilksiz.status, 400);
    assert.equal((await fetch(`${taban}/baska`)).status, 404);
  });
});

describe('yapılandırma', () => {
  it('platform yalnızca Appium adresi verilince açılır; uygulama kimliği zorunlu', () => {
    assert.deepEqual(Object.keys(ayarlariOku({}).platformlar), []);
    assert.throws(() => ayarlariOku({ APPIUM_URL_ANDROID: 'http://h:4723' }), /APP_ANDROID_PACKAGE gerekli/);
    assert.throws(() => ayarlariOku({ APPIUM_URL_IOS: 'ftp://h' , APP_IOS_BUNDLE_ID: 'x' }), /http\(s\) olmalı/);
    assert.throws(() => ayarlariOku({ APP_MCP_WAIT_MAX_S: '100' }), /1\.\.30/);
  });

  it('yetenekler: uygulama sabitleri ve boşta zaman aşımı', () => {
    const a = ayarlariOku({
      APPIUM_URL_ANDROID: 'http://host.docker.internal:4723',
      APP_ANDROID_PACKAGE: 'com.antreklabs.bayi',
      APP_ANDROID_ACTIVITY: '.MainActivity',
      APP_MCP_IDLE_S: '120',
    });
    const y = a.platformlar.android!.yetenekler;
    assert.equal(y['appium:appPackage'], 'com.antreklabs.bayi');
    assert.equal(y['appium:appActivity'], '.MainActivity');
    assert.equal(y['appium:newCommandTimeout'], 180);
    assert.equal(y['appium:automationName'], 'UiAutomator2');
    // RN testID öneksiz resource-id: sürücü paket öneki eklememeli.
    assert.equal(y['appium:disableIdLocatorAutocompletion'], true);
    assert.equal(y['appium:enforceAppInstall'], undefined, 'APK yokken kurulum zorlanmaz');
    const apk = ayarlariOku({
      APPIUM_URL_ANDROID: 'http://h:4723',
      APP_ANDROID_PACKAGE: 'com.antreklabs.bayisiparis',
      APP_ANDROID_APK: '/x/bayi-siparis.apk',
    });
    assert.equal(apk.platformlar.android!.yetenekler['appium:enforceAppInstall'], true);
    assert.equal(a.bostaSn, 120);
    assert.deepEqual(a.izinliHostlar, ['127.0.0.1:8932', 'localhost:8932']);
  });

  it('iOS ve Windows sürücü adları', () => {
    const a = testAyarlari();
    assert.equal(a.platformlar.ios!.yetenekler['appium:automationName'], 'XCUITest');
    assert.equal(a.platformlar.ios!.yetenekler['appium:bundleId'], 'com.antreklabs.bayi');
    assert.equal(a.platformlar.windows!.yetenekler['appium:automationName'], 'NovaWindows');
    assert.equal(a.platformlar.windows!.uygulamaKimligi, 'C:\\Bayi\\Bayi.exe');
  });

  it('Windows: uygulama argümanı ve çalışma dizini (NovaWindows 1.5.0 yetenekleri)', () => {
    const yok = testAyarlari().platformlar.windows!.yetenekler;
    assert.equal(yok['appium:appArguments'], undefined);
    assert.equal(yok['appium:appWorkingDir'], undefined);
    const y = testAyarlari({
      APP_WINDOWS_ARGS: ' --api-url http://192.168.64.1:18081/api ',
      APP_WINDOWS_WORKDIR: 'C:\\tp\\bayi\\win-arm64',
    }).platformlar.windows!.yetenekler;
    assert.equal(y['appium:appArguments'], '--api-url http://192.168.64.1:18081/api');
    assert.equal(y['appium:appWorkingDir'], 'C:\\tp\\bayi\\win-arm64');
    assert.equal(y['appium:app'], 'C:\\Bayi\\Bayi.exe');
  });

  it('Windows: PowerShell tırnağını kıran değerler reddedilir', () => {
    const kotu: Array<[string, string]> = [
      ['APP_WINDOWS_ARGS', "--api-url x'; Remove-Item C:\\ -Recurse; '"],
      ['APP_WINDOWS_ARGS', '--a\n--b'],
      ['APP_WINDOWS_ARGS', '--a \u2019x'],
      ['APP_WINDOWS_WORKDIR', "C:\\O'Brien"],
      ['APP_WINDOWS_APP', "C:\\a'b.exe"],
    ];
    for (const [ad, deger] of kotu) {
      assert.throws(() => testAyarlari({ [ad]: deger }), new RegExp(`${ad} tek tırnak`), `${ad}=${JSON.stringify(deger)}`);
    }
    // Windows kapalıyken (adres yok) bu değişkenler okunmaz.
    assert.doesNotThrow(() => testAyarlari({ APPIUM_URL_WINDOWS: '', APP_WINDOWS_ARGS: "'" }));
  });
});
