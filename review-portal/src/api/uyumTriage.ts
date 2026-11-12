// Faz 4 uçlarının (triage `GET /failures/{id}`, bug taslakları `GET /bug-drafts[/{id}]`) core
// yanıtlarını portal türlerine uyarlayan saf dönüştürücüler.
//
// Triage ve bugs şeritleri paralel geliştirildiği için yanıt hem portal şekliyle (types.ts) hem de
// veritabanı/araç adlarıyla (`sinyaller`, `signals`, `kanit`, `evidence`, `old_test_id`, `likelihood`,
// `rationale`, toolchain `/locator-probe` ve test-runner `saglik`) kabul edilir. Bilinmeyen alan
// `null` kalır: portal "ölçülmedi/yok" yazar, değer uydurmaz. Mock arka uç portal şeklini döndürür;
// aynı dönüştürücüden geçer.

import type {
  BugTaslagi,
  BugTaslakIcerik,
  Degerlendirme,
  EslesenSinyal,
  HataAnalizi,
  HataSinifi,
  LocatorOnarimi,
  LocatorProbeSonucu,
  MukerrerAday,
  MukerrerArama,
  OnarimDurumu,
  SaglikSonucu,
  SaglikUcu,
  TriageKaniti,
} from "./types";
import { dizgeler, ilk, jiraKayitAdresi, kimlik, metin, metinYaDaNull, modUyarla, nesneMi, sayiYaDaNull, type Ham } from "./uyum";
import { adresUyarla, prUyarla } from "./uyumDemoB";
import { platformUyarla } from "../lib/platform";
import { triageCaseBagi } from "./uyumKalite";

const nesne = (x: unknown): Ham => (nesneMi(x) ? x : {});
const dizi = (x: unknown): unknown[] => (Array.isArray(x) ? x : []);
const boolYaDaNull = (x: unknown): boolean | null => (typeof x === "boolean" ? x : null);

// ------------------------------------------------------------------ Değerlendirme

const DEGERLENDIRME = new Set(["pending", "evaluated", "waived", "stale", "missing"]);

/** `degerlendirme: {durum, etiket}` ya da düz dizge (`"pending"`) ya da `evaluation_status`. */
export function degerlendirmeUyarla(x: unknown): Degerlendirme | null {
  if (typeof x === "string") return DEGERLENDIRME.has(x) ? { durum: x as Degerlendirme["durum"], etiket: null } : null;
  if (!nesneMi(x)) return null;
  const d = metin(ilk(x, "durum", "status"));
  if (!DEGERLENDIRME.has(d)) return null;
  return { durum: d as Degerlendirme["durum"], etiket: metinYaDaNull(ilk(x, "etiket", "label")) };
}

function degerlendirmeBul(o: Ham): Degerlendirme | null {
  return degerlendirmeUyarla(ilk(o, "degerlendirme", "canli_degerlendirme", "evaluation", "evaluation_status", "degerlendirme_durumu"));
}

// ------------------------------------------------------------------ Triage

const SINIF_ESLEME: Record<string, HataSinifi> = {
  environment: "environment",
  ortam: "environment",
  flaky: "flaky",
  kararsiz: "flaky",
  test_maintenance: "test_maintenance",
  maintenance: "test_maintenance",
  bakim: "test_maintenance",
  product_defect: "product_defect",
  defect: "product_defect",
  urun_hatasi: "product_defect",
  test_data: "test_data",
  veri: "test_data",
  unknown: "unknown",
  bilinmiyor: "unknown",
};

/** "test_maintenance/locator" gibi birleşik değerleri sınıf + alt tür olarak ayırır. */
export function sinifUyarla(x: unknown, altTur: unknown = null): { sinif: HataSinifi; alt_tur: string | null } {
  const ham = metin(x).trim().toLowerCase();
  const [kok, alt] = ham.split("/", 2);
  return { sinif: SINIF_ESLEME[kok] ?? "unknown", alt_tur: metinYaDaNull(altTur) ?? (alt || null) };
}

