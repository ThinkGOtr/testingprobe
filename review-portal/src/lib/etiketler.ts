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

export type Ton = "notr" | "bilgi" | "basari" | "uyari" | "hata" | "vurgu";

export const ROL: Record<Rol, string> = {
  analyst: "Analist",
  engineer: "Mühendis",
  presenter: "Sunucu",
  po: "Ürün sahibi (PO)",
  tester: "Testçi",
};

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
export type OracleGorunumu = "uyumlu" | "uyumsuz" | "kontrol_edilemedi" | "tablo_yok" | "suruyor";
export const ORACLE_DURUMU: Record<OracleGorunumu, { etiket: string; ton: Ton; aciklama: string }> = {
  uyumlu: { etiket: "Tabloyla uyumlu ✓", ton: "bilgi", aciklama: "Beklenen değerler onaylı karar tablosuyla aynı." },
  uyumsuz: { etiket: "Tabloyla uyuşmuyor ✗", ton: "hata", aciklama: "En az bir beklenen değer onaylı karar tablosundan farklı." },
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
  iliski_gecersiz: "ilişki geçersiz",
  belirsiz_alinti: "belirsiz alıntı",
  olgu_yok: "olgu yok",
  zaten_turetildi: "zaten türetildi",
};

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
};
