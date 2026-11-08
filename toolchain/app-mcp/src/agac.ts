/**
 * Sayfa kaynağı (Appium XML) → sadeleştirilmiş erişilebilirlik ağacı (saf, deterministik).
 *
 * Üç sürücünün kaynağı farklıdır:
 *   - Android (UiAutomator2): etiket = sınıf adı (`android.widget.Button`), `text`,
 *     `content-desc`, `resource-id`, `bounds="[x1,y1][x2,y2]"`, `displayed`, `password` …
 *   - iOS (XCUITest): etiket = `XCUIElementType…`, `name` (= accessibilityIdentifier, yoksa
 *     label), `label`, `value`, `visible`, `x/y/width/height` …
 *   - Windows (NovaWindows/UIA): etiket = ControlType (`Button`, `Edit` …), `Name`,
 *     `AutomationId`, `IsOffscreen`, `IsPassword`, `x/y/width/height` …
 * Her biri ortak bir role (button, textbox, text, checkbox, switch, list, listitem, image …)
 * indirgenir. Görünmeyen / sıfır boyutlu / süs (adsız resim, düzen kabı) düğümler atılır; anlamsız
 * kaplar düzleştirilir (çocukları üst düzeye çıkar).
 *
 * Çıktı Playwright MCP aria snapshot'ının ruhundadır: satır başına bir eleman,
 *   `- <rol> "<ad>" [id=<kimlik>] [disabled] [checked] [ref=eN]: <değer>`
 * Ref'leri `Oturum` atar (oturum içinde kararlı); bu modül yalnızca ağacı üretir.
 */
import { XMLParser } from 'fast-xml-parser';

export type Platform = 'android' | 'ios' | 'windows';
export const PLATFORMLAR: readonly Platform[] = ['android', 'ios', 'windows'];

/** Ham XML düğümü (kaynak sırası korunur). */
export interface Dugum {
  etiket: string;
  oz: Record<string, string>;
  cocuklar: Dugum[];
  /** Kaynağa göre mutlak XPath (`/hierarchy/android.widget.FrameLayout[1]/…`). */
  xpath: string;
}

/** Elemanı yeniden bulmak için konum bilgisi (sunucu tarafında tutulur, ajana gösterilmez). */
export interface Konum {
  /** Kimlik varsa: kaynakta bu kimliği taşıyan elemanlar arasındaki sıra (0 tabanlı). */
  id?: { deger: string; sira: number };
  xpath: string;
}

/** Ortak role indirgenmiş, anlamlı eleman. */
export interface Oge {
  rol: string;
  ad: string;
  /** Alan değeri (textbox, combobox, slider); parola alanında asla düz metin değil. */
  deger?: string;
  id?: string;
  durumlar: string[];
  parola: boolean;
  /** Sürücüdeki özgün tür (`android.widget.EditText`, `XCUIElementTypePickerWheel` …). */
  tip: string;
  konum: Konum;
  cocuklar: Oge[];
}

export const PAROLA_MASKESI = '***';
const MAKS_AD = 120;
const GIZLI_AD = /parola|password|sifre|şifre|passcode/i;

// ------------------------------------------------------------------------------- XML ayrıştırma

const ayristirici = new XMLParser({
  preserveOrder: true,
  ignoreAttributes: false,
  attributeNamePrefix: '',
  parseAttributeValue: false,
  parseTagValue: false,
  trimValues: false,
  processEntities: true,
  htmlEntities: true,
});

type HamDugum = Record<string, unknown> & { ':@'?: Record<string, unknown> };

function dugumAdi(ham: HamDugum): string | undefined {
  return Object.keys(ham).find((k) => k !== ':@' && !k.startsWith('#') && !k.startsWith('?'));
}

function ozellikler(ham: HamDugum): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(ham[':@'] ?? {})) out[k] = String(v);
  return out;
}

function kur(ham: HamDugum, ust: string, sira: number): Dugum {
  const etiket = dugumAdi(ham) as string;
  const xpath = `${ust}/${etiket}${ust === '' ? '' : `[${sira}]`}`;
  const sayac = new Map<string, number>();
  const cocuklar: Dugum[] = [];
  for (const c of (ham[etiket] as HamDugum[] | undefined) ?? []) {
    const ad = dugumAdi(c);
    if (ad === undefined) continue;
    const n = (sayac.get(ad) ?? 0) + 1;
    sayac.set(ad, n);
    cocuklar.push(kur(c, xpath, n));
  }
  return { etiket, oz: ozellikler(ham), cocuklar, xpath };
}