function sinyalUyarla(x: unknown, i: number): EslesenSinyal | null {
  if (typeof x === "string") return x ? { kod: `s${i + 1}`, aciklama: x, kaynak: "", kanit: null } : null;
  if (!nesneMi(x)) return null;
  const aciklama = metin(ilk(x, "aciklama", "description", "mesaj", "message", "ad"));
  const kod = metin(ilk(x, "kod", "code", "id", "sinyal", "signal"), `s${i + 1}`);
  if (!aciklama && !kod) return null;
  const k = ilk(x, "kanit", "evidence", "deger", "value");
  return {
    kod,
    aciklama: aciklama || kod,
    kaynak: metin(ilk(x, "kaynak", "source")),
    kanit: typeof k === "string" ? k || null : nesneMi(k) || Array.isArray(k) ? JSON.stringify(k) : typeof k === "number" ? String(k) : null,
  };
}

function saglikUcuUyarla(x: unknown): SaglikUcu | null {
  if (!nesneMi(x)) return null;
  return {
    url: metinYaDaNull(x.url),
    status: sayiYaDaNull(x.status),
    ms: sayiYaDaNull(x.ms),
    hata: metinYaDaNull(x.hata),
  };
}

export function saglikUyarla(x: unknown): SaglikSonucu | null {
  if (!nesneMi(x)) return null;
  return {
    ok: boolYaDaNull(x.ok),
    zaman: metinYaDaNull(x.zaman),
    web: saglikUcuUyarla(x.web),
    api: saglikUcuUyarla(x.api),
    hata: metinYaDaNull(x.hata),
  };
}

const SHA_ESLESMESI = new Set(["eslesiyor", "farkli", "dogrulanamadi"]);

export function probeUyarla(x: unknown): LocatorProbeSonucu | null {
  if (!nesneMi(x)) return null;
  const sha = metin(x.sha_eslesmesi);
  return {
    rol: metinYaDaNull(ilk(x, "rol", "role")),
    ad: metinYaDaNull(ilk(x, "ad", "name")),
    scope_test_id: metinYaDaNull(x.scope_test_id),
    matches: sayiYaDaNull(ilk(x, "matches", "eslesme")),
    test_id: metinYaDaNull(ilk(x, "test_id", "testId")),
    olculen: metinYaDaNull(x.olculen),
    uygulama_sha: metinYaDaNull(x.uygulama_sha),
    sha_eslesmesi: SHA_ESLESMESI.has(sha) ? (sha as LocatorProbeSonucu["sha_eslesmesi"]) : null,
    uyari: metinYaDaNull(x.uyari),
    oneri_uretilebilir: boolYaDaNull(x.oneri_uretilebilir),
  };
}

function ariaMetni(x: unknown): string | null {
  if (typeof x === "string") return x || null;
  if (Array.isArray(x)) return dizgeler(x).join("\n") || null;
  return null;
}

/** Triage kanıtı: `kanit`/`evidence` nesnesi ya da üst düzey alanlar. Hiç parça yoksa null. */
export function triageKanitiUyarla(h: Ham): TriageKaniti | null {
  const k = nesne(ilk(h, "kanit", "evidence"));
  const al = (...adlar: string[]) => ilk(k, ...adlar) ?? ilk(h, ...adlar);
  const sonuc: TriageKaniti = {
    hata_mesaji: metinYaDaNull(al("hata_mesaji", "error_message", "message")),
    beklenen: metinYaDaNull(al("beklenen", "expected")),
    gerceklesen: metinYaDaNull(al("gerceklesen", "received", "actual")),
    konum: metinYaDaNull(al("konum", "location")) ?? metinYaDaNull(al("adim", "step")),
    aria_snippet: ariaMetni(al("aria_snippet", "aria_snapshot", "aria")),
    locator_probe: probeUyarla(al("locator_probe", "probe")),
    saglik: saglikUyarla(al("saglik", "health")),
  };
  return Object.values(sonuc).some((v) => v !== null) ? sonuc : null;
}

const ONARIM_DURUMU: Record<string, OnarimDurumu> = {
  proposed: "proposed",
  onerildi: "proposed",
  draft: "proposed",
  checking: "checking",
  kontrol: "checking",
  running: "checking",
  queued: "checking",
  pr_open: "pr_open",
  open: "pr_open",
  merged: "merged",
  rejected: "rejected",
  closed: "rejected",
  dismissed: "rejected",
  failed: "failed",
  error: "failed",
};

const KONTROL_SONUCU: Record<string, "passed" | "failed" | "error" | "pending"> = {
  passed: "passed",
  ok: "passed",
  success: "passed",
  failed: "failed",
  failure: "failed",
  red: "failed",
  error: "error",
  pending: "pending",
  running: "pending",
  queued: "pending",
};

