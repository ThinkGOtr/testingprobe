// Demo-B uçlarının (kod üretimi, PR, kırarak doğrulama, koşular, Kontrol Kulesi) core yanıtlarını
// portal türlerine uyarlayan saf dönüştürücüler.
//
// Özellik şeritleri (codegen, ci-runs) yanıtı portal şekliyle (types.ts) döndürmelidir; şekil
// paralel geliştirildiği için veritabanı kolon adları (`kirma_dogrulama`, `uretim_modu`, `sonuc`,
// `baslama`, `artefaktlar`, `po_sinifi` …) ve toolchain-worker / test-runner yanıt adları (`status`,
// `repeat_each`, `saglik`) da kabul edilir. Bilinmeyen/eksik ölçü `null` kalır: portal "ölçülmedi"
// yazar, sayı uydurmaz (canlı modda örnek değer yok). Mock arka uç portal şeklini döndürür; aynı
// dönüştürücüden geçer (iki şekil de kabul edilir).

import type {
  AdimEslemesi,
  AjanAdimi,
  BreakAsamasi,
  BreakVerify,
  CheckDurumu,
  KontrolKulesi,
  KpiAnahtari,
  Kosu,
  KosuDetay,
  KosuKaynagi,
  PrCheck,
  PullRequest,
  Script,
  ScriptDetay,
  ScriptDurumu,
  Tetik,
  TestSonucu,
  YerelKontrol,
  YerelKontrolHatasi,
  YerelKontrolSinifi,
} from "./types";
import { SCRIPT_DURUMLARI } from "./types";
import { dizgeler, ilk, kimlik, metin, metinYaDaNull, modUyarla, nesneMi, sayi, sayiYaDaNull, type Ham } from "./uyum";

const nesne = (x: unknown): Ham => (nesneMi(x) ? x : {});
const dizi = (x: unknown): Ham[] => (Array.isArray(x) ? x.filter(nesneMi) : []);
const bool = (x: unknown): boolean | null => {
  if (typeof x === "boolean") return x;
  // toolchain-worker /check: {tsc: {ok, ...}}
  if (nesneMi(x) && typeof x.ok === "boolean") return x.ok;
  if (typeof x === "string") {
    const k = x.toLowerCase();
    if (["ok", "passed", "success", "true", "gecti"].includes(k)) return true;
    if (["failed", "failure", "false", "error", "basarisiz"].includes(k)) return false;
  }
  return null;
};

/**
 * core'un verdiği adres: tam adres veya core köküne göre yol. Core yolları portalda `/api` önekiyle
 * erişilir (nginx); öneksiz göreli artefakt yolu (ör. `screens/3.png`) tahmin edilmez → null.
 */
