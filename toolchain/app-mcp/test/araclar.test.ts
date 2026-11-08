/**
 * Araç yüzeyi ve oturum mantığı: gerçek MCP istemcisi (süreç içi taşıma) + sahte Appium sürücüsü.
 */
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import type { CallToolResult } from '@modelcontextprotocol/sdk/types.js';
import { ARACLAR, sunucuKur } from '../src/araclar.js';
import { AppOturumu, CihazKilidi } from '../src/oturum.js';
import { fikstur, sahteFabrika, testAyarlari, type SahteFabrika } from './sahte.js';

type Arac = (ad: string, arg?: Record<string, unknown>) => Promise<CallToolResult & { metin: string }>;

async function baglan(
  f: SahteFabrika,
  kilit = new CihazKilidi(),
  kimlik = 'oturum-1',
  ayar = testAyarlari(),
): Promise<{ cagir: Arac; istemci: Client; oturum: AppOturumu }> {
  const oturum = new AppOturumu(kimlik, ayar, f.fabrika, kilit);
  const [a, b] = InMemoryTransport.createLinkedPair();
  await sunucuKur(oturum).connect(a);
  const istemci = new Client({ name: 'test', version: '0' });
  await istemci.connect(b);
  const cagir: Arac = async (ad, arg = {}) => {
    const r = (await istemci.callTool({ name: ad, arguments: arg })) as CallToolResult;
    const metin = r.content
      .filter((c) => c.type === 'text')
      .map((c) => (c as { text: string }).text)
      .join('\n');
    return { ...r, metin };
  };
  return { cagir, istemci, oturum };
}

function ref(metin: string, desen: RegExp): string {
  const satir = metin.split('\n').find((s) => desen.test(s));
  assert.ok(satir, `satır yok: ${desen}`);
  return /\[ref=(e\d+)\]/.exec(satir)![1]!;
}

const androidGiris = () => [fikstur('android-bayi-giris.xml')];

describe('araç listesi ve şemalar', () => {
  it('tam olarak §2.6 araçları; yasaklı araç yok', async () => {
    const { istemci } = await baglan(sahteFabrika({ android: androidGiris }));
    const { tools } = await istemci.listTools();
    assert.deepEqual(tools.map((t) => t.name).sort(), [...ARACLAR].sort());
    for (const t of tools) {
      assert.doesNotMatch(t.name, /execute|script|mobile|install|remove|push|pull|file|source|xpath/i);
      assert.equal(t.inputSchema.additionalProperties, false, `${t.name} şeması kapalı olmalı`);
      assert.ok(!('filename' in (t.inputSchema.properties ?? {})), `${t.name}: filename yok`);
    }
    const launch = tools.find((t) => t.name === 'app_launch')!;
    assert.deepEqual(Object.keys(launch.inputSchema.properties ?? {}).sort(), ['platform', 'reset']);
    assert.deepEqual(launch.inputSchema.required, ['platform']);
  });

  it('bilinmeyen argüman (ör. uygulama kimliği) reddedilir', async () => {
    const f = sahteFabrika({ android: androidGiris });
    const { cagir } = await baglan(f);
    const r = await cagir('app_launch', { platform: 'android', appPackage: 'com.evil' });
    assert.equal(r.isError, true);
    assert.equal(f.acilanlar.length, 0);
  });
});