function astGuardUyarla(x: unknown): LocatorOnarimi["ast_guard"] {
  if (typeof x === "boolean") return { ok: x, ihlaller: [] };
  if (!nesneMi(x)) return null;
  const ihlaller = dizi(ilk(x, "ihlaller", "violations")).map((v) =>
    typeof v === "string" ? v : nesneMi(v) ? metin(ilk(v, "mesaj", "message", "kural", "rule", "code"), JSON.stringify(v)) : String(v),
  );
  return { ok: boolYaDaNull(x.ok), ihlaller };
}

function yerelKontrolUyarla(x: unknown): LocatorOnarimi["yerel_kontrol"] {
  if (!nesneMi(x)) return null;
  const s = metin(ilk(x, "sonuc", "status", "durum")).toLowerCase();
  return {
    sonuc: KONTROL_SONUCU[s] ?? (typeof x.ok === "boolean" ? (x.ok ? "passed" : "failed") : null),
    run_id: metinYaDaNull(kimlik(x.run_id)),
    gecen: sayiYaDaNull(x.gecen),
    toplam: sayiYaDaNull(x.toplam),
  };
}

function etkilenenUyarla(x: unknown): NonNullable<LocatorOnarimi["etkilenen_testler"]> {
  return dizi(x)
    .map((t) => {
      if (typeof t === "string") return { test_adi: t, durum: null };
      if (!nesneMi(t)) return null;
      const d = KONTROL_SONUCU[metin(ilk(t, "durum", "sonuc", "status")).toLowerCase()];
      return {
        test_adi: metin(ilk(t, "test_adi", "ad", "title", "dosya", "file")),
        durum: d === "error" ? "failed" : (d ?? null),
      };
    })
    .filter((t): t is NonNullable<typeof t> => t !== null && t.test_adi !== "");
}

/**
 * Repair şeridinin aria kanıt kaynakları (`repair/service.py` `_aria_kaniti`) → onarım hattındaki
 * aşama etiketi. Etiket neyin gerçekten denetlendiğini söyler: aria dosyası yoksa "aria" denmez.
 */
export const ARIA_KAYNAKLARI: Record<string, string> = {
  son_yesil_kosu: "Son yeşil koşunun aria snapshot'ıyla rol + ad doğrulaması",
  triage_onerisi: "Son yeşil koşunun aria snapshot'ıyla (triage kanıtı) rol + ad doğrulaması",
  ajan_snapshot: "Ajan aria snapshot'ıyla rol + ad doğrulaması (son yeşil koşuda aria dosyası yok)",
  sozlesme_testi: "Son yeşil koşuda locators sözleşme testi (aria dosyası yok)",
};

/** `aria_dogrulama{eslesti, aciklama}` ya da repair şeridinin `aria{gecerli, kaynak, neden}` bloğu. */
function ariaDogrulamaUyarla(x: unknown, sonYesil: string | null = null): LocatorOnarimi["aria_dogrulama"] {
  if (typeof x === "boolean") return { eslesti: x, aciklama: null, run_id: sonYesil, kaynak: null };
  if (!nesneMi(x) || Object.keys(x).length === 0) return null;
  const kaynak = metinYaDaNull(x.kaynak);
  const neden = metinYaDaNull(ilk(x, "aciklama", "mesaj", "detail", "neden"));
  // Bilinen kaynak adı aşama etiketine taşınır (ham "sozlesme_testi:" öneki metinde kalmaz).
  const bilinen = kaynak !== null && kaynak in ARIA_KAYNAKLARI;
  return {
    eslesti: boolYaDaNull(ilk(x, "eslesti", "ok", "matched", "gecerli")),
    aciklama: neden ? (kaynak && !bilinen ? `${kaynak}: ${neden}` : neden) : bilinen ? null : kaynak,
    run_id: metinYaDaNull(kimlik(ilk(x, "run_id", "son_yesil_run_id"))) ?? sonYesil,
    kaynak,
  };
}

/** Repair şeridinin script durumu (script makinesi) → onarım hattı durumu. */
const SCRIPT_ONARIM: Record<string, OnarimDurumu> = {
  pending: "checking",
  verifying: "checking",
  checking: "checking",
  blocked: "failed",
  failed: "failed",
  pr_open: "pr_open",
  merged: "merged",
  closed: "rejected",
};

