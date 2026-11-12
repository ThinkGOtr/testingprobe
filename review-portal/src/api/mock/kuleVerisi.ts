// 012/Ş8 örnek verisi: ekilmiş hata kataloğu (ANALIZ §4.6'daki dokuz hata), örnek test paketi, hata ×
// platform sonuç tablosu ve bitmiş bir koşu (web + android). Sayılar ÖRNEK VERİ bandı altında gösterilir.
import type { Platform } from "../../lib/platform";
import type { HataKatalogOgesi, HataKosusuAdimi, HataKosusuDetay } from "../types";
import { TEST_C1, TEST_C2, TEST_C3 } from "./fixtures";
import { KALITE_REQ } from "./kaliteVerisi";

const hata = (
  kod: string,
  tur: HataKatalogOgesi["tur"],
  ad: string,
  aciklama: string,
  yakalayan_kural: string,
  kural: { ac_refs: string[]; tablo: string | null; ayirt_edici: HataKatalogOgesi["ayirt_edici"] },
): HataKatalogOgesi => ({ kod, ad, tur, aciklama, yakalayan_kural, ...kural, requirement_id: KALITE_REQ });

const T1 = (girdi: string, dogru: string, hatali: string) => ({ ac_refs: ["AC2"], tablo: "T1", ayirt_edici: { girdi, dogru, hatali } });
const T2 = (ac: string, girdi: string, dogru: string, hatali: string) => ({ ac_refs: [ac], tablo: "T2", ayirt_edici: { girdi, dogru, hatali } });

/**
 * core `rules/hata-katalogu.yaml` ile birebir (kod, ad, tür, açıklama, yakalayan kural; aynı sıra). K9 (§13.1):
 * `kampanya_esik_7` çıktı (story'ye uygun davranıştı); yerine `kampanya_tek_bedava`. Kayıtlar `ac_refs`,
 * `tablo` ve `ayirt_edici` taşır. `requirement_id` sözleşmede yok (bağlantı için önerilen alan; core
 * vermezse portal bağlantı çizmez).
 */
