// Portal ↔ core-api veri sözleşmesi (MIMARI-SOZLESME §5, TEKNIK-TASARIM §7/§8).
//
// Adlandırma kuralı: veritabanı kökenli alanlar Türkçe (kullanici_adi, olusturma, durum …);
// AI şemalarından gelen gömülü yükler (test case içeriği, bulgu kanıtı, bug taslağı içeriği,
// ön inceleme soruları) TEKNIK-TASARIM'daki İngilizce şema adlarını aynen taşır.

export type Rol = "analyst" | "engineer" | "presenter" | "po" | "tester";

/** Model geçidi modu (§8.8). live dışındaki her değer portalda rozetle gösterilir. */
export type CiktiModu = "live" | "replay" | "replay_miss";

export interface Kullanici {
  id: string;
  kullanici_adi: string;
  rol: Rol;
}

// ---------------------------------------------------------------- Gereksinimler

/**
 * Gereksinim durumları — core-api durum makinesiyle (tp_core/workflow/states.py REQUIREMENT)
 * birebir aynı küme; yetkili kaynak core'dur. "Kabul kriteri yok" bir durum değil, `ac_missing`
 * bayrağıdır (durum `new` kalır).
 */
export const GEREKSINIM_DURUMLARI = [
  "new", // Jira'dan çekildi / serbest metin girildi
  "in_review", // ön inceleme + tutarlılık denetimi sürüyor (yeniden kontrol dahil)
  "findings_open", // analist kararı bekleyen bulgular var
  "doc_final", // doküman son hâlinde
  "pending_po", // PO teyidi bekleniyor
  "po_approved",
  "generating", // case üretimi sürüyor
  "cases_ready", // case review
  "done", // case'ler yayınlandı; akış koda/CI'ya geçti
  "failed",
] as const;

export type GereksinimDurumu = (typeof GEREKSINIM_DURUMLARI)[number];

export interface KabulKriteri {
  ref: string; // "AC1"
  metin: string;
}

export interface PoDurumu {
  durum: "not_requested" | "pending" | "approved";
  onaylayan: string | null;
  zaman: string | null;
  /** jira: etiket (tp-po-approved) · portal: serbest metin yolunda PO rolüyle */
  kanal: "jira" | "portal";
  /** Onaylanan içerik hash'i (`requirement.onaylanan_hash`); PO'nun hangi metni onayladığını gösterir. */
  onaylanan_hash?: string | null;
}

export interface Gereksinim {
  id: string;
  kaynak: "jira" | "free_text";
  jira_key: string | null;
  baslik: string;
  aciklama: string;
  kabul_kriterleri: KabulKriteri[];
  ac_missing: boolean;
  durum: GereksinimDurumu;
  /**
   * İsteğe bağlı ipucu: akıştaki adım (1–14). Gösterilen adım her zaman `durum`dan türetilir
   * (lib/akis.ts); ipucu yalnızca `done` (akış koda/CI'ya geçti) ve `failed` için kullanılır.
   */
  adim?: number;
  cekim_zamani: string;
  po: PoDurumu;
  sayaclar: { bulgu_acik: number; case_toplam: number; case_onayli: number };
}

export type SoruTuru = "ambiguity" | "missing_ac" | "conflict" | "untestable";

export interface OnIncelemeSorusu {
  id: string;
  type: SoruTuru;
  text: string;
  ac_ref: string | null;
  cevap: string | null;
  /** Soru, doküman düzeltmesiyle metni değişen bir AC'ye ait (PO güncel metne göre cevaplar). */
  duzeltmeyle_degisti?: boolean;
  /**
   * Soru güncel döngüdeki bulgu kararlarıyla (fix_doc / accept_difference) kapandıysa açıklama
   * (ör. "doküman düzeltmesiyle cevaplandı: F1 (tur 1)"); kapanmadıysa null. PO'ya sorulmaz.
   */
  kararla_cozuldu?: string | null;
}

