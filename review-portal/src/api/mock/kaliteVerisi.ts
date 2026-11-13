// 012 Ş7 — örnek veri: TPD-1 karar tabloları, metamorfik ilişkiler ve "değer çıkarma" kuralları.
//
// Demo story TPD-1 (docs/DEMO-VERISI.md): kampanya tablosu PO onaylı, minimum sipariş tablosu AI
// taslağı (analist düzenler, PO onaylar), bir onaylı ve bir taslak ilişki. Kontrol sonuçları elle
// yazılmaz: `kalite.ts` aynı tabloları golden case metinleri üzerinde çalıştırır; böylece "örnekle
// dene" ile case kartındaki karşılaştırma birbirini tutar.
//
// Tablolar ve ilişki gerçek AI taslak golden'ının (`rules/replay/decision_table_draft/golden/TPD-1.json`)
// kolonlarını ve ifadelerini kullanır (T1 §13.1 V9 biçiminde): T1 `adet`, `ara_toplam` → `bedava_adet =
// adet // 7`, `indirim`, `toplam`; T2 `kampanyali_sepet`, `sepet_tutari` → `minimum_uyarisi` (eşik 750).
// "AI taslağı üret" golden'ı birebir döndürür. Case metinleri ara toplamı yazar: 7 adette bedava adet,
// indirim ve toplam karşılaştırılır.
//
// Demo anlatısı (review turu 2, u2 N2): AI taslağı T2'de klasik sınır hatası yapar — R2 `sepet_tutari <= 750`
// (story "altında uyarı" der: tam 750,00 TL'de uyarı yok). Taslak PO onayı bekler; PO sınır örnekleri ızgarasında
// "750,00 TL'de uyarı görünür" satırını story'yle karşılaştırır → "Değişiklik iste" → analist `< 750` yapar → PO
// onaylar. Aynı hatayı AI case üretiminde de yapar: C6 ("tam 750,00 TL'de uyarı görünür", `ai-sinir-hatasi`
// golden'ı). T2 düzeltilip onaylanınca C6 "Tabloyla uyuşmuyor" olur ve yüksek riskli onay kapısı kapanır.
// PO hatayı kaçırıp `<=`'yi onaylasaydı C6 da "uyumlu" görünürdü: bağımsızlık insan onayına dayanır.
import type { CiktiModu, KararTablosuIcerik, MetamorfikIliskiIcerik } from "../types";

export const KALITE_REQ = "req-tpd-1";

/**
 * T1 — §13.1 V9 biçimi: girdiler `adet`, `ara_toplam`; çıktılar `bedava_adet`, `indirim`, `toplam`.
 * `birim_fiyat` girdisi kalktı (case'ler birim fiyat yazmaz, ara toplam yazar); böylece C2/C10'da indirim
 * ve toplam da karşılaştırılır. Golden (`rules/replay/decision_table_draft/golden/TPD-1.json`) R2 şeridinde
 * aynı biçime güncellenir; bu kopya onu izler.
 */
export const KAMPANYA_TABLOSU: KararTablosuIcerik = {
  ad: "Kampanya: 6 al 1 bedava (7 adette 1 bedava)",
  ac_refs: ["AC2"],
  aciklama:
    "AC2: kampanyalı üründen her 6 adet alımda 1 adet bedava verilir (7 adette 1 bedava); bedava adet, adedin 7'ye tam bölümüdür. Bedava adet ücretlendirilmez: indirim bedava adetlerin tutarıdır, toplam ara toplamdan indirim düşülerek bulunur.",
  girdiler: [
    { ad: "adet", tur: "sayi", birim: "adet", aciklama: "Kampanyalı üründen sepetteki adet" },
    { ad: "ara_toplam", tur: "sayi", birim: "TL", aciklama: "Kampanyalı ürün satırının indirimsiz tutarı (adet × birim fiyat)" },
  ],
  ciktilar: [
    { ad: "bedava_adet", tur: "sayi", birim: "adet", aciklama: "Kampanyayla bedava verilen adet" },
    { ad: "indirim", tur: "sayi", birim: "TL", tolerans: "0.01", aciklama: "Bedava adetlerin tutarı (kampanya indirimi)" },
    { ad: "toplam", tur: "sayi", birim: "TL", tolerans: "0.01", aciklama: "İndirim düşülmüş satır tutarı" },
  ],
  satirlar: [
    {
      id: "R1",
      kosul: "adet >= 7",
      cikti: { bedava_adet: "adet // 7", indirim: "yuvarla(ara_toplam / adet * (adet // 7), 2)", toplam: "ara_toplam - yuvarla(ara_toplam / adet * (adet // 7), 2)" },
    },
    { id: "R2", kosul: "dogru", cikti: { bedava_adet: "0", indirim: "0", toplam: "ara_toplam" } },
  ],
};