function engelMetni(x: unknown): string | null {
  if (typeof x === "string") return x || null;
  if (!nesneMi(x)) return null;
  const neden = metinYaDaNull(ilk(x, "neden", "mesaj"));
  const adim = metinYaDaNull(x.adim);
  return neden ? (adim ? `${adim}: ${neden}` : neden) : null;
}

export function onarimUyarla(o: Ham): LocatorOnarimi {
  const prHam = ilk(o, "pr", "pull_request");
  const scriptDurumu = metin(o.script_durumu).toLowerCase();
  const durum = SCRIPT_ONARIM[scriptDurumu] ?? metin(ilk(o, "durum", "status")).toLowerCase();
  const pr = nesneMi(prHam) ? prUyarla(prHam) : typeof o.pr_no === "number" ? prUyarla({ number: o.pr_no, branch: o.branch, head_sha: o.head_sha }) : null;
  return {
    tur: "locator_fix",
    dosya: metin(ilk(o, "dosya", "file", "path")),
    anahtar: metin(ilk(o, "anahtar", "key", "locator_key")),
    eski_test_id: metinYaDaNull(ilk(o, "eski_test_id", "old_test_id", "old_testid", "eski")),
    yeni_test_id: metinYaDaNull(ilk(o, "yeni_test_id", "new_test_id", "new_testid", "yeni")),
    rol: metin(ilk(o, "rol", "role")),
    ad: metin(ilk(o, "ad", "name")),
    within: metinYaDaNull(o.within),
    scope_test_id: metinYaDaNull(o.scope_test_id),
    dogrulama: dizgeler(ilk(o, "dogrulama", "kontroller", "checks")),
    // Repair şeridinin bloğu (`script_durumu`/`son_kayit`) kendi kontrollerini taşır; yoksa triage gözlemleri.
    dogrulama_kaynagi: o.script_durumu !== undefined || o.son_kayit !== undefined ? "onarim" : "triage",
    durum: ONARIM_DURUMU[durum] ?? (pr ? (pr.durum === "merged" ? "merged" : pr.durum === "closed" ? "rejected" : "pr_open") : "proposed"),
    pr,
    aria_dogrulama: ariaDogrulamaUyarla(ilk(o, "aria_dogrulama", "aria_validation", "son_yesil_dogrulama", "aria"), metinYaDaNull(kimlik(o.son_yesil_run_id))),
    ast_guard: astGuardUyarla(ilk(o, "ast_guard", "ast_korumasi")),
    yerel_kontrol: yerelKontrolUyarla(ilk(o, "yerel_kontrol", "local_check")),
    etkilenen_testler: etkilenenUyarla(ilk(o, "etkilenen_testler", "affected_tests")),
    degisen_dosyalar: dizgeler(ilk(o, "degisen_dosyalar", "changed_files")),
    yama: metinYaDaNull(ilk(o, "yama", "diff", "patch")),
    neden: metinYaDaNull(ilk(o, "neden", "hata", "reason")) ?? engelMetni(o.engel),
    // 009: uygulama testinin kimlik onarımı (hata anı sayfa kaynağı); rol/ad/url_path boş gelir.
    kaynak: metinYaDaNull(o.kaynak),
    platform: platformUyarla(o.platform),
  };
}

function oneriUyarla(h: Ham): HataAnalizi["oneri"] {
  const o = ilk(h, "oneri", "onarim", "repair", "locator_fix");
  if (nesneMi(o)) {
    const tur = metin(o.tur);
    if (tur === "bug_draft" || (!tur && o.bug_draft_id)) {
      const id = kimlik(o.bug_draft_id);
      return id ? { tur: "bug_draft", bug_draft_id: id } : null;
    }
    if (tur === "locator_fix" || tur === "locator_repair" || "eski_test_id" in o || "old_test_id" in o || "old_testid" in o) return onarimUyarla(o);
  }
  const bug = kimlik(ilk(h, "bug_draft_id"));
  return bug ? { tur: "bug_draft", bug_draft_id: bug } : null;
}

function kanitLinkleri(h: Ham): HataAnalizi["kanit_linkleri"] {
  return dizi(ilk(h, "kanit_linkleri", "linkler", "links"))
    .map((l) => {
      if (!nesneMi(l)) return null;
      const etiket = metin(ilk(l, "etiket", "label", "ad"));
      if (!etiket) return null;
      const tur = metinYaDaNull(ilk(l, "tur", "ad", "kind"));
      return { etiket, url: adresUyarla(l.url), ...(tur ? { tur } : {}) };
    })
    .filter((l): l is NonNullable<typeof l> => l !== null);
}