export interface OnInceleme {
  verdict: "ready" | "needs_po";
  questions: OnIncelemeSorusu[];
  jira_comment_id: string | null;
  /** null: çekirdek modu bildirmedi (rozet yok; "live" varsayılmaz). */
  mode: CiktiModu | null;
  zaman: string;
  /** Modelin inceleme özeti (enjeksiyon notları dahil); karar dayanağı değildir. */
  ozet?: string | null;
}

export interface GereksinimDetay extends Gereksinim {
  /**
   * Kullanıcının gördüğü içeriğin (başlık, açıklama, kabul kriterleri) hash'i. PO onayı bu değeri
   * aynen geri gönderir (MIMARI-SOZLESME §5, TOCTOU bağı).
   */
  icerik_hash: string;
  on_inceleme: OnInceleme | null;
  kontrol_turu: number;
  kontrol_turu_ust_sinir: number;
  jira_url: string | null;
  /** Güvenilmeyen içerik uyarıları (ör. açıklamada talimat benzeri metin, §5). */
  uyarilar: string[];
  /**
   * Kanıtı deterministik olarak doğrulanamadığı için elenen (`discarded`) bulgu sayısı (bu tur dahil
   * tüm turlar). Bulgular kullanıcıya gösterilmez; yalnızca sayısı (Constitution XI).
   */
  elenen_bulgu?: number;
  /**
   * Son tutarlılık kontrolü koşusu (`requirement_kontrol`): model modu ve bulgu sayıları. Mod
   * REPLAY / REPLAY-MISS ise kartta rozet gösterilir; REPLAY-MISS'te "tutarlı" denmez.
   */
  son_kontrol?: SonKontrol | null;
  /** PO'nun Jira'daki cevap yorumları (`requirement.po_cevaplari`); soru bazında eşlenmez. */
  po_cevaplari?: PoCevabi[];
  /**
   * Son denetim güvenilmez (REPLAY-MISS ya da tüm bulgular elendi): belge otomatik son hal olmaz;
   * analist açıkça "son hal" der (fail-closed). null: güvenilir.
   */
  denetim_guvenilmez?: string | null;
  /** Gereksinim insan kararı bekliyor (tur sınırı ya da güvenilmez denetim). */
  insan_karari_gerekli?: boolean;
  /** Son başarısız işlemin nedeni (core `son_hata`); yoksa null. */
  son_hata?: SonHata | null;
  /** PO soru yorumunun Jira'ya yazılma durumu (core `po_istegi`). */
  po_istegi?: PoIstegi | null;
}

export interface SonHata {
  neden: string | null;
  zaman: string | null;
  job_tur: string | null;
  is_hatasi: string | null;
  /** Türkçe yönlendirme (ör. "yeniden denemek sonucu değiştirmez"). */
  oneri: string | null;
  yeniden_denemek_ise_yarar: boolean | null;
}

export interface PoIstegi {
  durum: "yazildi" | "bekliyor" | "basarisiz";
  jira_comment_id: string | null;
  hata: string | null;
}

export interface SonKontrol {
  mode: CiktiModu | null;
  bulgu: number;
  dogrulanan: number;
  elenen: number;
  zaman: string | null;
}

export interface PoCevabi {
  id: string;
  yazar: string | null;
  metin: string;
  zaman: string | null;
  /** Jira yorumunun adresi (yoksa story adresinden türetilir). */
  url?: string | null;
}

export interface SerbestMetinGirdisi {
  baslik: string;
  aciklama: string;
  ac: string[];
}

// ---------------------------------------------------------------- Tutarlılık bulguları

export type BulguTuru =
  | "internal_contradiction"
  | "doc_vs_code"
  | "doc_vs_data"
  | "missing_in_doc"
  | "missing_in_code"
  | "ambiguous";

export type Kanit =
  | { kind: "code"; repo: string; path: string; line: number; snippet: string }
  | { kind: "data"; query: string; result_digest: string; result_preview?: string | null };

export type BulguKarari = "fix_doc" | "code_defect" | "accept_difference";