export function adresUyarla(x: unknown): string | null {
  const a = metinYaDaNull(x);
  if (!a) return null;
  if (/^https?:\/\//i.test(a) || a.startsWith("data:image/")) return a;
  if (a.startsWith("/api/")) return a;
  if (a.startsWith("/")) return `/api${a}`;
  return null;
}

// ------------------------------------------------------------------ PR ve check'ler

const CHECK_DURUMU: Record<string, CheckDurumu> = {
  passed: "passed",
  pass: "passed",
  success: "passed",
  ok: "passed",
  green: "passed",
  failed: "failed",
  fail: "failed",
  failure: "failed",
  red: "failed",
  pending: "pending",
  queued: "pending",
  in_progress: "pending",
  running: "pending",
  requested: "pending",
  waiting: "pending",
  skipped: "skipped",
  neutral: "skipped",
  error: "error",
  cancelled: "error",
  timed_out: "error",
  action_required: "error",
};

export function checkUyarla(c: Ham): PrCheck {
  const ham = metin(ilk(c, "durum", "conclusion", "status", "state", "sonuc")).toLowerCase();
  const zorunlu = ilk(c, "zorunlu", "required");
  return {
    ad: metin(ilk(c, "ad", "name", "context"), "check"),
    durum: CHECK_DURUMU[ham] ?? "pending",
    zorunlu: typeof zorunlu === "boolean" ? zorunlu : null,
    url: adresUyarla(ilk(c, "url", "details_url", "target_url", "html_url")),
    aciklama: metinYaDaNull(ilk(c, "aciklama", "description", "summary", "ozet")),
  };
}

/** PR'ın CI özeti: açıkça verilmemişse check'lerden (zorunlular; yoksa hepsi) türetilir. */
function ciOzeti(ham: unknown, checks: PrCheck[]): PullRequest["ci"] {
  const h = typeof ham === "string" ? CHECK_DURUMU[ham.toLowerCase()] : undefined;
  if (h === "passed" || h === "failed" || h === "pending") return h;
  if (h === "error") return "failed";
  if (checks.length === 0) return null;
  const bakilan = checks.some((c) => c.zorunlu) ? checks.filter((c) => c.zorunlu) : checks;
  if (bakilan.some((c) => c.durum === "failed" || c.durum === "error")) return "failed";
  if (bakilan.every((c) => c.durum === "passed" || c.durum === "skipped")) return "passed";
  return "pending";
}

const PR_DURUMU: Record<string, PullRequest["durum"]> = { open: "open", acik: "open", merged: "merged", closed: "closed", kapali: "closed" };

export function prUyarla(p: Ham): PullRequest {
  const checks = dizi(ilk(p, "checks", "kontroller", "check_runs")).map(checkUyarla);
  const forge = metin(p.forge);
  return {
    number: sayi(ilk(p, "number", "pr_no", "numara")),
    url: adresUyarla(ilk(p, "url", "html_url")),
    baslik: metin(ilk(p, "baslik", "title")),
    branch: metin(ilk(p, "branch", "head", "dal")),
    durum: PR_DURUMU[metin(ilk(p, "durum", "state")).toLowerCase()] ?? "open",
    ci: ciOzeti(ilk(p, "ci", "ci_durumu"), checks),
    icerik_hash: metin(p.icerik_hash),
    head_sha: metin(p.head_sha),
    checks,
    forge: forge === "local" || forge === "github" ? forge : null,
    merge_sha: metinYaDaNull(ilk(p, "merge_sha", "merge_commit_sha")),
    merge_eden: metinYaDaNull(ilk(p, "merge_eden", "merged_by")),
    merge_zamani: metinYaDaNull(ilk(p, "merge_zamani", "merged_at")),
    govde: metinYaDaNull(ilk(p, "govde", "body")),
    dal: dalUyarla(p.dal),
  };
}

function dalUyarla(x: unknown): PullRequest["dal"] {
  if (!x || typeof x !== "object" || Array.isArray(x)) return null;
  const d = x as Ham;
  return { geride: d.geride === true, guncelleme: metinYaDaNull(d.guncelleme), neden: metinYaDaNull(d.neden) };
}

// ------------------------------------------------------------------ Kırarak doğrulama

const ASAMALAR: BreakAsamasi[] = ["baseline", "broken", "restored"];
const ASAMA_ADI: Record<string, BreakAsamasi> = {
  baseline: "baseline",
  once: "baseline",
  green1: "baseline",
  broken: "broken",
  kirik: "broken",
  break: "broken",
  red: "broken",
  restored: "restored",
  sonra: "restored",
  green2: "restored",
};

function asamaSonucu(x: unknown): BreakVerify["asamalar"][number]["sonuc"] {
  const k = (typeof x === "boolean" ? (x ? "passed" : "failed") : metin(x)).toLowerCase();
  if (["passed", "green", "yesil", "yeşil", "success"].includes(k)) return "passed";
  if (["failed", "red", "kirmizi", "kırmızı", "failure"].includes(k)) return "failed";
  if (["running", "kosuyor", "calisiyor", "queued"].includes(k)) return "running";
  return "pending";
}

function asamaUyarla(ad: BreakAsamasi, a: Ham): BreakVerify["asamalar"][number] {
  return {
    ad,
    sonuc: asamaSonucu(ilk(a, "sonuc", "status", "durum", "passed")),
    run_id: metinYaDaNull(typeof a.run_id === "number" ? String(a.run_id) : a.run_id),
    zaman: metinYaDaNull(ilk(a, "zaman", "bitis", "ts", "baslama")),
    sinif: SINIF[metin(ilk(a, "sinif", "siniflandirma")).toLowerCase()] ?? null,
  };
}

export function kirmaUyarla(x: unknown, zayif: boolean): BreakVerify {
  const b = nesne(x);
  let asamalar: BreakVerify["asamalar"];
  if (Array.isArray(b.asamalar)) {
    asamalar = ASAMALAR.map((ad) => {
      const a = dizi(b.asamalar).find((y) => ASAMA_ADI[metin(y.ad).toLowerCase()] === ad);
      return a ? asamaUyarla(ad, a) : { ad, sonuc: "pending", run_id: null, zaman: null };
    });
  } else {
    asamalar = ASAMALAR.map((ad) => {
      const anahtar = Object.keys(b).find((k) => ASAMA_ADI[k.toLowerCase()] === ad);
      const a = anahtar ? b[anahtar] : undefined;
      return nesneMi(a) ? asamaUyarla(ad, a) : { ad, sonuc: typeof a === "string" ? asamaSonucu(a) : "pending", run_id: null, zaman: null };
    });
  }
  const ham = metin(ilk(b, "durum", "sonuc", "status")).toLowerCase();
  let durum: BreakVerify["durum"] = "not_started";
  if (zayif || ["weak", "zayif", "zayıf", "zayif_test"].includes(ham)) durum = "weak";
  else if (["passed", "yakaliyor", "caught", "ok", "gecti"].includes(ham)) durum = "passed";
  else if (["running", "calisiyor", "kosuyor", "queued", "started"].includes(ham)) durum = "running";
  else if (ham === "failed" || ham === "error" || ham === "basarisiz") durum = "failed";
  else if (asamalar.some((a) => a.sonuc === "running")) durum = "running";
  else if (asamalar.every((a) => a.sonuc !== "pending")) {
    const [b0, b1, b2] = asamalar;
    durum = b0.sonuc === "passed" && b1.sonuc === "failed" && b2.sonuc === "passed" ? "passed" : b1.sonuc === "passed" ? "weak" : "not_started";
  }
  return { durum, asamalar, neden: metinYaDaNull(b.neden) };
}

// ------------------------------------------------------------------ Ajan adımları ve eşleme

/**
 * `agent.step` olayı ya da `adimlar[]` öğesi. Core'un ajan olayında (`{script_id, arac, ozet,
 * izinli, ...}`) adım doğrulaması yoksa `verified` null kalır (araç izinli olması doğrulama değildir).
 */
export function ajanAdimiUyarla(a: Ham, varsayilanSira = 0): AjanAdimi {
  const args = ilk(a, "args", "argumanlar");
  // Eşlenmemiş ham tarayıcı adımında `verified` aracın izinli olmasından türetilmiş olabilir
  // (core `script_adim.izinli`); izin doğrulama değildir → gösterilmez.
  const hamAdim = a.izinli !== undefined && !ilk(a, "po", "po_sinifi");
  const verified = hamAdim ? undefined : ilk(a, "verified", "dogrulandi");
  return {
    sira: sayi(ilk(a, "sira", "adim", "adim_no", "seq", "n"), varsayilanSira),
    step_id: metin(ilk(a, "step_id", "adim_kimligi", "case_step")),
    arac: metin(ilk(a, "arac", "tool")),
    aciklama: metin(ilk(a, "aciklama", "ozet", "summary", "result_summary")),
    po: metinYaDaNull(ilk(a, "po", "po_sinifi")),
    method: metinYaDaNull(ilk(a, "method", "po_metodu")),
    args: Array.isArray(args) ? args : [],
    verified: typeof verified === "boolean" ? verified : null,
    ekran_goruntusu_url: adresUyarla(ilk(a, "ekran_goruntusu_url", "ekran_url", "screenshot_url")),
    zaman: metin(ilk(a, "zaman", "ts", "olusturma")),
    ham_cikti: metinYaDaNull(ilk(a, "ham_cikti", "ham")),
  };
}

export function eslemeUyarla(e: Ham, i: number): AdimEslemesi {
  const method = metin(ilk(e, "method", "po_metodu"));
  const beklenen = ilk(e, "beklenen", "expect", "is_expect");
  const args = ilk(e, "args", "argumanlar");
  return {
    adim_no: sayi(ilk(e, "adim_no", "sira", "adim"), i + 1),
    step_id: metinYaDaNull(ilk(e, "step_id", "adim_kimligi")),
    po: metin(ilk(e, "po", "po_sinifi")),
    method,
    args: Array.isArray(args) ? args : [],
    beklenen: typeof beklenen === "boolean" ? beklenen : /^expect/.test(method),
    verified: ilk(e, "verified", "dogrulandi") === true,
    kaynak_metin: metinYaDaNull(ilk(e, "kaynak_metin", "beklenen_kaynak")),
    kanit_ref: metinYaDaNull(ilk(e, "kanit_ref", "evidence_ref")),
    dogrulama_notu: metinYaDaNull(ilk(e, "dogrulama_notu")),
  };
}

// ------------------------------------------------------------------ Yerel kontrol

const SINIF: Record<string, YerelKontrolSinifi> = {
  gecti: "gecti",
  passed: "gecti",
  ok: "gecti",
  defect_adayi: "defect_adayi",
  defect_candidate: "defect_adayi",
  kararsiz: "kararsiz",
  flaky: "kararsiz",
  assertion: "defect_adayi",
  product_defect: "defect_adayi",
  locator: "locator",
  mapping: "locator",
  eslesme: "locator",
  test_maintenance: "locator",
  derleme: "derleme",
  compile: "derleme",
  tsc: "derleme",
  eslint: "derleme",
  ast_guard: "derleme",
  ortam: "ortam",
  environment: "ortam",
  bilinmiyor: "bilinmiyor",
  unknown: "bilinmiyor",
};

function hataUyarla(h: Ham): YerelKontrolHatasi {
  return {
    test_adi: metin(ilk(h, "test_adi", "title", "name")),
    hata_mesaji: metinYaDaNull(ilk(h, "hata_mesaji", "message", "mesaj")),
    beklenen: metinYaDaNull(ilk(h, "beklenen", "expected")),
    gerceklesen: metinYaDaNull(ilk(h, "gerceklesen", "actual", "received")),
    adim: metinYaDaNull(ilk(h, "adim", "step")),
    tekrar: typeof h.tekrar === "number" && h.tekrar > 0 ? h.tekrar : 1,
  };
}

/** Kontrol sonucu: core `success|failure|error`, test-runner `passed|failed|error`. */
const KONTROL_SONUCU: Record<string, "passed" | "failed" | "error"> = {
  passed: "passed",
  success: "passed",
  failed: "failed",
  failure: "failed",
  error: "error",
};

export function yerelKontrolUyarla(x: unknown): YerelKontrol | null {
  if (!nesneMi(x)) return null;
  const run = nesne(x.run);
  // core `script_codegen.yerel_kontrol` (classify.Siniflama.ozet): adım sonuçları `adimlar`'da.
  const adimlar = nesne(x.adimlar);
  const sonucHam = metin(ilk(x, "sonuc", "status") ?? ilk(x, "run_status") ?? run.status).toLowerCase();
  const sonuc = KONTROL_SONUCU[sonucHam] ?? null;
  const sinifHam = metin(ilk(x, "sinif", "siniflandirma", "karar")).toLowerCase();
  let sinif: YerelKontrolSinifi | null = SINIF[sinifHam] ?? null;
  const tsc = bool(x.tsc ?? adimlar.tsc);
  const eslint = bool(x.eslint ?? adimlar.eslint);
  const ast = bool(x.ast_guard ?? adimlar.ast_guard);
  if (!sinif && (tsc === false || eslint === false || ast === false)) sinif = "derleme";
  if (!sinif && sonuc === "passed") sinif = "gecti";
  return {
    tsc,
    eslint,
    ast_guard: ast,
    tekrar: sayi(ilk(x, "tekrar", "repeat_each"), 0),
    sonuc,
    sinif,
    aciklama: metinYaDaNull(ilk(x, "aciklama", "neden", "mesaj")),
    run_id: metinYaDaNull(kimlik(ilk(x, "run_id") ?? run.run_id)),
    duzeltme_turu: sayi(ilk(x, "duzeltme_turu", "duzeltme_turlari"), 0),
    basarisiz: dizi(ilk(x, "basarisiz", "hatalar", "failures")).map(hataUyarla),
    gecen: sayiYaDaNull(x.gecen),
    toplam: sayiYaDaNull(x.toplam),
    hata: metinYaDaNull(x.hata),
  };
}

// ------------------------------------------------------------------ Script

const SCRIPT_KUMESI = new Set<string>(SCRIPT_DURUMLARI);

function caseKimlikleri(s: Ham): string[] {
  const d = ilk(s, "case_ids", "test_case_ids");
  if (Array.isArray(d)) return d.map(kimlik).filter(Boolean);
  const c = ilk(s, "caseler", "test_cases");
  if (Array.isArray(c)) return c.map((x) => (nesneMi(x) ? kimlik(x.id) : kimlik(x))).filter(Boolean);
  const tek = ilk(s, "case_id", "test_case_id");
  return tek ? [kimlik(tek)] : [];
}

export function scriptUyarla(s: Ham): Script {
  const zayif = s.zayif_test === true;
  const prHam = ilk(s, "pr", "pull_request");
  const pr = nesneMi(prHam) ? prUyarla(prHam) : typeof s.pr_no === "number" ? prUyarla({ number: s.pr_no, branch: s.branch, head_sha: s.head_sha }) : null;
  const yk = yerelKontrolUyarla(ilk(s, "yerel_kontrol", "yerel_kontrol_sonucu"));
  const durum = metin(s.durum, "pending");
  const sinifHam = metin(ilk(s, "yerel_sinif", "yerel_kontrol_sinifi")).toLowerCase();
  return {
    id: kimlik(s.id),
    case_ids: caseKimlikleri(s),
    requirement_key: metinYaDaNull(ilk(s, "requirement_key", "jira_key", "story_key")),
    baslik: metin(ilk(s, "baslik", "title", "case_baslik"), metin(s.dosya_yolu)),
    dosya_yolu: metin(s.dosya_yolu),
    branch: metin(s.branch, pr?.branch ?? ""),
    durum: (SCRIPT_KUMESI.has(durum) ? durum : "pending") as ScriptDurumu,
    pr,
    pass_at_1: typeof s.pass_at_1 === "boolean" ? s.pass_at_1 : null,
    zayif_test: zayif,
    break_verify: kirmaUyarla(ilk(s, "break_verify", "kirma_dogrulama"), zayif),
    engel: nesneMi(s.engel) && typeof s.engel.tur === "string" ? { tur: s.engel.tur, neden: metinYaDaNull(s.engel.neden) } : null,
    yerel_sinif: SINIF[sinifHam] ?? yk?.sinif ?? null,
    failure_id: metinYaDaNull(kimlik(s.failure_id)),
    mode: modUyarla(ilk(s, "mode", "uretim_modu")),
    olusturma: metin(s.olusturma),
    hata: metinYaDaNull(ilk(s, "hata", "son_hata")),
  };
}

function mergeEngelleri(s: Ham): string[] | null {
  const d = ilk(s, "merge_engelleri");
  if (Array.isArray(d)) return dizgeler(d);
  const k = s.merge_kapisi;
  if (nesneMi(k)) {
    const n = ilk(k, "nedenler", "engeller", "reasons");
    if (Array.isArray(n)) return dizgeler(n);
    if (k.acik === true) return [];
  }
  return null;
}

export function scriptDetayUyarla(s: Ham): ScriptDetay {
  const adimlar = dizi(ilk(s, "adimlar", "ajan_adimlari", "agent_steps")).map((a, i) => ajanAdimiUyarla(a, i + 1));
  return {
    ...scriptUyarla(s),
    kod: metinYaDaNull(ilk(s, "kod", "icerik")),
    adimlar,
    eslemeler: dizi(ilk(s, "eslemeler", "step_mapping", "step_mappings")).map(eslemeUyarla),
    yerel_kontrol: yerelKontrolUyarla(ilk(s, "yerel_kontrol", "yerel_kontrol_sonucu")),
    merge_engelleri: mergeEngelleri(s),
    merge_kabul_gerekli: Array.isArray(s.merge_kabul_gerekli) ? dizgeler(s.merge_kabul_gerekli) : null,
    uyarilar: dizgeler(s.uyarilar),
    gecikme_butcesi_s: typeof s.gecikme_butcesi_s === "number" ? s.gecikme_butcesi_s : null,
  };
}

// ------------------------------------------------------------------ Koşular

const TETIKLER = new Set<Tetik>(["pr", "push", "nightly", "deploy", "break_verify", "local_check", "manual"]);
const KAYNAKLAR = new Set<KosuKaynagi>(["local", "github", "sauce"]);
const KOSU_DURUMLARI = new Set<Kosu["durum"]>(["queued", "running", "passed", "failed", "error"]);

function testSonucDurumu(x: unknown): TestSonucu["durum"] {
  const k = metin(x).toLowerCase();
  if (k === "passed" || k === "flaky" || k === "skipped") return k;
  if (k === "expected") return "passed";
  return "failed";
}

const TRIAGE_SINIFLARI = new Set<string>(["environment", "flaky", "test_maintenance", "product_defect", "test_data", "unknown"]);

/** Koşu detayındaki triage özeti (`triage_sinifi` ya da `triage{sinif, alt_tur}`); yoksa alan eklenmez. */
function triageOzeti(t: Ham): Pick<TestSonucu, "triage_sinifi" | "triage_alt_tur"> {
  const tr = nesne(ilk(t, "triage", "failure"));
  const ham = metin(ilk(t, "triage_sinifi", "sinif") ?? ilk(tr, "sinif", "class")).toLowerCase();
  if (!ham) return {};
  const [kok, alt] = ham.split("/", 2);
  return {
    triage_sinifi: (TRIAGE_SINIFLARI.has(kok) ? kok : "unknown") as TestSonucu["triage_sinifi"],
    triage_alt_tur: metinYaDaNull(ilk(t, "triage_alt_tur") ?? ilk(tr, "alt_tur")) ?? (alt || null),
  };
}

export function testSonucuUyarla(t: Ham): TestSonucu {
  const ekler = dizi(t.ekler).map((e) => ({
    ad: metin(ilk(e, "ad", "name"), "ek"),
    tur: metinYaDaNull(ilk(e, "tur", "contentType", "content_type")),
    url: adresUyarla(e.url),
  }));
  return {
    ...(ekler.length ? { ekler } : {}),
    id: kimlik(t.id),
    test_adi: metin(t.test_adi),
    durum: testSonucDurumu(ilk(t, "durum", "sonuc", "status")),
    sure_ms: sayi(ilk(t, "sure_ms", "duration_ms")),
    retry: sayi(t.retry),
    hata_mesaji: metinYaDaNull(t.hata_mesaji),
    failure_id: metinYaDaNull(kimlik(t.failure_id ?? nesne(t.triage).failure_id ?? nesne(t.triage).id)),
    ...triageOzeti(t),
    case_id: metinYaDaNull(kimlik(ilk(t, "case_id", "test_case_id"))),
  };
}

/**
 * JUnit XML bağlantısı: core `junit_url` gönderirse o; göndermiyorsa yerel test-runner düzeninde
 * (`src/e2e/results/{junit.xml,html/}`) HTML raporunun kardeşi olarak türetilir.
 */
function junitAdresi(k: Ham, art: Ham): string | null {
  const acik = adresUyarla(ilk(k, "junit_url") ?? ilk(art, "junit_url"));
  if (acik) return acik;
  const rapor = metin(ilk(k, "rapor_url"));
  const raporlar = nesne(k.raporlar);
  if (raporlar.junit === false) return null;
  const m = /^(\/api\/artifacts\/runs\/[^/]+\/(?:[^/]+\/)*results)\/html\/index\.html$/.exec(rapor);
  return m ? `${m[1]}/junit.xml` : null;
}

export function kosuUyarla(k: Ham): Kosu {
  const art = nesne(ilk(k, "artefaktlar", "artifacts"));
  const ortam = nesne(k.ortam);
  const saglik = nesne(ilk(k, "saglik") ?? art.saglik);
  const sonuclar = dizi(k.sonuclar).map(testSonucuUyarla);
  const say = (alan: string, fn: (t: TestSonucu) => boolean) => sayiYaDaNull(k[alan]) ?? sonuclar.filter(fn).length;
  const tetik = metin(k.tetik) as Tetik;
  const kaynak = metin(k.kaynak, "local") as KosuKaynagi;
  const durum = metin(ilk(k, "durum", "sonuc", "status"), "queued") as Kosu["durum"];
  const bc = ilk(k, "break_campaign", "kirma");
  const ortamKirma = ilk(ortam, "BREAK_CAMPAIGN", "break_campaign");
  return {
    id: kimlik(k.id),
    tetik: TETIKLER.has(tetik) ? tetik : "manual",
    kaynak: KAYNAKLAR.has(kaynak) ? kaynak : "local",
    commit: metin(k.commit).slice(0, 12),
    pr_no: sayiYaDaNull(k.pr_no),
    durum: KOSU_DURUMLARI.has(durum) ? durum : "error",
    baslangic: metin(ilk(k, "baslangic", "baslama", "olusturma")),
    sure_ms: sayiYaDaNull(ilk(k, "sure_ms", "duration_ms")),
    toplam: say("toplam", () => true),
    gecen: say("gecen", (t) => t.durum === "passed" || t.durum === "flaky"),
    basarisiz: say("basarisiz", (t) => t.durum === "failed"),
    flaky: say("flaky", (t) => t.durum === "flaky"),
    atlanan: say("atlanan", (t) => t.durum === "skipped"),
    allure_url: adresUyarla(ilk(k, "allure_url") ?? ilk(art, "allure_url", "allure")),
    allure_sonuclari_url: adresUyarla(ilk(k, "allure_sonuclari_url")),
    rapor_url: adresUyarla(ilk(k, "rapor_url", "html_url", "playwright_report_url") ?? ilk(art, "rapor_url", "html_url", "html", "report")),
    junit_url: junitAdresi(k, art),
    sauce_url: adresUyarla(ilk(k, "sauce_url") ?? ilk(art, "sauce_url", "sauce")),
    ci_url: adresUyarla(ilk(k, "ci_url", "github_url") ?? ilk(art, "ci_url", "github")),
    break_campaign: bc === true || ortamKirma === true || ortamKirma === "1",
    script_id: metinYaDaNull(kimlik(k.script_id)),
    saglik_hatasi:
      metinYaDaNull(k.saglik_hatasi) ?? (saglik.ok === false ? metin(saglik.hata, "Koşu öncesi sağlık yoklaması başarısız.") : null),
  };
}

function kosuHatalari(x: unknown): KosuDetay["hatalar"] {
  if (!Array.isArray(x)) return undefined;
  return dizi(x)
    .map((h) => {
      const ham = metin(ilk(h, "sinif", "class")).toLowerCase();
      const [kok, alt] = ham.split("/", 2);
      return {
        id: kimlik(ilk(h, "id", "failure_id")),
        test_adi: metin(h.test_adi),
        sinif: ham ? ((TRIAGE_SINIFLARI.has(kok) ? kok : "unknown") as NonNullable<KosuDetay["hatalar"]>[number]["sinif"]) : null,
        alt_tur: metinYaDaNull(h.alt_tur) ?? (alt || null),
        ozet: metinYaDaNull(ilk(h, "ozet", "oneri_ozeti")),
      };
    })
    .filter((h) => h.id !== "");
}

export function kosuDetayUyarla(k: Ham): KosuDetay {
  const hatalar = kosuHatalari(ilk(k, "hatalar", "failures"));
  return {
    ...kosuUyarla(k),
    ...(hatalar ? { hatalar } : {}),
    sonuclar: dizi(k.sonuclar).map(testSonucuUyarla),
    log_url: adresUyarla(k.log_url),
    hata: metinYaDaNull(k.hata),
    uyarilar: dizgeler(k.uyarilar),
  };
}

// ------------------------------------------------------------------ Kontrol Kulesi

const KPI_ANAHTARLARI: KpiAnahtari[] = [
  "gecme_orani",
  "flaky",
  "karne",
  "kabul_orani",
  "script_ilk_review",
  "hazirlik_suresi",
  "manuel_baz",
  "maliyet",
  "a11y",
  "son_kosular",
];

function kaynaklarUyarla(x: unknown): KontrolKulesi["kaynaklar"] {
  const k = nesne(x);
  const sonuc: KontrolKulesi["kaynaklar"] = {};
  for (const a of KPI_ANAHTARLARI) {
    const v = k[a];
    const m = typeof v === "string" ? v : nesneMi(v) ? metin(ilk(v, "kaynak", "aciklama")) : "";
    if (m) sonuc[a] = m;
  }
  return sonuc;
}

export function kontrolKulesiUyarla(govde: unknown): KontrolKulesi {
  const g = nesne(govde);
  const go = g.gecme_orani;
  const goN = nesne(go);
  const ai = nesne(ilk(g, "ai_katkisi", "ai"));
  const a11y = ilk(g, "a11y", "erisilebilirlik");
  const a = nesneMi(a11y) ? a11y : null;
  return {
    son_kosular: dizi(g.son_kosular).map(kosuUyarla),
    gecme_orani: {
      oran: typeof go === "number" ? go : sayiYaDaNull(goN.oran),
      toplam: sayi(goN.toplam),
      gecen: sayi(goN.gecen),
      donem_gun: sayiYaDaNull(goN.donem_gun),
      son_n: sayiYaDaNull(goN.son_n),
      // core: son_n koşu bazında; test alt nesnesi test bazında. Eski/örnek şekil test bazında.
      birim: goN.birim === "test" || goN.birim === "kosu" ? goN.birim : typeof goN.son_n === "number" || nesneMi(goN.test) ? "kosu" : "test",
      test: nesneMi(goN.test) ? { oran: sayiYaDaNull(goN.test.oran), toplam: sayi(goN.test.toplam), gecen: sayi(goN.test.gecen) } : null,
    },
    gecme_hedefi: sayiYaDaNull(g.gecme_hedefi),
    gunluk_gecme: dizi(g.gunluk_gecme).map((x) => ({ tarih: metin(x.tarih), oran: sayi(x.oran), kosu: sayi(x.kosu) })),
    flaky: dizi(g.flaky).map((f) => ({
      test_adi: metin(f.test_adi),
      neden: f.neden === "same_commit" ? "same_commit" : "retry",
      sayi: sayi(f.sayi, 1),
      son_gorulme: metinYaDaNull(f.son_gorulme),
    })),
    karne: dizi(g.karne).map((s) => {
      const son = metin(s.son_sonuc);
      return {
        story_key: metin(ilk(s, "story_key", "jira_key")),
        baslik: metin(s.baslik),
        alan: metinYaDaNull(s.alan),
        case_sayisi: sayi(s.case_sayisi),
        otomasyon_kapsami: sayiYaDaNull(s.otomasyon_kapsami),
        son_sonuc: son === "passed" || son === "failed" ? son : "none",
        acik_bug: sayi(s.acik_bug),
        acik_defect_adayi: sayi(s.acik_defect_adayi),
      };
    }),
    ai_katkisi: {
      kabul_orani: sayiYaDaNull(ai.kabul_orani),
      kabul_hedefi: sayi(ai.kabul_hedefi, 0.7),
      script_ilk_review: sayiYaDaNull(ai.script_ilk_review),
      script_hedefi: sayi(ai.script_hedefi, 0.6),
      pass_at_1: sayiYaDaNull(ai.pass_at_1),
      duzeltme_sonrasi: sayiYaDaNull(ai.duzeltme_sonrasi),
      ort_ai_sure_ms: sayiYaDaNull(ai.ort_ai_sure_ms),
      ort_review_sure_ms: sayiYaDaNull(ai.ort_review_sure_ms),
      manuel_baz_ms: sayiYaDaNull(ai.manuel_baz_ms),
      maliyet_usd_toplam: sayiYaDaNull(ai.maliyet_usd_toplam),
      maliyet_usd_bugun: sayiYaDaNull(ai.maliyet_usd_bugun),
      gunluk_butce_usd: sayiYaDaNull(ai.gunluk_butce_usd),
      cagri_sayisi: sayiYaDaNull(ai.cagri_sayisi),
      replay_cagri: sayiYaDaNull(ai.replay_cagri),
    },
    a11y:
      a && typeof a.ihlal === "number"
        ? {
            ihlal: sayi(a.ihlal),
            kritik: sayi(a.kritik),
            son_tarama: metinYaDaNull(a.son_tarama),
            sayfalar: dizi(a.sayfalar).map((p) => ({ yol: metin(p.yol), ihlal: sayi(p.ihlal), kritik: sayi(p.kritik) })),
          }
        : null,
    kaynaklar: kaynaklarUyarla(g.kaynaklar),
    uyarilar: dizgeler(g.uyarilar),
  };
}
