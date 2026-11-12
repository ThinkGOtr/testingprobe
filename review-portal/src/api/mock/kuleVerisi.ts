// 012/Ş8 örnek verisi: ekilmiş hata kataloğu (ANALIZ §4.6'daki dokuz hata), örnek test paketi, hata ×
// platform sonuç tablosu ve bitmiş bir koşu (web + android). Sayılar ÖRNEK VERİ bandı altında gösterilir.
import type { Platform } from "../../lib/platform";
import type { HataKatalogOgesi, HataKosusuAdimi, HataKosusuDetay, KuleBeklentiDogrulugu } from "../types";

const hata = (kod: string, tur: HataKatalogOgesi["tur"], ad: string, aciklama: string, yakalayan_kural: string): HataKatalogOgesi => ({
  kod,
  ad,
  tur,
  aciklama,
  yakalayan_kural,
});

/** core `rules/hata-katalogu.yaml` ile birebir (kod, ad, tür, açıklama, yakalayan kural; aynı sıra). */
export const HATA_KATALOGU: HataKatalogOgesi[] = [
  hata("kampanya_bedava_yok", "kod", "Kampanyada bedava ürün verilmiyor", "Kampanyalı üründe bedava adet her zaman 0 hesaplanır (mevcut kırılma; BREAK_CAMPAIGN ile aynı etki).", "Kampanya (6 al 1 bedava)"),
  hata("kampanya_esik_7", "kod", "Kampanya eşiği 6 yerine 7", "Bedava adet, adet 6'ya değil 7'ye tam bölünerek hesaplanır.", "Kampanya (6'nın katlarında bedava adet)"),
  hata("kampanya_cift_indirim", "kod", "Kampanya indirimi iki kez düşülüyor", "Kampanya indirimi sepet toplamından iki kez düşülür.", "Kampanyalı sepetin toplamı"),
  hata("min_siparis_haric", "kod", "Minimum sipariş sınırı dahil değil", "Toplam minimum tutara eşitken sipariş kabul edilmez (sınır dahil olması gerekirken hariç tutulur).", "Minimum sipariş tutarı sınır değeri"),
  hata("min_siparis_muafiyet_yok", "kod", "Kampanyalı sepet minimumdan muaf değil", "Kampanyalı sepet de minimum sipariş tutarına tabi tutulur.", "Minimum sipariş muafiyeti (kampanyalı sepet)"),
  hata("min_siparis_500", "veri", "Minimum sipariş tutarı 500", "Minimum sipariş tutarı 750 yerine 500 okunur.", "Minimum sipariş tutarı"),
  hata("min_siparis_1000", "veri", "Minimum sipariş tutarı 1000", "Minimum sipariş tutarı 750 yerine 1000 okunur.", "Minimum sipariş tutarı"),
  hata("fiyat_p004_31", "veri", "P-004 fiyatı 31", "P-004 ürününün birim fiyatı 30 yerine 31 okunur.", "Satır ve sepet toplamı"),
  hata("kampanya_urunu_p002", "veri", "Kampanyalı ürün P-002", "Kampanyalı ürün P-001 yerine P-002 olarak okunur.", "Kampanya (kampanyalı ürün)"),
];