/**
 * Tutarlılık bulgusu durumları — core `consistency_finding` makinesiyle birebir aynı küme
 * (sozlesme.test.ts denetler). `unverified`: kanıt henüz deterministik doğrulanmadı, karar
 * verilemez ve doğrulanmış gibi gösterilmez; `discarded` kullanıcıya gösterilmez.
 * "Jira'ya yazıldı" bir durum değil: `resolved` + `karar === "fix_doc"`.
 */
export const BULGU_DURUMLARI = ["unverified", "open", "decided", "resolved", "stale", "discarded"] as const;
export type BulguDurumu = (typeof BULGU_DURUMLARI)[number];

export interface Bulgu {
  id: string;
  requirement_id: string;
  /** Jira doküman düzeltme yorumundaki etiket, ör. "F2 (tur 1)". */
  bulgu_etiketi?: string | null;
  type: BulguTuru;
  doc_ref: string;
  /** Model gerekçesinin kısa özeti (karar dayanağı değildir; kanıt esastır). */
  ozet: string;
  evidence: Kanit[];
  kanit_dogrulandi: boolean;
  severity: "blocking" | "warning";
  mevcut_doc_text: string | null;
  suggested_doc_text: string | null;
  karar: BulguKarari | null;
  karar_metni: string | null;
  gerekce: string | null;
  karar_veren: string | null;
  karar_zamani: string | null;
  kontrol_turu: number;
  durum: BulguDurumu;
  bug_draft_id: string | null;
  /** Gösterilen bulgu içeriğinin (tür, ref, kanıt, metinler) hash'i; karar bunu geri gönderir. */
  icerik_hash: string;
  mode: CiktiModu | null;
  /**
   * Aynı fark önceki turda insan kararıyla kapandıysa o karar (bulgu `stale`, karar istenmez;
   * `karar*` alanları bu karardan doldurulur).
   */
  onceki_karar?: {
    finding_id: string;
    bulgu_no: string | number | null;
    kontrol_turu: number;
    karar: BulguKarari | null;
    gerekce: string | null;
    karar_veren: string | null;
    karar_zamani: string | null;
  } | null;
}

export interface BulguKararGirdisi {
  /** Kararı verilen, ekranda görülen bulgu içeriğinin hash'i (zorunlu; eksikse 422, eskiyse 409). */
  icerik_hash: string;
  karar: BulguKarari;
  metin?: string;
  gerekce?: string;
}

// ---------------------------------------------------------------- Test case'ler

export interface TestAdimi {
  id: string;
  action: string;
  data: string | null;
  expected: string;
}

/** TEKNIK-TASARIM §7 test case şeması. */
export interface TestCaseIcerik {
  title: string;
  type: "positive" | "negative" | "boundary";
  risk: "high" | "medium" | "low";
  acceptance_criteria_refs: string[];
  preconditions: string[];
  steps: TestAdimi[];
  expected_result: string;
  tags: string[];
}

export type RetNedeni =
  | "hallucinated_step"
  | "missing_ac"
  | "wrong_test_data"
  | "out_of_scope"
  | "duplicate"
  | "wrong_element";

/** Test case durumları — core `test_case` makinesiyle birebir aynı küme. */
export const CASE_DURUMLARI = ["draft", "approved", "rejected", "published", "superseded"] as const;
export type CaseDurumu = (typeof CASE_DURUMLARI)[number];

