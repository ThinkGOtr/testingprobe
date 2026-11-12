// Portal ↔ core-api veri sözleşmesi (MIMARI-SOZLESME §5, TEKNIK-TASARIM §7/§8).
//
// Adlandırma kuralı: veritabanı kökenli alanlar Türkçe (kullanici_adi, olusturma, durum …);
// AI şemalarından gelen gömülü yükler (test case içeriği, bulgu kanıtı, bug taslağı içeriği,
// ön inceleme soruları) TEKNIK-TASARIM'daki İngilizce şema adlarını aynen taşır.

import type { Platform } from "../lib/platform";
export type { Platform } from "../lib/platform";

export type Rol = "analyst" | "engineer" | "presenter" | "po" | "tester";

/** Model geçidi modu (§8.8). live dışındaki her değer portalda rozetle gösterilir. */
export type CiktiModu = "live" | "replay" | "replay_miss";

export interface Kullanici {
  id: string;
  kullanici_adi: string;
  rol: Rol;
  /** Yalnızca gösterim (yetki her zaman `rol`): "Cengizhan Gunaydin · Analist"; ad yoksa rol etiketi. */
  gorunen_ad?: string;
  /** Kişi adı (rol etiketsiz); tanımsızsa null. */
  ad_soyad?: string | null;
  /** Adın kaynağı: "aiprobe" = kişinin AI Probe hesabından (TP doğrulamaz; arayüz belirtir). */
  ad_kaynak?: string | null;
  /** Tüm portal kullanıcılarının görünen adları ({kullanici_adi: gorunen_ad}); denetim/onay görünümleri için. */
  kisiler?: Record<string, string>;
  /** Yalnız AI Probe oturumunda: katalogdaki ürün kimliği (`testing-probe`; değiştirici kullanır). */
  product?: string;
  /** Yalnız AI Probe oturumunda: kişiye bağlı rol hesaplarının rolleri ("Rol değiştir" için). */
  roles?: Rol[];
  /** Yalnız AI Probe oturumunda: kişinin tüm ürünlerdeki rolleri (`{tp: [...], ap: [...]}`; değiştirici). */
  products?: Record<string, string[]>;
}

/** `POST /auth/logout`: AI Probe oturumunda `redirect` (tüm ürünlerden çıkış sayfası). */
export interface CikisYaniti {
  ok?: boolean;
  redirect?: string;
}

/** AI Probe rol seçici / "Rol değiştir" hesabı (`GET /auth/aiprobe/hesaplar`). */
export interface AiprobeHesabi {
  id: string;
  kullanici_adi: string;
  rol: Rol;
  gorunen_ad: string;
}

export interface AiprobeHesaplari {
  hesaplar: AiprobeHesabi[];
  /** Etkin oturumun hesabı ("Rol değiştir"); seçim çereziyle (girişte) boş. */
  aktif_id?: string | null;
  /** Girişteki rol seçicide dönülecek portal yolu. */
  continue?: string;
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
   * Son denetim güvenilmez (REPLAY-MISS ya da tüm bulgular elendi): belge otomatik son hâl olmaz;
   * analist açıkça "son hâl" der (fail-closed). null: güvenilir.
   */
  denetim_guvenilmez?: string | null;
  /** Gereksinim insan kararı bekliyor (tur sınırı ya da güvenilmez denetim). */
  insan_karari_gerekli?: boolean;
  /** Son başarısız işlemin nedeni (core `son_hata`); yoksa null. */
  son_hata?: SonHata | null;
  /** PO soru yorumunun Jira'ya yazılma durumu (core `po_istegi`). */
  po_istegi?: PoIstegi | null;
  /**
   * Story başına manuel test tasarımı baz değeri (Faz 5). `undefined`: çekirdek bu bilgiyi
   * sunmuyor (eski core) — ekran "bilinmiyor" der, değer uydurulmaz.
   */
  manuel_baz?: ManuelBaz;
}

// ---------------------------------------------------------------- Manuel baz değer (Faz 5)

/**
 * Baz değerin kaynağı: `olcum` story için elle girilmiş gerçek ölçüm (kim/ne zaman/not ile),
 * `varsayilan` `TP_MANUAL_BASELINE_S` (story için ölçülmedi), `olculmedi` hiçbiri.
 * Kazanç yalnızca `olcum` story'lerde hesaplanır.
 */
export type BazKaynagi = "olcum" | "varsayilan" | "olculmedi";

export interface ManuelBaz {
  /** Saniye; ölçülmediyse null (sayı uydurulmaz). */
  deger_s: number | null;
  kaynak: BazKaynagi;
  /** Ölçümü giren portal kullanıcısı (yalnızca `olcum`). */
  giren: string | null;
  zaman: string | null;
  /** Ölçüm notu (kim, nasıl ölçtü). */
  not: string | null;
}

/** `PUT /requirements/{id}/baseline` gövdesi. */
export interface BazDegerGirdisi {
  deger_s: number;
  not: string;
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
   * Story başına manuel case hazırlama süresi (baz değer, §1.6/§12). Çekirdek: story ölçümü →
   * yoksa TP_MANUAL_BASELINE_S (`manuel_baz_kaynagi='varsayilan'`, kazanca GİRMEZ) → yoksa null.
   */
  manuel_baz_ms?: number | null;
  /** `olcum` | `varsayilan` | null (ölçülmedi). Kazanç yalnızca `olcum` ile hesaplanır. */
  manuel_baz_kaynagi?: string | null;
  /** Ayrıntılı baz değer nesnesi (`deger_s`, `kaynak`, `giren`, `zaman`, `not`). */
  manuel_baz?: unknown;
  /** İnsan review süresi tabanı (ms; core TP_CT_REVIEW_MIN_S). Yoksa portal 5 sn varsayar. */
  review_tabani_ms?: number;
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
  /** Adım snapshot'ta doğrulandı mı; ajan olayı bunu taşımıyorsa null (araç izni doğrulama değildir). */
  verified: boolean | null;
  ekran_goruntusu_url: string | null;
  zaman: string;
  /** Aracın temizlenmiş ham çıktısı (parola maskeli); kartta "Ham çıktı" altında. Yoksa null. */
  ham_cikti?: string | null;
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
  /**
   * PR'ın check'leri (LocalForge: `local-ci` = toolchain-worker + test-runner sonucu; GitHub:
   * `test-local`, `ast-guard`, `semgrep`, isteğe bağlı Sauce). Yoksa yalnızca `ci` özeti gösterilir.
   */
  checks?: PrCheck[];
  /** PR'ın yaşadığı forge (TP_FORGE). Bilinmiyorsa yok. */
  forge?: "local" | "github" | null;
  /** Birleştirildiyse: merge commit'i, birleştiren ve zaman (core `pull_request`); bilinmiyorsa yok. */
  merge_sha?: string | null;
  merge_eden?: string | null;
  merge_zamani?: string | null;
  /** PR açıklaması (core `pull_request.govde`: izlenebilirlik, eşleme, yerel kontrol, denetim zinciri). */
  govde?: string | null;
  /** Dal durumu: başka bir PR merge edilince bot dalı main'in gerisinde kalır. */
  dal?: PrDalDurumu | null;
}