/** XML kaynağını ağaca çevirir; kök eleman yoksa hata. */
export function kaynakAyristir(xml: string): Dugum {
  let ham: HamDugum[];
  try {
    ham = ayristirici.parse(xml) as HamDugum[];
  } catch (e) {
    throw new Error(`sayfa kaynağı ayrıştırılamadı: ${(e as Error).message}`);
  }
  const kok = ham.find((h) => dugumAdi(h) !== undefined);
  if (!kok) throw new Error('sayfa kaynağında kök eleman yok');
  return kur(kok, '', 1);
}

// ---------------------------------------------------------------------------- platform kuralları

function sade(metin: string | undefined): string {
  const s = (metin ?? '').replace(/\s+/g, ' ').trim();
  return s.length > MAKS_AD ? `${s.slice(0, MAKS_AD - 1)}…` : s;
}

function sayi(v: string | undefined): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

interface Uyarlayici {
  /** Kimlik özniteliği (konum sırası bu özniteliğin değerine göre sayılır). */
  kimlikOz: string;
  gorunur(d: Dugum): boolean;
  /** Alt ağacın tamamı atılır (klavye, kaydırma çubuğu …). */
  atla(d: Dugum): boolean;
  /** Rol; null = anlamsız kap (kimliği yoksa düzleştirilir). */
  rol(d: Dugum): string | null;
  ad(d: Dugum, rol: string): string;
  deger(d: Dugum, rol: string): string | undefined;
  id(d: Dugum): string | undefined;
  durumlar(d: Dugum, rol: string): string[];
  parola(d: Dugum): boolean;
}

// Android ---------------------------------------------------------------------------------

const ANDROID_ROL: Record<string, string> = {
  Button: 'button',
  ImageButton: 'button',
  FloatingActionButton: 'button',
  MaterialButton: 'button',
  EditText: 'textbox',
  AutoCompleteTextView: 'textbox',
  MultiAutoCompleteTextView: 'textbox',
  TextInputEditText: 'textbox',
  TextView: 'text',
  CheckBox: 'checkbox',
  Switch: 'switch',
  SwitchCompat: 'switch',
  SwitchMaterial: 'switch',
  ToggleButton: 'switch',
  RadioButton: 'radio',
  RadioGroup: 'radiogroup',
  ImageView: 'image',
  Spinner: 'combobox',
  ListView: 'list',
  RecyclerView: 'list',
  GridView: 'list',
  ScrollView: 'list',
  HorizontalScrollView: 'list',
  NestedScrollView: 'list',
  ReactScrollView: 'list',
  ReactHorizontalScrollView: 'list',
  ViewPager: 'list',
  SeekBar: 'slider',
  RatingBar: 'slider',
  ProgressBar: 'progressbar',
  TabWidget: 'tablist',
  TabLayout: 'tablist',
  WebView: 'webview',
};

function kisaSinif(etiket: string): string {
  return etiket.slice(etiket.lastIndexOf('.') + 1);
}

function androidSinirlar(d: Dugum): [number, number] {
  const m = /^\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]$/.exec(d.oz.bounds ?? '');
  if (!m) return [1, 1]; // sınır bilgisi yoksa görünür say
  return [sayi(m[3]) - sayi(m[1]), sayi(m[4]) - sayi(m[2])];
}