/** Tekrar/deneme durumları ("failed ×3") ve kanıt uyarıları. */
function kanitEkleri(h: Ham): Pick<TriageKaniti, "tekrarlar" | "uyarilar"> {
  const k = nesne(ilk(h, "kanit", "evidence"));
  const tekrar = dizgeler(ilk(k, "tekrar_durumlari", "deneme_durumlari"));
  return { tekrarlar: tekrar, uyarilar: dizgeler(k.uyarilar) };
}

export function hataAnaliziUyarla(h: Ham): HataAnalizi {
  const { sinif, alt_tur } = sinifUyarla(ilk(h, "sinif", "class", "classification"), ilk(h, "alt_tur", "subclass", "sub_type"));
  const kaynak = metin(ilk(h, "karar_kaynagi", "kaynak", "source")).toLowerCase();
  const llm = kaynak === "llm" || kaynak === "model" || kaynak === "ai";
  const temelKanit = triageKanitiUyarla(h);
  const ekler = kanitEkleri(h);
  const kanit = temelKanit ? { ...temelKanit, ...ekler } : null;
  return {
    id: kimlik(h.id),
    run_id: kimlik(h.run_id),
    test_adi: metin(h.test_adi),
    hata_imzasi: metin(ilk(h, "hata_imzasi", "imza", "signature")),
    hata_mesaji: metin(ilk(h, "hata_mesaji", "error_message"), kanit?.hata_mesaji ?? ""),
    sinif,
    alt_tur,
    eslesen_sinyaller: dizi(ilk(h, "eslesen_sinyaller", "sinyaller", "signals", "matched_signals"))
      .map(sinyalUyarla)
      .filter((s): s is EslesenSinyal => s !== null),
    karar_kaynagi: llm ? "llm" : "rule",
    kural: metinYaDaNull(ilk(h, "kural", "rule", "eslesen_kural")),
    gerekce: metinYaDaNull(h.gerekce),
    llm_yorumu: metinYaDaNull(ilk(h, "llm_yorumu", "llm_gerekce", "rationale")),
    oneri: oneriUyarla(h),
    oneri_yok_nedeni: metinYaDaNull(ilk(h, "oneri_yok_nedeni", "onarim_yok_nedeni", "no_repair_reason")),
    kanit,
    kanit_linkleri: kanitLinkleri(h),
    mode: modUyarla(ilk(h, "mode", "uretim_modu")),
    degerlendirme: degerlendirmeBul(h),
    zaman: metin(ilk(h, "zaman", "olusturma", "created_at")),
    script_id: metinYaDaNull(kimlik(h.script_id)),
    platform: platformUyarla(h.platform) ?? platformUyarla(nesne(ilk(h, "oneri", "onarim")).platform),
    // 012 Ş7: case bağı (alt tür `beklenti` için "Case düzeltilmeli").
    ...triageCaseBagi(h),
  };
}

// ------------------------------------------------------------------ Bug taslakları

const OLASILIK = new Set(["high", "medium", "low"]);
const SEVERITY = new Set(["critical", "major", "minor", "trivial"]);
const KANIT_TURU = new Set(["sauce_video", "allure", "trace", "screenshot", "log", "code", "data"]);
const KAYNAKLAR = new Set(["triage", "consistency", "a11y"]);
const DURUMLAR = new Set(["draft", "approved", "dismissed", "published"]);
const KARARLAR = new Set(["new", "link", "dismiss"]);

function kanitAdresi(x: unknown): string | null {
  const a = metinYaDaNull(x);
  if (a?.startsWith("#")) return a;
  return adresUyarla(a);
}