export interface PrDalDurumu {
  geride: boolean;
  /** `codegen.update_branch` işinin durumu (ör. "kuyrukta", "calisiyor", "basarisiz"); yoksa null. */
  guncelleme: string | null;
  neden: string | null;
}

export type CheckDurumu = "passed" | "failed" | "pending" | "skipped" | "error";

export interface PrCheck {
  ad: string;
  durum: CheckDurumu;
  /** Zorunlu check mi (merge kapısı; `TP_REQUIRED_CHECKS`). Bilinmiyorsa null. */
  zorunlu: boolean | null;
  url: string | null;
  aciklama: string | null;
}

/** `POST /prs/{number}/merge` gövdesi: kullanıcının incelediği içerik ve head commit. */
export interface MergeGirdisi {
  icerik_hash: string;
  head_sha: string;
  /**
   * İnsanın kabul ettiği uyarılar için not (ör. "Zayıf test olarak merge edildi"). Core onay kaydına
   * yazar; eski core alanı yok sayar (pydantic extra=ignore).
   */
  onay_notu?: string | null;
}

export type BreakAsamasi = "baseline" | "broken" | "restored";

export interface BreakVerify {
  /** `failed`: doğrulama tamamlanamadı (ör. bayraksız koşu kırmızı ya da ortam hatası). */
  durum: "not_started" | "running" | "passed" | "weak" | "failed";
  /** Tamamlanamadıysa ya da zayıfsa core'un nedeni. */
  neden?: string | null;
  asamalar: {
    ad: BreakAsamasi;
    sonuc: "pending" | "running" | "passed" | "failed";
    run_id: string | null;
    zaman: string | null;
    /** Koşunun yerel kontrol sınıfı (core gönderirse): kırık koşuda yalnızca `defect_adayi` (assertion) kanıttır. */
    sinif?: YerelKontrolSinifi | null;
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
  /** İnsana düşme nedeni (core `script_codegen.engel_turu`/`engel_nedeni`), yoksa null. */
  engel: { tur: string; neden: string | null } | null;
  /** Yerel kontrolün sınıfı (liste rozeti: "defect adayı"); kontrol yapılmadıysa null. */
  yerel_sinif: YerelKontrolSinifi | null;
  /** Defect adayının triage kaydı (core `script.failure_id`); yoksa null/yok. */
  failure_id?: string | null;
  /**
   * 009: testin platformu (core `script.platform`: web | android | ios | windows). 009 öncesi core
   * alanı göndermez; o zaman yalnız web üretilebildiği için uyarlayıcı `web` yazar.
   */
  platform?: Platform | null;
  /** null: model çağrısı yok ya da mod bilinmiyor ("live" uydurulmaz). */
  mode: CiktiModu | null;
  olusturma: string;
  hata: string | null;
}

/**
 * Doğrulanmış adım → page object eşlemesi (core `step_mapping`, §8.4 adım 2–3). Kod yalnızca
 * bu eşlemeden şablonla üretilir (model TypeScript yazmaz).
 */
export interface AdimEslemesi {
  adim_no: number;
  /** Case adımı referansı ("S1"); beklenen sonuç doğrulamasında null olabilir. */
  step_id: string | null;
  po: string;
  method: string;
  args: unknown[];
  /** `expect*` doğrulama metodu (assertion). */
  beklenen: boolean;
  verified: boolean;
  /** Assertion değerinin onaylı case metnindeki karşılığı (§8.4 adım 3); bilinmiyorsa null. */
  kaynak_metin: string | null;
  kanit_ref: string | null;
  /** Doğrulama notu (ör. giriş adımı ajan bayisiyle doğrulandı; test case bayisiyle koşar). */
  dogrulama_notu?: string | null;
}

/**
 * Yerel kontrolün (toolchain-worker: tsc/eslint/AST koruması → test-runner: repeat-each) sonucu.
 * `sinif` başarısızlığın deterministik sınıfıdır: `defect_adayi` = assertion hatası, otomatik
 * onarım yok, insana gider (§8.4 adım 5); `locator` = eşleme/locator hatası (1 düzeltme turu).
 */
export type YerelKontrolSinifi = "gecti" | "defect_adayi" | "kararsiz" | "locator" | "derleme" | "ortam" | "bilinmiyor";

export interface YerelKontrolHatasi {
  /** Core aynı hatanın repeat-each tekrarlarını tek satıra toplar: kaç tekrarda görüldü (yoksa 1). */
  tekrar?: number;
  test_adi: string;
  hata_mesaji: string | null;
  beklenen: string | null;
  gerceklesen: string | null;
  /** Hatanın olduğu test adımı (Playwright step başlığı), biliniyorsa. */
  adim: string | null;
}

export interface YerelKontrol {
  tsc: boolean | null;
  eslint: boolean | null;
  ast_guard: boolean | null;
  tekrar: number;
  /** Playwright koşusunun sonucu; koşu yapılmadıysa null. */
  sonuc: "passed" | "failed" | "error" | null;
  sinif: YerelKontrolSinifi | null;
  /** Sınıfın Türkçe açıklaması (core'dan); yoksa portal sınıfa göre metin gösterir. */
  aciklama: string | null;
  run_id: string | null;
  /** Yapılan eşleme düzeltme turu sayısı (en fazla 1; assertion'a dokunmaz). */
  duzeltme_turu: number;
  basarisiz: YerelKontrolHatasi[];
  /** Playwright tekrarlarında geçen / toplam test (repeat-each dahil); bilinmiyorsa null. */
  gecen: number | null;
  toplam: number | null;
  /** Kısa hata özeti (ör. "Başarısız adım: tsc"). */
  hata: string | null;
}

export interface ScriptDetay extends Script {
  kod: string | null;
  adimlar: AjanAdimi[];
  /** Doğrulanmış adım eşlemesi; core sunmuyorsa boş. */
  eslemeler: AdimEslemesi[];
  yerel_kontrol: YerelKontrol | null;
  /**
   * Core'un merge kapısı gerekçeleri (boş = kapı açık). Core göndermiyorsa `null`: portal kapıyı
   * PR/CI/kırma alanlarından türetir (karar yine core'da; buton yalnızca rehberdir).
   */
  merge_engelleri: string[] | null;
  /**
   * Merge'i engellemeyen ama açık insan kabulü (`onay_notu`) isteyen core gerekçeleri (zayıf test,
   * kırarak doğrulama yapılmadı/tamamlanamadı). Core göndermiyorsa `null` (portal türetir).
   */
  merge_kabul_gerekli?: string[] | null;
  /** core'un ekran uyarıları (REPLAY kaynağı, kırma yapılmadı …). */
  uyarilar: string[];
  /** Adım 5 (ajan) gecikme bütçesi, saniye (core `TP_CODEGEN_STEP5_BUDGET_S`); bilinmiyorsa yok. */
  gecikme_butcesi_s?: number | null;
}

// ---------------------------------------------------------------- Koşular

/** core `run.tetik` (enums.RUN_TETIK; CI workflow `trigger` girdisiyle ortak liste). */
export type Tetik = "pr" | "push" | "nightly" | "deploy" | "break_verify" | "local_check" | "manual";
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
  /** Üretilmiş statik Allure raporu (yoksa allure-results artefaktı). */
  allure_url: string | null;
  /** Ham allure-results dizini (JSON listesi); rapor varken ikincil bağlantı. */
  allure_sonuclari_url?: string | null;
  /** Playwright HTML raporu. */
  rapor_url: string | null;
  /** JUnit XML (core `junit_url`; yoksa yerel artefakt düzeninden türetilir). */
  junit_url?: string | null;
  sauce_url: string | null;
  /** GitHub koşusunun Sauce job'u (sauce.json): koştu mu, ulaşılamadı mı, kimlik yok mu. */
  sauce_durum?: "passed" | "failed" | "error" | "atlandi" | null;
  sauce_neden?: string | null;
  ci_url: string | null;
  break_campaign: boolean;
  /** Koşunun ait olduğu üretilen test (yerel kontrol / kırarak doğrulama); yoksa null. */
  script_id: string | null;
  /** Koşu öncesi sağlık yoklaması başarısız (test-runner `saglik.ok=false`): Playwright başlamadı. */
  saglik_hatasi: string | null;
  /**
   * GitHub koşusunun raporlarının core'daki yerel kopyası (core `github_artefakt`). `indirildi` /
   * `mevcut`: bağlantılar core'dan; `hata` / `yok` / `budandi`: bağlantılar GitHub'a düşer.
   */
  github_artefakt?: { durum: string; hata: string | null } | null;
  /**
   * 009: koşunun platformu (core `platform` ya da `ortam.platform`; CI `run.ortam.platform`).
   * Bilinmiyorsa null: hiçbir platforma yazılmaz (süzgeçte yalnız "Tümü"nde görünür).
   */
  platform?: Platform | null;
}

