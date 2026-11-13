// Kod değerlerinin Türkçe arayüz etiketleri.
import type {
  BugDurumu,
  BulguDurumu,
  BulguKarari,
  BulguTuru,
  CaseDurumu,
  GereksinimDurumu,
  HataSinifi,
  KosuKaynagi,
  RetNedeni,
  Rol,
  ScriptDurumu,
  SoruTuru,
  Tetik,
} from "../api/types";
import { ROL_ETIKETLERI } from "./yetki";

export type Ton = "notr" | "bilgi" | "basari" | "uyari" | "hata" | "vurgu";

/** Rol etiketleri (core `yetki.ROL_ETIKETLERI`; tek kaynak `lib/yetki.ts`). */
export const ROL: Record<Rol, string> = ROL_ETIKETLERI;

/** core REQUIREMENT durum makinesinin her durumu için Türkçe etiket (eksik anahtar derleme hatasıdır). */
export const GEREKSINIM_DURUMU: Record<GereksinimDurumu, { etiket: string; ton: Ton }> = {
  new: { etiket: "Yeni", ton: "notr" },
  in_review: { etiket: "İnceleniyor", ton: "bilgi" },
  findings_open: { etiket: "Bulgu kararı bekliyor", ton: "uyari" },
  doc_final: { etiket: "Doküman son hâlinde", ton: "basari" },
  pending_po: { etiket: "PO teyidi bekliyor", ton: "uyari" },
  po_approved: { etiket: "PO onaylı", ton: "basari" },
  generating: { etiket: "Case üretiliyor", ton: "bilgi" },
  cases_ready: { etiket: "Case review", ton: "bilgi" },
  done: { etiket: "Case'ler yayınlandı", ton: "basari" },
  failed: { etiket: "Hata", ton: "hata" },
};

/** Kabul kriteri olmayan gereksinim için durumun yerine gösterilen etiket. */
export const AC_EKSIK = { etiket: "AC eksik", ton: "uyari" as Ton };

export function gereksinimDurumu(d: string): { etiket: string; ton: Ton } {
  return GEREKSINIM_DURUMU[d as GereksinimDurumu] ?? { etiket: d, ton: "notr" };
}

/** TEKNIK-TASARIM §2 — 14 adımlı akış. */
export const AKIS_ADIMLARI: { ad: string; tur: "sistem" | "ai" | "insan" | "ai_insan" }[] = [
  { ad: "Jira", tur: "sistem" },
  { ad: "Ön inceleme", tur: "ai_insan" },
  { ad: "PO teyidi", tur: "insan" },
  { ad: "Test case", tur: "ai_insan" },
  { ad: "Kod taslağı", tur: "ai" },
  { ad: "Review + kırma", tur: "insan" },
  { ad: "Korumalı ana dal", tur: "sistem" },
  { ad: "CI gece/deploy", tur: "sistem" },
  { ad: "Sauce + QA", tur: "sistem" },
  { ad: "Sonuçlar", tur: "sistem" },
  { ad: "Kontrol Kulesi", tur: "sistem" },
  { ad: "Triage", tur: "ai" },
  { ad: "Kaydı açar", tur: "insan" },
  { ad: "Jira hata", tur: "sistem" },
];

export const SORU_TURU: Record<SoruTuru, string> = {
  ambiguity: "Belirsizlik",
  missing_ac: "Eksik AC",
  conflict: "Çelişki",
  untestable: "Test edilemez",
};

export const BULGU_TURU: Record<BulguTuru, string> = {
  internal_contradiction: "İç çelişki",
  doc_vs_code: "Doküman ↔ kod",
  doc_vs_data: "Doküman ↔ veri",
  missing_in_doc: "Dokümanda eksik",
  missing_in_code: "Kodda eksik",
  ambiguous: "Belirsiz",
};

export const BULGU_KARARI: Record<BulguKarari, string> = {
  fix_doc: "Dokümanı düzelt",
  code_defect: "Kod/veri hatalı",
  accept_difference: "Bilinçli fark",
};