// Demo uygulamanın el yazımı web paketi (`demo-app/e2e/tests/*.spec.ts`); adlar Playwright test başlığıdır
// (core `kiran_testler` = rapordaki `title`).
const T_DEALER = "case metnindeki bayi ile arayüzden giriş yapılır";
const T_KATALOG = "katalog ürünleri ve fiyatları tr-TR biçiminde gösterir";
const T_AC1 = "AC1: Sepete ekle ürünü sepete ekler ve sepet sayacı artar";
const T_KAMPANYA = "kampanya: 7 adet P-001 → 1 bedava, toplam 150,00 TL";
const T_KAMPANYASIZ = "kampanyasız üründe bedava adet verilmez";
const T_MIN_ALT = "kampanyasız siparişte minimum tutar altında uyarı gösterilir ve onay pasif olur";
const T_MUAF = "kampanyalı siparişte minimum tutar aranmaz";
const T_MIN_ULAS = "minimum tutara ulaşınca uyarı kalkar ve onay aktif olur";
const T_KALDIR = "ürün sepetten kaldırılabilir";
const T_A11Y_KATALOG = "katalog sayfası";
const T_A11Y_SEPET = "sepet sayfası (uyarı ve satırlarla)";
const T_A11Y_GIRIS = "giriş sayfası (hata mesajıyla)";
const T_MOBIL = "satır tutarı ve Kaldır butonu kaydırmadan görünür";
const T_MOBIL_EKSI = "indirim yokken eksi işareti gösterilmez";
const T_BOS_GECMIS = "siparişi olmayan bayide boş geçmiş bilgisi gösterilir @sifir-veri";
const T_SIPARIS = "onaylanan sipariş numarasıyla gösterilir ve geçmişte listelenir";
const T_API_RED = "minimum tutarın altındaki sepet API'de de reddedilir";
const T_LOGIN = "doğru bilgilerle giriş yapılır ve katalog açılır";
const T_LOGIN_HATA = "hatalı parolada hata mesajı gösterilir";
const T_LOGIN_YON = "oturumsuz kullanıcı giriş sayfasına yönlendirilir";
const T_LOGIN_KONSOL = "oturumsuz açılış ve giriş konsola hata yazmaz";
const T_CIKIS = "çıkış yapınca giriş sayfasına dönülür";
const T_LOC_GIRIS = "giriş sayfası";
const T_LOC_MENU = "menü, katalog, sepet ve sipariş sayfaları";
const T_PO_SAYAC = "adet alanı, menü gezintisi ve sepet sayfasındaki sayaç";
const T_PO_BEDAVA = "7 adet Portakal Gazozu sepette 1 bedava adet ve sayaç 7 gösterir";
const T_PO_MIN = "indirimsiz sepette minimum tutar uyarısı metni ve pasif onay";
const T_PO_GECMIS = "onaylanan sipariş geçmişte numarasıyla bulunur";
const T_PO_EXPECT = "expect* metotları yanlış değerde assertion hatasıyla kırmızı olur";

/** Onaylı test paketi (adım koşusu ayrıntısındaki test listesi). */
export const PAKET_TESTLERI = [
  T_DEALER,
  T_KATALOG,
  T_AC1,
  T_KAMPANYA,
  T_KAMPANYASIZ,
  T_MIN_ALT,
  T_MUAF,
  T_MIN_ULAS,
  T_KALDIR,
  T_A11Y_KATALOG,
  T_A11Y_SEPET,
  T_A11Y_GIRIS,
  T_MOBIL,
  T_MOBIL_EKSI,
  T_BOS_GECMIS,
  T_SIPARIS,
  T_API_RED,
  T_LOGIN,
  T_LOGIN_HATA,
  T_LOGIN_YON,
  T_LOGIN_KONSOL,
  T_CIKIS,
  T_LOC_GIRIS,
  T_LOC_MENU,
  T_PO_SAYAC,
  T_PO_BEDAVA,
  T_PO_MIN,
  T_PO_GECMIS,
  T_PO_EXPECT,
];

export type MockAdimSonucu = { sonuc: "yakalandi"; testler: string[] } | { sonuc: "kacti" } | { sonuc: "gecersiz"; neden: string };

/**
 * Web: demo uygulamada ölçülen gerçek matris (2026-11-12; `demo-app/README.md` "Ekilmiş hatalar"):
 * yakalanan 8/9, kaçan yalnız `kampanya_esik_7` (el yazımı testler 6. adet sınırını bilerek doğrulamaz;
 * 7 ve 14 adette iki kural aynı sonucu verir).
 */
