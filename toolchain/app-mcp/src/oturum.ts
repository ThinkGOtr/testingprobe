/**
 * Bir MCP oturumunun uygulama oturumu: tek Appium oturumu, son snapshot'ın ref tablosu ve araç
 * mantığı. Araç çağrıları sırayla yürütülür (aynı Appium oturumunda çakışan komut yok).
 *
 * Ref'ler oturum içinde kararlıdır: aynı eleman (kimlik + sıra, kimlik yoksa XPath) sonraki
 * snapshot'larda aynı `eN`'i alır; `app_launch` tabloyu sıfırlar. Eylemler yalnızca SON
 * snapshot'taki ref'leri kabul eder.
 */
import {
  duzlestir,
  gorunurMetinler,
  kaynakAyristir,
  ogelereCevir,
  PAROLA_MASKESI,
  snapshotYaz,
  type Oge,
  type Platform,
} from './agac.js';
import type { Strateji, Surucu, SurucuFabrikasi } from './surucu.js';
import type { Ayarlar } from './yapilandirma.js';

/** Ajanın göreceği hata (isError sonucu); iç ayrıntı sızdırmaz. */
export class AracHatasi extends Error {}

export interface AracCiktisi {
  metin: string;
  /** PNG base64 (yalnızca app_screenshot). */
  resim?: string;
}

/** Platform başına tek cihaz: aynı anda yalnızca bir MCP oturumu o cihazı sürer. */
export class CihazKilidi {
  private readonly sahip = new Map<Platform, string>();
  al(platform: Platform, oturum: string): void {
    const s = this.sahip.get(platform);
    if (s !== undefined && s !== oturum) {
      throw new AracHatasi(`${platform} cihazı başka bir MCP oturumunda kullanılıyor; o oturum kapanınca tekrar deneyin`);
    }
    this.sahip.set(platform, oturum);
  }
  birak(platform: Platform, oturum: string): void {
    if (this.sahip.get(platform) === oturum) this.sahip.delete(platform);
  }
  kimde(platform: Platform): string | undefined {
    return this.sahip.get(platform);
  }
}

const bekle = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
const YOKLAMA_MS = 500;
/** Eylemden sonra ekranın durulmasını bekleme: art arda iki aynı kaynak ya da üst sınır. */
const DURULMA_ARALIK_MS = 300;
const DURULMA_MAKS_MS = 3000;
const SECENEK_BEKLEME_MS = 5000;