/** core `consistency_finding` makinesinin her durumu (eksik anahtar derleme hatasıdır). */
export const BULGU_DURUMU: Record<BulguDurumu, { etiket: string; ton: Ton }> = {
  unverified: { etiket: "Kanıt doğrulanmadı", ton: "uyari" },
  open: { etiket: "Karar bekliyor", ton: "uyari" },
  decided: { etiket: "Karar verildi", ton: "bilgi" },
  resolved: { etiket: "Çözüldü", ton: "basari" },
  stale: { etiket: "Güncelliğini yitirdi", ton: "notr" },
  discarded: { etiket: "Elendi", ton: "notr" },
};

export const CASE_DURUMU: Record<CaseDurumu, { etiket: string; ton: Ton }> = {
  draft: { etiket: "Karar bekliyor", ton: "uyari" },
  ready: { etiket: "Onaya hazır", ton: "bilgi" },
  approved: { etiket: "Onaylı", ton: "basari" },
  rejected: { etiket: "Reddedildi", ton: "hata" },
  published: { etiket: "Yayınlandı", ton: "basari" },
  superseded: { etiket: "Yerini yenisi aldı", ton: "notr" },
};

export const CASE_TURU: Record<string, string> = { positive: "Pozitif", negative: "Negatif", boundary: "Sınır" };
export const RISK: Record<string, { etiket: string; ton: Ton }> = {
  high: { etiket: "Yüksek risk", ton: "hata" },
  medium: { etiket: "Orta risk", ton: "uyari" },
  low: { etiket: "Düşük risk", ton: "notr" },
};

/** TEKNIK-TASARIM §7 ret nedeni taksonomisi (sabit). */
export const RET_NEDENI: Record<RetNedeni, string> = {
  hallucinated_step: "Halüsinasyon adımı",
  missing_ac: "Eksik kabul kriteri",
  wrong_test_data: "Yanlış test verisi",
  out_of_scope: "Kapsam dışı",
  duplicate: "Tekrar",
  wrong_element: "Yanlış eleman/aksiyon",
};

/** core `script` makinesinin her durumu (eksik anahtar derleme hatasıdır). */
export const SCRIPT_DURUMU: Record<ScriptDurumu, { etiket: string; ton: Ton }> = {
  pending: { etiket: "Sırada", ton: "notr" },
  verifying: { etiket: "Ajan doğruluyor", ton: "bilgi" },
  checking: { etiket: "Yerel kontrol", ton: "bilgi" },
  blocked: { etiket: "İnsana düştü", ton: "uyari" },
  pr_open: { etiket: "PR açık", ton: "bilgi" },
  merged: { etiket: "Birleştirildi", ton: "basari" },
  closed: { etiket: "Kapatıldı", ton: "notr" },
  failed: { etiket: "Başarısız", ton: "hata" },
  // 011: doğrulanmamış dil (C#, Python) — kod var ama derlenmedi/koşulmadı; başarı değil, dikkat ister.
  unverified: { etiket: "Doğrulanmamış", ton: "uyari" },
};

/** Ajan hâlâ çalışıyor mu (adımlar canlı akıyor). */
export function scriptUretiliyor(d: ScriptDurumu): boolean {
  return d === "pending" || d === "verifying";
}

/** Kırarak doğrulamada yeşil kalan (`weak` / `zayif_test`) testin liste ipucu. */
export const ZAYIF_TEST_ACIKLAMA =
  "Kampanya kırılması (BREAK_CAMPAIGN) bu testi kırmızıya çevirmedi. Kampanya dışı davranışı (ör. sepet sayacı, minimum sipariş) doğrulayan testte beklenir; kampanya testinde zayıf test demektir. Merge engellenmez, açık insan kabulü ister.";

/**
 * Durumdan ayrı, türetilmiş script işareti: `pr_open` iken kırarak doğrulama sonucu.
 * Zayıf test durumu değil `zayif_test` alanıdır; merge'e hazırlık PR + CI + kırma sonucundan çıkar.
 */
export function scriptIsareti(s: {
  durum: ScriptDurumu;
  zayif_test: boolean;
  break_verify: { durum: string };
  pr: { durum: string; ci: string | null } | null;
}): { etiket: string; ton: Ton; aciklama?: string } | null {
  // Zayıf test bir işarettir, kapı değil (TEKNIK-TASARIM §2 adım 6): uyarı tonunda. Liste kopyası
  // olguyu söyler ("kırma etkilemedi"): BREAK_CAMPAIGN yalnızca kampanyayı bozar; kampanya dışı
  // testlerde (sepet sayacı, minimum sipariş) bu beklenir, "AI zayıf test yazdı" anlamına gelmez.
  if (s.zayif_test || s.break_verify.durum === "weak") return { etiket: "Kırma etkilemedi", ton: "uyari", aciklama: ZAYIF_TEST_ACIKLAMA };
  if (s.durum === "pr_open" && s.pr?.durum === "open" && s.pr.ci === "passed" && s.break_verify.durum === "passed") {
    return { etiket: "Merge'e hazır", ton: "basari" };
  }
  return null;
}