/** Playwright `test.step` ağacı (core results.json'dan; sınırlı). */
export interface PwAdimi {
  baslik: string;
  sure_ms: number;
  hata?: string | null;
  adimlar?: PwAdimi[];
}

/** Bir testin tek denemesi (core `denemeler[]`): hata + stack, adımlar, stdout/stderr. */
export interface TestDenemesi {
  deneme: number;
  sonuc: string;
  sure_ms: number;
  hata?: { mesaj?: string | null; stack?: string | null; snippet?: string | null; konum?: string | null } | null;
  adimlar?: PwAdimi[];
  stdout?: string | null;
  stderr?: string | null;
}

/** Yerel CI adımı (toolchain `/check`: deps, tsc, eslint, ast_guard, run). */
export interface KosuAdimi {
  ok: boolean;
  atlandi: boolean;
  reason?: string | null;
  error?: string | null;
  mode?: string | null;
  status?: string | null;
}

/** GitHub koşusu özeti (core `github`): işler ve ci-meta.json alanları. */
export interface GithubKosuBilgisi {
  isler: { ad: string; sonuc: string | null; url: string | null }[];
  meta: Record<string, string>;
  conclusion: string | null;
}

export interface TestSonucu {
  id: string;
  test_adi: string;
  durum: "passed" | "failed" | "flaky" | "skipped";
  sure_ms: number;
  retry: number;
  hata_mesaji: string | null;
  failure_id: string | null;
  /** Triage sınıfı (core koşu detayında gönderirse); sınıflandırma sürüyorsa/yoksa null. */
  triage_sinifi?: HataSinifi | null;
  triage_alt_tur?: string | null;
  case_id: string | null;
  /** Playwright ekleri (trace, ekran görüntüsü, video); url core'un artefakt ucundan. */
  ekler?: { ad: string; tur: string | null; url: string | null; deneme?: number | null }[];
  /** Spec dosyası (core `dosya`). */
  dosya?: string | null;
  /** Denemeler (core results.json'dan): hata/stack, adımlar, çıktı. */
  denemeler?: TestDenemesi[];
}

/** Koşunun triage kayıtları (core `failure`; test sonucuna bağlı olmayan ortam hatası dahil). */
export interface KosuHatasi {
  id: string;
  test_adi: string;
  sinif: HataSinifi | null;
  alt_tur: string | null;
  /** Bağlı bug taslağı / onarım durumu kısa özeti; yoksa null. */
  ozet: string | null;
}

export interface KosuDetay extends Kosu {
  sonuclar: TestSonucu[];
  /** Triage kayıtları (core göndermiyorsa sonuçlardaki `failure_id`'lerden türetilir). */
  hatalar?: KosuHatasi[];
  /** Koşu günlüğü (test-runner stdout) ve core'un koşu uyarıları. */
  log_url: string | null;
  hata: string | null;
  uyarilar: string[];
  /** Yerel CI adımları (toolchain `/check`); GitHub koşusunda yok. */
  adimlar?: Record<string, KosuAdimi> | null;
  /** GitHub koşusu: işler + ci-meta.json özeti. */
  github?: GithubKosuBilgisi | null;
  /**
   * 009: commit'in platform başına yerel CI kontrolleri (core `checks.platformlar`:
   * `local-ci-<platform>` → {durum, conclusion}). Yoksa null/yok.
   */
  platform_kontrolleri?: { ad: string; platform: Platform | null; durum: CheckDurumu }[] | null;
}

// ---------------------------------------------------------------- Triage

export type HataSinifi =
  | "environment"
  | "flaky"
  | "test_maintenance"
  | "product_defect"
  | "test_data"
  | "unknown";

/**
 * Prompt paketinin canlı değerlendirme durumu (rules/evaluations.yaml, Anayasa X). Core bunu
 * gönderiyorsa REPLAY rozetinin yanında "canlı değerlendirme bekliyor" yazılır; göndermiyorsa hiçbir
 * şey uydurulmaz.
 */
export interface Degerlendirme {
  durum: "pending" | "evaluated" | "waived" | "stale" | "missing";
  etiket: string | null;
}

export interface EslesenSinyal {
  kod: string;
  aciklama: string;
  kaynak: string;
  /** Sinyalin dayandığı ham kanıt parçası (hata metni, aria satırı, probe sonucu …); yoksa null. */
  kanit?: string | null;
}

/** test-runner koşu öncesi sağlık yoklaması (`saglik`; MIMARI-SOZLESME §2). */
export interface SaglikSonucu {
  ok: boolean | null;
  zaman: string | null;
  web: SaglikUcu | null;
  api: SaglikUcu | null;
  hata: string | null;
}

export interface SaglikUcu {
  url: string | null;
  status: number | null;
  ms: number | null;
  hata: string | null;
}

/** toolchain-worker `POST /locator-probe` sonucu (çalışan demo-app-web üzerinde ölçülür). */
export interface LocatorProbeSonucu {
  rol: string | null;
  ad: string | null;
  scope_test_id: string | null;
  matches: number | null;
  test_id: string | null;
  olculen: string | null;
  uygulama_sha: string | null;
  sha_eslesmesi: "eslesiyor" | "farkli" | "dogrulanamadi" | null;
  uyari: string | null;
  oneri_uretilebilir: boolean | null;
}