export interface TestCase {
  id: string;
  requirement_id: string;
  jira_key: string | null;
  sira_no: number;
  kanal: "portal" | "ide";
  surum: number;
  icerik: TestCaseIcerik;
  durum: CaseDurumu;
  /** approve | edit | reject — son insan kararı */
  karar: "approve" | "edit" | "reject" | null;
  ret_nedeni: RetNedeni | null;
  karar_veren: string | null;
  karar_zamani: string | null;
  /** Alan bazlı normalize düzenleme mesafesi (§12); edit kararında dolu. */
  duzeltme_olcusu: number | null;
  icerik_hash: string;
  onaylanan_hash: string | null;
  ai_generated: boolean;
  ai_sure_ms: number;
  review_sure_ms: number | null;
  maliyet_usd: number;
  jira_test_key: string | null;
  /** Analistin case'i ilk görüntülediği an (`POST /cases/{id}/viewed`); review süresi buradan ölçülür. */
  goruntulenme?: string | null;
  /** Yayınlanan Test kaydının adresi (`external_ref.url`). */
  jira_test_url?: string | null;
  /** Düzeltme küçük mü (§12: ölçü ≤ eşik ve beklenen sonuç anlamca aynı) — kabul oranına girer. */
  kucuk_duzeltme?: boolean | null;
  /** Deterministik içerik uyarıları (ör. gereksinimde olmayan kabul kriteri referansı). */
  uyarilar?: string[];
  mode: CiktiModu | null;
  /** AI'ın özgün içeriği (ilk düzeltme kararından önce); düzeltilmemişse yok. */
  ai_icerik?: TestCaseIcerik | null;
  /** AI özgünü → insan düzeltmesi alan farkları (core metriğinin değişti saydığı alanlar). */
  fark?: CaseAlanFarki[];
  /** Düzeltmenin küçük sayılıp sayılmadığının Türkçe gerekçesi. */
  duzeltme_nedeni?: string | null;
  /** Case gereksinimin önceki (PO onayı değişmiş) içeriğine ait. */
  onceki_icerik?: boolean;
}

export interface CaseAlanFarki {
  alan: string;
  etiket: string;
  once: string;
  sonra: string;
}

/** `GET /requirements/{id}/case-metrics` (§12): ilk karara göre kabul oranı, süreler, maliyet. */
export interface CaseMetrikleri {
  requirement_id: string;
  uretilen: number;
  karar_verilen: number;
  bekleyen: number;
  kabul: number;
  /** Kabul / üretilen; hiç case yoksa null. */
  kabul_orani: number | null;
  kabul_hedefi: number;
  ilk_kararlar: Record<string, number>;
  ret_nedenleri: Record<string, number>;
  ai_sure_ms: number;
  review_sure_ms: number;
  ort_review_sure_ms: number | null;
  maliyet_usd: number;
  /** Case üretim çağrılarının model modu dağılımı ({replay: 1, live: 0, …}). */
  ai_cagri_modlari: Record<string, number>;
  /**
   * Story başına manuel case hazırlama süresi (baz değer, §1.6/§12; F0'da ölçülür). Çekirdek
   * yapılandırmadan verirse dolu; yoksa portal derleme ayarına (VITE_MANUEL_BAZ_DK) bakar.
   */
  manuel_baz_ms?: number | null;
  /** Deterministik kapsam denetimi: hiçbir güncel (onaylı/taslak) case'in atıf yapmadığı AC'ler. */
  kapsanmayan_ac?: string[];
  /** Çekirdeğin ölçüm uyarıları (ör. manuel baz değer yok; REPLAY'de AI süresi ölçülmez). */
  uyarilar?: string[];
}

export interface CaseKararGirdisi {
  /** Ekranda görülen case içeriğinin hash'i (`TestCase.icerik_hash`); düzeltmede de düzeltme öncesi. */
  icerik_hash: string;
  karar: "approve" | "edit" | "reject";
  icerik?: TestCaseIcerik;
  ret_nedeni?: RetNedeni;
  /**
   * §12 "küçük düzeltme": beklenen sonuç ANLAMCA değişti mi (insan kararı). Düzeltmede beklenen
   * sonuç metni değiştiyse analist seçer; gönderilmezse core metin karşılaştırmasına düşer.
   */
  beklenen_anlam_degisti?: boolean;
}

// ---------------------------------------------------------------- Yayın

export type YayinHedefi = "jira" | "xray";