/** core `bug_draft` makinesinin her durumu. Yayınlanan kaydın etiketi karara göre ayrışır (bağla/yeni). */
export const BUG_DURUMU: Record<BugDurumu, { etiket: string; ton: Ton }> = {
  draft: { etiket: "Onay bekliyor", ton: "uyari" },
  approved: { etiket: "Onaylandı, Jira'ya yazılıyor", ton: "bilgi" },
  dismissed: { etiket: "Reddedildi", ton: "notr" },
  published: { etiket: "Jira'da", ton: "basari" },
};

export const TETIK: Record<Tetik, string> = {
  pr: "PR",
  push: "Push (main)",
  nightly: "Gece",
  deploy: "Deploy",
  break_verify: "Kırarak doğrula",
  local_check: "Yerel kontrol",
  manual: "Elle",
};
export const KAYNAK: Record<KosuKaynagi, string> = { local: "Yerel Chromium", github: "GitHub Actions", sauce: "Sauce Labs" };

export const HATA_SINIFI: Record<HataSinifi, { etiket: string; ton: Ton }> = {
  environment: { etiket: "Ortam", ton: "notr" },
  flaky: { etiket: "Flaky", ton: "uyari" },
  test_maintenance: { etiket: "Test bakımı", ton: "notr" },
  product_defect: { etiket: "Ürün hatası", ton: "hata" },
  test_data: { etiket: "Test verisi", ton: "uyari" },
  unknown: { etiket: "Belirsiz", ton: "notr" },
};

export const KOSU_DURUMU: Record<string, { etiket: string; ton: Ton }> = {
  queued: { etiket: "Sırada", ton: "notr" },
  running: { etiket: "Koşuyor", ton: "bilgi" },
  passed: { etiket: "Geçti", ton: "basari" },
  failed: { etiket: "Başarısız", ton: "hata" },
  error: { etiket: "Hata", ton: "hata" },
  flaky: { etiket: "Flaky", ton: "uyari" },
  skipped: { etiket: "Atlandı", ton: "notr" },
};

export const SEVERITY: Record<string, string> = {
  critical: "Kritik",
  major: "Yüksek",
  minor: "Düşük",
  trivial: "Önemsiz",
};

// ---------------------------------------------------------------- 012/Ş8: ekilmiş hata koşusu

import type { HataAdimSonucu, HataKosusuDurumu, HataTuru } from "../api/types";

/** `hata_kosusu.durum` etiketi. */
export const HATA_KOSUSU_DURUMU: Record<HataKosusuDurumu, { etiket: string; ton: Ton }> = {
  queued: { etiket: "Sırada", ton: "notr" },
  running: { etiket: "Koşuyor", ton: "bilgi" },
  done: { etiket: "Tamamlandı", ton: "notr" },
  failed: { etiket: "Tamamlanamadı", ton: "hata" },
  cancelled: { etiket: "İptal edildi", ton: "notr" },
};

/** Adım sonucu: işaret metindir (renk tek başına anlam taşımaz). */
export const HATA_ADIM_SONUCU: Record<HataAdimSonucu, { etiket: string; ton: Ton }> = {
  bekliyor: { etiket: "bekliyor", ton: "notr" },
  yakalandi: { etiket: "✓ yakalandı", ton: "basari" },
  kacti: { etiket: "✗ kaçtı", ton: "hata" },
  gecersiz: { etiket: "⚠ geçersiz", ton: "uyari" },
  yesil: { etiket: "✓ yeşil", ton: "basari" },
  kirmizi: { etiket: "✗ kırmızı", ton: "hata" },
};

export const HATA_TURU: Record<HataTuru, string> = { kod: "Kod hatası", veri: "Veri hatası" };

