// 012 Ş7 — örnek veri: TPD-1 karar tabloları, metamorfik ilişkiler ve "değer çıkarma" kuralları.
//
// Demo story TPD-1 (docs/DEMO-VERISI.md): kampanya tablosu PO onaylı, minimum sipariş tablosu AI
// taslağı (analist düzenler, PO onaylar), bir onaylı ve bir taslak ilişki. Kontrol sonuçları elle
// yazılmaz: `kalite.ts` aynı tabloları golden case metinleri üzerinde çalıştırır; böylece "örnekle
// dene" ile case kartındaki karşılaştırma birbirini tutar.
//
// Tablolar ve ilişki gerçek AI taslak golden'ının (`rules/replay/decision_table_draft/golden/TPD-1.json`)
// kolonlarını ve ifadelerini kullanır: T1 `adet`, `birim_fiyat` → `bedava_adet = adet // 7`, `indirim`;
// T2 `kampanyali_sepet`, `sepet_tutari` → `minimum_uyarisi` (eşik 750). "AI taslağı üret" golden'ı birebir
// döndürür. Case metinleri birim fiyatı yazmaz: 7 adette `indirim` karşılaştırılamaz (çekirdek
// `kismi_degerlendir`), 6 adette (R2, sabit) karşılaştırılır — C3 "6 adet … bedava ürün verilmez" uyumlu.
//
// Bilinçli örnek: başlangıçtaki T2 taslağında sınır `sepet_tutari <= 750` yazılıdır (golden: `< 750`).
// AC3 "altında uyarı" der (750 dahil geçer). Analist düzeltmeden PO onaylarsa yüksek riskli sınır case'i
// (C6, toplam 750,00 TL) "Tabloyla uyuşmuyor" olur ve onay kapısı kapanır (ANALIZ §4.3, kabul senaryosu 3).
import type { CiktiModu, KararTablosuIcerik, MetamorfikIliskiIcerik } from "../types";

export const KALITE_REQ = "req-tpd-1";

/** Gerçek AI taslak golden'ı (`rules/replay/decision_table_draft/golden/TPD-1.json`) T1 — birebir. */
export const KAMPANYA_TABLOSU: KararTablosuIcerik = {
  ad: "Kampanya: 6 al 1 bedava (7 adette 1 bedava)",
  ac_refs: ["AC2"],
  aciklama:
    "AC2: kampanyalı üründen her 6 adet alımda 1 adet bedava verilir (7 adette 1 bedava); bedava adet, adedin 7'ye tam bölümüdür. Bedava adet ücretlendirilmez.",
  girdiler: [
    { ad: "adet", tur: "sayi", birim: "adet", aciklama: "Kampanyalı üründen sepetteki adet" },
    { ad: "birim_fiyat", tur: "sayi", birim: "TL", aciklama: "Kampanyalı ürünün birim fiyatı" },
  ],
  ciktilar: [
    { ad: "bedava_adet", tur: "sayi", birim: "adet", aciklama: "Kampanyayla bedava verilen adet" },
    { ad: "indirim", tur: "sayi", birim: "TL", tolerans: "0.01", aciklama: "Bedava adetlerin tutarı (kampanya indirimi)" },
  ],
  satirlar: [
    { id: "R1", kosul: "adet >= 7", cikti: { bedava_adet: "adet // 7", indirim: "(adet // 7) * birim_fiyat" } },
    { id: "R2", kosul: "dogru", cikti: { bedava_adet: "0", indirim: "0" } },
  ],
};

/** Golden T2 — birebir (sınır `sepet_tutari < 750`: tam 750,00 TL'de uyarı yok). */
export const MIN_SIPARIS_GOLDEN: KararTablosuIcerik = {
  ad: "Minimum sipariş tutarı (kampanyasız siparişler)",
  ac_refs: ["AC3", "AC6"],
  aciklama:
    'AC3: kampanyasız siparişlerde minimum sipariş tutarı 750,00 TL\'dir; altında "Minimum sipariş tutarı 750,00 TL" uyarısı gösterilir ve onay butonu pasif olur. AC6: kampanyalı siparişlerde bu şart aranmaz.',
  girdiler: [
    { ad: "kampanyali_sepet", tur: "mantiksal", aciklama: "Sepette kampanyalı ürün var mı" },
    { ad: "sepet_tutari", tur: "sayi", birim: "TL", aciklama: "Siparişin tutarı" },
  ],
  ciktilar: [
    {
      ad: "minimum_uyarisi",
      tur: "mantiksal",
      aciklama: '"Minimum sipariş tutarı 750,00 TL" uyarısı gösterilir ve onay butonu pasif olur',
    },
  ],
  satirlar: [
    { id: "R1", kosul: "kampanyali_sepet", cikti: { minimum_uyarisi: "yanlis" } },
    { id: "R2", kosul: "sepet_tutari < 750", cikti: { minimum_uyarisi: "dogru" } },
    { id: "R3", kosul: "dogru", cikti: { minimum_uyarisi: "yanlis" } },
  ],
};

/**
 * Örnek verideki T2 taslağı: golden'la aynı kolonlar, R2 sınırı bilinçli olarak `<= 750` (demo anlatısı,
 * dosya başı). Yalnız bu satır golden'dan ayrılır.
 */
export const MIN_SIPARIS_TABLOSU: KararTablosuIcerik = {
  ...MIN_SIPARIS_GOLDEN,
  satirlar: MIN_SIPARIS_GOLDEN.satirlar.map((s) => (s.id === "R2" ? { ...s, kosul: "sepet_tutari <= 750" } : s)),
};