/** Triage'ın baktığı kanıt (§8.6 adım 1); her parça yoksa null. */
export interface TriageKaniti {
  hata_mesaji: string | null;
  beklenen: string | null;
  gerceklesen: string | null;
  /** Başarısız adım / test konumu (Playwright `location`). */
  konum: string | null;
  /** Hata anındaki aria snapshot'ından ilgili kısım (yalnızca rol + ad). */
  aria_snippet: string | null;
  locator_probe: LocatorProbeSonucu | null;
  saglik: SaglikSonucu | null;
  /** Tekrar/deneme sonuçları (repeat-each, retry), ör. ["failed", "failed", "failed"]. */
  tekrarlar?: string[];
  /** Kanıt toplama uyarıları (ör. "trace okunamadı"). */
  uyarilar?: string[];
}

export type OnarimDurumu = "proposed" | "checking" | "pr_open" | "merged" | "rejected" | "failed";

export interface LocatorOnarimi {
  tur: "locator_fix";
  dosya: string;
  anahtar: string;
  /** null: öneri üretilmedi (onarım engellendi); portal boş "" → "" farkı göstermez. */
  eski_test_id: string | null;
  yeni_test_id: string | null;
  rol: string;
  ad: string;
  /** Kapsayıcı testId öneki (`within`, ör. "product-card-"); onarımda değişmez. */
  within?: string | null;
  scope_test_id?: string | null;
  dogrulama: string[];
  /**
   * `dogrulama` kimin: triage gözlemleri (eşleşen sinyaller; onay işareti taşımaz) ya da onarım
   * işinin kontrolleri (her satır kendi sonucuna göre ✓/✗/!). Bilinmiyorsa triage sayılır.
   */
  dogrulama_kaynagi?: "triage" | "onarim";
  durum: OnarimDurumu;
  pr: PullRequest | null;
  /** Son yeşil koşunun aria snapshot'ıyla rol + ad karşılaştırması. */
  aria_dogrulama?: { eslesti: boolean | null; aciklama: string | null; run_id: string | null; kaynak?: string | null } | null;
  /** AST koruması (onarım modu): yalnızca testId değeri değişti mi. */
  ast_guard?: { ok: boolean | null; ihlaller: string[] } | null;
  /** Yerel kontrol: etkilenen TÜM testler (üretilen + elle yazılmış). */
  yerel_kontrol?: { sonuc: "passed" | "failed" | "error" | "pending" | null; run_id: string | null; gecen: number | null; toplam: number | null } | null;
  etkilenen_testler?: { test_adi: string; durum: "passed" | "failed" | "pending" | null }[];
  /** Değişen dosyalar (yama yalnızca `pages/**\/locators.ts`). */
  degisen_dosyalar?: string[];
  /** Yama (unified diff); varsa gösterilir. */
  yama?: string | null;
  /** Öneri neden PR'a dönüşmedi/başarısız (core'un Türkçe gerekçesi). */
  neden?: string | null;
  /**
   * 009: önerinin kaynağı. `sayfa_kaynagi`: uygulama testinin hata anı sayfa kaynağından (Appium XML)
   * kimlik değişimi — rol/ad/url_path boştur ve gösterilmez. Yoksa web locator önerisi.
   */
  kaynak?: string | null;
  /** 009: onarılan testin platformu (core `oneri.platform`). */
  platform?: Platform | null;
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
  /** Eşleşen kuralın adı (ör. "product_defect", "test_maintenance/locator"); yoksa null. */
  kural?: string | null;
  /** Kuralın/LLM'in Türkçe gerekçesi (core `failure.gerekce`); yoksa null. */
  gerekce?: string | null;
  llm_yorumu: string | null;
  oneri: LocatorOnarimi | { tur: "bug_draft"; bug_draft_id: string } | null;
  /** Öneri üretilmediyse nedeni (ör. "rol + ad 2 eleman buldu", "uygulama sha'sı farklı"). */
  oneri_yok_nedeni?: string | null;
  kanit?: TriageKaniti | null;
  /**
   * url null: artifact henüz sunulmuyor (etiket düz metin gösterilir). `tur`: kanıt türü (core
   * `trace|screenshot|error_context|video` ya da Playwright ek adı); yoksa etiketten türetilir.
   */
  kanit_linkleri: { etiket: string; url: string | null; tur?: string | null }[];
  /** null: model çağrısı yok (kural kararı); "live" uydurulmaz. */
  mode: CiktiModu | null;
  degerlendirme?: Degerlendirme | null;
  zaman: string;
  /** Kaynak script (kod üretimi defect adayı) varsa. */
  script_id?: string | null;
  /**
   * 009: başarısız testin platformu (core `platform`, yoksa `oneri.platform`; kanıtta Appium sayfa
   * kaynağı varsa uygulama testi olduğu bilinir ama hangi platform olduğu uydurulmaz). Bilinmiyorsa null.
   */
  platform?: Platform | null;
}

// ---------------------------------------------------------------- Bug taslakları

export interface BugTaslakIcerik {
  summary: string;
  steps: string[];
  expected: string;
  actual: string;
  environment: string;
  /** url null: kanıtın açılabilir adresi yok (ör. artifact sunucusu yok); "#…" sayfa içi referans. */
  /** `ref`: core şemasındaki ham referans (bağlantı ya da `dosya:satır`); karar gövdesine geri yazılır. */
  evidence: { tur: "sauce_video" | "allure" | "trace" | "screenshot" | "log" | "code" | "data"; url: string | null; etiket: string; ref?: string }[];
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
  /** AI sıralaması (dup_rank): high | medium | low; yoksa null. */
  olasilik?: "high" | "medium" | "low" | null;
  sira?: number | null;
  /** Jira kaydının tarayıcı adresi; yoksa null. */
  url?: string | null;
}