/**
 * Hata kodunun görünen adı (core `rules/hata-katalogu.yaml` ile aynı dokuz kod, ANALIZ §4.6). Katalog
 * ucu okunabildiyse oradaki ad önceliklidir; bu tablo katalog yokken (koşu listeleri) yedektir.
 */
export const EKILMIS_HATA_ADI: Record<string, string> = {
  kampanya_bedava_yok: "Kampanyada bedava ürün verilmiyor",
  kampanya_esik_7: "Kampanya eşiği 6 yerine 7",
  kampanya_tek_bedava: "Kampanyada en çok 1 bedava",
  kampanya_cift_indirim: "Kampanya indirimi iki kez düşülüyor",
  min_siparis_haric: "Minimum sipariş sınırı dahil değil",
  min_siparis_muafiyet_yok: "Kampanyalı sepet minimumdan muaf değil",
  min_siparis_500: "Minimum sipariş tutarı 500",
  min_siparis_1000: "Minimum sipariş tutarı 1000",
  fiyat_p004_31: "P-004 fiyatı 31",
  kampanya_urunu_p002: "Kampanyalı ürün P-002",
};

export function ekilmisHataAdi(kod: string, katalogAdi?: string | null): string {
  return katalogAdi?.trim() || EKILMIS_HATA_ADI[kod] || kod;
}

/** Ekilmiş hata koşusunun adımı olan koşunun etiketi ("Ekilmiş hata: <ad>"); başka koşuda null. */
export function ekilmisHataEtiketi(k: { hata_kodu?: string | null }, katalogAdi?: string | null): string | null {
  return k.hata_kodu ? `Ekilmiş hata: ${ekilmisHataAdi(k.hata_kodu, katalogAdi)}` : null;
}
// ---------------------------------------------------------------- 012 Ş7: test kalite doğrulama
import type { KararTablosuDurumu, KolonTuru, TuretmeAtlamaSonucu } from "../api/types";

/** Karar tablosu ve metamorfik ilişki durumları (ANALIZ §4.1). Yeşil yalnız PO onayı (insan kapısı). */
export const KARAR_TABLOSU_DURUMU: Record<KararTablosuDurumu, { etiket: string; ton: Ton }> = {
  draft: { etiket: "Taslak", ton: "notr" },
  pending_po: { etiket: "PO onayı bekliyor", ton: "uyari" },
  approved: { etiket: "Onaylı", ton: "basari" },
  superseded: { etiket: "Yerini yenisi aldı", ton: "notr" },
};

export const KOLON_TURU: Record<KolonTuru, string> = { sayi: "Sayı", metin: "Metin", mantiksal: "Mantıksal" };

/**
 * Case kartındaki beklenen sonuç kontrolü çipi (ANALIZ §7). "uyumlu" yeşil değildir: makine
 * karşılaştırmasıdır, insan onayı değil (yeşil yalnız insan kapısı) — bilgi tonu + ✓ işareti.
 */
export type OracleGorunumu = "uyumlu" | "uyumsuz" | "kismen" | "kontrol_edilemedi" | "tablo_yok" | "suruyor";
export const ORACLE_DURUMU: Record<OracleGorunumu, { etiket: string; ton: Ton; aciklama: string }> = {
  uyumlu: { etiket: "Tabloyla uyumlu ✓", ton: "bilgi", aciklama: "Beklenen değerler onaylı karar tablosuyla aynı." },
  uyumsuz: { etiket: "Tabloyla uyuşmuyor ✗", ton: "hata", aciklama: "En az bir beklenen değer onaylı karar tablosundan farklı." },
  kismen: {
    etiket: "Kısmen uyumlu",
    ton: "uyari",
    aciklama: "Karşılaştırılan değerler tabloyla aynı, ama bazı beklenen değerler tabloyla kontrol edilemedi. Onay engellenmez; kontrol edilemeyen değerleri elle doğrulayın.",
  },
  kontrol_edilemedi: {
    etiket: "Kontrol edilemedi",
    ton: "uyari",
    aciklama: "Case metninden tabloyla karşılaştırılacak değer çıkarılamadı. Uyuşmazlık değildir; değerleri elle doğrulayın.",
  },
  tablo_yok: { etiket: "Tablo yok", ton: "notr", aciklama: "Bu case'in kabul kriterlerini kapsayan onaylı karar tablosu yok." },
  suruyor: { etiket: "Kontrol sürüyor", ton: "notr", aciklama: "Kapsayan onaylı tablo var; beklenen sonuç kontrolü henüz bitmedi." },
};

