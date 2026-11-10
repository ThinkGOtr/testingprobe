/**
 * Duman betiklerinin platform ortamı (scripts/duman-ortami.mjs) ve Windows demo akışının cihazsız
 * provası: betiğin ürettiği ortam → ayarlariOku → sahte NovaWindows sürücüsü (UIA fikstürü).
 * Gerçek Windows VM'e karşı koşu: docs/WINDOWS-VM.md §6.
 */
import assert from 'node:assert/strict';
import { dirname, join } from 'node:path';
import { describe, it } from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import type { CallToolResult } from '@modelcontextprotocol/sdk/types.js';
import { sunucuKur } from '../src/araclar.js';
import { AppOturumu, CihazKilidi } from '../src/oturum.js';
import { ayarlariOku } from '../src/yapilandirma.js';
import { fikstur, sahteFabrika } from './sahte.js';

// dist/test/… → kaynak ağacındaki scripts/ (betikler derlenmez).
const modul = pathToFileURL(join(dirname(fileURLToPath(import.meta.url)), '../../scripts/duman-ortami.mjs')).href;
const D = (await import(modul)) as typeof import('../scripts/duman-ortami.mjs');

describe('duman ortamı', () => {
  it('platform listesi ve bilinmeyen platform', () => {
    assert.deepEqual(D.PLATFORMLAR, ['android', 'ios', 'windows']);
    assert.equal(D.stokOrtami('macos', {}), undefined);
    assert.equal(D.demoOrtami('macos', {}), undefined);
  });

  it('Appium adresi: APPIUM_URL > TP_WINDOWS_VM_APPIUM > varsayılan', () => {
    assert.equal(D.appiumAdresi('android', {}), 'http://127.0.0.1:4723');
    assert.equal(D.appiumAdresi('windows', {}), 'http://192.168.64.2:4723');
    assert.equal(D.appiumAdresi('windows', { TP_WINDOWS_VM_APPIUM: '192.168.64.7:4723' }), 'http://192.168.64.7:4723');
    assert.equal(D.appiumAdresi('windows', { APPIUM_URL: 'http://10.0.0.9:4723', TP_WINDOWS_VM_APPIUM: 'x:1' }), 'http://10.0.0.9:4723');
  });

  it('duman windows: yapılandırılmış uygulama zorunlu (harici app-mcp hariç), tıklama yok', () => {
    assert.throws(() => D.stokOrtami('windows', {}), /APP_WINDOWS_APP gerekli/);
    assert.deepEqual(D.stokOrtami('windows', {}, '', true), { env: { APPIUM_URL_WINDOWS: 'http://192.168.64.2:4723' }, hedef: null });
    const s = D.stokOrtami('windows', { APP_WINDOWS_APP: 'C:\\x\\Uyg.exe', APP_WINDOWS_ARGS: '--a 1', APP_WINDOWS_WORKDIR: '' })!;
    assert.equal(s.hedef, null);
    assert.deepEqual(s.env, { APPIUM_URL_WINDOWS: 'http://192.168.64.2:4723', APP_WINDOWS_APP: 'C:\\x\\Uyg.exe', APP_WINDOWS_ARGS: '--a 1' });
    const a = ayarlariOku(s.env).platformlar;
    assert.deepEqual(Object.keys(a), ['windows']);
    assert.equal(a.windows!.yetenekler['appium:appArguments'], '--a 1');
    assert.ok(D.stokOrtami('android', {})!.hedef instanceof RegExp);
  });

  it('duman-demo windows: demo exe varsayılanı, argüman/çalışma dizini geçer, beklenen strateji', () => {
    const env = D.demoOrtami('windows', {
      APP_WINDOWS_ARGS: '--api-url http://192.168.64.1:18081/api',
      APP_WINDOWS_WORKDIR: 'C:\\tp\\bayi\\win-arm64',
    })!;
    assert.equal(env.APP_WINDOWS_APP, D.DEMO_WINDOWS_APP);
    assert.equal(D.uygulamaKimligi('windows', env), 'C:\\tp\\bayi\\win-arm64\\BayiSiparis.exe');
    const y = ayarlariOku(env).platformlar.windows!.yetenekler;
    assert.equal(y['appium:app'], D.DEMO_WINDOWS_APP);
    assert.equal(y['appium:appArguments'], '--api-url http://192.168.64.1:18081/api');
    assert.equal(y['appium:appWorkingDir'], 'C:\\tp\\bayi\\win-arm64');
    assert.equal(D.BEKLENEN_STRATEJI.windows, 'accessibilityId');
    // Mobil platformlar değişmedi.
    assert.equal(D.demoOrtami('android', {})!.APP_ANDROID_PACKAGE, D.DEMO_UYGULAMA);
    assert.equal(D.demoOrtami('ios', {}, 'U-1')!.APP_IOS_UDID, 'U-1');
  });
});