export interface YayinOnizlemeKalemi {
  case_id: string;
  title: string;
  issue_type: string;
  summary: string;
  labels: string[];
  link: { type: string; story_key: string | null };
  adim_sayisi: number;
  islem:
    | "create"
    | "skip_existing"
    | "blocked_hash_mismatch"
    | "blocked_not_approved"
    | "blocked_no_story"
    | "blocked_requirement_changed";
  external_key: string | null;
}

export interface YayinOnizleme {
  requirement_id: string;
  hedef: YayinHedefi;
  proje: string;
  kalemler: YayinOnizlemeKalemi[];
  uyarilar: string[];
  /** Kullanıcıya gösterilen Jira bağlantı kökü (JIRA_BROWSE_URL; yerelde jira-sim). */
  jira_browse_url?: string | null;
}

export interface YayinSonucKalemi {
  case_id: string;
  durum: "created" | "exists" | "failed";
  external_key: string | null;
  /** Hedef sistemdeki kaydın adresi (`PublishedCase.url`); yoksa portal browse kökünden türetir. */
  url?: string | null;
  hata: string | null;
}

export interface YayinSonucu {
  hedef: YayinHedefi;
  sonuclar: YayinSonucKalemi[];
}

// ---------------------------------------------------------------- Kod üretimi

export interface AjanAdimi {
  sira: number;
  step_id: string;
  arac: string; // browser_click …
  aciklama: string;
  po: string | null;
  method: string | null;
  args: unknown[];
  verified: boolean;
  ekran_goruntusu_url: string | null;
  zaman: string;
}

export interface PullRequest {
  number: number;
  /** Tarayıcıda açılabilen PR adresi; LocalForge'da (forge web arayüzü yok) null. */
  url: string | null;
  baslik: string;
  branch: string;
  durum: "open" | "merged" | "closed";
  ci: "pending" | "passed" | "failed" | null;
  /** İncelenen PR içeriğinin (script/onarım) hash'i; merge gövdesi bunu geri gönderir. */
  icerik_hash: string;
  /** İncelenen head commit'i; merge yalnızca dal hâlâ bu commit'teyse yapılır. */
  head_sha: string;
}

/** `POST /prs/{number}/merge` gövdesi: kullanıcının incelediği içerik ve head commit. */
export interface MergeGirdisi {
  icerik_hash: string;
  head_sha: string;
}

export type BreakAsamasi = "baseline" | "broken" | "restored";

export interface BreakVerify {
  durum: "not_started" | "running" | "passed" | "weak";
  asamalar: {
    ad: BreakAsamasi;
    sonuc: "pending" | "running" | "passed" | "failed";
    run_id: string | null;
    zaman: string | null;
  }[];
}

/**
 * Script durumları — core `script` makinesiyle birebir aynı küme. "Merge'e hazır" ve "zayıf test"
 * durum değildir: `pr_open` + `break_verify.durum` / `zayif_test` alanlarından türetilir.
 */
export const SCRIPT_DURUMLARI = ["pending", "verifying", "checking", "blocked", "pr_open", "merged", "closed", "failed"] as const;
export type ScriptDurumu = (typeof SCRIPT_DURUMLARI)[number];

export interface Script {
  id: string;
  case_ids: string[];
  requirement_key: string | null;
  baslik: string;
  dosya_yolu: string;
  branch: string;
  durum: ScriptDurumu;
  pr: PullRequest | null;
  pass_at_1: boolean | null;
  /** Kırarak doğrulamada uygulama kırıldığında da yeşil kaldı (core `script.zayif_test`). */
  zayif_test: boolean;
  break_verify: BreakVerify;
  mode: CiktiModu;
  olusturma: string;
  hata: string | null;
}

export interface ScriptDetay extends Script {
  kod: string | null;
  adimlar: AjanAdimi[];
  yerel_kontrol: { tsc: boolean | null; eslint: boolean | null; ast_guard: boolean | null; tekrar: number } | null;
}

// ---------------------------------------------------------------- Koşular

export type Tetik = "pr" | "push" | "nightly" | "deploy";
export type KosuKaynagi = "local" | "github" | "sauce";