/** Jira mükerrer araması (JQL + dup_rank) durumu. */
export interface MukerrerArama {
  durum: "yapildi" | "yapilmadi" | "suruyor" | "basarisiz";
  jql: string | null;
  /** AI önerisi: yeni kayıt mı, bağla mı (karar testçinin). */
  oneri: "new" | "link" | null;
  oneri_link_key: string | null;
  /** Öneri neden "new"e düştü / arama neden atlandı (core gerekçesi). */
  neden?: string | null;
  mode: CiktiModu | null;
  degerlendirme?: Degerlendirme | null;
  hata: string | null;
  /**
   * Model sıralaması yapılamadıysa (REPLAY-MISS, gateway hatası, uydurulan anahtar) neden AI önerisi
   * olmadığı (Türkçe); bu durumda `oneri` null'dır — model karşılaştırmadıysa "yeni kayıt" denmez.
   */
  ai_onerisi_yok?: string | null;
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
  /** Arama durumu (core gönderiyorsa); yoksa adaylardan ve kaynaktan türetilir. */
  mukerrer_arama?: MukerrerArama | null;
  karar: "new" | "link" | "dismiss" | null;
  durum: BugDurumu;
  /** `karar === "link"`: bağlanan mevcut Jira kaydı. */
  link_key: string | null;
  /** Gösterilen taslak içeriğinin hash'i; karar bunu geri gönderir. */
  icerik_hash: string;
  onaylayan: string | null;
  onay_zamani: string | null;
  jira_key: string | null;
  /** Yayınlanan/bağlanan kaydın tarayıcı adresi; yoksa null. */
  jira_url?: string | null;
  /** Jira browse kökü (story/test bağlantıları için); yoksa null. */
  jira_browse_url?: string | null;
  /** Yayın hatası (publish_bug başarısız); yoksa null. */
  yayin_hatasi?: string | null;
  /** Yayın işi kuyrukta / sürüyor (core `yayin.durum`). */
  yayin_suruyor?: boolean;
  /** Ret gerekçesi (dismissed). */
  ret_gerekcesi?: string | null;
  /** Core'un Türkçe sonuç metni ("Mevcut kayda bağlandı: TPD-5", "Jira'da açıldı: TPD-n" …). */
  sonuc_metni?: string | null;
  /** Testçi taslağı yeniden açabilir (reddedilmiş ya da yayını kalıcı başarısız). */
  yeniden_acilabilir?: boolean;
  /** Bu sistemin açtığı Bug demo sıfırlamasında Jira'dan silindi (`jira_url` null). */
  jira_silindi?: boolean;
  /** null: model çağrısı yok (ör. şablon taslağı); "live" varsayılmaz. */
  mode: CiktiModu | null;
  degerlendirme?: Degerlendirme | null;
  olusturma: string;
}

export interface BugKararGirdisi {
  /** Ekranda görülen taslak içeriğinin hash'i (düzenleme öncesi). */
  icerik_hash: string;
  /** `edit`: düzenlemeyi kaydet (onay değil) · `reopen`: reddedilmişi taslağa al. */
  karar: "new" | "link" | "dismiss" | "edit" | "reopen";
  icerik?: BugTaslakIcerik;
  link_key?: string;
  /** Ret gerekçesi (dismiss için zorunlu). */
  gerekce?: string;
}

/** `GET /demo/status`: forge main ve çalışan demo uygulamasının durumu. */
export interface DemoDurumu {
  forge: {
    main?: string | null;
    /** Uygulama tarafı (web/src) "Sepete ekle" testId'si. */
    testid?: unknown;
    /** Test tarafı (e2e/pages/catalog/locators.ts `catalog.addToCart.testId`) main'de; core verirse. */
    e2e_testid?: string | null;
    baseline?: string | null;
    main_baseline_mi?: boolean;
    hata?: string;
  };
  /** Core açıkça verirse locator senaryosunun durumu (yoksa portal forge + koşulardan türetir). */
  locator_durumu?: "baseline" | "kirik" | "onarildi" | null;
  uygulama: { sha?: string | null; kaynak?: string | null; main_ile_eslesiyor?: boolean; neden?: string | null; yonerge?: string | null };
  web_yenileme_istegi: unknown;
  /** Locator demosu bu kipte destekleniyor mu. GitHub kipinde de evet (`kip: "github"`: kırılma insan kimliğiyle PR). Core vermezse yok. */
  locator_demo?: { destekleniyor: boolean; neden: string | null; kip?: string | null } | null;
  /** Kırma ön koşulu: main için yeşil temel koşu (yoksa core 409 + yönerge). Bilinmiyorsa `hazir: null`. */
  onarim_on_kosulu?: {
    hazir: boolean | null;
    son_yesil_kosu: { run_id: string; commit: string | null; tetik: string | null; zaman: string | null } | null;
    yonerge: string | null;
    hata?: string | null;
  } | null;
  /**
   * Model geçidinin kipi (core verirse): `mod` etkin kip, `replay_strict` prova kipi. Yoksa portal
   * gözlenen çağrı modlarından türetir ve "çekirdek bildirmiyor" der ("live" uydurulmaz).
   */
  model?: ModelDurumu | null;
  /** Prompt paketlerinin canlı değerlendirme durumu (rules/evaluations.yaml); core verirse. */
  degerlendirme?: PaketDegerlendirmesi[] | null;
}

export interface ModelDurumu {
  mod: "live" | "replay" | "record" | "auto" | string | null;
  replay_strict: boolean | null;
  /** Model anahtarı tanımlı mı (değer asla gönderilmez). */
  anahtar_var?: boolean | null;
  aciklama?: string | null;
}

export interface PaketDegerlendirmesi {
  paket: string;
  surum: number | null;
  durum: Degerlendirme["durum"];
  etiket: string | null;
}

// ---------------------------------------------------------------- Kontrol Kulesi

/**
 * Kontrol Kulesi KPI anahtarları: her KPI'nın kaynağı (`kaynaklar[anahtar]`) ipucunda gösterilir.
 */
export type KpiAnahtari =
  | "gecme_orani"
  | "flaky"
  | "karne"
  | "kabul_orani"
  | "script_ilk_review"
  | "hazirlik_suresi"
  | "manuel_baz"
  | "kazanc_orani"
  | "maliyet"
  | "a11y"
  | "son_kosular"
  /** Asistan ölçümü (Kule "Öneriler ve asistan" kartı; core `asistan.KAYNAK`). */
  | "asistan"
  /** 012 §4.7: beklenti doğruluğu ve hata yakalama oranı (Kule KPI şeridi). */
  | "beklenti_dogrulugu"
  | "hata_yakalama";

/**
 * Ölçülmemiş değerler `null`'dır: portal "ölçülmedi" / "veri yok" yazar, sayı uydurmaz
 * (canlı modda örnek değer gösterilmez).
 */