export const HATA_KATALOGU: HataKatalogOgesi[] = [
  hata("kampanya_bedava_yok", "kod", "Kampanyada bedava ürün verilmiyor", "Kampanyalı üründe bedava adet her zaman 0 hesaplanır (mevcut kırılma; BREAK_CAMPAIGN ile aynı etki).", "Kampanya (6 al 1 bedava)", T1("adet = 7", "bedava_adet = 1", "bedava_adet = 0")),
  hata("kampanya_tek_bedava", "kod", "Kampanyada en çok 1 bedava", "Ayırt edici girdi 14 adet: doğru 2 bedava, hatalı 1. Bedava adet en çok 1 verilir (min(1, adet // 6)). Hatasız uygulamayla 6 ve 7 adette aynı sonucu verir; 14 adette (7'nin 2 katı) ayrılır.", "Kampanya (çoklu bedava adet)", T1("adet = 14", "bedava_adet = 2", "bedava_adet = 1")),
  hata("kampanya_cift_indirim", "kod", "Kampanya indirimi iki kez düşülüyor", "Kampanya indirimi sepet toplamından iki kez düşülür.", "Kampanyalı sepetin indirimi ve toplamı", T1("adet = 7, ara_toplam = 175,00", "toplam = 150,00", "toplam = 125,00")),
  hata("min_siparis_haric", "kod", "Minimum sipariş sınırı dahil değil", "Toplam minimum tutara eşitken sipariş kabul edilmez (sınır dahil olması gerekirken hariç tutulur).", "Minimum sipariş tutarı sınır değeri", T2("AC3", "kampanyali_sepet = yanlış, sepet_tutari = 750,00", "minimum_uyarisi = yanlış", "minimum_uyarisi = doğru")),
  hata("min_siparis_muafiyet_yok", "kod", "Kampanyalı sepet minimumdan muaf değil", "Kampanyalı sepet de minimum sipariş tutarına tabi tutulur.", "Minimum sipariş muafiyeti (kampanyalı sepet)", T2("AC6", "kampanyali_sepet = doğru, sepet_tutari = 150,00", "minimum_uyarisi = yanlış", "minimum_uyarisi = doğru")),
  hata("min_siparis_500", "veri", "Minimum sipariş tutarı 500", "Minimum sipariş tutarı 750 yerine 500 okunur (story'nin eski değeri).", "Minimum sipariş tutarı", T2("AC3", "kampanyali_sepet = yanlış, sepet_tutari = 600,00", "minimum_uyarisi = doğru", "minimum_uyarisi = yanlış")),
  hata("min_siparis_1000", "veri", "Minimum sipariş tutarı 1000", "Minimum sipariş tutarı 750 yerine 1000 okunur.", "Minimum sipariş tutarı", T2("AC3", "kampanyali_sepet = yanlış, sepet_tutari = 800,00", "minimum_uyarisi = yanlış", "minimum_uyarisi = doğru")),
  hata("fiyat_p004_31", "veri", "P-004 fiyatı 31", "P-004 ürününün birim fiyatı 30 yerine 31 okunur.", "Satır ve sepet toplamı", { ac_refs: ["AC1"], tablo: null, ayirt_edici: { girdi: "1 adet P-004", dogru: "satır tutarı = 30,00", hatali: "satır tutarı = 31,00" } }),
  hata("kampanya_urunu_p002", "veri", "Kampanyalı ürün P-002", "Kampanyalı ürün P-001 yerine P-002 olarak okunur.", "Kampanya (kampanyalı ürün)", T1("7 adet P-001", "bedava_adet = 1", "bedava_adet = 0")),
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

/**
 * Üretilmiş (AI) testler (`tests/generated/`): onaylı TPD-1 case'lerinden şablonla üretilen C1, C2, C3 testleri —
 * triage ve script ekranlarındaki testlerle aynı adlar (u2 N4: Kule ile triage aynı şeyi söyler). K12: ana oran
 * yalnız bunlarla ölçülür.
 */
export const AI_TESTLERI: readonly string[] = [TEST_C1, TEST_C2, TEST_C3];

/**
 * Hatasız temel koşuda zaten kırmızı olan testler (K12: hariç tutulur ve listelenir). C3'ün testi onaylı tabloyu
 * izler (6 adette bedava 0), bugünkü uygulama 1 bedava verir → açık defect adayı (triage `fail-4`).
 */
export const TEMELDE_KIRMIZI: readonly string[] = [TEST_C3];

/** Onaylı test paketi (adım koşusu ayrıntısındaki test listesi): üretilmiş testler + el yazısı suite. */
export const PAKET_TESTLERI = [
  ...AI_TESTLERI,
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

/**
 * `sayilmayan`: hatalı koşuda kırmızıya dönen ama assertion dışı nedenle (locator bulunamadı, zaman aşımı)
 * düştüğü için yakalama sayılmayan testler (K12). Core bunları adımın `neden` notunda bildirir.
 */
export type MockAdimSonucu =
  | { sonuc: "yakalandi"; testler: string[]; sayilmayan?: string[] }
  | { sonuc: "kacti" }
  | { sonuc: "gecersiz"; neden: string };

/**
 * Web: demo uygulamada ölçülen el yazısı matris (2026-11-12; `demo-app/README.md` "Ekilmiş hatalar") + üretilmiş
 * C2 testi (7 adet, ara toplam 175 / indirim 25 / toplam 150 / bedava 1): bedava yok, çift indirim ve kampanya ürünü
 * hatalarında kırmızıya döner; C1 (sepete ekle) hiçbir hatayı ayırt etmez; C3 temelde kırmızı (hariç). AI: 3/9.
 * El yazısı:
 * yakalanan 8/9, kaçan yalnız `kampanya_tek_bedava` (K9: el yazımı testler yalnız 6–7 adeti dener; hata 12
 * adet ve üstünde görünür). Kıran testlerin hepsi el yazısı suite'ten; assertion kırmızısı sayıları
 * 3, 2, 1, 1, 4, 5, 5, 7. Locator / zaman aşımıyla düşen testler sayılmaz: `min_siparis_haric` 1,
 * `min_siparis_1000` 2, `kampanya_urunu_p002` 1.
 */
const WEB: Record<string, MockAdimSonucu> = {
  kampanya_bedava_yok: { sonuc: "yakalandi", testler: [TEST_C2, T_KAMPANYA, T_SIPARIS, T_PO_BEDAVA] },
  kampanya_tek_bedava: { sonuc: "kacti" },
  kampanya_cift_indirim: { sonuc: "yakalandi", testler: [TEST_C2, T_KAMPANYA, T_SIPARIS] },
  min_siparis_haric: { sonuc: "yakalandi", testler: [T_MIN_ULAS], sayilmayan: [T_PO_GECMIS] },
  min_siparis_muafiyet_yok: { sonuc: "yakalandi", testler: [T_MUAF] },
  min_siparis_500: { sonuc: "yakalandi", testler: [T_A11Y_SEPET, T_MIN_ALT, T_API_RED, T_PO_MIN] },
  min_siparis_1000: { sonuc: "yakalandi", testler: [T_A11Y_SEPET, T_MIN_ALT, T_MIN_ULAS, T_API_RED, T_PO_MIN], sayilmayan: [T_PO_GECMIS, T_LOC_MENU] },
  fiyat_p004_31: { sonuc: "yakalandi", testler: [T_KATALOG, T_MIN_ULAS, T_MOBIL, T_SIPARIS, T_PO_GECMIS] },
  kampanya_urunu_p002: { sonuc: "yakalandi", testler: [TEST_C2, T_A11Y_SEPET, T_KATALOG, T_KAMPANYA, T_KAMPANYASIZ, T_MIN_ALT, T_MUAF, T_PO_BEDAVA], sayilmayan: [T_SIPARIS] },
};

/** Sayılmayan kırmızılar için adım notu (core `neden`). */
export const sayilmayanNotu = (testler: readonly string[]) =>
  // u2 N15: test adları cümleye karışmasın — tırnak içinde.
  `${testler.length} test assertion dışı nedenle kırmızı (locator / zaman aşımı); yakalama sayılmadı: ${testler.map((t) => `“${t}”`).join(", ")}`;

/** Platform × hata sonucu. `null`: platformun temel koşusu koşulamadı (cihaz kapalı) → tüm adımlar geçersiz. */
export const MOCK_SONUCLAR: Record<Platform, Record<string, MockAdimSonucu> | null> = {
  web: WEB,
  // Android (Java + Appium) ölçülmedi: örnek veride web'le aynı sonuçlar, bir adım ortam hatasıyla geçersiz.
  android: {
    ...WEB,
    min_siparis_1000: {
      sonuc: "gecersiz",
      neden: "Cihaz/Appium erişilemiyor: oturum komutu zaman aşımına uğradı.",
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
    adimlar.push({
      id: `${kosuId}-a${sira}`,
      platform,
      hata_kodu,
      hata_adi: hata_kodu ? (HATA_KATALOGU.find((h) => h.kod === hata_kodu)?.ad ?? null) : null,
      asama,
      run_id: null,
      sonuc: "bekliyor",
      kiran_testler: [],
      temelde_kirmizi: [],
      neden: null,
      sure_ms: null,
      sira,
    });
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
      // K12: temel koşu "yeşil" sayılır; temelde kırmızı testler listelenir ve platformun sayımından hariç tutulur.
      a.sonuc = "yesil";
      a.temelde_kirmizi = [...TEMELDE_KIRMIZI];
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
  if (s.sonuc === "yakalandi") {
    a.kiran_testler = s.testler.map((test) => ({ test, kaynak: AI_TESTLERI.includes(test) ? "ai" : "el" }));
    if (s.sayilmayan?.length) a.neden = sayilmayanNotu(s.sayilmayan);
  }
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
