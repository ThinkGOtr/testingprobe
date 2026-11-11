// 012/Ş8 örnek verisi: ekilmiş hata kataloğu (ANALIZ §4.6'daki dokuz hata), örnek test paketi, hata ×
// platform sonuç tablosu ve bitmiş bir koşu (web + android). Sayılar ÖRNEK VERİ bandı altında gösterilir.
import { EKILMIS_HATA_ADI } from "../../lib/etiketler";
import type { Platform } from "../../lib/platform";
import type { HataKatalogOgesi, HataKosusuAdimi, HataKosusuDetay, KuleBeklentiDogrulugu } from "../types";

const hata = (kod: string, tur: HataKatalogOgesi["tur"], aciklama: string, yakalayan_kural: string): HataKatalogOgesi => ({
  kod,
  ad: EKILMIS_HATA_ADI[kod] ?? kod,
  tur,
  aciklama,
  yakalayan_kural,
});

/** core `rules/hata-katalogu.yaml` ile aynı kodlar ve sıra (§4.6 tablosu). */
export const HATA_KATALOGU: HataKatalogOgesi[] = [
  hata("kampanya_bedava_yok", "kod", "Kampanyada bedava adet hep 0 hesaplanır.", "kampanya"),
  hata("kampanya_esik_7", "kod", "Bedava adet 6 yerine her 7 üründe bir verilir (adet // 7).", "kampanya (6'nın katlarında)"),
  hata("kampanya_cift_indirim", "kod", "Kampanya indirimi sepet toplamından iki kez düşülür.", "kampanya toplamı"),
  hata("min_siparis_haric", "kod", "Minimum sipariş sınırı dahil sayılmaz (toplam > minimum).", "minimum sipariş sınırı"),
  hata("min_siparis_muafiyet_yok", "kod", "Kampanyalı sepet de minimum sipariş tutarına tabi tutulur.", "minimum sipariş muafiyeti"),
  hata("min_siparis_500", "veri", "Minimum sipariş tutarı 750,00 TL yerine 500,00 TL okunur.", "minimum sipariş"),
  hata("min_siparis_1000", "veri", "Minimum sipariş tutarı 750,00 TL yerine 1.000,00 TL okunur.", "minimum sipariş"),
  hata("fiyat_p004_31", "veri", "P-004 ürününün fiyatı 30,00 TL yerine 31,00 TL okunur.", "toplam"),
  hata("kampanya_urunu_p002", "veri", "Kampanyalı ürün P-001 yerine P-002 olur.", "kampanya"),
];

const T_SAYAC = "TPD-1 C1 · Sepete ekle ile sepet sayacı artar";
const T_KAMPANYA = "TPD-1 C2 · 7 adet kampanyalı üründe 1 adet bedava";
const T_MIN_ALT = "TPD-1 C4 · Minimum sipariş tutarının altında sipariş verilemez";
const T_MIN_SINIR = "TPD-1 C5 · Minimum sipariş sınırında (750,00 TL) sipariş verilir";
const T_MUAF = "TPD-1 C6 · Kampanyalı sepet minimum sipariş tutarından muaftır";
const T_TOPLAM = "TPD-1 C7 · Kampanya indirimi sepet toplamından bir kez düşülür";

/** Onaylı test paketi (her platformda aynı case'ler). */
export const PAKET_TESTLERI = [T_SAYAC, T_KAMPANYA, T_MIN_ALT, T_MIN_SINIR, T_MUAF, T_TOPLAM];

export type MockAdimSonucu = { sonuc: "yakalandi"; testler: string[] } | { sonuc: "kacti" } | { sonuc: "gecersiz"; neden: string };

const WEB: Record<string, MockAdimSonucu> = {
  kampanya_bedava_yok: { sonuc: "yakalandi", testler: [T_KAMPANYA, T_TOPLAM] },
  // 7 adette `adet // 6` ve `adet // 7` aynı sonucu verir; 6 adetlik onaylı test yok → kaçar.
  kampanya_esik_7: { sonuc: "kacti" },
  kampanya_cift_indirim: { sonuc: "yakalandi", testler: [T_TOPLAM] },
  min_siparis_haric: { sonuc: "yakalandi", testler: [T_MIN_SINIR] },
  min_siparis_muafiyet_yok: { sonuc: "yakalandi", testler: [T_MUAF] },
  min_siparis_500: { sonuc: "yakalandi", testler: [T_MIN_ALT] },
  min_siparis_1000: { sonuc: "yakalandi", testler: [T_MIN_SINIR] },
  // Hiçbir onaylı case P-004'ü sepete koymuyor → kaçar.
  fiyat_p004_31: { sonuc: "kacti" },
  kampanya_urunu_p002: { sonuc: "yakalandi", testler: [T_KAMPANYA] },
};

/** Platform × hata sonucu. `null`: platformun temel koşusu koşulamadı (cihaz kapalı) → tüm adımlar geçersiz. */
export const MOCK_SONUCLAR: Record<Platform, Record<string, MockAdimSonucu> | null> = {
  web: WEB,
  android: {
    ...WEB,
    kampanya_cift_indirim: { sonuc: "kacti" },
    min_siparis_1000: { sonuc: "gecersiz", neden: "Appium oturumu koptu (ortam hatası); adım sayılmadı." },
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

/** Örnek veride bitmiş koşu: web + android, dokuz hata (web 7/9; android 5/8 + 1 geçersiz). */
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

export const KULE_KALITE_KAYNAKLARI = {
  beklenti_dogrulugu:
    "case_oracle_kontrol: AI'ın ürettiği içeriğin (insan düzeltmesinden önce) onaylı karar tablosuyla karşılaştırması · uyumlu / (uyumlu + uyuşmayan)",
  hata_yakalama: "hata_kosusu_adim: son ekilmiş hata koşusu · yakalanan / (yakalanan + kaçan); geçersiz adımlar paydaya girmez",
} as const;
