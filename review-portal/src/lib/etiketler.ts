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
import type { ModelRetNedeni } from "../api/tasarimModeliTipleri";
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
  modeling: { etiket: "Tasarım modeli üretiliyor", ton: "bilgi" },
  model_ready: { etiket: "Tasarım modeli onayı bekliyor", ton: "uyari" },
  generating: { etiket: "Case üretiliyor", ton: "bilgi" },
  cases_ready: { etiket: "Case review aşamasında", ton: "bilgi" },
  done: { etiket: "Case'ler yayınlandı", ton: "basari" },
  failed: { etiket: "Hata", ton: "hata" },
};

/**
 * Sunucu metnindeki ham gereksinim durum kodunu ("… (durum: pending_po)") Türkçe etikete çevirir:
 * "(durum: PO teyidi bekliyor)". Bilinmeyen kod olduğu gibi kalır.
 */
export function durumKodunuCevir(metin: string): string {
  return metin.replace(/\(durum:\s*([a-z_]+)\s*\)/g, (t, d: string) =>
    d in GEREKSINIM_DURUMU ? `(durum: ${GEREKSINIM_DURUMU[d as GereksinimDurumu].etiket})` : t,
  );
}

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

export const CASE_TURU: Record<string, string> = {
  positive: "Pozitif",
  negative: "Negatif",
  boundary: "Sınır",
  authorization: "Yetki",
  integration: "Entegrasyon",
};

/** Test tasarım tekniği kısaltması → tam Türkçe ad (rozetin `title`'ı ve erişilebilir adı). */
export const CASE_TEKNIGI: Record<string, string> = {
  EP: "eşdeğerlik bölümleme",
  BVA: "sınır değer analizi",
  DT: "karar tablosu",
  ST: "durum geçişi",
  PW: "pairwise",
  UC: "kullanım senaryosu",
  EG: "hata tahmini",
  CL: "kontrol listesi",
};

/** Hazır olma durumu: renk tek başına anlam taşımaz; metin + işaret birlikte gösterilir. */
export const CASE_HAZIRLIK: Record<string, { etiket: string; ton: Ton; isaret: string; aciklama: string }> = {
  ready: { etiket: "Hazır", ton: "basari", isaret: "✓", aciklama: "Beklenen sonuçlar yazılı; açık soru ya da varsayıma bağlı değil." },
  assumption_dependent: {
    etiket: "Varsayıma bağlı",
    ton: "uyari",
    isaret: "⚠",
    aciklama: "Beklenen sonuç bir varsayıma dayanıyor; varsayım doğrulanmadan onaylanamaz.",
  },
  blocked: { etiket: "Soru bekliyor", ton: "uyari", isaret: "?", aciklama: "Açık soru PO yanıtını bekliyor; yanıt gelmeden beklenen sonuç yazılamaz ve case onaylanamaz." },
};

export const CASE_ONCELIGI: Record<string, { etiket: string; ton: Ton; aciklama: string }> = {
  P1: { etiket: "P1", ton: "hata", aciklama: "Öncelik 1, en yüksek" },
  P2: { etiket: "P2", ton: "uyari", aciklama: "Öncelik 2, orta" },
  P3: { etiket: "P3", ton: "notr", aciklama: "Öncelik 3, düşük" },
};

export const DOGRULAMA_NOKTASI: Record<string, string> = {
  UI: "Arayüz (UI)",
  API: "API",
  event: "Olay (event)",
  DB: "Veritabanı",
  log: "Log",
  other: "Diğer",
};

export const TEST_SEVIYESI: Record<string, string> = {
  UNIT: "Birim",
  COMPONENT: "Bileşen",
  INTEGRATION: "Entegrasyon",
  SYSTEM: "Sistem",
  E2E: "Uçtan uca",
  UAT: "Kullanıcı kabul",
};

/** Açık soru / varsayım sahibi (şema: PO | analyst | developer | ""). */
export const SORU_SAHIBI: Record<string, string> = { PO: "PO", analyst: "Analist", developer: "Geliştirici", "": "Belirsiz" };

export const NEGATIF_KARAR: Record<string, { etiket: string; ton: Ton }> = {
  tested: { etiket: "Test ediliyor", ton: "basari" },
  covered_by: { etiket: "Başka case kapsıyor", ton: "bilgi" },
  out_of_scope: { etiket: "Kapsam dışı", ton: "notr" },
};