export function bugIcerikUyarla(x: unknown): BugTaslakIcerik {
  const i = nesne(x);
  const sev = metin(i.severity_suggestion, "major");
  const steps = dizi(i.steps)
    .map((s) => (typeof s === "string" ? s : nesneMi(s) ? metin(ilk(s, "action", "metin", "adim")) : ""))
    .filter(Boolean);
  return {
    ...(typeof i.uretim === "string" ? { uretim: i.uretim } : {}),
    summary: metin(i.summary),
    steps,
    expected: metin(i.expected),
    actual: metin(i.actual),
    environment: metin(i.environment),
    evidence: dizi(i.evidence)
      .map((e) => {
        if (!nesneMi(e)) return null;
        // Core bug şeması `{ref, kind}` taşır (ref: /api/artifacts/... bağlantısı ya da
        // `dosya:satır` gibi düz kanıt referansı); eski/portal biçimi `{tur, url, etiket}`.
        const tur = metin(ilk(e, "tur", "type", "kind"), "data");
        const ref = metinYaDaNull(e.ref);
        const url = kanitAdresi(e.url ?? (ref && /^(\/api\/|https?:\/\/)/.test(ref) ? ref : null));
        const dosya = url ? decodeURIComponent(url.split(/[?#]/)[0].split("/").pop() ?? "") : "";
        return {
          tur: (KANIT_TURU.has(tur) ? tur : "data") as BugTaslakIcerik["evidence"][number]["tur"],
          url,
          etiket: metin(ilk(e, "etiket", "label"), url ? `${tur}: ${dosya || url}` : (ref ?? tur)),
          ...(ref ? { ref } : {}),
        };
      })
      .filter((e): e is NonNullable<typeof e> => e !== null),
    story_key: metinYaDaNull(i.story_key),
    test_case_key: metinYaDaNull(i.test_case_key),
    severity_suggestion: (SEVERITY.has(sev) ? sev : "major") as BugTaslakIcerik["severity_suggestion"],
    labels: dizgeler(i.labels),
  };
}

export function mukerrerAdayUyarla(x: unknown, browseKoku: string | null): MukerrerAday | null {
  if (!nesneMi(x)) return null;
  const key = metin(ilk(x, "key", "anahtar", "jira_key"));
  if (!key) return null;
  const ol = metin(ilk(x, "olasilik", "likelihood")).toLowerCase();
  return {
    key,
    summary: metin(ilk(x, "summary", "ozet", "baslik")),
    durum: metin(ilk(x, "durum", "status")),
    gerekce: metin(ilk(x, "gerekce", "rationale", "reason", "neden")),
    sinyaller: dizgeler(ilk(x, "sinyaller", "signals")),
    olasilik: OLASILIK.has(ol) ? (ol as MukerrerAday["olasilik"]) : null,
    sira: sayiYaDaNull(ilk(x, "sira", "rank")),
    url: jiraKayitAdresi(key, { url: metinYaDaNull(x.url), browseKoku }),
  };
}

const ARAMA_DURUMU: Record<string, MukerrerArama["durum"]> = {
  yapildi: "yapildi",
  done: "yapildi",
  completed: "yapildi",
  yapilmadi: "yapilmadi",
  not_run: "yapilmadi",
  none: "yapilmadi",
  suruyor: "suruyor",
  running: "suruyor",
  pending: "suruyor",
  queued: "suruyor",
  basarisiz: "basarisiz",
  failed: "basarisiz",
  error: "basarisiz",
};

export function mukerrerAramaUyarla(x: unknown): MukerrerArama | null {
  if (!nesneMi(x)) return null;
  const d = ARAMA_DURUMU[metin(ilk(x, "durum", "status")).toLowerCase()];
  if (!d) return null;
  const oneri = metin(ilk(x, "oneri", "recommendation"));
  return {
    durum: d,
    jql: metinYaDaNull(x.jql),
    oneri: oneri === "new" || oneri === "link" ? oneri : null,
    oneri_link_key: metinYaDaNull(ilk(x, "oneri_link_key", "link_key")),
    neden: metinYaDaNull(x.neden),
    mode: modUyarla(ilk(x, "mode", "uretim_modu")),
    degerlendirme: degerlendirmeBul(x),
    hata: metinYaDaNull(ilk(x, "hata", "error")),
    ai_onerisi_yok: metinYaDaNull(x.ai_onerisi_yok),
  };
}

/**
 * Bugs şeridinin Faz 4 alanlarından arama durumu: `hazirlik{durum: kuyrukta|hazirlaniyor|hazir|basarisiz}`,
 * `arama{durum: yapildi|atlandi|hata, neden, hata}`, `jql`, `oneri{recommendation, link_key, neden}`,
 * `dup_mode` (sıralamanın üretim modu). Hiçbiri yoksa null.
 */
export function faz4AramaUyarla(b: Ham): MukerrerArama | null {
  const hz = nesne(b.hazirlik);
  const ar = nesne(b.arama);
  const on = nesne(b.oneri);
  const hd = metin(hz.durum);
  const ad = metin(ar.durum);
  if (!hd && !ad && b.jql === undefined && b.mukerrer_aramasi_yapildi === undefined) return null;
  const durum: MukerrerArama["durum"] =
    hd === "kuyrukta" || hd === "hazirlaniyor"
      ? "suruyor"
      : ad === "yapildi" || b.mukerrer_aramasi_yapildi === true
        ? "yapildi"
        : ad === "hata" || hd === "basarisiz"
          ? "basarisiz"
          : "yapilmadi";
  const rec = metin(ilk(on, "recommendation", "oneri"));
  const sirasiz = siralamaYapilamadi(b, on);
  const nedenHam = metinYaDaNull(on.neden);
  return {
    durum,
    jql: metinYaDaNull(b.jql),
    // Model adayları karşılaştırmadıysa "yeni kayıt (adaylar aynı hata değil)" bir AI kararı değildir.
    oneri: sirasiz ? null : rec === "new" || rec === "link" ? rec : null,
    oneri_link_key: sirasiz ? null : metinYaDaNull(on.link_key),
    neden: sirasiz ? null : (nedenHam ?? metinYaDaNull(ar.neden)),
    mode: modUyarla(b.dup_mode) ?? (sirasiz?.replayMiss ? "replay_miss" : null),
    degerlendirme: degerlendirmeUyarla(b.dup_degerlendirme),
    hata: metinYaDaNull(ar.hata) ?? (hd === "basarisiz" ? metinYaDaNull(hz.hata) : null),
    ai_onerisi_yok: sirasiz?.metin ?? null,
  };
}

/**
 * Mükerrer sıralaması yapılamadı mı (core `_sirasiz`: gateway hatası/REPLAY-MISS ya da uydurulan
 * anahtar)? Core tipli neden (`neden_turu: replay_miss|hata`) ya da `recommendation: null` gönderirse
 * o; eski biçimde adayların hiçbiri model çıktısı taşımıyorsa (`ai: false`, gerekçe/olasılık yok)
 * sıralama yok sayılır. Dönen metin Türkçe'dir; Python istisna adı arayüze sızmaz.
 */
export function siralamaYapilamadi(b: Ham, on: Ham): { replayMiss: boolean; metin: string } | null {
  const adaylar = dizi(ilk(b, "mukerrer_adaylari", "candidates", "dup_candidates")).filter(nesneMi);
  if (adaylar.length === 0) return null;
  const tur = metin(ilk(on, "neden_turu", "reason_code", "neden_kodu")).toLowerCase();
  const neden = metin(on.neden);
  const modelCiktisi = adaylar.some(
    (a) => a.ai === true || metin(ilk(a, "rationale", "gerekce")) !== "" || metin(ilk(a, "likelihood", "olasilik")) !== "",
  );
  const recYok = "recommendation" in on && on.recommendation === null;
  if (!tur && modelCiktisi && !recYok) return null;
  const replayMiss = tur === "replay_miss" || metin(b.dup_mode).toLowerCase().replace("-", "_") === "replay_miss" || /replay/i.test(neden);
  if (replayMiss) return { replayMiss, metin: "REPLAY-MISS: kayıtlı sıralama yok" };
  if (tur === "uydurulan_anahtar" || /aramada olmayan anahtar/i.test(neden))
    return { replayMiss, metin: "model aramada olmayan anahtar döndürdü; sıralama kullanılmadı" };
  return { replayMiss, metin: "AI sıralaması yapılamadı" };
}

/** Yayın durumu: `yayin{durum: kuyrukta|tamam|basarisiz|incelenmeli, hata, key}` + karar yanıtının `yayin_sonucu`. */
function yayinUyarla(b: Ham): Pick<BugTaslagi, "yayin_hatasi" | "yayin_suruyor"> {
  const y = nesne(b.yayin);
  const ys = nesne(b.yayin_sonucu);
  const d = metin(y.durum);
  const hata =
    metinYaDaNull(ilk(b, "yayin_hatasi", "publish_error")) ??
    (d === "basarisiz" ? metin(y.hata, "Jira'ya yazılamadı.") : null) ??
    (d === "incelenmeli" ? `Jira'ya yazıldı ama sonuç doğrulanamadı${y.key ? ` (${metin(y.key)})` : ""}; Jira'da kontrol edin.` : null) ??
    (ys.durum === "failed" ? metin(ys.hata, "Jira'ya yazılamadı.") : null);
  return { yayin_hatasi: hata, yayin_suruyor: d === "kuyrukta" || ys.durum === "queued" || ys.durum === "running" };
}

/** `https://…/browse/KEY` adresinden browse kökü. */
function browseKoku(...adresler: unknown[]): string | null {
  for (const a of adresler) {
    const m = typeof a === "string" ? /^(https?:\/\/.+\/browse)\/[^/]+$/.exec(a) : null;
    if (m) return m[1];
  }
  return null;
}

export function bugTaslagiUyarla(b: Ham): BugTaslagi {
  const adayHam = dizi(ilk(b, "mukerrer_adaylari", "candidates", "dup_candidates"));
  const browse =
    metinYaDaNull(ilk(b, "jira_browse_url", "browse_url")) ?? browseKoku(b.jira_url, ...adayHam.map((a) => (nesneMi(a) ? a.url : null)));
  const kaynak = metin(b.kaynak, b.finding_id ? "consistency" : "triage");
  const durum = metin(b.durum, "draft");
  const karar = metin(b.karar);
  const jiraKey = metinYaDaNull(b.jira_key);
  const linkKey = metinYaDaNull(b.link_key);
  const adaylar = adayHam
    .map((x) => mukerrerAdayUyarla(x, browse))
    .filter((x): x is MukerrerAday => x !== null);
  // AI sırası varsa ona göre (1 = en olası); yoksa core'un sırası korunur.
  if (adaylar.some((a) => a.sira != null)) adaylar.sort((a, c) => (a.sira ?? 99) - (c.sira ?? 99));
  return {
    id: kimlik(b.id),
    kaynak: (KAYNAKLAR.has(kaynak) ? kaynak : "triage") as BugTaslagi["kaynak"],
    failure_id: metinYaDaNull(kimlik(b.failure_id)),
    finding_id: metinYaDaNull(kimlik(b.finding_id)),
    icerik: { ...bugIcerikUyarla(b.icerik), ...(typeof b.uretim === "string" && !nesne(b.icerik).uretim ? { uretim: b.uretim } : {}) },
    mukerrer_adaylari: adaylar,
    mukerrer_arama: mukerrerAramaUyarla(ilk(b, "mukerrer_arama", "dup_search")) ?? faz4AramaUyarla(b),
    karar: KARARLAR.has(karar) ? (karar as BugTaslagi["karar"]) : null,
    durum: (DURUMLAR.has(durum) ? durum : "draft") as BugTaslagi["durum"],
    link_key: linkKey,
    icerik_hash: metin(b.icerik_hash),
    onaylayan: metinYaDaNull(b.onaylayan),
    onay_zamani: metinYaDaNull(b.onay_zamani),
    jira_key: jiraKey,
    // Demo sıfırlamasında silinen kayda (core `jira_silindi`) bağlantı kurulmaz.
    jira_url:
      b.jira_silindi === true
        ? null
        : jiraKayitAdresi(karar === "link" ? (linkKey ?? jiraKey) : jiraKey, { url: metinYaDaNull(b.jira_url), browseKoku: browse }),
    jira_silindi: b.jira_silindi === true,
    jira_browse_url: browse,
    ...yayinUyarla(b),
    ret_gerekcesi: metinYaDaNull(b.ret_gerekcesi),
    sonuc_metni: metinYaDaNull(b.sonuc_metni),
    yeniden_acilabilir: b.yeniden_acilabilir === true,
    mode: modUyarla(ilk(b, "mode", "uretim_modu")),
    degerlendirme: degerlendirmeBul(b),
    olusturma: metin(b.olusturma),
  };
}

/**
 * Portal içerik biçimi → core `bug_draft` şeması (`rules/schemas/bug_draft.schema.json`,
 * additionalProperties=false): `uretim` gibi portal/görünüm alanları atılır, kanıt `{ref, kind}`'e döner.
 */
export function bugIcerikCoreBicimi(i: BugTaslakIcerik): Record<string, unknown> {
  return {
    summary: i.summary,
    steps: i.steps,
    expected: i.expected,
    actual: i.actual,
    environment: i.environment,
    evidence: i.evidence
      .map((e) => ({ kind: e.tur, ref: e.ref ?? e.url ?? e.etiket }))
      .filter((e) => Boolean(e.ref)),
    story_key: i.story_key,
    test_case_key: i.test_case_key,
    severity_suggestion: i.severity_suggestion,
    labels: i.labels,
  };
}
