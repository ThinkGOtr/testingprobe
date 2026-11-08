/**
 * Sayfa kaynağı → snapshot dönüşümü: gerçek (Android/iOS Ayarlar) ve elle yazılmış (RN/WPF Bayi)
 * fikstürler, altın çıktılar ve platform kuralları. Altınları yenilemek: ALTIN_GUNCELLE=1 npm test
 */
import assert from 'node:assert/strict';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, it } from 'node:test';
import {
  duzlestir,
  gorunurMetinler,
  kaynakAyristir,
  ogelereCevir,
  snapshotYaz,
  type Oge,
  type Platform,
} from '../src/agac.js';
import { FIKSTUR, fikstur } from './sahte.js';

function snapshot(xml: string, platform: Platform): { metin: string; ogeler: Oge[] } {
  const ogeler = ogelereCevir(kaynakAyristir(xml), platform);
  let n = 0;
  const refler = new Map<Oge, string>();
  const { metin } = snapshotYaz(ogeler, {
    ref: (o) => refler.get(o) ?? (refler.set(o, `e${++n}`), `e${n}`),
    maksSatir: 1000,
    maksKarakter: 100000,
  });
  return { metin, ogeler };
}

function bul(ogeler: Oge[], f: (o: Oge) => boolean): Oge {
  const o = duzlestir(ogeler).find(f);
  assert.ok(o, 'eleman bulunamadı');
  return o;
}

const ALTINLAR: [string, Platform][] = [
  ['android-ayarlar.xml', 'android'],
  ['android-ayarlar-arama.xml', 'android'],
  ['android-bayi-giris.xml', 'android'],
  ['ios-ayarlar.xml', 'ios'],
  ['ios-bayi-giris.xml', 'ios'],
  ['windows-bayi-giris.xml', 'windows'],
];

describe('altın snapshot çıktıları (deterministik)', () => {
  for (const [dosya, platform] of ALTINLAR) {
    it(`${dosya} → ${dosya.replace('.xml', '.snapshot.txt')}`, () => {
      const xml = fikstur(dosya);
      const a = snapshot(xml, platform).metin;
      const b = snapshot(xml, platform).metin;
      assert.equal(a, b, 'aynı kaynak iki kez aynı çıktıyı vermeli');
      const altin = join(FIKSTUR, dosya.replace('.xml', '.snapshot.txt'));
      if (process.env.ALTIN_GUNCELLE === '1' || !existsSync(altin)) writeFileSync(altin, `${a}\n`);
      assert.equal(`${a}\n`, readFileSync(altin, 'utf8'));
    });
  }
});

describe('Android (UiAutomator2)', () => {
  const { metin, ogeler } = snapshot(fikstur('android-bayi-giris.xml'), 'android');

  it('RN testID resource-id olarak kimlik olur; düğme adı alt metinden', () => {
    assert.match(metin, /^\s*- button "Giriş yap" \[id=login-submit\] \[ref=e\d+\]$/m);
  });
  it('başlık rolü ve süs resmi', () => {
    assert.match(metin, /- heading "Bayi Sipariş Portalı"/);
    assert.doesNotMatch(metin, /- image/);
  });
  it('ipucu gösteren boş alan değer taşımaz; ad ipucudur', () => {
    assert.match(metin, /- textbox "Kullanıcı adı" \[id=login-username\] \[ref=e\d+\]$/m);
  });
  it('parola alanı maskeli ve işaretli; düz metin hiçbir yerde yok', () => {
    assert.match(metin, /- textbox "Parola" \[id=login-password\] \[password\] \[ref=e\d+\]: \*\*\*$/m);
    assert.doesNotMatch(metin, /••/);
    const o = bul(ogeler, (x) => x.id === 'login-password');
    assert.equal(o.parola, true);
    assert.ok(!gorunurMetinler(ogeler).includes('***'));
  });
  it('durumlar: checked, disabled', () => {
    assert.match(metin, /- switch \[id=login-remember\] \[checked\]/);
    assert.match(metin, /- button "Kayıt ol" \[id=login-register\] \[disabled\]/);
  });
  it('kimlikli tek çocuklu sarmalayıcı kimliğini metne devreder', () => {
    assert.match(metin, /- text "Kullanıcı adı veya parola hatalı" \[id=login-error\]/);
    const o = bul(ogeler, (x) => x.id === 'login-error');
    assert.deepEqual(o.konum.id, { deger: 'login-error', sira: 0 });
    assert.match(o.konum.xpath, /android\.view\.ViewGroup\[\d+\]$/);
  });
  it('açılır liste: combobox + seçili değer', () => {
    assert.match(metin, /- combobox \[id=login-language\] \[ref=e\d+\]: Türkçe$/m);
  });
  it('görünmeyen ve sıfır boyutlu düğümler atılır', () => {
    assert.doesNotMatch(metin, /Görünmez|Gizli ipucu|login-hidden/);
  });
  it('yinelenen kimlik: kaynak sırası konuma yazılır', () => {
    const iki = duzlestir(ogeler).filter((o) => o.id === 'add-to-cart');
    assert.deepEqual(
      iki.map((o) => o.konum.id),
      [
        { deger: 'add-to-cart', sira: 0 },
        { deger: 'add-to-cart', sira: 1 },
      ],
    );
    assert.equal(iki[0]!.ad, 'Sepete ekle');
  });
  it('ürün kartı kapsamı korunur (kart kimliği + kod + düğme)', () => {
    assert.match(metin, /- group \[id=product-card-P-001\] \[ref=e\d+\]:\n\s+- text "P-001" \[ref=e\d+\]\n\s+- button "Sepete ekle" \[id=add-to-cart\]/);
  });
});