function javaDizesi(s: string): string {
  return `"${s.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}

function yuklemDizesi(s: string): string {
  return `"${s.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}

function hataMetni(e: unknown): string {
  const m = e instanceof Error ? e.message : String(e);
  // Sürücü hatalarının ilk satırı yeterli (yığın / iç yol yok).
  return m.split('\n')[0]!.slice(0, 300);
}

export class AppOturumu {
  private surucu: Surucu | undefined;
  private platform: Platform | undefined;
  private refSayaci = 0;
  private readonly refAnahtar = new Map<string, string>();
  private refler = new Map<string, Oge>();
  private sira: Promise<unknown> = Promise.resolve();
  sonEtkinlik = Date.now();
  private aktifCagri = 0;

  constructor(
    readonly kimlik: string,
    private readonly ayar: Ayarlar,
    private readonly fabrika: SurucuFabrikasi,
    private readonly kilit: CihazKilidi,
  ) {}

  get aktifPlatform(): Platform | undefined {
    return this.platform;
  }

  /** Yürüyen ya da sırada bekleyen araç çağrısı var mı (boşta kapatma bunu atlar)? */
  get mesgul(): boolean {
    return this.aktifCagri > 0;
  }

  /** Çağrıları sıraya koyar (aynı oturumda eşzamanlı Appium komutu olmaz). */
  calistir<T>(is: () => Promise<T>): Promise<T> {
    this.sonEtkinlik = Date.now();
    this.aktifCagri++;
    const sonuc = this.sira.then(is, is);
    this.sira = sonuc.catch(() => undefined);
    return sonuc.finally(() => {
      this.aktifCagri--;
      this.sonEtkinlik = Date.now();
    });
  }

  // ------------------------------------------------------------------------------- araçlar

  async baslat(platform: Platform, sifirla: boolean): Promise<AracCiktisi> {
    const pa = this.ayar.platformlar[platform];
    if (!pa) {
      const acik = Object.keys(this.ayar.platformlar).join(', ') || 'yok';
      throw new AracHatasi(`${platform} platformu yapılandırılmamış (açık platformlar: ${acik})`);
    }
    const yeniden = this.surucu !== undefined && this.platform === platform && !sifirla && platform !== 'windows';
    if (yeniden) {
      try {
        await this.surucu!.uygulamayiSonlandir(pa.uygulamaKimligi);
        await this.surucu!.uygulamayiEtkinlestir(pa.uygulamaKimligi);
      } catch (e) {
        throw new AracHatasi(`uygulama yeniden başlatılamadı: ${hataMetni(e)}`);
      }
    } else {
      await this.kapat();
      this.kilit.al(platform, this.kimlik);
      try {
        this.surucu = await this.fabrika(pa, { sifirla, zamanAsimiMs: this.ayar.oturumAcmaSn * 1000 });
      } catch (e) {
        this.kilit.birak(platform, this.kimlik);
        throw new AracHatasi(`Appium oturumu açılamadı (${platform}): ${hataMetni(e)}`);
      }
      this.platform = platform;
    }
    this.refAnahtar.clear();
    this.refler.clear();
    this.refSayaci = 0;
    const kip = yeniden ? 'yeniden başlatıldı' : sifirla ? 'verisi sıfırlanarak başlatıldı' : 'başlatıldı';
    return this.sonucla(`Uygulama ${kip}: ${pa.uygulamaKimligi} (${platform})`);
  }

  async snapshot(): Promise<AracCiktisi> {
    return this.sonucla(undefined);
  }

  async tikla(ref: string, eleman: string | undefined): Promise<AracCiktisi> {
    const o = this.refCoz(ref);
    const e = await this.elemanBul(o, ref);
    try {
      await this.surucuAl().tikla(e);
    } catch (err) {
      throw new AracHatasi(`tıklanamadı (${ref}): ${hataMetni(err)}`);
    }
    return this.sonucla(`Tıklandı: ${this.tarif(o, eleman)} [ref=${ref}]`);
  }

  async yaz(ref: string, metin: string, eleman: string | undefined): Promise<AracCiktisi> {
    const o = this.refCoz(ref);
    if (o.rol !== 'textbox' && o.rol !== 'combobox') {
      throw new AracHatasi(`${ref} bir metin alanı değil (${o.rol}); textbox ref'i verin`);
    }
    const e = await this.elemanBul(o, ref);
    const s = this.surucuAl();
    try {
      await s.temizle(e);
      if (metin !== '') await s.yaz(e, metin);
    } catch (err) {
      // Sürücü hatası yazılan metni içerebilir: parola alanında hata metni gösterilmez.
      throw new AracHatasi(`yazılamadı (${ref})${o.parola ? '' : `: ${hataMetni(err)}`}`);
    }
    const gosterilen = o.parola ? PAROLA_MASKESI : JSON.stringify(metin);
    return this.sonucla(`Yazıldı: ${gosterilen} → ${this.tarif(o, eleman)} [ref=${ref}]`);
  }

  async secenekSec(ref: string, degerler: string[], eleman: string | undefined): Promise<AracCiktisi> {
    if (degerler.length !== 1) throw new AracHatasi('mobil seçicide tek değer seçilebilir (values: ["…"])');
    const deger = degerler[0]!;
    const o = this.refCoz(ref);
    const s = this.surucuAl();
    const tur = o.tip.replace(/^XCUIElementType/, '');
    if (tur === 'PickerWheel' || tur === 'Picker') {
      // iOS çark: değere doğrudan ayarlanır.
      const hedef = tur === 'PickerWheel' ? o : (duzlestir(o.cocuklar).find((c) => c.tip.endsWith('PickerWheel')) ?? o);
      const e = await this.elemanBul(hedef, ref);
      try {
        await s.yaz(e, deger);
      } catch (err) {
        throw new AracHatasi(`seçilemedi (${ref}): ${hataMetni(err)}`);
      }
    } else {
      // Açılır liste (Android Spinner, Windows ComboBox, özel seçiciler): aç → seçeneği bul → tıkla.
      const e = await this.elemanBul(o, ref);
      try {
        await s.tikla(e);
      } catch (err) {
        throw new AracHatasi(`seçici açılamadı (${ref}): ${hataMetni(err)}`);
      }
      const son = Date.now() + SECENEK_BEKLEME_MS;
      let secenek: Oge | undefined;
      for (;;) {
        const ogeler = await this.agacAl();
        secenek = duzlestir(ogeler).find((c) => c.ad === deger && c.konum.xpath !== o.konum.xpath && c.rol !== 'textbox');
        if (secenek || Date.now() > son) break;
        await bekle(YOKLAMA_MS);
      }
      if (!secenek) throw new AracHatasi(`seçenek bulunamadı: ${JSON.stringify(deger)}`);
      const se = await this.elemanBul(secenek, ref);
      try {
        await s.tikla(se);
      } catch (err) {
        throw new AracHatasi(`seçenek tıklanamadı: ${hataMetni(err)}`);
      }
    }
    return this.sonucla(`Seçildi: ${JSON.stringify(deger)} → ${this.tarif(o, eleman)} [ref=${ref}]`);
  }

  async bekle(arg: { text?: string | undefined; textGone?: string | undefined; time?: number | undefined }): Promise<AracCiktisi> {
    const maks = this.ayar.beklemeMaksSn;
    const verilen = [arg.text, arg.textGone, arg.time].filter((v) => v !== undefined).length;
    if (verilen !== 1) throw new AracHatasi('text, textGone ya da time parametrelerinden tam olarak biri verilmeli');
    this.surucuAl();
    if (arg.time !== undefined) {
      if (!(arg.time > 0) || arg.time > maks) throw new AracHatasi(`time 0 < t ≤ ${maks} saniye olmalı`);
      await bekle(arg.time * 1000);
      return this.sonucla(`${arg.time} sn beklendi`);
    }
    const aranan = (arg.text ?? arg.textGone)!;
    if (!aranan.trim()) throw new AracHatasi('aranan metin boş olamaz');
    const gorunmeli = arg.text !== undefined;
    const son = Date.now() + maks * 1000;
    for (;;) {
      const ogeler = await this.agacAl();
      const var_ = gorunurMetinler(ogeler).some((m) => m.includes(aranan));
      if (var_ === gorunmeli) {
        return this.sonucla(`${gorunmeli ? 'Göründü' : 'Kayboldu'}: ${JSON.stringify(aranan)}`, ogeler);
      }
      if (Date.now() > son) {
        throw new AracHatasi(`${maks} sn içinde ${gorunmeli ? 'görünmedi' : 'kaybolmadı'}: ${JSON.stringify(aranan)}`);
      }
      await bekle(YOKLAMA_MS);
    }
  }

  async locator(ref: string): Promise<AracCiktisi> {
    const o = this.refCoz(ref);
    const platform = this.platform!;
    const strateji = platform === 'android' ? 'id' : 'accessibilityId';
    const sonuc = { platform, strategy: strateji, id: o.id ?? null };
    const not = o.id ? '' : '\nUyarı: elemanın erişilebilirlik kimliği yok (locator eksik).';
    return { metin: `### Locator\n${JSON.stringify(sonuc)}${not}` };
  }

  async ekranGoruntusu(): Promise<AracCiktisi> {
    const s = this.surucuAl();
    let png: string;
    try {
      png = await s.ekranGoruntusu();
    } catch (e) {
      throw new AracHatasi(`ekran görüntüsü alınamadı: ${hataMetni(e)}`);
    }
    return { metin: 'Ekran görüntüsü', resim: png };
  }

  /** Appium oturumunu kapatır, cihaz kilidini bırakır (idempotent). */
  async kapat(): Promise<void> {
    const s = this.surucu;
    const p = this.platform;
    this.surucu = undefined;
    this.platform = undefined;
    this.refler.clear();
    if (p) this.kilit.birak(p, this.kimlik);
    if (s) {
      try {
        await s.kapat();
      } catch {
        // oturum zaten düşmüş olabilir
      }
    }
  }

  // ------------------------------------------------------------------------------ yardımcı

  private surucuAl(): Surucu {
    if (!this.surucu) throw new AracHatasi('Uygulama başlatılmadı: önce app_launch çağırın');
    return this.surucu;
  }

  private tarif(o: Oge, eleman: string | undefined): string {
    const ad = eleman?.trim() || [o.rol, o.ad && JSON.stringify(o.ad)].filter(Boolean).join(' ');
    return ad.slice(0, 120);
  }

  private refCoz(ref: string): Oge {
    this.surucuAl();
    const o = this.refler.get(ref);
    if (!o) throw new AracHatasi(`ref ${ref} son snapshot'ta yok; app_snapshot ile güncel ref alın`);
    return o;
  }

  private async kaynakAl(): Promise<string> {
    const s = this.surucuAl();
    try {
      return await s.kaynak();
    } catch (e) {
      throw new AracHatasi(`sayfa kaynağı alınamadı: ${hataMetni(e)}`);
    }
  }

  /** Güncel ağaç. `durulma`: eylem sonrası geçiş animasyonu bitene dek (kaynak değişmeyene dek) bekler. */
  private async agacAl(durulma = false): Promise<Oge[]> {
    let xml = await this.kaynakAl();
    if (durulma) {
      const son = Date.now() + DURULMA_MAKS_MS;
      while (Date.now() < son) {
        await bekle(DURULMA_ARALIK_MS);
        const yeni = await this.kaynakAl();
        if (yeni === xml) break;
        xml = yeni;
      }
    }
    return ogelereCevir(kaynakAyristir(xml), this.platform!);
  }

  private refVer(o: Oge): string {
    // Anahtar = konum + rol + ad: aynı eleman sonraki snapshot'larda aynı ref'i alır; başka ekranda
    // aynı kimlik/konumu taşıyan farklı eleman (ör. liste satırı başlığı) yeni ref alır.
    const yer = o.konum.id ? `i:${o.konum.id.deger}#${o.konum.id.sira}` : `x:${o.konum.xpath}`;
    const anahtar = `${yer}|${o.rol}|${o.ad}`;
    let ref = this.refAnahtar.get(anahtar);
    if (!ref) {
      ref = `e${++this.refSayaci}`;
      this.refAnahtar.set(anahtar, ref);
    }
    return ref;
  }

  /** Elemanı sürücüde bulur: kimlik (+sıra) → yoksa / tutmazsa XPath. */
  private async elemanBul(o: Oge, ref: string): Promise<string> {
    const s = this.surucuAl();
    const id = o.konum.id;
    try {
      if (id) {
        const [strateji, deger] = this.kimlikSorgusu(id.deger);
        const bulunan = await s.bul(strateji, deger);
        if (bulunan.length > id.sira) return bulunan[id.sira]!;
      }
      const x = await s.bul('xpath', o.konum.xpath);
      if (x.length > 0) return x[0]!;
    } catch (e) {
      throw new AracHatasi(`eleman aranamadı (${ref}): ${hataMetni(e)}`);
    }
    throw new AracHatasi(`eleman bulunamadı (${ref}); ekran değişmiş olabilir, app_snapshot alın`);
  }

  private kimlikSorgusu(id: string): [Strateji, string] {
    switch (this.platform) {
      case 'android':
        return ['-android uiautomator', `new UiSelector().resourceId(${javaDizesi(id)})`];
      case 'ios':
        return ['-ios predicate string', `name == ${yuklemDizesi(id)}`];
      default:
        return ['accessibility id', id];
    }
  }

  /** Sonuç metni: isteğe bağlı mesaj + uygulama bilgisi + güncel snapshot (ref tablosu yenilenir). */
  private async sonucla(mesaj: string | undefined, hazir?: Oge[]): Promise<AracCiktisi> {
    // Eylem sonuçlarında (mesaj var) ekranın durulması beklenir; düz snapshot anlık alınır.
    const ogeler = hazir ?? (await this.agacAl(mesaj !== undefined));
    const yeni = new Map<string, Oge>();
    const snap = snapshotYaz(ogeler, {
      ref: (o) => {
        const r = this.refVer(o);
        yeni.set(r, o);
        return r;
      },
      maksSatir: this.ayar.snapshotMaksSatir,
      maksKarakter: this.ayar.snapshotMaksKarakter,
    });
    this.refler = yeni;
    const pa = this.ayar.platformlar[this.platform!]!;
    const parcalar: string[] = [];
    if (mesaj) parcalar.push(`### Sonuç\n${mesaj}`);
    parcalar.push(`### Uygulama\n- Platform: ${this.platform}\n- Uygulama: ${pa.uygulamaKimligi}`);
    const govde = snap.metin || '- (ekranda erişilebilir eleman yok)';
    const kesik = snap.kesildi ? `\n(Snapshot ${snap.satir} satırda kesildi.)` : '';
    parcalar.push(`### Snapshot\n\`\`\`yaml\n${govde}\n\`\`\`${kesik}`);
    return { metin: parcalar.join('\n') };
  }
}
