// 012 Ş7 — örnek veri: TPD-1 karar tabloları, metamorfik ilişkiler ve "değer çıkarma" kuralları.
//
// Demo story TPD-1 (docs/DEMO-VERISI.md): kampanya tablosu PO onaylı, minimum sipariş tablosu AI
// taslağı (analist düzenler, PO onaylar), bir onaylı ve bir taslak ilişki. Kontrol sonuçları elle
// yazılmaz: `kalite.ts` aynı tabloları golden case metinleri üzerinde çalıştırır; böylece "örnekle
// dene" ile case kartındaki karşılaştırma birbirini tutar.
//
// Bilinçli örnek: minimum sipariş taslağında sınır `toplam > 750` (dahil değil) yazılıdır. AC3 "altında
// uyarı" der (750 dahil geçer). Analist düzeltmeden PO onaylarsa yüksek riskli sınır case'i (C6,
// toplam 750,00 TL) "Tabloyla uyuşmuyor" olur ve onay kapısı kapanır (ANALIZ §4.3, kabul senaryosu 3).
import type { CiktiModu, KararTablosuIcerik, MetamorfikIliskiIcerik } from "../types";

export const KALITE_REQ = "req-tpd-1";

export const KAMPANYA_TABLOSU: KararTablosuIcerik = {
  ad: "Kampanya: 6 al 1 bedava",
  ac_refs: ["AC2", "AC6"],
  aciklama: "Kampanyalı üründen her 6 adet alımda 1 adet bedava verilir (7 adette 1 bedava). İndirim, bedava adetlerin satır tutarıdır.",
  girdiler: [
    { ad: "adet", tur: "sayi", aciklama: "Kampanyalı üründen sepetteki adet" },
    { ad: "ara_toplam", tur: "sayi", birim: "TL", aciklama: "Kampanya uygulanmadan önceki satır tutarı" },
  ],
  ciktilar: [
    { ad: "bedava_adet", tur: "sayi" },
    { ad: "indirim", tur: "sayi", birim: "TL", tolerans: "0.01" },
    { ad: "toplam", tur: "sayi", birim: "TL", tolerans: "0.01" },
  ],
  satirlar: [
    {
      id: "R1",
      kosul: "adet >= 7",
      cikti: {
        bedava_adet: "adet // 7",
        indirim: "yuvarla(ara_toplam / adet * (adet // 7), 2)",
        toplam: "ara_toplam - yuvarla(ara_toplam / adet * (adet // 7), 2)",
      },
    },
    { id: "R2", kosul: "adet < 7", cikti: { bedava_adet: "0", indirim: "0", toplam: "ara_toplam" } },
  ],
};

export const MIN_SIPARIS_TABLOSU: KararTablosuIcerik = {
  ad: "Minimum sipariş tutarı",
  ac_refs: ["AC3"],
  aciklama: "Kampanyasız siparişte toplam minimum tutarın altındaysa uyarı gösterilir ve onay butonu pasif olur.",
  girdiler: [
    { ad: "toplam", tur: "sayi", birim: "TL", aciklama: "İndirim sonrası sepet toplamı" },
    { ad: "kampanyali", tur: "mantiksal", aciklama: "Sepette kampanyalı ürün var mı" },
  ],
  ciktilar: [
    { ad: "uyari_gosterilir", tur: "mantiksal" },
    { ad: "onay_aktif", tur: "mantiksal" },
  ],
  satirlar: [
    { id: "R1", kosul: "kampanyali", cikti: { uyari_gosterilir: "yanlis", onay_aktif: "dogru" } },
    { id: "R2", kosul: "toplam > 750", cikti: { uyari_gosterilir: "yanlis", onay_aktif: "dogru" } },
    { id: "R3", kosul: "toplam <= 750", cikti: { uyari_gosterilir: "dogru", onay_aktif: "yanlis" } },
  ],
};