const android: Uyarlayici = {
  kimlikOz: 'resource-id',
  gorunur(d) {
    if (d.oz.displayed === 'false') return false;
    const [g, y] = androidSinirlar(d);
    return g > 0 && y > 0;
  },
  atla() {
    return false;
  },
  rol(d) {
    const sinif = kisaSinif(d.etiket);
    if (sinif === 'CheckedTextView') return d.oz.checkable === 'true' ? 'option' : 'text';
    const r = ANDROID_ROL[sinif];
    // RN TextInput uzun basılabilir; yalnızca `clickable` dokunulabilirlik sayılır.
    const tiklanir = d.oz.clickable === 'true';
    if (r === 'text' || r === 'image') {
      if (tiklanir) return 'button';
      return r === 'text' && d.oz.heading === 'true' ? 'heading' : r;
    }
    if (r) return r;
    if (tiklanir) return 'button';
    // RN (Fabric) accessibilityRole="header" olan Text'i TextView değil düz `android.view.View`
    // olarak yayımlar (ör. katalogda ürün adı); metni ve heading işareti vardır.
    if (d.oz.heading === 'true' && (sade(d.oz.text) || sade(d.oz['content-desc']))) return 'heading';
    return null;
  },
  ad(d, rol) {
    const metin = sade(d.oz.text);
    const aciklama = sade(d.oz['content-desc']);
    if (rol === 'textbox') return aciklama || sade(d.oz.hint) || (d.oz['showing-hint'] === 'true' ? metin : '');
    if (rol === 'combobox') return aciklama;
    return aciklama || metin;
  },
  deger(d, rol) {
    if (rol === 'textbox') {
      // Boş alanda UiAutomator `text` olarak ipucunu döndürür (`showing-hint="true"`).
      const metin = d.oz.text ?? '';
      if (!metin || d.oz['showing-hint'] === 'true' || metin === d.oz.hint) return undefined;
      return sade(metin);
    }
    if (rol === 'combobox') {
      // Spinner'ın seçili değeri çocuk TextView'dadır.
      const t = ilkMetin(d, (c) => c.oz.text);
      return t ? sade(t) : undefined;
    }
    return undefined;
  },
  id(d) {
    return d.oz['resource-id'] || undefined;
  },
  durumlar(d) {
    const s: string[] = [];
    if (d.oz.enabled === 'false') s.push('disabled');
    if (d.oz.checkable === 'true' && d.oz.checked === 'true') s.push('checked');
    if (d.oz.selected === 'true') s.push('selected');
    return s;
  },
  parola(d) {
    return d.oz.password === 'true';
  },
};

// iOS -------------------------------------------------------------------------------------

const IOS_ROL: Record<string, string> = {
  Button: 'button',
  Link: 'link',
  StaticText: 'text',
  TextField: 'textbox',
  SearchField: 'textbox',
  TextView: 'textbox',
  SecureTextField: 'textbox',
  Switch: 'switch',
  Toggle: 'switch',
  Cell: 'listitem',
  Image: 'image',
  Icon: 'image',
  Table: 'list',
  CollectionView: 'list',
  ScrollView: 'list',
  NavigationBar: 'navigation',
  TabBar: 'tablist',
  Tab: 'tab',
  Picker: 'combobox',
  PickerWheel: 'combobox',
  SegmentedControl: 'radiogroup',
  Slider: 'slider',
  ProgressIndicator: 'progressbar',
  ActivityIndicator: 'progressbar',
  PageIndicator: 'progressbar',
  Alert: 'alertdialog',
  Sheet: 'dialog',
  WebView: 'webview',
  MenuItem: 'menuitem',
  CheckBox: 'checkbox',
  RadioButton: 'radio',
};
const IOS_ATLA = new Set(['Keyboard', 'Keyboards', 'StatusBar', 'ScrollBar']);

function iosTur(etiket: string): string {
  return etiket.replace(/^XCUIElementType/, '');
}

function iosKimlik(d: Dugum): string | undefined {
  // XCUITest `name` = accessibilityIdentifier; tanımlayıcı yoksa label'a düşer. Bu yüzden yalnızca
  // label'dan farklı (ya da label boşken) olan name kimlik sayılır.
  const name = d.oz.name ?? '';
  const label = d.oz.label ?? '';
  if (!name) return undefined;
  return label === '' || name !== label ? name : undefined;
}