export interface Kosu {
  id: string;
  tetik: Tetik;
  kaynak: KosuKaynagi;
  commit: string;
  pr_no: number | null;
  durum: "queued" | "running" | "passed" | "failed" | "error";
  baslangic: string;
  sure_ms: number | null;
  toplam: number;
  gecen: number;
  basarisiz: number;
  flaky: number;
  atlanan: number;
  allure_url: string | null;
  sauce_url: string | null;
  ci_url: string | null;
  break_campaign: boolean;
}

export interface TestSonucu {
  id: string;
  test_adi: string;
  durum: "passed" | "failed" | "flaky" | "skipped";
  sure_ms: number;
  retry: number;
  hata_mesaji: string | null;
  failure_id: string | null;
  case_id: string | null;
}

export interface KosuDetay extends Kosu {
  sonuclar: TestSonucu[];
}

// ---------------------------------------------------------------- Triage

export type HataSinifi =
  | "environment"
  | "flaky"
  | "test_maintenance"
  | "product_defect"
  | "test_data"
  | "unknown";

export interface EslesenSinyal {
  kod: string;
  aciklama: string;
  kaynak: string;
}

export interface LocatorOnarimi {
  tur: "locator_fix";
  dosya: string;
  anahtar: string;
  eski_test_id: string;
  yeni_test_id: string;
  rol: string;
  ad: string;
  dogrulama: string[];
  durum: "proposed" | "pr_open" | "merged" | "rejected";
  pr: PullRequest | null;
}

export interface HataAnalizi {
  id: string;
  run_id: string;
  test_adi: string;
  hata_imzasi: string;
  hata_mesaji: string;
  sinif: HataSinifi;
  alt_tur: string | null;
  eslesen_sinyaller: EslesenSinyal[];
  karar_kaynagi: "rule" | "llm";
  llm_yorumu: string | null;
  oneri: LocatorOnarimi | { tur: "bug_draft"; bug_draft_id: string } | null;
  /** url null: artifact henüz sunulmuyor (etiket düz metin gösterilir). */
  kanit_linkleri: { etiket: string; url: string | null }[];
  mode: CiktiModu;
  zaman: string;
}

// ---------------------------------------------------------------- Bug taslakları

export interface BugTaslakIcerik {
  summary: string;
  steps: string[];
  expected: string;
  actual: string;
  environment: string;
  /** url null: kanıtın açılabilir adresi yok (ör. artifact sunucusu yok); "#…" sayfa içi referans. */
  evidence: { tur: "sauce_video" | "allure" | "trace" | "screenshot" | "code" | "data"; url: string | null; etiket: string }[];
  story_key: string | null;
  test_case_key: string | null;
  severity_suggestion: "critical" | "major" | "minor" | "trivial";
  labels: string[];
  /** "sablon": doğrulanmış kanıttan deterministik şablonla yazıldı (model çağrısı yok, `mode` null). */
  uretim?: string;
}

export interface MukerrerAday {
  key: string;
  summary: string;
  durum: string;
  gerekce: string;
  sinyaller: string[];
}

/** Bug taslağı durumları — core `bug_draft` makinesiyle birebir aynı küme. */
export const BUG_DURUMLARI = ["draft", "approved", "dismissed", "published"] as const;
export type BugDurumu = (typeof BUG_DURUMLARI)[number];

export interface BugTaslagi {
  id: string;
  kaynak: "triage" | "consistency" | "a11y";
  failure_id: string | null;
  finding_id: string | null;
  icerik: BugTaslakIcerik;
  mukerrer_adaylari: MukerrerAday[];
  karar: "new" | "link" | "dismiss" | null;
  durum: BugDurumu;
  /** `karar === "link"`: bağlanan mevcut Jira kaydı. */
  link_key: string | null;
  /** Gösterilen taslak içeriğinin hash'i; karar bunu geri gönderir. */
  icerik_hash: string;
  onaylayan: string | null;
  onay_zamani: string | null;
  jira_key: string | null;
  /** null: model çağrısı yok (ör. şablon taslağı); "live" varsayılmaz. */
  mode: CiktiModu | null;
  olusturma: string;
}