export interface KontrolKulesi {
  son_kosular: Kosu[];
  /**
   * Geçme oranı: core'da son `son_n` tamamlanmış CI koşusundan geçenlerin oranı (`birim: "kosu"`);
   * `test` aynı koşuların test bazında oranı. Örnek veri test bazındadır (`birim: "test"`).
   */
  gecme_orani: {
    oran: number | null;
    toplam: number;
    gecen: number;
    donem_gun: number | null;
    son_n: number | null;
    birim: "kosu" | "test";
    test: { oran: number | null; toplam: number; gecen: number } | null;
    /** Core'un hazır Türkçe cümlesi (pencere + hariç tutulan kasıtlı kırma koşuları); yoksa portal kurar. */
    metin?: string | null;
    /** Penceredeki kasıtlı kırma koşusu sayısı (orana girmez). */
    haric_kirma?: number | null;
  };
  /** Hedef çizgisi yalnızca core bir hedef bildirirse çizilir. */
  gecme_hedefi: number | null;
  gunluk_gecme: { tarih: string; oran: number; kosu: number }[];
  flaky: { test_adi: string; neden: "retry" | "same_commit"; sayi: number; son_gorulme: string | null }[];
  karne: {
    story_key: string;
    baslik: string;
    alan: string | null;
    case_sayisi: number;
    otomasyon_kapsami: number | null;
    son_sonuc: "passed" | "failed" | "none";
    /** Story'ye bağlı, yayınlanmış (Jira'da açılmış) farklı Jira anahtarı sayısı; kırma koşusu taslakları hariç (core `_acik_bug`). */
    acik_bug: number;
    /** Henüz yayınlanmamış (taslak/onaylı), kırma koşusundan gelmeyen bug taslağı sayısı. Eski core vermezse 0. */
    bug_taslagi: number;
    /**
     * Güncel case'lerden en son script'i defect adayı (yerel kontrolde assertion kırmızı; PR yok)
     * olanların sayısı (core `_acik_defect_adayi`). "Son sonuç" yalnızca main koşularından gelir;
     * defect adayı main'e girmediği için ayrıca gösterilir. Eski core vermezse 0.
     */
    acik_defect_adayi: number;
  }[];
  ai_katkisi: {
    kabul_orani: number | null;
    kabul_hedefi: number;
    script_ilk_review: number | null;
    script_hedefi: number;
    /** pass@1 (yerel düzeltme turu öncesi) ve düzeltme sonrası ayrı (§12). */
    pass_at_1: number | null;
    duzeltme_sonrasi: number | null;
    ort_ai_sure_ms: number | null;
    ort_review_sure_ms: number | null;
    manuel_baz_ms: number | null;
    maliyet_usd_toplam: number | null;
    maliyet_usd_bugun: number | null;
    gunluk_butce_usd: number | null;
    cagri_sayisi: number | null;
    replay_cagri: number | null;
  };
  /**
   * Story bazında hazırlık süresi ve baz değer (core `hazirlik`). Kazanç yalnızca baz değeri
   * ölçülmüş (`baz_kaynagi === "olcum"`) story'lerde gösterilir. Core vermezse boş.
   */
  hazirlik: HazirlikSatiri[];
  /** `null`: erişilebilirlik taraması hiç yapılmadı. */
  a11y: {
    ihlal: number;
    kritik: number;
    son_tarama: string | null;
    sayfalar: { yol: string; ihlal: number; kritik: number }[];
  } | null;
  /** KPI → kaynağı (ör. "test_result (JUnit XML), son 7 gün, kırma koşuları hariç"). */
  kaynaklar: Partial<Record<KpiAnahtari, string>>;
  /** Core'un dürüstlük uyarıları (ör. "Manuel baz değer girilmedi"). */
  uyarilar: string[];
}