/** Golden'daki tek ilişki (T1) — birebir. */
export const IKI_KAT_ILISKISI: MetamorfikIliskiIcerik = {
  ad: "Adet iki katına çıkınca bedava adet ve indirim iki katına çıkar",
  ac_refs: ["AC2"],
  tablo_ref: "T1",
  on_kosul: "adet >= 7 ve adet % 7 == 0",
  donusum: { adet: "adet * 2" },
  iliski: { bedava_adet: "bedava_adet * 2", indirim: "indirim * 2" },
  aciklama: "AC2: her 7 adette 1 bedava; adet 7'nin katıyken iki katına çıkarsa bedava adet de iki katına çıkar (7 → 1, 14 → 2).",
};

/** Örnek verideki elle eklenmiş ilişki taslağı (golden'da yok; analist ekledi — `ai_generated: false`). */
export const YEDI_ARTIS_ILISKISI: MetamorfikIliskiIcerik = {
  ad: "Adet 7 artınca bedava adet 1 artar",
  ac_refs: ["AC2"],
  tablo_ref: "T1",
  on_kosul: "adet >= 1",
  donusum: { adet: "adet + 7" },
  iliski: { bedava_adet: "bedava_adet + 1" },
  aciklama: "Her 7 adetlik ek alımda 1 adet daha bedava verilir.",
};

export interface TabloTohumu {
  icerik: KararTablosuIcerik;
  durum: "draft" | "approved";
}
export interface IliskiTohumu {
  icerik: MetamorfikIliskiIcerik;
  durum: "draft" | "approved";
  /** Elle eklenmiş ilişki (golden'da yok). */
  elle?: boolean;
}

/** Başlangıç durumu (yalnız TPD-1): T1 onaylı, T2 AI taslağı (sınırı bilinçli hatalı); I1 onaylı (golden), I2 elle eklenmiş taslak. */
export const ILK_TABLOLAR: TabloTohumu[] = [
  { icerik: KAMPANYA_TABLOSU, durum: "approved" },
  { icerik: MIN_SIPARIS_TABLOSU, durum: "draft" },
];
export const ILK_ILISKILER: IliskiTohumu[] = [
  { icerik: IKI_KAT_ILISKISI, durum: "approved" },
  { icerik: YEDI_ARTIS_ILISKISI, durum: "draft", elle: true },
];

/**
 * "AI taslağı üret" çıktısı (amaç `decision_table_draft`): TPD-1 için kayıtlı (REPLAY) taslak; başka
 * gereksinimde kayıt yoktur — politika nötr boş çıktıdır (REPLAY-MISS, tablo uydurulmaz).
 */
export function taslakCiktisi(jiraKey: string | null): { mod: CiktiModu; tablolar: KararTablosuIcerik[]; iliskiler: MetamorfikIliskiIcerik[] } {
  if (jiraKey !== "TPD-1") return { mod: "replay_miss", tablolar: [], iliskiler: [] };
  return { mod: "replay", tablolar: [KAMPANYA_TABLOSU, MIN_SIPARIS_GOLDEN], iliskiler: [IKI_KAT_ILISKISI] };
}

/**
 * Değer çıkarma (amaç `case_facts`) için örnek veri kuralları: kolon adı → case metninde aranacak
 * kalıplar. Gerçekte bu adımı model yapar; burada TPD-1 golden case'lerinin dilini bilen kalıplar
 * aynı çıktıyı üretir. Sayı kolonunda ilk yakalama grubu alıntıdır (`sayi_ayristir(alinti)` = değer);
 * mantıksal kolonda eşleşen metin alıntıdır ve değer kalıbın `deger`idir. Kural tablosunda olmayan
 * kolondan olgu çıkmaz → grup "çıkarılamadı" → sonuç `kontrol_edilemedi` (REPLAY kaçırma politikası).
 */
export interface CikarmaKurali {
  kalip: RegExp;
  /** Mantıksal kolon: eşleşme bu değeri bildirir. */
  deger?: boolean;
}

const TL = "([0-9][0-9.]*,[0-9]{2} TL)";

export const CIKARMA_KURALLARI: Record<string, CikarmaKurali[]> = {
  adet: [
    { kalip: /×\s*([0-9]+)\b/g },
    { kalip: /(?<!bedava )\badet ([0-9]+)\b/g },
    { kalip: /\badedi ([0-9]+) yap/g },
    { kalip: /\b([0-9]+) adette\b/g },
    { kalip: /\b([0-9]+) adet\b(?! bedava)/g },
    { kalip: /Sepet sayacı ([0-9]+) olur/g },
  ],
  // Birim fiyat case metinlerinde yazmaz (golden case_facts da çıkarmaz).
  birim_fiyat: [],
  bedava_adet: [{ kalip: /\bbedava adet ([0-9]+)\b/g }, { kalip: /\b([0-9]+) adet bedava\b/g }],
  indirim: [{ kalip: new RegExp(`\\bindirim ${TL}`, "g") }],
  sepet_tutari: [{ kalip: new RegExp(`(?<!ara )\\b[Tt]oplam ${TL}`, "g") }],
  kampanyali_sepet: [
    { kalip: /[Ss]epette kampanyalı ürün yok/g, deger: false },
    { kalip: /"6 al 1 bedava" kampanyasında/g, deger: true },
    { kalip: /Kampanyalı sepette/g, deger: true },
  ],
  minimum_uyarisi: [
    { kalip: /"Minimum sipariş tutarı 750,00 TL" uyarısı (?:gösterilir|görünür)/g, deger: true },
    { kalip: /(?:minimum sipariş )?uyarı(?:sı)? (?:gösterilmez|görünmez)/g, deger: false },
  ],
};
