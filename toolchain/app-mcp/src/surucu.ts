/**
 * Appium sürücü katmanı: araçların kullandığı dar arayüz + WebdriverIO (W3C, remote) uygulaması.
 * Testler bu arayüzün sahtesini kullanır (gerçek Appium gerekmez).
 *
 * Bu katman ajana açılmaz; `mobile:` uzantıları yalnızca burada, sabit adlarla (uygulamayı
 * sonlandır / etkinleştir) ve yapılandırılmış uygulama kimliğiyle çağrılır.
 */
import type { PlatformAyari } from './yapilandirma.js';

export type Strateji = 'accessibility id' | '-android uiautomator' | '-ios predicate string' | 'xpath';

export interface Surucu {
  kaynak(): Promise<string>;
  /** Eşleşen elemanların W3C eleman kimlikleri (kaynak sırasında). */
  bul(strateji: Strateji, deger: string): Promise<string[]>;
  tikla(eleman: string): Promise<void>;
  temizle(eleman: string): Promise<void>;
  yaz(eleman: string, metin: string): Promise<void>;
  /** PNG, base64. */
  ekranGoruntusu(): Promise<string>;
  uygulamayiSonlandir(kimlik: string): Promise<void>;
  uygulamayiEtkinlestir(kimlik: string): Promise<void>;
  kapat(): Promise<void>;
}

export type SurucuFabrikasi = (ayar: PlatformAyari, ek: { sifirla: boolean; zamanAsimiMs: number }) => Promise<Surucu>;

const W3C_ELEMAN = 'element-6066-11e4-a52e-4f735466cecf';

function elemanKimligi(e: unknown): string {
  const o = e as Record<string, string>;
  const k = o[W3C_ELEMAN] ?? o.ELEMENT;
  if (!k) throw new Error('sürücü eleman kimliği döndürmedi');
  return k;
}

/** WebdriverIO `remote` ile Appium oturumu açar. */
export const wdioFabrikasi: SurucuFabrikasi = async (ayar, ek) => {
  const { remote } = await import('webdriverio');
  const u = ayar.appiumUrl;
  const yetenekler: Record<string, unknown> = { ...ayar.yetenekler, 'appium:noReset': !ek.sifirla };
  const tarayici = await remote({
    protocol: u.protocol.replace(':', '') as 'http' | 'https',
    hostname: u.hostname,
    port: Number(u.port || (u.protocol === 'https:' ? 443 : 80)),
    path: u.pathname && u.pathname !== '' ? u.pathname : '/',
    capabilities: yetenekler as WebdriverIO.Capabilities,
    logLevel: 'silent',
    connectionRetryTimeout: ek.zamanAsimiMs,
    connectionRetryCount: 0,
  });
  return {
    kaynak: () => tarayici.getPageSource(),
    async bul(strateji, deger) {
      const sonuc = (await tarayici.findElements(strateji, deger)) as unknown[];
      return sonuc.map(elemanKimligi);
    },
    async tikla(e) {
      await tarayici.elementClick(e);
    },
    async temizle(e) {
      await tarayici.elementClear(e);
    },
    async yaz(e, metin) {
      await tarayici.elementSendKeys(e, metin);
    },
    ekranGoruntusu: () => tarayici.takeScreenshot(),
    async uygulamayiSonlandir(kimlik) {
      await tarayici.execute('mobile: terminateApp', {
        [ayar.platform === 'ios' ? 'bundleId' : 'appId']: kimlik,
      });
    },
    async uygulamayiEtkinlestir(kimlik) {
      await tarayici.execute('mobile: activateApp', {
        [ayar.platform === 'ios' ? 'bundleId' : 'appId']: kimlik,
      });
    },
    async kapat() {
      await tarayici.deleteSession();
    },
  };
};