describe('Android gerçek kaynak (Ayarlar)', () => {
  it('satır düğmeleri adını başlık + özetten alır, sarmalayıcılar düzleşir', () => {
    const { metin } = snapshot(fikstur('android-ayarlar.xml'), 'android');
    assert.match(metin, /- button "Network & internet Mobile, Wi‑Fi, hotspot" \[ref=e\d+\]:/);
    assert.doesNotMatch(metin, /icon_frame|text_frame/);
  });
  it('arama kutusu: değer = yazılan metin, ad = ipucu', () => {
    const { metin } = snapshot(fikstur('android-ayarlar-arama.xml'), 'android');
    assert.match(metin, /- textbox "Search settings" \[id=com\.google\.android\.settings\.intelligence:id\/open_search_view_edit_text\] \[ref=e\d+\]: wifi/);
  });
});

describe('iOS (XCUITest)', () => {
  const { metin, ogeler } = snapshot(fikstur('ios-bayi-giris.xml'), 'ios');

  it('accessibilityIdentifier kimlik; label ile aynı name kimlik sayılmaz', () => {
    assert.match(metin, /- textbox "Kullanıcı adı" \[id=login-username\] \[ref=e\d+\]: bayi3/);
    assert.match(metin, /- text "P-001" \[ref=e\d+\]/);
    assert.match(metin, /- button "Kayıt ol" \[disabled\]/);
  });
  it('güvenli metin alanı maskeli', () => {
    assert.match(metin, /- textbox "Parola" \[id=login-password\] \[password\] \[ref=e\d+\]: \*\*\*/);
    assert.doesNotMatch(metin, /••/);
  });
  it('erişilebilir RN Other düğme olur; çocuk metni yinelenmez', () => {
    assert.match(metin, /- button "Giriş yap" \[id=login-submit\] \[ref=e\d+\]$/m);
    assert.equal(metin.match(/Giriş yap/g)?.length, 1);
  });
  it('switch değeri 1 → checked; başlık traits=Header', () => {
    assert.match(metin, /- switch "Beni hatırla" \[id=login-remember\] \[checked\]/);
    assert.match(metin, /- heading "Bayi Sipariş Portalı"/);
  });
  it('klavye, görünmeyen, sıfır boyutlu ve adsız resim atılır', () => {
    assert.doesNotMatch(metin, /Keyboard|"q"|Görünmez|Sıfır|- image/);
  });
  it('çark seçici değeri gösterilir', () => {
    const o = bul(ogeler, (x) => x.tip === 'XCUIElementTypePickerWheel');
    assert.equal(o.deger, 'Türkçe');
  });
  it('gerçek Ayarlar kaynağı: arama alanı ve satırlar', () => {
    const s = snapshot(fikstur('ios-ayarlar.xml'), 'ios').metin;
    assert.match(s, /- heading "Settings"/);
    assert.match(s, /- textbox "Search"/);
    assert.match(s, /General/);
  });
});

describe('Windows (NovaWindows / UIA)', () => {
  const { metin } = snapshot(fikstur('windows-bayi-giris.xml'), 'windows');

  it('AutomationId kimlik; değer Value.Value', () => {
    assert.match(metin, /- textbox "Kullanıcı adı" \[id=login-username\] \[ref=e\d+\]: bayi3/);
    assert.match(metin, /- combobox "Dil" \[id=login-language\] \[ref=e\d+\]: Türkçe/);
  });
  it('parola (IsPassword) maskeli; gerçek değer hiçbir yerde yok', () => {
    assert.match(metin, /- textbox "Parola" \[id=login-password\] \[password\] \[ref=e\d+\]: \*\*\*/);
    assert.doesNotMatch(metin, /Ornek-Parola-9/);
  });
  it('başlık çubuğu, kaydırma çubuğu ve ekran dışı elemanlar atılır', () => {
    assert.doesNotMatch(metin, /Kapat|VerticalScrollBar|Gizli ipucu|English/);
  });
  it('durumlar: checked, selected, disabled', () => {
    assert.match(metin, /- checkbox "Beni hatırla" \[id=login-remember\] \[checked\]/);
    assert.match(metin, /- listitem "P-001" \[id=product-card-P-001\] \[selected\]/);
    assert.match(metin, /- button "Kayıt ol" \[id=login-register\] \[disabled\]/);
  });
});

describe('sınırlar ve hatalar', () => {
  it('satır sınırı aşılınca kesilir', () => {
    const ogeler = ogelereCevir(kaynakAyristir(fikstur('android-ayarlar.xml')), 'android');
    let n = 0;
    const s = snapshotYaz(ogeler, { ref: () => `e${++n}`, maksSatir: 5, maksKarakter: 100000 });
    assert.equal(s.satir, 5);
    assert.equal(s.kesildi, true);
  });
  it('bozuk XML açık hata verir', () => {
    assert.throws(() => kaynakAyristir(''), /kök eleman yok|ayrıştırılamadı/);
  });
  it('ad içindeki tırnak kaçışlanır (core snapshot ayrıştırıcısıyla uyumlu)', () => {
    const xml =
      '<hierarchy><android.widget.Button text=\'Sepet "6"\' clickable="true" bounds="[0,0][10,10]" displayed="true"/></hierarchy>';
    assert.match(snapshot(xml, 'android').metin, /^- button "Sepet \\"6\\"" \[ref=e1\]$/);
  });
});