export interface BugKararGirdisi {
  /** Ekranda görülen taslak içeriğinin hash'i (düzenleme öncesi). */
  icerik_hash: string;
  karar: "new" | "link" | "dismiss";
  icerik?: BugTaslakIcerik;
  link_key?: string;
}

// ---------------------------------------------------------------- Kontrol Kulesi

export interface KontrolKulesi {
  son_kosular: Kosu[];
  gecme_orani: { oran: number; toplam: number; gecen: number; donem_gun: number };
  gunluk_gecme: { tarih: string; oran: number; kosu: number }[];
  flaky: { test_adi: string; neden: "retry" | "same_commit"; sayi: number; son_gorulme: string }[];
  karne: {
    story_key: string;
    baslik: string;
    alan: string;
    case_sayisi: number;
    otomasyon_kapsami: number;
    son_sonuc: "passed" | "failed" | "none";
    acik_bug: number;
  }[];
  ai_katkisi: {
    kabul_orani: number;
    kabul_hedefi: number;
    script_ilk_review: number;
    script_hedefi: number;
    ort_ai_sure_ms: number;
    ort_review_sure_ms: number;
    manuel_baz_ms: number | null;
    maliyet_usd_toplam: number;
    maliyet_usd_bugun: number;
    gunluk_butce_usd: number;
    cagri_sayisi: number;
    replay_cagri: number;
  };
  a11y: {
    ihlal: number;
    kritik: number;
    son_tarama: string | null;
    sayfalar: { yol: string; ihlal: number; kritik: number }[];
  };
}

// ---------------------------------------------------------------- Denetim

export interface DenetimOlayi {
  id: string;
  sira: number;
  aktor: string;
  eylem: string;
  nesne: string;
  ozet: string;
  zaman: string;
  prev_hash: string;
  hash: string;
}

export interface ZincirDogrulama {
  gecerli: boolean;
  kontrol_edilen: number;
  ilk_kirik_id: string | null;
  son_hash: string | null;
  zaman: string;
}

export interface DenetimYaniti {
  olaylar: DenetimOlayi[];
  dogrulama: ZincirDogrulama | null;
}

// ---------------------------------------------------------------- MCP token

export type TokenKapsami = "submit" | "publish";

export interface McpToken {
  id?: string;
  token: string;
  kapsam: TokenKapsami;
  son_kullanma: string;
  mcp_url: string;
}

/** `GET /tokens` satırı (ham token yok; yalnızca oluşturulduğu an bir kez gösterilir). */
export interface McpTokenKaydi {
  id: string;
  kapsam: TokenKapsami;
  son_kullanma: string;
  iptal: boolean;
  son_kullanim: string | null;
  olusturma: string;
}

// ---------------------------------------------------------------- Genel işlem yanıtı

/** Arka plan işi başlatan uçların yanıtı (POST review/generate/... → 202). */
export interface IsYaniti {
  job_id: string | null;
  durum: string;
  mesaj?: string;
  /** apply-doc-fixes "son hal onayı": kararsız uyarıların accept_difference olarak kaydı (ör. "F2 (tur 1)"). */
  kabul_edilen_uyarilar?: string[];
}

// ---------------------------------------------------------------- SSE

export type OlayTuru =
  | "case.generated"
  | "agent.step"
  | "pr.opened"
  | "ci.status"
  | "failure.classified"
  | "requirement.updated"
  | "finding.updated"
  | "finding.verified"
  | "po.approved"
  | "publish.started"
  | "publish.progress"
  | "publish.completed"
  | "publish.failed"
  | "bug.published";

export interface PortalOlayi {
  type: OlayTuru | string;
  /** İlgili nesne kimliği (script_id, requirement_id, run_id …). */
  id?: string;
  data: Record<string, unknown>;
}
