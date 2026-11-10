/** Testler için sahte Appium sürücüsü: kaydedilmiş XML kaynakları üstünde eleman arama. */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { kaynakAyristir, type Dugum } from '../src/agac.js';
import type { Strateji, Surucu, SurucuFabrikasi } from '../src/surucu.js';
import { ayarlariOku, type Ayarlar, type PlatformAyari } from '../src/yapilandirma.js';

// dist/test/… → kaynak ağacındaki test/fixtures
export const FIKSTUR = join(dirname(fileURLToPath(import.meta.url)), '../../test/fixtures');
export const fikstur = (ad: string): string => readFileSync(join(FIKSTUR, ad), 'utf8');

export interface Cagri {
  ad: string;
  arg: unknown[];
}

function hepsi(d: Dugum, out: Dugum[] = []): Dugum[] {
  out.push(d);
  d.cocuklar.forEach((c) => hepsi(c, out));
  return out;
}

/** Kaynak listesi: `kaynak()` her çağrıda sıradakini döndürür, son eleman tekrarlanır. */
export class SahteSurucu implements Surucu {
  cagrilar: Cagri[] = [];
  kapali = false;
  private elemanlar = new Map<string, Dugum>();
  private sayac = 0;
  /** Bir sonraki tıklamada kaynak listesini bununla değiştir (ekran geçişi). */
  tiklayinca: string[] | undefined;
  hataVer: Partial<Record<keyof Surucu, Error>> = {};

  constructor(public kaynaklar: string[]) {}

  private kayit(ad: string, ...arg: unknown[]): void {
    this.cagrilar.push({ ad, arg });
    const h = this.hataVer[ad as keyof Surucu];
    if (h) throw h;
  }

  private simdiki(): string {
    return this.kaynaklar[0]!;
  }

  async kaynak(): Promise<string> {
    this.kayit('kaynak');
    const x = this.simdiki();
    if (this.kaynaklar.length > 1) this.kaynaklar.shift();
    return x;
  }

  async bul(strateji: Strateji, deger: string): Promise<string[]> {
    this.kayit('bul', strateji, deger);
    const dugumler = hepsi(kaynakAyristir(this.simdiki()));
    let eslesen: Dugum[];
    if (strateji === 'xpath') {
      eslesen = dugumler.filter((d) => d.xpath === deger);
    } else if (strateji === '-android uiautomator') {
      const m = /resourceId\("((?:[^"\\]|\\.)*)"\)/.exec(deger);
      const id = m ? m[1]!.replace(/\\(.)/g, '$1') : '';
      eslesen = dugumler.filter((d) => d.oz['resource-id'] === id);
    } else if (strateji === '-ios predicate string') {
      const m = /^name == "((?:[^"\\]|\\.)*)"$/.exec(deger);
      const id = m ? m[1]!.replace(/\\(.)/g, '$1') : '';
      eslesen = dugumler.filter((d) => d.oz.name === id);
    } else {
      eslesen = dugumler.filter((d) => d.oz.AutomationId === deger || d.oz.name === deger);
    }
    return eslesen.map((d) => {
      const k = `el-${++this.sayac}`;
      this.elemanlar.set(k, d);
      return k;
    });
  }

  /** Eleman kimliğinin işaret ettiği düğüm (doğrulama için). */
  dugum(eleman: string): Dugum | undefined {
    return this.elemanlar.get(eleman);
  }

  async tikla(e: string): Promise<void> {
    this.kayit('tikla', e);
    if (this.tiklayinca) {
      this.kaynaklar = this.tiklayinca;
      this.tiklayinca = undefined;
    }
  }
  async temizle(e: string): Promise<void> {
    this.kayit('temizle', e);
  }
  async yaz(e: string, metin: string): Promise<void> {
    this.kayit('yaz', e, metin);
  }
  async ekranGoruntusu(): Promise<string> {
    this.kayit('ekranGoruntusu');
    return Buffer.from('png').toString('base64');
  }
  async uygulamayiSonlandir(k: string): Promise<void> {
    this.kayit('uygulamayiSonlandir', k);
  }
  async uygulamayiEtkinlestir(k: string): Promise<void> {
    this.kayit('uygulamayiEtkinlestir', k);
  }
  async kapat(): Promise<void> {
    this.kayit('kapat');
    this.kapali = true;
  }
}

export interface SahteFabrika {
  fabrika: SurucuFabrikasi;
  acilanlar: { ayar: PlatformAyari; sifirla: boolean; surucu: SahteSurucu }[];
}

/** Her oturum açılışında platformun kaynaklarıyla yeni sahte sürücü. */
export function sahteFabrika(kaynaklar: Partial<Record<string, () => string[]>>): SahteFabrika {
  const acilanlar: SahteFabrika['acilanlar'] = [];
  return {
    acilanlar,
    fabrika: async (ayar, ek) => {
      const k = kaynaklar[ayar.platform];
      if (!k) throw new Error(`sahte: ${ayar.platform} kaynağı yok`);
      const surucu = new SahteSurucu(k());
      acilanlar.push({ ayar, sifirla: ek.sifirla, surucu });
      return surucu;
    },
  };
}

export function testAyarlari(ek: Record<string, string> = {}): Ayarlar {
  return ayarlariOku({
    APPIUM_URL_ANDROID: 'http://127.0.0.1:4723',
    APP_ANDROID_PACKAGE: 'com.antreklabs.bayi',
    APPIUM_URL_IOS: 'http://127.0.0.1:4723',
    APP_IOS_BUNDLE_ID: 'com.antreklabs.bayi',
    APPIUM_URL_WINDOWS: 'http://10.0.0.5:4723',
    APP_WINDOWS_APP: 'C:\\Bayi\\Bayi.exe',
    APP_MCP_WAIT_MAX_S: '2',
    ...ek,
  });
}