const WEB: Record<string, MockAdimSonucu> = {
  kampanya_bedava_yok: { sonuc: "yakalandi", testler: [T_KAMPANYA, T_SIPARIS, T_PO_BEDAVA] },
  kampanya_esik_7: { sonuc: "kacti" },
  kampanya_cift_indirim: { sonuc: "yakalandi", testler: [T_KAMPANYA, T_SIPARIS] },
  min_siparis_haric: { sonuc: "yakalandi", testler: [T_MIN_ULAS, T_PO_GECMIS] },
  min_siparis_muafiyet_yok: { sonuc: "yakalandi", testler: [T_MUAF] },
  min_siparis_500: { sonuc: "yakalandi", testler: [T_A11Y_SEPET, T_MIN_ALT, T_API_RED, T_PO_MIN] },
  min_siparis_1000: { sonuc: "yakalandi", testler: [T_A11Y_SEPET, T_MIN_ALT, T_MIN_ULAS, T_API_RED, T_PO_MIN, T_PO_GECMIS, T_LOC_MENU] },
  fiyat_p004_31: { sonuc: "yakalandi", testler: [T_KATALOG, T_MIN_ULAS, T_MOBIL, T_SIPARIS, T_PO_GECMIS] },
  kampanya_urunu_p002: { sonuc: "yakalandi", testler: [T_A11Y_SEPET, T_KATALOG, T_KAMPANYA, T_KAMPANYASIZ, T_MIN_ALT, T_MUAF, T_SIPARIS, T_PO_BEDAVA] },
};

/** Platform × hata sonucu. `null`: platformun temel koşusu koşulamadı (cihaz kapalı) → tüm adımlar geçersiz. */
export const MOCK_SONUCLAR: Record<Platform, Record<string, MockAdimSonucu> | null> = {
  web: WEB,
  // Android (Java + Appium) ölçülmedi: örnek veride web'le aynı sonuçlar, bir adım ortam hatasıyla geçersiz.
  android: {
    ...WEB,
    min_siparis_1000: {
      sonuc: "gecersiz",
      neden: "Cihaz/Appium erişilemiyor (http://127.0.0.1:4723): oturum komutu zaman aşımına uğradı (UiAutomator2 yanıt vermedi).",
    },
  },
  // Örnek veride iOS simülatörü kapalıdır (kabul senaryosu 13: adımlar geçersiz, oran etkilenmez).
  ios: null,
  windows: WEB,
};

export const TEMEL_KOSULAMADI: Partial<Record<Platform, string>> = {
  ios: "iOS simülatörüne ulaşılamadı (Appium sunucusu yanıt vermedi).",
};
export const TEMEL_YESIL_DEGIL = "Temel koşu yeşil değil";

/** Bir koşunun adım iskeleti: platform başına temel → her hata → kapanış (hepsi `bekliyor`). */
export function adimIskeleti(kosuId: string, platformlar: readonly Platform[], hatalar: readonly string[]): HataKosusuAdimi[] {
  const adimlar: HataKosusuAdimi[] = [];
  const ekle = (platform: Platform, asama: HataKosusuAdimi["asama"], hata_kodu: string | null) => {
    const sira = adimlar.length + 1;
    adimlar.push({ id: `${kosuId}-a${sira}`, platform, hata_kodu, asama, run_id: null, sonuc: "bekliyor", kiran_testler: [], neden: null, sure_ms: null, sira });
  };
  for (const p of platformlar) {
    ekle(p, "temel", null);
    for (const h of hatalar) ekle(p, "hata", h);
    ekle(p, "kapanis", null);
  }
  return adimlar;
}