describe('duman-demo windows akışı (sahte NovaWindows, UIA fikstürü)', () => {
  it('giriş kimlikleri → maskeli parola → add-to-cart locator = accessibilityId', async () => {
    const env = D.demoOrtami('windows', { APP_WINDOWS_ARGS: '--api-url http://192.168.64.1:18081/api' })!;
    const f = sahteFabrika({ windows: () => [fikstur('windows-bayi-giris.xml')] });
    const oturum = new AppOturumu('duman', ayarlariOku({ ...env, APP_MCP_WAIT_MAX_S: '2' }), f.fabrika, new CihazKilidi());
    const [a, b] = InMemoryTransport.createLinkedPair();
    await sunucuKur(oturum).connect(a);
    const istemci = new Client({ name: 'duman-test', version: '0' });
    await istemci.connect(b);
    const cagir = async (ad: string, arg: Record<string, unknown> = {}): Promise<string> => {
      const r = (await istemci.callTool({ name: ad, arguments: arg })) as CallToolResult;
      const metin = r.content.filter((c) => c.type === 'text').map((c) => (c as { text: string }).text).join('\n');
      assert.notEqual(r.isError, true, `${ad}: ${metin}`);
      return metin;
    };
    // duman-demo.mjs satirBul ile aynı arama.
    const satirBul = (snap: string, kimlik: string): string => {
      const s = snap.split('\n').find((l) => l.includes(`[id=${kimlik}]`) && /\[ref=e\d+\]/.test(l));
      assert.ok(s, `snapshot'ta [id=${kimlik}] yok`);
      return /\[ref=(e\d+)\]/.exec(s)![1]!;
    };

    const ilk = await cagir('app_launch', { platform: 'windows', reset: true });
    assert.equal(f.acilanlar[0]!.ayar.yetenekler['appium:appArguments'], '--api-url http://192.168.64.1:18081/api');
    const parola = 'Gizli-Parola-1';
    await cagir('app_type', { element: 'Kullanıcı adı', ref: satirBul(ilk, 'login-username'), text: 'bayi1' });
    const p = await cagir('app_type', { element: 'Parola', ref: satirBul(ilk, 'login-password'), text: parola });
    assert.ok(!p.includes(parola), 'parola çıktıda görünmemeli');
    await cagir('app_click', { element: 'Giriş yap', ref: satirBul(ilk, 'login-submit') });
    await cagir('app_wait_for', { text: 'Sepete ekle' });
    const katalog = await cagir('app_snapshot');
    const loc = await cagir('app_generate_locator', { element: 'Sepete ekle', ref: satirBul(katalog, 'add-to-cart') });
    const json = JSON.parse(/\{[\s\S]*\}/.exec(loc)![0]) as Record<string, unknown>;
    assert.deepEqual(json, { platform: 'windows', strategy: D.BEKLENEN_STRATEJI.windows, id: 'add-to-cart' });
    await istemci.close();
  });
});