describe('app_launch', () => {
  it('önce başlatılmadan eylem: isError', async () => {
    const { cagir } = await baglan(sahteFabrika({ android: androidGiris }));
    for (const ad of ['app_snapshot', 'app_screenshot']) {
      const r = await cagir(ad);
      assert.equal(r.isError, true);
      assert.match(r.metin, /^### Hata\nUygulama başlatılmadı: önce app_launch/);
    }
  });

  it('yapılandırılmış uygulamayla oturum açar, snapshot döndürür', async () => {
    const f = sahteFabrika({ android: androidGiris });
    const { cagir } = await baglan(f);
    const r = await cagir('app_launch', { platform: 'android' });
    assert.equal(r.isError, undefined);
    assert.match(r.metin, /^### Sonuç\nUygulama başlatıldı: com\.antreklabs\.bayi \(android\)/);
    assert.match(r.metin, /### Snapshot\n```yaml\n- group/);
    assert.equal(f.acilanlar[0]!.ayar.yetenekler['appium:appPackage'], 'com.antreklabs.bayi');
    assert.equal(f.acilanlar[0]!.sifirla, false);
  });

  it('aynı platformda tekrar: uygulama kapatılıp açılır (yeni oturum yok); reset yeni oturum açar', async () => {
    const f = sahteFabrika({ android: androidGiris });
    const { cagir } = await baglan(f);
    await cagir('app_launch', { platform: 'android' });
    const r = await cagir('app_launch', { platform: 'android' });
    assert.match(r.metin, /yeniden başlatıldı/);
    const ad = f.acilanlar[0]!.surucu.cagrilar.map((c) => c.ad);
    assert.ok(ad.includes('uygulamayiSonlandir') && ad.includes('uygulamayiEtkinlestir'));
    assert.equal(f.acilanlar.length, 1);
    await cagir('app_launch', { platform: 'android', reset: true });
    assert.equal(f.acilanlar.length, 2);
    assert.equal(f.acilanlar[1]!.sifirla, true);
    assert.equal(f.acilanlar[0]!.surucu.kapali, true);
  });

  it('yapılandırılmamış platform: isError', async () => {
    const ayar = testAyarlari({ APPIUM_URL_WINDOWS: '' });
    const { cagir } = await baglan(sahteFabrika({ android: androidGiris }), new CihazKilidi(), 'x', ayar);
    const r = await cagir('app_launch', { platform: 'windows' });
    assert.equal(r.isError, true);
    assert.match(r.metin, /windows platformu yapılandırılmamış \(açık platformlar: android, ios\)/);
  });

  it('cihaz başka MCP oturumunda: isError; ilk oturum kapanınca açılır', async () => {
    const kilit = new CihazKilidi();
    const f = sahteFabrika({ android: androidGiris });
    const a = await baglan(f, kilit, 'a');
    const b = await baglan(f, kilit, 'b');
    await a.cagir('app_launch', { platform: 'android' });
    const r = await b.cagir('app_launch', { platform: 'android' });
    assert.equal(r.isError, true);
    assert.match(r.metin, /başka bir MCP oturumunda/);
    await a.oturum.kapat();
    assert.equal((await b.cagir('app_launch', { platform: 'android' })).isError, undefined);
  });

  it('Appium oturumu açılamazsa isError ve kilit bırakılır', async () => {
    const kilit = new CihazKilidi();
    const f: SahteFabrika = {
      acilanlar: [],
      fabrika: async () => {
        throw new Error('ECONNREFUSED 127.0.0.1:4723\nyığın…');
      },
    };
    const { cagir } = await baglan(f, kilit);
    const r = await cagir('app_launch', { platform: 'android' });
    assert.equal(r.isError, true);
    assert.equal(r.metin, '### Hata\nAppium oturumu açılamadı (android): ECONNREFUSED 127.0.0.1:4723');
    assert.equal(kilit.kimde('android'), undefined);
  });
});

describe('eylemler', () => {
  it('app_click: kimlik + sıra ile bulur (yinelenen kimlikte ikinci eleman)', async () => {
    const f = sahteFabrika({ android: androidGiris });
    const { cagir } = await baglan(f);
    await cagir('app_launch', { platform: 'android' });
    const snap = await cagir('app_snapshot');
    const satirlar = snap.metin.split('\n').filter((s) => s.includes('[id=add-to-cart]'));
    const ikinci = /\[ref=(e\d+)\]/.exec(satirlar[1]!)![1]!;
    const r = await cagir('app_click', { ref: ikinci, element: 'P-002 Sepete ekle' });
    assert.match(r.metin, new RegExp(`^### Sonuç\\nTıklandı: P-002 Sepete ekle \\[ref=${ikinci}\\]`));
    const s = f.acilanlar[0]!.surucu;
    const bul = s.cagrilar.find((c) => c.ad === 'bul')!;
    assert.deepEqual(bul.arg, ['-android uiautomator', 'new UiSelector().resourceId("add-to-cart")']);
    const tik = s.cagrilar.find((c) => c.ad === 'tikla')!;
    const d = s.dugum(tik.arg[0] as string)!;
    assert.match(d.xpath, /ViewGroup\[2\]\/android\.view\.ViewGroup\[1\]$/); // P-002 kartının düğmesi
  });

  it('kimliksiz eleman XPath ile bulunur', async () => {
    const f = sahteFabrika({ android: androidGiris });
    const { cagir } = await baglan(f);
    const l = await cagir('app_launch', { platform: 'android' });
    const r = ref(l.metin, /- button "Beni hatırla"/);
    assert.equal((await cagir('app_click', { ref: r })).isError, undefined);
    const bul = f.acilanlar[0]!.surucu.cagrilar.filter((c) => c.ad === 'bul');
    assert.equal(bul.length, 1);
    assert.equal(bul[0]!.arg[0], 'xpath');
  });

  it('son snapshot\'ta olmayan ref ve geçersiz biçim: isError', async () => {
    const { cagir } = await baglan(sahteFabrika({ android: androidGiris }));
    await cagir('app_launch', { platform: 'android' });
    const r = await cagir('app_click', { ref: 'e999' });
    assert.equal(r.isError, true);
    assert.match(r.metin, /ref e999 son snapshot'ta yok; app_snapshot ile güncel ref alın/);
    assert.equal((await cagir('app_click', { ref: '//android.widget.Button' })).isError, true);
  });

  it('eleman artık yoksa: isError', async () => {
    const f = sahteFabrika({ android: androidGiris });
    const { cagir } = await baglan(f);
    const l = await cagir('app_launch', { platform: 'android' });
    const r = ref(l.metin, /- button "Giriş yap"/);
    f.acilanlar[0]!.surucu.kaynaklar = ['<hierarchy><android.widget.FrameLayout bounds="[0,0][1,1]"/></hierarchy>'];
    const s = await cagir('app_click', { ref: r });
    assert.equal(s.isError, true);
    assert.match(s.metin, /eleman bulunamadı/);
  });

  it('app_type: normal alana yazılan metin gösterilir', async () => {
    const f = sahteFabrika({ android: androidGiris });
    const { cagir } = await baglan(f);
    const l = await cagir('app_launch', { platform: 'android' });
    const r = await cagir('app_type', { ref: ref(l.metin, /login-username/), text: 'bayi3', element: 'Kullanıcı adı' });
    assert.match(r.metin, /Yazıldı: "bayi3" → Kullanıcı adı/);
    const ad = f.acilanlar[0]!.surucu.cagrilar.map((c) => c.ad);
    assert.ok(ad.indexOf('temizle') < ad.indexOf('yaz'));
  });

  it('app_type: parola alanında metin hiçbir çıktıda yok (hata dahil)', async () => {
    const f = sahteFabrika({ android: androidGiris });
    const { cagir } = await baglan(f);
    const l = await cagir('app_launch', { platform: 'android' });
    const pr = ref(l.metin, /login-password/);
    const r = await cagir('app_type', { ref: pr, text: 'Gizli-Parola-42' });
    assert.doesNotMatch(r.metin, /Gizli-Parola-42/);
    assert.match(r.metin, /Yazıldı: \*\*\* →/);
    f.acilanlar[0]!.surucu.hataVer.yaz = new Error('cannot set text Gizli-Parola-42');
    const h = await cagir('app_type', { ref: pr, text: 'Gizli-Parola-42' });
    assert.equal(h.isError, true);
    assert.doesNotMatch(h.metin, /Gizli-Parola-42/);
  });

  it('app_type: metin alanı olmayan ref reddedilir', async () => {
    const { cagir } = await baglan(sahteFabrika({ android: androidGiris }));
    const l = await cagir('app_launch', { platform: 'android' });
    const r = await cagir('app_type', { ref: ref(l.metin, /- button "Giriş yap"/), text: 'x' });
    assert.equal(r.isError, true);
    assert.match(r.metin, /bir metin alanı değil \(button\)/);
  });

  it('eylem sonrası ekran değişince yeni snapshot döner; ref\'ler eleman başına kararlı', async () => {
    const f = sahteFabrika({ android: androidGiris });
    const { cagir } = await baglan(f);
    const l = await cagir('app_launch', { platform: 'android' });
    const kayitRef = ref(l.metin, /login-register/);
    const hata = fikstur('android-bayi-giris.xml').replace('Kullanıcı adı veya parola hatalı', 'Bayi bulunamadı');
    f.acilanlar[0]!.surucu.tiklayinca = [hata];
    const r = await cagir('app_click', { ref: ref(l.metin, /- button "Giriş yap"/) });
    assert.match(r.metin, /- text "Bayi bulunamadı" \[id=login-error\]/);
    assert.equal(ref(r.metin, /login-register/), kayitRef);
    assert.notEqual(ref(r.metin, /login-error/), ref(l.metin, /login-error/));
  });
});

describe('app_select_option', () => {
  it('Android Spinner: aç → seçeneği adıyla bul → tıkla', async () => {
    const f = sahteFabrika({ android: androidGiris });
    const { cagir } = await baglan(f);
    const l = await cagir('app_launch', { platform: 'android' });
    const acik = `<hierarchy><android.widget.ListView bounds="[0,0][100,100]" displayed="true">
      <android.widget.CheckedTextView text="Türkçe" checkable="true" checked="true" clickable="true" bounds="[0,0][100,50]" displayed="true"/>
      <android.widget.CheckedTextView text="English" checkable="true" checked="false" clickable="true" bounds="[0,50][100,100]" displayed="true"/>
    </android.widget.ListView></hierarchy>`;
    f.acilanlar[0]!.surucu.tiklayinca = [acik];
    const r = await cagir('app_select_option', { ref: ref(l.metin, /login-language/), values: ['English'] });
    assert.equal(r.isError, undefined, r.metin);
    const s = f.acilanlar[0]!.surucu;
    const tiklar = s.cagrilar.filter((c) => c.ad === 'tikla');
    assert.equal(tiklar.length, 2);
    assert.equal(s.dugum(tiklar[1]!.arg[0] as string)!.oz.text, 'English');
  });

  it('iOS çark: değer doğrudan yazılır', async () => {
    const f = sahteFabrika({ ios: () => [fikstur('ios-bayi-giris.xml')] });
    const { cagir } = await baglan(f);
    const l = await cagir('app_launch', { platform: 'ios' });
    const r = await cagir('app_select_option', { ref: ref(l.metin, /- combobox \[ref=e\d+\]: Türkçe/), values: ['English'] });
    assert.equal(r.isError, undefined, r.metin);
    const yaz = f.acilanlar[0]!.surucu.cagrilar.find((c) => c.ad === 'yaz')!;
    assert.equal(yaz.arg[1], 'English');
  });

  it('birden çok değer ve bulunamayan seçenek: isError', async () => {
    const { cagir } = await baglan(sahteFabrika({ android: androidGiris }));
    const l = await cagir('app_launch', { platform: 'android' });
    const r1 = await cagir('app_select_option', { ref: ref(l.metin, /login-language/), values: ['a', 'b'] });
    assert.equal(r1.isError, true);
    const r2 = await cagir('app_select_option', { ref: ref(l.metin, /login-language/), values: ['Klingonca'] });
    assert.equal(r2.isError, true);
    assert.match(r2.metin, /seçenek bulunamadı: "Klingonca"/);
  });
});

describe('app_wait_for', () => {
  it('text: metin görünene dek yoklar', async () => {
    const bos = '<hierarchy><android.widget.FrameLayout bounds="[0,0][1,1]"/></hierarchy>';
    const f = sahteFabrika({ android: () => [bos, bos, bos, bos, bos, bos, fikstur('android-bayi-giris.xml')] });
    const { cagir } = await baglan(f);
    await cagir('app_launch', { platform: 'android' });
    const r = await cagir('app_wait_for', { text: 'parola hatalı' });
    assert.equal(r.isError, undefined, r.metin);
    assert.match(r.metin, /Göründü: "parola hatalı"/);
  });

  it('textGone ve zaman aşımı', async () => {
    const { cagir } = await baglan(sahteFabrika({ android: androidGiris }));
    await cagir('app_launch', { platform: 'android' });
    assert.match((await cagir('app_wait_for', { textGone: 'yok-boyle-metin' })).metin, /Kayboldu/);
    const r = await cagir('app_wait_for', { textGone: 'Giriş yap' });
    assert.equal(r.isError, true);
    assert.match(r.metin, /2 sn içinde kaybolmadı: "Giriş yap"/);
  });

  it('parola değeri (***) metin olarak beklenemez', async () => {
    const { cagir } = await baglan(sahteFabrika({ android: androidGiris }));
    await cagir('app_launch', { platform: 'android' });
    assert.equal((await cagir('app_wait_for', { text: '***' })).isError, true);
  });

  it('time üst sınırı ve tek parametre kuralı', async () => {
    const { cagir } = await baglan(sahteFabrika({ android: androidGiris }));
    await cagir('app_launch', { platform: 'android' });
    assert.match((await cagir('app_wait_for', { time: 60 })).metin, /time 0 < t ≤ 2 saniye olmalı/);
    assert.equal((await cagir('app_wait_for', {})).isError, true);
    assert.equal((await cagir('app_wait_for', { text: 'a', time: 1 })).isError, true);
    assert.match((await cagir('app_wait_for', { time: 0.1 })).metin, /0\.1 sn beklendi/);
  });
});

describe('app_generate_locator', () => {
  for (const [platform, xml, strateji] of [
    ['android', 'android-bayi-giris.xml', 'id'],
    ['ios', 'ios-bayi-giris.xml', 'accessibilityId'],
    ['windows', 'windows-bayi-giris.xml', 'accessibilityId'],
  ] as const) {
    it(`${platform}: {platform, strategy, id}`, async () => {
      const { cagir } = await baglan(sahteFabrika({ [platform]: () => [fikstur(xml)] }));
      const l = await cagir('app_launch', { platform });
      const r = await cagir('app_generate_locator', { ref: ref(l.metin, /login-submit/) });
      assert.equal(r.metin, `### Locator\n${JSON.stringify({ platform, strategy: strateji, id: 'login-submit' })}`);
    });
  }

  it('kimliksiz eleman: id null + uyarı', async () => {
    const { cagir } = await baglan(sahteFabrika({ ios: () => [fikstur('ios-bayi-giris.xml')] }));
    const l = await cagir('app_launch', { platform: 'ios' });
    const r = await cagir('app_generate_locator', { ref: ref(l.metin, /- button "Kayıt ol"/) });
    assert.match(r.metin, /^### Locator\n\{"platform":"ios","strategy":"accessibilityId","id":null\}\nUyarı:/);
  });
});

describe('app_screenshot ve kapanış', () => {
  it('PNG görüntü içeriği döner', async () => {
    const { cagir } = await baglan(sahteFabrika({ android: androidGiris }));
    await cagir('app_launch', { platform: 'android' });
    const r = await cagir('app_screenshot');
    const img = r.content.find((c) => c.type === 'image') as { data: string; mimeType: string };
    assert.equal(img.mimeType, 'image/png');
    assert.equal(Buffer.from(img.data, 'base64').toString(), 'png');
  });

  it('oturum kapanınca Appium oturumu kapanır, kilit bırakılır (idempotent)', async () => {
    const kilit = new CihazKilidi();
    const f = sahteFabrika({ android: androidGiris });
    const { cagir, oturum } = await baglan(f, kilit);
    await cagir('app_launch', { platform: 'android' });
    assert.equal(kilit.kimde('android'), 'oturum-1');
    await oturum.kapat();
    await oturum.kapat();
    assert.equal(f.acilanlar[0]!.surucu.kapali, true);
    assert.equal(kilit.kimde('android'), undefined);
    assert.equal((await cagir('app_snapshot')).isError, true);
  });
});