/**
 * T2'nin doğru hâli (story: "altında uyarı" → `sepet_tutari < 750`; tam 750,00 TL'de uyarı yok). Analistin PO
 * isteğiyle yaptığı düzeltme budur; testler ve örnek veri bu içeriği "düzeltilmiş T2" olarak kullanır.
 */
export const MIN_SIPARIS_DOGRU: KararTablosuIcerik = {
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
 * AI taslağının PO'ya sorusu: golden `decision_table_draft/TPD-1` `output.notes`'taki soru. Çekirdek taslak
 * yazarken notlardaki "PO sorusu:" cümlelerini AC'si tutan tablonun açıklamasının sonuna aynı önekle ekler
 * (`karar_tablosu.service.po_sorulari` / `_po_sorulu`); örnek veri aynı metni taşır.
 */
export const T2_PO_SORUSU =
  "PO sorusu (AI taslak notu): tam 750,00 TL'lik kampanyasız siparişte uyarı gösterilmeli mi? (sınır örneklerinde 750 satırını kontrol edin)";

/**
 * AI taslağındaki T2 (golden `decision_table_draft/TPD-1`, u2 N2): R2 sınırı `sepet_tutari <= 750` — AI'ın
 * sınır hatası; açıklamada PO'ya soru. Örnek veride T2 bu içerikle PO onayı bekler.
 */
export const MIN_SIPARIS_TABLOSU: KararTablosuIcerik = {
  ...MIN_SIPARIS_DOGRU,
  aciklama: `${MIN_SIPARIS_DOGRU.aciklama} ${T2_PO_SORUSU}`,
  satirlar: MIN_SIPARIS_DOGRU.satirlar.map((s) => (s.id === "R2" ? { ...s, kosul: "sepet_tutari <= 750" } : s)),
};
/** Geriye uyum: eski ad (golden artık AI'ın `<=` taslağıdır). */
export const MIN_SIPARIS_GOLDEN = MIN_SIPARIS_TABLOSU;

/** Golden'daki tek ilişki (T1) — V9 biçiminde (ara toplam ve toplam da iki katına çıkar). */
export const IKI_KAT_ILISKISI: MetamorfikIliskiIcerik = {
  ad: "Adet iki katına çıkınca bedava adet ve tutarlar iki katına çıkar",
  ac_refs: ["AC2"],
  tablo_ref: "T1",
  on_kosul: "adet >= 7 ve adet % 7 == 0",
  // V9: ara toplam da dönüşür; aksi hâlde türetilen case'te kaynak tutar kalırdı (tutarsiz_kalan_deger).
  donusum: { adet: "adet * 2", ara_toplam: "ara_toplam * 2" },
  iliski: { bedava_adet: "bedava_adet * 2", indirim: "indirim * 2", toplam: "toplam * 2" },
  aciklama: "AC2: her 7 adette 1 bedava; adet 7'nin katıyken iki katına çıkarsa bedava adet de iki katına çıkar (7 → 1, 14 → 2).",
};

/**
 * Elle eklenebilecek ilişki örneği (golden'da yok). Review turu 1 (analist/PO 20): başlangıç verisinden
 * çıkarıldı — örnek veri gerçek çekirdekle aynı hikâyeyi anlatır (yalnız golden'daki I1). Testler elle
 * ilişki akışını bu içerikle kurar.
 */
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
  durum: "draft" | "pending_po" | "approved";
}
export interface IliskiTohumu {
  icerik: MetamorfikIliskiIcerik;
  durum: "draft" | "approved";
  /** Elle eklenmiş ilişki (golden'da yok). */
  elle?: boolean;
}

/**
 * Başlangıç durumu (yalnız TPD-1): T1 onaylı; T2 AI taslağı PO onayı bekliyor (analist değiştirmeden gönderdi;
 * R2'de AI'ın `<= 750` sınır hatası var — demo adımı 2'de PO yakalar); I1 onaylı (golden).
 */
export const ILK_TABLOLAR: TabloTohumu[] = [
  { icerik: KAMPANYA_TABLOSU, durum: "approved" },
  { icerik: MIN_SIPARIS_TABLOSU, durum: "pending_po" },
];
export const ILK_ILISKILER: IliskiTohumu[] = [
  { icerik: IKI_KAT_ILISKISI, durum: "approved" },
];

/** Tablo tohumunun AI taslağındaki özgün içeriği ("analist değiştirdi" işareti için; sıra = ILK_TABLOLAR). */
export const ILK_TABLO_AI_ICERIKLERI: KararTablosuIcerik[] = [KAMPANYA_TABLOSU, MIN_SIPARIS_TABLOSU];