/** Üretim türü (`case_uretim.tur`). */
export const URETIM_TURU: Record<string, string> = { uretim: "Üretim", negatif: "Negatif genişletme", teknik: "Teknik derinleştirme" };
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

/** D1: tasarım modeli ret nedenleri (modele özgü). */
export const MODEL_RET_NEDENI: Record<ModelRetNedeni, string> = {
  wrong_technique: "Yanlış teknik",
  missing_condition: "Eksik koşul",
  wrong_coverage_item: "Yanlış kapsam öğesi",
  wrong_boundary: "Yanlış sınır değer",
  invented_rule: "Uydurulmuş kural",
  missing_ac: "Eksik kabul kriteri",
  out_of_scope: "Kapsam dışı",
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
  "Kasıtlı kampanya kırılması bu testi kırmızıya çevirmedi. Kampanya dışı davranışı (ör. sepet sayacı, minimum sipariş) doğrulayan testte beklenir; kampanya testinde zayıf test demektir. Merge engellenmez, açık insan kabulü ister.";

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
  /** core takılan koşuyu süre aşımıyla kapattı: başarısız benzeri. */
  zaman_asimi: { etiket: "Zaman aşımı", ton: "hata" },
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
  tablo_yok: { etiket: "Karar tablosu yok", ton: "notr", aciklama: "Bu case'in kabul kriterlerini kapsayan onaylı karar tablosu yok: beklenen değer bağımsız kontrol edilmedi." },
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

// ---------------------------------------------------------------- CL-07 okunur metin (iç terim ayıklama)
// Canlı UX doğrulaması (liste şeridi) CL-07: çekirdekten gelen serbest metinlerde iç kodlar (adım öneki
// `S4:`, `REPLAY-MISS:`, test etiketi `@tp-uretilen`, ortam değişkeni `BREAK_CAMPAIGN`, `jira-sim`) kullanıcıya
// sızıyordu. Ham metin kaybolmaz: çağıran yer gerekirse ham hali ipucu/"Ayrıntı" açılırında verir.

/** Test adındaki Playwright etiketleri (`@tp-uretilen`, `@tp-…`) gösterimde ayıklanır. */
export function testAdiGoster(ad: string): string;
export function testAdiGoster(ad: string | null | undefined): string | null | undefined;
export function testAdiGoster(ad: string | null | undefined): string | null | undefined {
  if (!ad) return ad;
  return ad.replace(/\s*@tp-[\w-]+/g, "").replace(/\s{2,}/g, " ").trim();
}

const IC_TERIMLER: [RegExp, string][] = [
  // Adım kodu öneki: "S4: page object'te eksik metot" → "page object'te eksik metot".
  [/(^|[;—–:]\s*|\.\s+)S\d{1,2}\s*[:—–]\s*/g, "$1"],
  [/\bREPLAY-MISS\s*:\s*/g, ""],
  [/\s*@tp-[\w-]+/g, ""],
  // Bug taslağı ortamı (eski kayıtlar; core artık `ortam_metni` ile üretimde çeviriyor).
  [/kampanya\s+kırılması\s*\(\s*BREAK_CAMPAIGN(?:=1)?\s*\)\s*:?\s*kapalı/giu, "kasıtlı kırma yok (normal koşu)"],
  [/kampanya\s+kırılması\s*\(\s*BREAK_CAMPAIGN(?:=1)?\s*\)\s*:?\s*açık/giu, "kampanya kuralı kasıtlı kırılmış (kırarak doğrula koşusu)"],
  [/\bBREAK_CAMPAIGN(?:=1)?\s*:?\s*kapalı/gu, "kasıtlı kırma yok (normal koşu)"],
  [/\bBREAK_CAMPAIGN(?:=1)?\s*:?\s*açık/gu, "kampanya kuralı kasıtlı kırılmış (kırarak doğrula koşusu)"],
  [/\bBREAK_CAMPAIGN(?:=1)?\b/g, "kasıtlı kırma"],
  [/\bjira-sim\b/g, "Jira simülatörü"],
  [/\bTP_FORGE=local\b/g, "yerel kod deposu kipi"],
];

/** Serbest metindeki iç kodları kullanıcı diline çevirir (tanınmayan metin aynen döner). */
export function icTerimleriAyikla(metin: string): string;
export function icTerimleriAyikla(metin: string | null | undefined): string | null | undefined;
export function icTerimleriAyikla(metin: string | null | undefined): string | null | undefined {
  if (!metin) return metin;
  let m = metin;
  for (const [desen, yerine] of IC_TERIMLER) m = m.replace(desen, yerine);
  m = m.replace(/\s{2,}/g, " ").trim();
  return m ? m.charAt(0).toLocaleUpperCase("tr-TR") + m.slice(1) : m;
}

const karsilastir = (m: string) => m.toLocaleLowerCase("tr-TR").replace(/\p{M}/gu, "").replace(/[^\p{L}\p{N}]+/gu, " ").trim();

/**
 * "Başlık — ayrıntı" birleşiminde ayrıntı başlığın söylediğiyle başlıyorsa tekrar atılır:
 * ("İnsana düştü: page object'te eksik metot", "S4: page object'te eksik metot. Ayrıntı.") → "Ayrıntı."
 * Ayrıntıdan geriye bir şey kalmazsa null.
 */
export function tekrarsizAyrinti(baslik: string, ayrinti: string | null | undefined): string | null {
  const a = icTerimleriAyikla(ayrinti ?? "").trim();
  if (!a) return null;
  const b = karsilastir(baslik);
  // Başlığın kendisi ya da ":" sonrası parçası ayrıntının başındaysa o parça düşer.
  const parcalar = [b, ...baslik.split(/:\s+/).slice(1).map(karsilastir), karsilastir(baslik.split(/:\s+/)[0] ?? "")].filter((p) => p.length >= 6);
  const ak = karsilastir(a);
  for (const p of parcalar) {
    if (!ak.startsWith(p)) continue;
    // Ham metinde aynı uzunluktaki öneki (noktalama dahil) at.
    let i = 0;
    let say = 0;
    const hedef = p.replace(/ /g, "").length;
    while (i < a.length && say < hedef) {
      if (/[\p{L}\p{N}]/u.test(a[i])) say++;
      i++;
    }
    const kalan = a.slice(i).replace(/^[\s.,;:—–-]+/, "").trim();
    return kalan ? kalan.charAt(0).toLocaleUpperCase("tr-TR") + kalan.slice(1) : null;
  }
  return a;
}

/** Model çağrısı amaçları (core `ai_call.amac`) — Kule › Hız ve maliyet. */
export const MODEL_CAGRI_AMACI: Record<string, string> = {
  assistant: "soru-cevap",
  assistant_deep: "derin yanıt",
  assistant_guard: "güvenlik denetimi",
};
export const modelCagriAmaci = (a: string): string => MODEL_CAGRI_AMACI[a] ?? a.replace(/_/g, " ");

/** Denetim özeti alanları (core olay `ozet` JSON anahtarları). Teknik kimlikler kısa özete girmez. */
export const DENETIM_ALANI: Record<string, string> = {
  kanal: "Kanal",
  onceki: "Önceki",
  yeni: "Yeni",
  talep_no: "Talep",
  neden: "Neden",
  hata: "Hata",
  rol: "Rol",
  anahtar: "Anahtar",
  eklenen: "Eklenen",
  sonuc: "Sonuç",
  baz: "Baz değer",
  durum: "Durum",
  karar: "Karar",
  sayi: "Sayı",
  adet: "Adet",
  platform: "Platform",
  dil: "Dil",
  tetik: "Tetik",
  proje: "Proje",
  from: "Kaynak",
  kaynak: "Kaynak",
  jira_key: "Jira",
  pr: "PR",
  amac: "Amaç",
  mesaj: "Mesaj",
  sebep: "Neden",
};
const DENETIM_DEGERI: Record<string, string> = {
  pr_open: "PR açılışı",
  pr_sync: "PR güncellemesi",
  push: "push",
  manual: "elle",
  nightly: "gece",
  portal: "portal",
  mcp: "IDE kanalı",
};
/** Kısa özete girmeyen teknik alan: oturum/çağrı/iş kimliği, sha, hash. */
export function denetimTeknikAlanMi(anahtar: string): boolean {
  return /^(sid|uid|pv|id)$/.test(anahtar) || /(_id|_sha|_hash|_uuid)$/.test(anahtar) || /^(hash|sha|set_hash)$/.test(anahtar);
}
export function denetimAlanEtiketi(anahtar: string): string {
  if (DENETIM_ALANI[anahtar]) return DENETIM_ALANI[anahtar];
  const m = anahtar.replace(/_/g, " ");
  return m.charAt(0).toLocaleUpperCase("tr-TR") + m.slice(1);
}
export function denetimDegeri(v: string): string {
  return DENETIM_DEGERI[v] ?? v;
}