/** "Ek case türet" sonucunda atlanan kaynak case'in nedeni (§4.5). */
export const TURETME_ATLAMA: Record<TuretmeAtlamaSonucu, string> = {
  iliski_gecersiz: "ilişkinin ön koşulu bu case için sağlanmıyor",
  belirsiz_alinti: "değer metinde birden çok yerde farklı anlamlarla geçiyor",
  olgu_yok: "kaynak case'te gerekli değer bulunamadı",
  zaten_turetildi: "bu case'ten bu ilişkiyle daha önce türetildi",
  tutarsiz_kalan_deger: "türetilen case'te güncellenmeyen değer kalırdı",
};

/** Kontrol sonucunun nedeni (§13.2 `oracle.neden`); bilinmeyen kod gösterilmez. */
export const ORACLE_NEDENI: Record<string, string> = {
  cagri_hatasi: "Kontrol yapılamadı (model hatası)",
  replay_miss: "Kayıtlı yanıt yok (REPLAY)",
};
/** Nedenin açıklama cümlesi (karşılaştırma ayrıntısında). */
export const ORACLE_NEDENI_ACIKLAMA: Record<string, string> = {
  cagri_hatasi: "değer çıkarma adımı model çağrısında hata aldı; tablo ile case karşılaştırılmadı.",
  replay_miss: "bu case metni için kayıtlı (REPLAY) model yanıtı yok — metin kayıttaki golden'la birebir değil; tablo ile case karşılaştırılmadı.",
};

/** Tur 2: `kismen` sonucun nedenleri, düz Türkçe (bilinmeyen kod aynen gösterilir). */
export const KISMEN_NEDENI: Record<string, string> = {
  eksik_girdi: "case metninde tablonun bir girdisi yok; o değer hesaplanamadı",
  atilan_olgu: "case'ten çıkarılan bir değer metinde doğrulanamadığı için atıldı",
  kapsanmayan_sayi: "beklenen sonuçta tabloyla eşleştirilemeyen bir sayı var",
  yok_sayilan: "beklenen sonuçtaki bir ifade kontrol dışında bırakıldı",
};
export const kismenNedeniMetni = (n: string): string => KISMEN_NEDENI[n] ?? n;

/** 012 Ş3 triage ayrımı (ANALIZ §4.4): alt tür etiketleri; bilinmeyen alt tür ham gösterilir. */
export const TRIAGE_ALT_TUR: Record<string, string> = {
  beklenti: "Test beklentisi (karar tablosu)",
};
export const altTurEtiketi = (alt: string | null | undefined): string | null => (alt ? (TRIAGE_ALT_TUR[alt] ?? alt) : null);

/** 012 Ş3 karar tablosu sinyalleri (kural `karar_tablosu`). */
export const KARAR_TABLOSU_SINYALI: Record<string, string> = {
  karar_tablosu_uyumlu: "Test beklentisi onaylı karar tablosuyla aynı; uygulama tabloya aykırı",
  karar_tablosu_beklenti_farkli: "Uygulama onaylı karar tablosuyla aynı; test beklentisi farklı",
  karar_tablosu_ikisi_de_farkli: "Hem test beklentisi hem uygulama onaylı karar tablosundan farklı",
  // R3: ürün hatası adayı ama tablonun kendisi de yanlış olabilir (ör. story'den sonra değişen kural).
  karar_tablosu_tablo_suphesi: "Tablo da yanlış olabilir",
};

/**
 * Sinyalin tek satırlık başlığı ve ayrıntısı (analist/PO 19): core `baslik` verirse başlık odur, `aciklama`
 * ayrıntıdır; vermezse karar tablosu sinyalinde etiket başlık olur, diğerlerinde açıklama tek satırdır.
 */
export function sinyalBasligi(s: { kod: string; baslik?: string | null; aciklama: string }): { baslik: string; ayrinti: string | null } {
  const baslik = s.baslik || KARAR_TABLOSU_SINYALI[s.kod] || s.aciklama;
  return { baslik, ayrinti: s.aciklama && s.aciklama !== baslik ? s.aciklama : null };
}