/** Adımın örnek sonucu (koşucunun yapacağı iş): temel yeşil değilse platformun kalan adımları geçersiz. */
export function adimiSonuclandir(kosuId: string, a: HataKosusuAdimi, temelYesil: boolean): void {
  const tablo = MOCK_SONUCLAR[a.platform];
  const kosu = () => {
    a.run_id = `${kosuId}-r${a.sira}`;
    a.sure_ms = (a.platform === "web" ? 41_000 : 196_000) + a.sira * 700;
  };
  if (a.asama === "temel") {
    if (tablo) {
      kosu();
      a.sonuc = "yesil";
    } else {
      a.sonuc = "gecersiz";
      a.neden = TEMEL_KOSULAMADI[a.platform] ?? "Platforma ulaşılamadı.";
    }
    return;
  }
  if (!temelYesil || !tablo) {
    a.sonuc = "gecersiz";
    a.neden = `${TEMEL_YESIL_DEGIL}; adım koşulmadı.`;
    return;
  }
  if (a.asama === "kapanis") {
    kosu();
    a.sonuc = "yesil";
    return;
  }
  const s: MockAdimSonucu = tablo[a.hata_kodu ?? ""] ?? { sonuc: "kacti" };
  a.sonuc = s.sonuc;
  if (s.sonuc === "gecersiz") {
    a.neden = s.neden;
    return;
  }
  kosu();
  if (s.sonuc === "yakalandi") a.kiran_testler = [...s.testler];
}

/** Örnek veride bitmiş koşu: web + android, dokuz hata (web 8/9; android 7/8 + 1 geçersiz). */
export function ilkHataKosulari(): HataKosusuDetay[] {
  const id = "hk-1";
  const platformlar: Platform[] = ["web", "android"];
  const hatalar = HATA_KATALOGU.map((h) => h.kod);
  const adimlar = adimIskeleti(id, platformlar, hatalar);
  for (const a of adimlar) adimiSonuclandir(id, a, true);
  return [
    {
      id,
      durum: "done",
      platformlar,
      hatalar,
      commit: "9c41e2b07a11",
      baslatan_id: "u-muhendis",
      baslatan: "muhendis",
      ozet: null, // kule.ts `ozetHesapla` ile doldurur (tek formül)
      uyarilar: [],
      baslama: "2026-11-10T14:02:00+03:00",
      bitis: "2026-11-10T14:46:00+03:00",
      olusturma: "2026-11-10T14:01:40+03:00",
      adimlar,
    },
  ];
}

/** Örnek beklenti doğruluğu (§4.7): 5 uyumlu, 1 uyuşmayan (istisnayla onaylandı), 3 kapsam dışı, 1 kontrol edilemedi. */
export const MOCK_BEKLENTI: KuleBeklentiDogrulugu = {
  oran: 5 / 6,
  uyumlu: 5,
  uyumsuz: 1,
  kapsam_disi: 3,
  kontrol_edilemedi: 1,
  istisna: 1,
  kapsam_orani: 7 / 10,
};

/** core `oracle/metrik.py` `KAYNAK` (Kule bunu `kaynaklar.beklenti_dogrulugu`'na yazar). */
export const BEKLENTI_KAYNAGI =
  "AI'ın ürettiği case içeriklerinin (insan düzeltmesinden önceki hali) PO onaylı karar " +
  "tablolarıyla deterministik karşılaştırması (case_oracle_kontrol, ai_icerik=true; güncel " +
  "tablolarla yapılmış kontroller). Oran = uyumlu / (uyumlu + uyumsuz); kontrol edilemeyen ve " +
  "kapsam dışı case'ler orana girmez, ayrı sayılır. İstisna: gerekçeli istisnayla onaylanan " +
  "uyuşmazlıklar.";

/** core `control_tower.HATA_YAKALAMA_KOSU_YOK` (henüz bitmiş koşu yokken). */
export const HATA_YAKALAMA_KOSU_YOK =
  "hata_kosusu + hata_kosusu_adim: son tamamlanmış (done) ekilmiş hata koşusu; henüz yok " +
  "(ölçülmedi). Oran = yakalanan / (yakalanan + kaçan); geçersiz adımlar paydaya girmez";

export const KULE_KALITE_KAYNAKLARI = {
  beklenti_dogrulugu: BEKLENTI_KAYNAGI,
  hata_yakalama: HATA_YAKALAMA_KOSU_YOK,
} as const;