const ios: Uyarlayici = {
  kimlikOz: 'name',
  gorunur(d) {
    if (d.oz.visible === 'false') return false;
    if (d.oz.width === undefined) return true;
    return sayi(d.oz.width) > 0 && sayi(d.oz.height) > 0;
  },
  atla(d) {
    return IOS_ATLA.has(iosTur(d.etiket));
  },
  rol(d) {
    const tur = iosTur(d.etiket);
    const r = IOS_ROL[tur];
    if (r === 'text' && /\bHeader\b/.test(d.oz.traits ?? '')) return 'heading';
    if (r) return r;
    // React Native dokunulabilirleri (Pressable/Touchable…) erişilebilir `Other` olarak gelir.
    if (tur === 'Other' && d.oz.accessible === 'true' && (d.oz.label ?? '') !== '') return 'button';
    return null;
  },
  ad(d, rol) {
    const label = sade(d.oz.label);
    if (rol === 'textbox') return label || sade(d.oz.placeholderValue);
    if (rol === 'text') return label || sade(d.oz.value);
    if (rol === 'combobox' && iosTur(d.etiket) === 'PickerWheel') return label;
    return label || (iosKimlik(d) ? '' : sade(d.oz.name));
  },
  deger(d, rol) {
    const v = d.oz.value ?? '';
    if (rol === 'textbox') return v && v !== d.oz.placeholderValue ? sade(v) : undefined;
    if (rol === 'combobox' || rol === 'slider') return v ? sade(v) : undefined;
    return undefined;
  },
  id: iosKimlik,
  durumlar(d, rol) {
    const s: string[] = [];
    if (d.oz.enabled === 'false') s.push('disabled');
    if ((rol === 'switch' || rol === 'checkbox') && d.oz.value === '1') s.push('checked');
    if (d.oz.selected === 'true') s.push('selected');
    return s;
  },
  parola(d) {
    return iosTur(d.etiket) === 'SecureTextField';
  },
};

// Windows ---------------------------------------------------------------------------------

const WINDOWS_ROL: Record<string, string> = {
  Button: 'button',
  SplitButton: 'button',
  Edit: 'textbox',
  Document: 'textbox',
  Text: 'text',
  CheckBox: 'checkbox',
  RadioButton: 'radio',
  ComboBox: 'combobox',
  List: 'list',
  DataGrid: 'list',
  Table: 'list',
  Tree: 'list',
  ListItem: 'listitem',
  DataItem: 'listitem',
  TreeItem: 'listitem',
  Hyperlink: 'link',
  Image: 'image',
  Menu: 'menu',
  MenuBar: 'menu',
  MenuItem: 'menuitem',
  Tab: 'tablist',
  TabItem: 'tab',
  Slider: 'slider',
  Spinner: 'spinbutton',
  ProgressBar: 'progressbar',
  Window: 'window',
  ToolBar: 'toolbar',
  StatusBar: 'status',
  Header: 'row',
  HeaderItem: 'columnheader',
};
const WINDOWS_ATLA = new Set(['TitleBar', 'ScrollBar', 'Thumb']);

const windows: Uyarlayici = {
  kimlikOz: 'AutomationId',
  gorunur(d) {
    if (d.oz.IsOffscreen === 'True' || d.oz.IsOffscreen === 'true') return false;
    if (d.oz.width === undefined) return true;
    return sayi(d.oz.width) > 0 && sayi(d.oz.height) > 0;
  },
  atla(d) {
    return WINDOWS_ATLA.has(d.etiket);
  },
  rol(d) {
    return WINDOWS_ROL[d.etiket] ?? null;
  },
  ad(d, rol) {
    const ad = sade(d.oz.Name);
    // UIA'da düzenleme alanının Name'i çoğu zaman etiketidir; değer ayrı (Value.Value).
    return rol === 'textbox' && ad === sade(windowsDeger(d)) ? '' : ad;
  },
  deger(d, rol) {
    if (rol === 'textbox' || rol === 'combobox' || rol === 'slider' || rol === 'spinbutton') {
      const v = windowsDeger(d);
      return v ? sade(v) : undefined;
    }
    return undefined;
  },
  id(d) {
    return d.oz.AutomationId || undefined;
  },
  durumlar(d) {
    const s: string[] = [];
    if (d.oz.IsEnabled === 'False' || d.oz.IsEnabled === 'false') s.push('disabled');
    const t = d.oz['Toggle.ToggleState'] ?? d.oz.ToggleState;
    if (t === 'On' || t === '1') s.push('checked');
    const sec = d.oz['SelectionItem.IsSelected'] ?? d.oz.IsSelected;
    if (sec === 'True' || sec === 'true') s.push('selected');
    return s;
  },
  parola(d) {
    return d.oz.IsPassword === 'True' || d.oz.IsPassword === 'true';
  },
};