/**
 * "AI taslağı üret" çıktısı (amaç `decision_table_draft`): TPD-1 için kayıtlı (REPLAY) taslak; başka
 * gereksinimde kayıt yoktur — politika nötr boş çıktıdır (REPLAY-MISS, tablo uydurulmaz).
 */
export function taslakCiktisi(jiraKey: string | null): { mod: CiktiModu; tablolar: KararTablosuIcerik[]; iliskiler: MetamorfikIliskiIcerik[] } {
  if (jiraKey !== "TPD-1") return { mod: "replay_miss", tablolar: [], iliskiler: [] };
  return { mod: "replay", tablolar: [KAMPANYA_TABLOSU, MIN_SIPARIS_TABLOSU], iliskiler: [IKI_KAT_ILISKISI] };
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
  // V9: ara toplam ve (T1) toplam case metninde yazılıdır ("ara toplam 175,00 TL, indirim 25,00 TL, toplam 150,00 TL").
  ara_toplam: [{ kalip: new RegExp(`\\bara toplam ${TL}`, "g") }],
  toplam: [{ kalip: new RegExp(`(?<!ara )\\b[Tt]oplam ${TL}`, "g") }],
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

/**
 * Sınır örnekleri için girdi kümeleri (R2 `ornekler` ucunun mock karşılığı). Sayı koşullarındaki sabitlerin
 * çevresi (`adet >= 7` → 6, 7, 8; `sepet_tutari < 750` → 749,99 / 750 / 750,01) ve tam bölme bölenlerinin
 * katları (`adet // 7` → 13, 14) denenir. Mantıksal girdi her iki değeriyle, diğer girdiler temsil değeriyle
 * doldurulur. TPD-1 T1'de `ara_toplam` demo birim fiyatından (25,00 TL) hesaplanır; böylece indirim ve
 * toplam okunur değer çıkar.
 */
export function ornekGirdileri(icerik: KararTablosuIcerik): Record<string, number | boolean>[] {
  const sayilar = icerik.girdiler.filter((g) => g.tur === "sayi").map((g) => g.ad);
  const mantiksal = icerik.girdiler.filter((g) => g.tur === "mantiksal").map((g) => g.ad);
  const ifadeler = icerik.satirlar.flatMap((s) => [s.kosul, ...Object.values(s.cikti)]);
  const sinirlar: Record<string, Set<number>> = Object.fromEntries(sayilar.map((a) => [a, new Set<number>()]));
  for (const ad of sayilar) {
    const ondalik = icerik.girdiler.find((g) => g.ad === ad)?.birim === "TL";
    const adim = ondalik ? 0.01 : 1;
    for (const m of ifadeler.join(" ").matchAll(new RegExp(`\\b${ad}\\s*(<=|>=|<|>|==|!=)\\s*([0-9]+(?:\\.[0-9]+)?)`, "g"))) {
      const c = Number(m[2]);
      [c - adim, c, c + adim].forEach((v) => sinirlar[ad].add(Math.round(v * 100) / 100));
    }
    for (const m of ifadeler.join(" ").matchAll(new RegExp(`\\b${ad}\\s*//\\s*([0-9]+)`, "g"))) {
      const d = Number(m[1]);
      [d - 1, d, d + 1, 2 * d - 2, 2 * d - 1, 2 * d].forEach((v) => sinirlar[ad].add(v));
    }
  }
  const birimFiyat = 25;
  const temsil = (ad: string, kume: Record<string, number | boolean>): number =>
    ad === "ara_toplam" && typeof kume.adet === "number" ? kume.adet * birimFiyat : ([...sinirlar[ad]].sort((a, b) => a - b)[1] ?? 0);
  const sonuc: Record<string, number | boolean>[] = [];
  const mantiksalKume = mantiksal.length ? [false, true] : [null];
  for (const ad of sayilar) {
    for (const v of [...sinirlar[ad]].filter((x) => x >= 0).sort((a, b) => a - b)) {
      for (const mv of mantiksalKume) {
        const kume: Record<string, number | boolean> = { [ad]: v };
        mantiksal.forEach((m) => (kume[m] = mv as boolean));
        sayilar.filter((x) => x !== ad).forEach((x) => (kume[x] = temsil(x, kume)));
        // Mantıksal "doğru" kolu yalnız bir kez (ilk sınır değeriyle) yeterli; ızgara kısa kalır.
        if (mv === true && sonuc.some((o) => mantiksal.every((m) => o[m] === true))) continue;
        sonuc.push(kume);
      }
    }
  }
  return sonuc;
}