export const IKI_KAT_ILISKISI: MetamorfikIliskiIcerik = {
  ad: "Adet iki katına çıkınca bedava adet iki katına çıkar",
  ac_refs: ["AC2"],
  tablo_ref: "T1",
  on_kosul: "adet % 7 == 0 ve adet * 2 <= 999",
  donusum: { adet: "adet * 2", ara_toplam: "ara_toplam * 2" },
  iliski: { bedava_adet: "bedava_adet * 2", indirim: "indirim * 2", toplam: "toplam * 2" },
  aciklama: "Yalnız adet 7'nin katıyken geçerlidir (aksi halde tam bölme iki katı vermez).",
};

export const YEDI_ARTIS_ILISKISI: MetamorfikIliskiIcerik = {
  ad: "Adet 7 artınca bedava adet 1 artar",
  ac_refs: ["AC2"],
  tablo_ref: "T1",
  on_kosul: "adet >= 1 ve adet + 7 <= 999",
  donusum: { adet: "adet + 7", ara_toplam: "ara_toplam / adet * (adet + 7)" },
  iliski: { bedava_adet: "bedava_adet + 1", indirim: "indirim + ara_toplam / adet", toplam: "toplam + ara_toplam / adet * 6" },
  aciklama: "Her 7 adetlik ek alımda 1 adet daha bedava verilir.",
};

export interface TabloTohumu {
  icerik: KararTablosuIcerik;
  durum: "draft" | "approved";
}
export interface IliskiTohumu {
  icerik: MetamorfikIliskiIcerik;
  durum: "draft" | "approved";
}

/** Başlangıç durumu (yalnız TPD-1): T1 onaylı, T2 AI taslağı; I1 onaylı, I2 AI taslağı. */
export const ILK_TABLOLAR: TabloTohumu[] = [
  { icerik: KAMPANYA_TABLOSU, durum: "approved" },
  { icerik: MIN_SIPARIS_TABLOSU, durum: "draft" },
];
export const ILK_ILISKILER: IliskiTohumu[] = [
  { icerik: IKI_KAT_ILISKISI, durum: "approved" },
  { icerik: YEDI_ARTIS_ILISKISI, durum: "draft" },
];

/**
 * "AI taslağı üret" çıktısı (amaç `decision_table_draft`): TPD-1 için kayıtlı (REPLAY) taslak; başka
 * gereksinimde kayıt yoktur — politika nötr boş çıktıdır (REPLAY-MISS, tablo uydurulmaz).
 */
export function taslakCiktisi(jiraKey: string | null): { mod: CiktiModu; tablolar: KararTablosuIcerik[]; iliskiler: MetamorfikIliskiIcerik[] } {
  if (jiraKey !== "TPD-1") return { mod: "replay_miss", tablolar: [], iliskiler: [] };
  return { mod: "replay", tablolar: [KAMPANYA_TABLOSU, MIN_SIPARIS_TABLOSU], iliskiler: [IKI_KAT_ILISKISI, YEDI_ARTIS_ILISKISI] };
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
  bedava_adet: [{ kalip: /\bbedava adet ([0-9]+)\b/g }, { kalip: /\b([0-9]+) adet bedava\b/g }],
  ara_toplam: [{ kalip: new RegExp(`\\bara toplam ${TL}`, "g") }],
  indirim: [{ kalip: new RegExp(`\\bindirim ${TL}`, "g") }],
  toplam: [{ kalip: new RegExp(`(?<!ara )\\b[Tt]oplam ${TL}`, "g") }],
  kampanyali: [
    { kalip: /kampanyalı ürün yok/g, deger: false },
    { kalip: /"6 al 1 bedava" kampanyasında/g, deger: true },
  ],
  uyari_gosterilir: [
    { kalip: /uyarısı (?:gösterilir|görünür)/g, deger: true },
    { kalip: /uyarı(?:sı)? (?:gösterilmez|görünmez)/g, deger: false },
  ],
  onay_aktif: [
    { kalip: /butonu aktif(?:tir)?|sipariş onaylanabilir/g, deger: true },
    { kalip: /butonu pasif(?:tir| olur)?|sipariş onaylanamaz/g, deger: false },
  ],
};