function windowsDeger(d: Dugum): string {
  return d.oz['Value.Value'] ?? d.oz.Value ?? '';
}

const UYARLAYICI: Record<Platform, Uyarlayici> = { android, ios, windows };

function ilkMetin(d: Dugum, f: (c: Dugum) => string | undefined): string | undefined {
  for (const c of d.cocuklar) {
    const v = f(c);
    if (v) return v;
    const alt = ilkMetin(c, f);
    if (alt) return alt;
  }
  return undefined;
}

// ------------------------------------------------------------------------------------ dönüşüm

/** Eylem elemanları: içlerindeki kaplar düzleştirilir, adları alt metinlerden hesaplanır. */
const EYLEM_ROLLERI = new Set(['button', 'link', 'menuitem', 'tab', 'option', 'checkbox', 'radio', 'switch']);
const KAP_ROLLERI = new Set(['list', 'listitem', 'navigation', 'toolbar', 'tablist', 'menu', 'radiogroup', 'webview']);

/** Ağacı ortak role indirger. `kimlikSirasi` aynı kimliği taşıyan elemanların kaynak sırasıdır. */
export function ogelereCevir(kok: Dugum, platform: Platform): Oge[] {
  const uy = UYARLAYICI[platform];
  // Kimlik → kaynak sırasındaki sayaç (görünmeyenler dahil: sürücünün findElements sırası).
  const sayac = new Map<string, number>();
  const sira = new Map<Dugum, number>();
  const say = (d: Dugum): void => {
    const v = d.oz[uy.kimlikOz];
    if (v) {
      const n = sayac.get(v) ?? 0;
      sayac.set(v, n + 1);
      sira.set(d, n);
    }
    d.cocuklar.forEach(say);
  };
  say(kok);

  const cevir = (d: Dugum, eylemIci: boolean): Oge[] => {
    if (uy.atla(d) || !uy.gorunur(d)) return [];
    const rol = uy.rol(d);
    const id = uy.id(d);
    const eylem = rol !== null && EYLEM_ROLLERI.has(rol);
    let cocuklar = d.cocuklar.flatMap((c) => cevir(c, eylemIci || eylem));
    if (rol === null) {
      // Anlamsız kap. Eylem elemanının (düğme…) içindeki sarmalayıcılar ve kimliksiz kaplar
      // düzleştirilir. Kimlikli tek çocuklu sarmalayıcı: kimliksiz çocuğa kimliğini ve konumunu
      // devreder (RN: <View testID="sepet-toplam"><Text>…</Text></View> → text "…" [id=sepet-toplam]),
      // kimlikli çocuğu varsa sarmalayıcı atılır.
      if (!id || eylemIci) return cocuklar;
      if (cocuklar.length === 1) {
        const tek = cocuklar[0]!;
        if (!tek.id) {
          const kap = ogeKur(d, 'group', id, []);
          tek.id = id;
          tek.konum = kap.konum;
        }
        return cocuklar;
      }
      return [ogeKur(d, 'group', id, cocuklar)];
    }
    const parola = uy.parola(d) || (rol === 'textbox' && GIZLI_AD.test(`${uy.ad(d, rol)} ${id ?? ''}`));
    let ad = uy.ad(d, rol);
    if (!ad && (eylem || rol === 'listitem')) {
      // Adsız düğme / satır: adı alt metinlerinden (Playwright erişilebilir ad hesabı gibi).
      ad = sade(
        duzlestir(cocuklar)
          .filter((c) => (c.rol === 'text' || c.rol === 'heading') && c.ad)
          .map((c) => c.ad)
          .join(' '),
      );
    }
    if (ad && (eylem || rol === 'listitem')) {
      // Ada katılan (adın parçası olan) kimliksiz metinler ayrıca basılmaz.
      cocuklar = cocuklar.filter(
        (c) => !((c.rol === 'text' || c.rol === 'heading') && !c.id && c.cocuklar.length === 0 && ad.includes(c.ad)),
      );
    }
    // Süs: adsız resim (eylem içinde kimlikli olsa da), adsız ve kimliksiz metin; boş kaplar.
    if (rol === 'image' && !ad && (!id || eylemIci)) return cocuklar;
    if ((rol === 'text' || rol === 'heading') && !ad && !id) return cocuklar;
    if (KAP_ROLLERI.has(rol) && !ad && !id && cocuklar.length === 0) return [];
    const oge = ogeKur(d, rol, id, cocuklar);
    oge.ad = ad;
    oge.parola = parola;
    const deger = uy.deger(d, rol);
    if (deger !== undefined) {
      oge.deger = parola ? PAROLA_MASKESI : deger;
      // Değeri gösteren iç metin (Android Spinner'ın seçili satırı) ayrıca basılmaz.
      oge.cocuklar = oge.cocuklar.filter((c) => !(c.rol === 'text' && c.ad === deger && c.cocuklar.length === 0));
    }
    oge.durumlar = uy.durumlar(d, rol);
    return [oge];
  };

  const ogeKur = (d: Dugum, rol: string, id: string | undefined, cocuklar: Oge[]): Oge => {
    const konum: Konum = { xpath: d.xpath };
    if (id) {
      const ham = d.oz[uy.kimlikOz];
      // Kimlik özniteliği değeri ile kimlik aynıysa sıra bilinir; değilse yalnızca XPath.
      if (ham === id) konum.id = { deger: id, sira: sira.get(d) ?? 0 };
    }
    const oge: Oge = { rol, ad: '', durumlar: [], parola: false, tip: d.etiket, konum, cocuklar };
    if (id) oge.id = id;
    return oge;
  };

  return cevir(kok, false);
}