export interface HazirlikSatiri {
  requirement_id: string;
  story_key: string | null;
  ai_sure_ms: number | null;
  review_sure_ms: number | null;
  /** AI + review; REPLAY'de AI süresi ölçülmez (yalnız review — `ai_olculmedi`). */
  toplam_ms: number | null;
  ai_olculmedi: boolean;
  review_olculmedi: boolean;
  manuel_baz_ms: number | null;
  baz_kaynagi: BazKaynagi;
  /** Core'un kazanç oranı; portal yalnızca `olcum` satırlarında kullanır. */
  kazanc_orani: number | null;
  /** Core: başlık kazancına girer mi (ölçülmüş baz + AI + review; REPLAY yalnız-review hariç). */
  kazanca_girer?: boolean;
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
  /** apply-doc-fixes "son hâl onayı": kararsız uyarıların accept_difference olarak kaydı (ör. "F2 (tur 1)"). */
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

// ---------------------------------------------------------------- 012/Ş8: ekilmiş hata koşusu ve kalite KPI'ları
// (specs/012-test-kalite-dogrulama/ANALIZ.md §4.6, §4.7, §5). Bu blok yalnız ekleme yapar; `Kosu` ve
// `KontrolKulesi` arayüz birleştirmesiyle (declaration merging) genişler, var olan satırlar değişmez.

export type HataTuru = "kod" | "veri";

/** `GET /fault-runs/catalog` öğesi (core `rules/hata-katalogu.yaml`: kod, ad, tür, açıklama, yakalayan kural). */
export interface HataKatalogOgesi {
  kod: string;
  ad: string;
  tur: HataTuru;
  aciklama: string;
  /** Hatayı yakalaması beklenen kural (ANALIZ §4.6 tablosu, ör. "kampanya"); core vermezse null. */
  yakalayan_kural: string | null;
}

/** `hata_kosusu.durum`. */
export type HataKosusuDurumu = "queued" | "running" | "done" | "failed" | "cancelled";
/** `hata_kosusu_adim.asama`. */
export type HataAdimAsamasi = "temel" | "hata" | "kapanis";
/**
 * `hata_kosusu_adim.sonuc`. Hata adımı: `yakalandi | kacti | gecersiz`; temel ve kapanış koşusu:
 * `yesil | kirmizi` (koşulamadıysa `gecersiz`); henüz koşmadıysa `bekliyor`.
 */
export type HataAdimSonucu = "bekliyor" | "yakalandi" | "kacti" | "gecersiz" | "yesil" | "kirmizi";

/** `hata_kosusu_adim` satırı (koşu detayında `adimlar[]`). */
export interface HataKosusuAdimi {
  id: string;
  platform: Platform;
  /** Temel ve kapanış koşusunda null. */
  hata_kodu: string | null;
  asama: HataAdimAsamasi;
  /** Adımın `run` kaydı (`/kosular/:id`); koşu açılmadıysa null. */
  run_id: string | null;
  sonuc: HataAdimSonucu;
  /** `yakalandi` adımında kırmızıya dönen testlerin adları. */
  kiran_testler: string[];
  /** `gecersiz` (ve kırmızı temel/kapanış) adımının nedeni. */
  neden: string | null;
  sure_ms: number | null;
  sira: number;
  /** Katalogdaki görünen ad (core `hata_adi`); temel/kapanışta ya da core vermezse null. */
  hata_adi?: string | null;
}

export interface HataYakalamaPlatformu {
  platform: Platform;
  /** `yakalanan / (yakalanan + kacan)`; payda 0 ise null (ölçülmedi). */
  oran: number | null;
  yakalanan: number;
  kacan: number;
  gecersiz: number;
  /** Koşu özetinde (core `ozet_hesapla`): koşmamış hata adımları ve temel/kapanış sonucu. Kule ölçüsünde yok. */
  bekleyen?: number;
  temel?: HataAdimSonucu | null;
  kapanis?: HataAdimSonucu | null;
}

export interface KacanHata {
  hata_kodu: string;
  ad: string;
  platform: Platform;
}

/** `hata_kosusu.ozet` (JSONB): koşu bitince yazılır; süren koşuda null. */
export interface HataKosusuOzeti {
  oran: number | null;
  yakalanan: number;
  kacan: number;
  gecersiz: number;
  /** Koşmamış (`bekliyor`) hata adımları (core verirse; iptal edilen koşuda > 0 olabilir). */
  bekleyen?: number;
  platformlar: HataYakalamaPlatformu[];
  kacanlar: KacanHata[];
}

/** `hata_kosusu` satırı (`GET /fault-runs` öğesi). */
export interface HataKosusu {
  id: string;
  durum: HataKosusuDurumu;
  platformlar: Platform[];
  hatalar: string[];
  commit: string | null;
  /** Başlatan kullanıcının kimliği (`baslatan_id`) ve — core verirse — kullanıcı adı (`baslatan`). */
  baslatan_id: string | null;
  baslatan: string | null;
  ozet: HataKosusuOzeti | null;
  uyarilar: string[];
  baslama: string | null;
  bitis: string | null;
  olusturma: string;
}

/** `GET /fault-runs/{id}`: koşu + adımları (sıra numarasına göre). */
export interface HataKosusuDetay extends HataKosusu {
  adimlar: HataKosusuAdimi[];
}

/** `POST /fault-runs` gövdesi; `hatalar` verilmezse kataloğun tamamı. */
export interface HataKosusuGirdisi {
  platformlar: Platform[];
  hatalar?: string[];
}

/** `GET /control-tower` → `beklenti_dogrulugu` (§4.7). `oran = uyumlu / (uyumlu + uyumsuz)`; payda 0 ise null. */
export interface KuleBeklentiDogrulugu {
  oran: number | null;
  uyumlu: number;
  uyumsuz: number;
  kapsam_disi: number;
  kontrol_edilemedi: number;
  /** Uyuşmazlığa rağmen gerekçeli istisnayla onaylanan case sayısı. */
  istisna: number;
  /** Karar tablosu kapsamındaki case'lerin payı; core vermezse null. */
  kapsam_orani: number | null;
}

/** `GET /control-tower` → `hata_yakalama` (§4.7); hiç koşu yoksa anahtar `null`. */
export interface KuleHataYakalama {
  son_kosu: { id: string; bitis: string | null; durum: HataKosusuDurumu };
  oran: number | null;
  yakalanan: number;
  kacan: number;
  gecersiz: number;
  platformlar: HataYakalamaPlatformu[];
  kacanlar: KacanHata[];
}

export interface KontrolKulesi {
  /** `undefined`: core bu anahtarı sunmuyor (eski sürüm); `null`: ölçülmedi. Sıfır uydurulmaz. */
  beklenti_dogrulugu?: KuleBeklentiDogrulugu | null;
  /** `undefined`: core sunmuyor; `null`: henüz ekilmiş hata koşusu yok. */
  hata_yakalama?: KuleHataYakalama | null;
}

export interface Kosu {
  /** Ekilmiş hata koşusunun adımıysa hatanın kodu (core `run.ortam.hata_kodu`, V6); değilse yok. */
  hata_kodu?: string | null;
  /** Bağlı ekilmiş hata koşusu (core `run.ortam.hata_kosusu_id`). */
  hata_kosusu_id?: string | null;
}


// ---------------------------------------------------------------- 012 Ş7: test kalite doğrulama
// Karar tablosu, beklenen sonuç kontrolü (oracle) ve ilişki tabanlı ek case (specs/012 ANALIZ §4, §6).
// Var olan arayüzlere eklenen alanlar bildirim birleştirmesiyle (aynı adlı `interface`) bu blokta durur.

/** Karar tablosu ve metamorfik ilişki durumları (ANALIZ §4.1; core `karar_tablosu` makinesi). */
export const KARAR_TABLOSU_DURUMLARI = ["draft", "pending_po", "approved", "superseded"] as const;
export type KararTablosuDurumu = (typeof KARAR_TABLOSU_DURUMLARI)[number];

export type KolonTuru = "sayi" | "metin" | "mantiksal";

export interface KararTablosuGirdisi {
  ad: string;
  tur: KolonTuru;
  birim?: string;
  aciklama?: string;
}

export interface KararTablosuCiktisi {
  ad: string;
  tur: KolonTuru;
  birim?: string;
  /** Sayısal karşılaştırma toleransı (metin olarak ondalık; verilmezse 0). */
  tolerans?: string;
  aciklama?: string;
}

export interface KararTablosuSatiri {
  id: string;
  /** Sınırlı ifade dili (§4.2); ilk koşulu sağlayan satır geçerlidir. */
  kosul: string;
  /** Çıktı adı → ifade. */
  cikti: Record<string, string>;
}

/** `karar_tablosu.icerik` (şema `rules/schemas/karar_tablosu.schema.json`). */
export interface KararTablosuIcerik {
  ad: string;
  ac_refs: string[];
  aciklama?: string;
  girdiler: KararTablosuGirdisi[];
  ciktilar: KararTablosuCiktisi[];
  satirlar: KararTablosuSatiri[];
}

/** PO'nun son kararı (`approve` | `request_changes`); "Değişiklik iste" gerekçesi buradan gösterilir. */
export interface KaliteSonKarar {
  karar: string;
  gerekce: string | null;
  kullanici: string | null;
  zaman: string | null;
}

interface KaliteKaydi {
  id: string;
  /** `karar_tablosu` | `metamorfik_iliski`. */
  tur: "karar_tablosu" | "metamorfik_iliski";
  requirement_id: string;
  sira_no: number;
  icerik_hash: string;
  onaylanan_hash: string | null;
  durum: KararTablosuDurumu;
  /** Gereksinim onaydan sonra değişti (hesaplanan özellik); bayat kayıt kontrolde kullanılmaz. */
  bayat: boolean;
  ai_generated: boolean;
  uretim_modu: CiktiModu | null;
  /** Yalnız `approved` iken dolu. */
  onaylayan: string | null;
  onay_zamani: string | null;
  son_karar: KaliteSonKarar | null;
  olusturma: string | null;
  guncelleme: string | null;
}

export interface KararTablosu extends KaliteKaydi {
  icerik: KararTablosuIcerik;
}

/** `metamorfik_iliski.icerik` (§4.5). */
export interface MetamorfikIliskiIcerik {
  ad: string;
  ac_refs: string[];
  /** Bağlı tablonun atfı ("T<sira_no>"); tablosuz ilişkide null. */
  tablo_ref?: string | null;
  on_kosul: string;
  /** Girdi adı → yeni girdinin ifadesi (kaynak case değerlerinden). */
  donusum: Record<string, string>;
  /** Çıktı adı → yeni beklenen değerin ifadesi (kaynak case değerlerinden). */
  iliski: Record<string, string>;
  aciklama?: string;
}

export interface MetamorfikIliski extends KaliteKaydi {
  karar_tablosu_id: string | null;
  icerik: MetamorfikIliskiIcerik;
}

/** Son AI taslak işi (`son_taslak`); `sonuc.atilan`: şemaya/doğrulamaya uymadığı için yazılmayan öğeler. */
export interface KaliteTaslakIsi {
  job_id: string | null;
  workflow_id: string | null;
  durum: string;
  sonuc: { atilan: { tur: string; ref: string | null; ad: string | null; hatalar: string[] }[]; [k: string]: unknown } | null;
  hata: string | null;
  olusturma: string | null;
}

/** `GET /requirements/{id}/decision-tables?tumu=` (tumu=true yerini yenisi alanları da içerir). */
export interface KararTablolariYaniti {
  tablolar: KararTablosu[];
  iliskiler: MetamorfikIliski[];
  son_taslak: KaliteTaslakIsi | null;
}

/** Tablo/ilişki içerik güncellemesi: ekranda görülen hash ile iyimser eşzamanlılık (409). */
export interface KararTablosuGuncelleme {
  icerik: KararTablosuIcerik;
  icerik_hash: string;
}
export interface IliskiGuncelleme {
  icerik: MetamorfikIliskiIcerik;
  icerik_hash: string;
  /** Yoksa bağ korunur; `null` bağı kaldırır. */
  karar_tablosu_id?: string | null;
}

/** `POST /requirements/{id}/relations`. */
export interface IliskiOlusturma {
  icerik: MetamorfikIliskiIcerik;
  karar_tablosu_id?: string | null;
}

/** Durum geçişi gövdesi: görülen hash (submit isteğe bağlı, approve / request-changes zorunlu); "Değişiklik iste"de gerekçe. withdraw / reopen gövdesizdir. */
export interface KaliteGecisGirdisi {
  icerik_hash?: string;
  gerekce?: string;
}

/** `POST /requirements/{id}/decision-tables/draft` (202). Bir taslak işi sürerken aynı iş döner. */
export interface KaliteTaslakYaniti {
  job_id: string | null;
  workflow_id: string | null;
  durum: string;
  mesaj?: string;
  uretim_no: number | null;
}

/** `GET /requirements/{id}/metamorphic-derivations`. */
export interface MetamorfikTuretme {
  id: string;
  iliski_id: string;
  kaynak_case_id: string;
  turetilen_case_id: string | null;
  sonuc: string;
  neden: string | null;
  olusturan_id: string | null;
  olusturma: string | null;
}

export type KaliteGecisi = "submit" | "withdraw" | "reopen" | "approve" | "request-changes";

/** `POST /decision-tables/{id}/evaluate` yanıtı (core `Degerlendirme`; önizleme, kayıt yok). */
export interface TabloDegerlendirmesi {
  satir_id: string | null;
  /** Sayılar core'da Decimal'dir: metin ("25.00") ya da sayı gelebilir. */
  ciktilar: Record<string, string | number | boolean | null>;
  eksik_girdiler: string[];
  hata: string | null;
}

export type OracleSonucu = "uyumlu" | "uyumsuz" | "kapsam_disi" | "kontrol_edilemedi";

/** Bir beklenen olgunun tabloyla karşılaştırması (§4.3 `ayrintilar.gruplar[].karsilastirmalar[]`). */
export interface OracleKarsilastirma {
  column: string;
  /** Case içindeki yol (`steps[3].expected`, `expected_result` …). */
  alan: string;
  alinti: string;
  case_degeri: string | number | boolean | null;
  tablo_degeri: string | number | boolean | null;
  uyumlu: boolean;
  tablo_id?: string | null;
  tablo_ad?: string | null;
  satir_id?: string | null;
}

/**
 * Case'te doğrulanmış ama tablonun eksik girdi yüzünden hesaplayamadığı beklenen değer (core
 * `karsilastirilamayanlar`; ör. birim fiyat yazmayan case'te `indirim`). Sonuca girmez.
 */
export interface OracleKarsilastirilamayan {
  tablo_id: string | null;
  tablo_ad: string | null;
  column: string;
  alan: string;
  alinti: string;
  case_degeri: string | number | boolean | null;
  neden: string;
}

export interface OracleIstisnasi {
  gerekce: string;
  veren: string | null;
  zaman: string | null;
}

/** `GET /cases` ve `GET /cases/{id}` yanıtındaki `oracle` ve `GET /cases/{id}/oracle`. */
export interface CaseOracle {
  /** `null` yalnız `kontrol_suruyor` iken (bu içerik için henüz sonuç yok). */
  sonuc: OracleSonucu | null;
  ozet: string;
  karsilastirmalar: OracleKarsilastirma[];
  /** Karşılaştırılamayan beklenen değerler (sonucu etkilemez); core vermezse boş. */
  karsilastirilamayan: OracleKarsilastirilamayan[];
  istisna: OracleIstisnasi | null;
  /** Kontrolün yapıldığı case içeriğinin hash'i (güncel ya da önerilen içerik). */
  icerik_hash: string | null;
  /** Bu içerik için kontrol işi kuyrukta / çalışıyor (yüksek riskte onay 409 `oracle_bekleniyor`). */
  kontrol_suruyor: boolean;
}

/** `POST /cases/{id}/oracle-check` (202): `{job_id, icerik_hash}`; sonuç `oracle.checked` ile gelir. */
export interface OracleKontrolYaniti {
  job_id: string | null;
  icerik_hash: string | null;
}

/** Atlanan kaynak case'in nedeni (§4.5; `zaten_turetildi`: aynı kaynak + ilişki çifti daha önce türetildi). */
export type TuretmeAtlamaSonucu = "iliski_gecersiz" | "belirsiz_alinti" | "olgu_yok" | "zaten_turetildi";

export interface TuretilenCase {
  case_id: string;
  kaynak_case_id: string;
  baslik: string;
}

export interface AtlananKaynak {
  kaynak_case_id: string;
  /** Bilinen kodlar `TuretmeAtlamaSonucu`; tanınmayan kod olduğu gibi kalır. */
  sonuc: TuretmeAtlamaSonucu | (string & {});
  neden: string | null;
  /** `zaten_turetildi`: önceki türetmenin case'i (bağlantı için; çekirdek vermeyebilir). */
  case_id?: string | null;
}

/** `POST /requirements/{id}/metamorphic-cases`. */
export interface TuretmeYaniti {
  turetilen: TuretilenCase[];
  atlanan: AtlananKaynak[];
}

export interface TuretmeGirdisi {
  iliski_id: string;
  case_ids?: string[];
}

/** §4.7 beklenti doğruluğu (gereksinim kapsamında `case-metrics`, genelde `control-tower`). */
export interface BeklentiDogrulugu {
  /** uyumlu / (uyumlu + uyumsuz); payda 0 ise null ("ölçülmedi"). */
  oran: number | null;
  uyumlu: number;
  uyumsuz: number;
  kapsam_disi: number;
  kontrol_edilemedi: number;
  istisna: number;
  kapsam_orani: number | null;
}

export interface TestCase {
  /**
   * Güncel içeriğin beklenen sonuç kontrolü. `null`: kontrol kaydı yok; alan hiç yoksa çekirdek
   * bu özelliği sunmuyor (çip çizilmez).
   */
  oracle?: CaseOracle | null;
}

export interface CaseMetrikleri {
  beklenti_dogrulugu?: BeklentiDogrulugu | null;
}

export interface CaseKararGirdisi {
  /** Yüksek riskli uyuşmazlıkta gerekçeli istisna (en az 20 karakter; denetim kaydına düşer). */
  oracle_istisna_gerekce?: string;
}

/** 012 Ş7: triage kaydının bağlı olduğu case (alt tür `beklenti` → "Case düzeltilmeli" bağlantısı). */
export interface HataAnalizi {
  case_id?: string | null;
  requirement_id?: string | null;
}