// -------------------------------------------------------------------------------------- metin

function tirnakla(s: string): string {
  return `"${s.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}

export interface SatirSecenek {
  /** Elemanın ref'i (`e12`). */
  ref: (o: Oge) => string;
  maksSatir: number;
  maksKarakter: number;
}

export interface SnapshotMetni {
  metin: string;
  satir: number;
  kesildi: boolean;
}

/** Ağacı YAML benzeri satırlara çevirir (girinti = iç içelik, 2 boşluk). */
export function snapshotYaz(ogeler: Oge[], s: SatirSecenek): SnapshotMetni {
  const satirlar: string[] = [];
  let karakter = 0;
  let kesildi = false;
  const yaz = (o: Oge, girinti: number): void => {
    if (kesildi) return;
    let satir = `${'  '.repeat(girinti)}- ${o.rol}`;
    if (o.ad) satir += ` ${tirnakla(o.ad)}`;
    if (o.id) satir += ` [id=${o.id}]`;
    if (o.parola) satir += ' [password]';
    for (const d of o.durumlar) satir += ` [${d}]`;
    satir += ` [ref=${s.ref(o)}]`;
    if (o.cocuklar.length > 0) satir += ':';
    else if (o.deger !== undefined) satir += `: ${o.deger}`;
    if (satirlar.length >= s.maksSatir || karakter + satir.length + 1 > s.maksKarakter) {
      kesildi = true;
      return;
    }
    satirlar.push(satir);
    karakter += satir.length + 1;
    for (const c of o.cocuklar) yaz(c, girinti + 1);
  };
  for (const o of ogeler) yaz(o, 0);
  return { metin: satirlar.join('\n'), satir: satirlar.length, kesildi };
}

/** Ağaçtaki görünür metinler (ad + parola olmayan değerler), `app_wait_for` için. */
export function gorunurMetinler(ogeler: Oge[]): string[] {
  const out: string[] = [];
  const gez = (o: Oge): void => {
    if (o.ad) out.push(o.ad);
    if (o.deger !== undefined && !o.parola) out.push(o.deger);
    o.cocuklar.forEach(gez);
  };
  ogeler.forEach(gez);
  return out;
}

/** Ağacı derinlik öncelikli düzleştirir (kaynak sırası). */
export function duzlestir(ogeler: Oge[]): Oge[] {
  const out: Oge[] = [];
  const gez = (o: Oge): void => {
    out.push(o);
    o.cocuklar.forEach(gez);
  };
  ogeler.forEach(gez);
  return out;
}
