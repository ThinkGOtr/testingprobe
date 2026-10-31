// core-api yanıtlarını portalın türlerine uyarlayan saf dönüştürücüler.
// core-api'nin gerçek şekli (platform şeridi) ile portalın beklediği şekil farklı olduğunda burada
// eşlenir; mock arka uç zaten portal şeklini döndürdüğü için iki şekil de kabul edilir.

import type {
  Bulgu,
  DenetimOlayi,
  DenetimYaniti,
  BulguDurumu,
  BulguKarari,
  BulguTuru,
  CaseDurumu,
  CiktiModu,
  Gereksinim,
  GereksinimDetay,
  GereksinimDurumu,
  KabulKriteri,
  Kanit,
  OnInceleme,
  OnIncelemeSorusu,
  PoCevabi,
  PoDurumu,
  RetNedeni,
  SonKontrol,
  TestAdimi,
  TestCase,
  TestCaseIcerik,
  YayinOnizleme,
  YayinOnizlemeKalemi,
  YayinSonucKalemi,
  YayinSonucu,
  ZincirDogrulama,
} from "./types";

/** core-api GET /audit gövdesi (tp_core.api.routers.audit.AuditOut). */
interface CoreDenetimOlayi {
  id: number | string;
  zaman: string;
  aktor: string;
  eylem: string;
  nesne: string | null;
  ozet: unknown;
  prev_hash: string;
  hash: string;
}

interface CoreDenetimYaniti {
  events: CoreDenetimOlayi[];
  tip_hash: string;
  next_before_id: number | null;
  verify?: {
    ok: boolean;
    count: number;
    tip_hash: string;
    broken_at: number | null;
    reason: string | null;
  } | null;
}

function nesneMi(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}

/** Denetim özeti (jsonb) tabloda tek satır metin olarak gösterilir; boş nesne → "". */
export function ozetMetni(ozet: unknown): string {
  if (ozet === null || ozet === undefined) return "";
  if (typeof ozet === "string") return ozet;
  if (nesneMi(ozet) && Object.keys(ozet).length === 0) return "";
  try {
    return JSON.stringify(ozet);
  } catch {
    return String(ozet);
  }
}

/** GET /audit yanıtını portal şekline çevirir (core-api veya mock şekli). */
export function denetimiUyarla(govde: unknown, simdi: () => Date = () => new Date()): DenetimYaniti {
  if (nesneMi(govde) && Array.isArray(govde.olaylar)) {
    return govde as unknown as DenetimYaniti; // zaten portal şekli (mock)
  }
  if (!nesneMi(govde) || !Array.isArray(govde.events)) {
    throw new Error("Beklenmeyen denetim yanıtı");
  }
  const core = govde as unknown as CoreDenetimYaniti;
  const olaylar: DenetimOlayi[] = core.events.map((e) => ({
    id: String(e.id),
    sira: Number(e.id),
    aktor: e.aktor,
    eylem: e.eylem,
    nesne: e.nesne ?? "",
    ozet: ozetMetni(e.ozet),
    zaman: e.zaman,
    prev_hash: e.prev_hash,
    hash: e.hash,
  }));
  const v = core.verify;
  const dogrulama: ZincirDogrulama | null = v
    ? {
        gecerli: v.ok,
        kontrol_edilen: v.count,
        ilk_kirik_id: v.broken_at === null ? null : String(v.broken_at),
        son_hash: v.tip_hash || null,
        zaman: simdi().toISOString(),
      }
    : null;
  return { olaylar, dogrulama };
}

// ---------------------------------------------------------------------------------------------
// Demo-A uçları (gereksinim, bulgu, case, yayın). Özellik şeritleri yanıtı portal şekliyle
// (types.ts) döndürmelidir; şekil henüz kesinleşmediği için veritabanı kolon adları (tur,
// kanitlar, onerilen_metin, analist_karari, uretim_modu, po_onaylayan …) da kabul edilir.
// Çıktı modu bilinmiyorsa `null` kalır: rozet gösterilmez ama "live" da uydurulmaz.


type Ham = Record<string, unknown>;

const metin = (x: unknown, varsayilan = ""): string => (typeof x === "string" ? x : varsayilan);
const metinYaDaNull = (x: unknown): string | null => (typeof x === "string" && x !== "" ? x : null);
const sayi = (x: unknown, varsayilan = 0): number => (typeof x === "number" && Number.isFinite(x) ? x : varsayilan);
const sayiYaDaNull = (x: unknown): number | null => (typeof x === "number" && Number.isFinite(x) ? x : null);
const kimlik = (x: unknown): string => (typeof x === "string" || typeof x === "number" ? String(x) : "");
/** İlk tanımlı (undefined olmayan) alan. */
const ilk = (o: Ham, ...adlar: string[]): unknown => {
  for (const a of adlar) if (o[a] !== undefined) return o[a];
  return undefined;
};

/** Liste yanıtı: dizi ya da `{items|kayitlar|data: [...]}`. */
export function listeUyarla<T>(govde: unknown, donustur: (x: Ham) => T): T[] {
  const dizi = Array.isArray(govde)
    ? govde
    : nesneMi(govde)
      ? (([govde.items, govde.kayitlar, govde.data].find(Array.isArray) as unknown[] | undefined) ?? null)
      : null;
  if (!dizi) throw new Error("Beklenmeyen liste yanıtı");
  return dizi.filter(nesneMi).map(donustur);
}

/** Model geçidi modu; tanınmayan/eksik değer `null` (rozet yok, "live" uydurulmaz). */
export function modUyarla(x: unknown): CiktiModu | null {
  const m = typeof x === "string" ? x.toLowerCase().replace("-", "_") : "";
  return m === "live" || m === "replay" || m === "replay_miss" ? m : null;
}

export function kabulKriteriUyarla(x: unknown, i: number): KabulKriteri | null {
  if (typeof x === "string") {
    const e = /^\s*(AC\s*\d+)\s*[:.\-–]\s*(.*)$/i.exec(x);
    return e ? { ref: e[1].replace(/\s+/g, "").toUpperCase(), metin: e[2].trim() } : { ref: `AC${i + 1}`, metin: x.trim() };
  }
  if (!nesneMi(x)) return null;
  return {
    ref: metin(ilk(x, "ref", "id", "kod"), `AC${i + 1}`),
    metin: metin(ilk(x, "metin", "text", "aciklama")),
  };
}

const PO_ONAYLI_DURUMLAR = new Set(["po_approved", "generating", "cases_ready", "done"]);

export function poUyarla(g: Ham): PoDurumu {
  const kanalVarsayilan: PoDurumu["kanal"] = g.kaynak === "free_text" ? "portal" : "jira";
  if (nesneMi(g.po)) {
    const p = g.po;
    const d = metin(p.durum);
    return {
      durum: d === "approved" || d === "pending" ? d : "not_requested",
      onaylayan: metinYaDaNull(p.onaylayan),
      zaman: metinYaDaNull(p.zaman),
      kanal: p.kanal === "portal" || p.kanal === "jira" ? p.kanal : kanalVarsayilan,
      onaylanan_hash: metinYaDaNull(ilk(p, "onaylanan_hash") ?? g.onaylanan_hash),
    };
  }
  const onaylayan = metinYaDaNull(g.po_onaylayan);
  const durum = metin(g.durum);
  const kaynak = metin(g.po_onay_kaynagi);
  return {
    durum: onaylayan && PO_ONAYLI_DURUMLAR.has(durum) ? "approved" : durum === "pending_po" ? "pending" : "not_requested",
    onaylayan,
    zaman: metinYaDaNull(g.po_onay_zamani),
    kanal: kaynak === "portal" ? "portal" : kaynak === "jira_label" ? "jira" : kanalVarsayilan,
    onaylanan_hash: metinYaDaNull(g.onaylanan_hash),
  };
}

function soruUyarla(x: Ham, i: number): OnIncelemeSorusu {
  return {
    id: kimlik(x.id) || `Q${i + 1}`,
    type: metin(ilk(x, "type", "tur"), "ambiguity") as OnIncelemeSorusu["type"],
    text: metin(ilk(x, "text", "metin")),
    ac_ref: metinYaDaNull(x.ac_ref),
    cevap: metinYaDaNull(x.cevap),
    ...("duzeltmeyle_degisti" in x ? { duzeltmeyle_degisti: x.duzeltmeyle_degisti === true } : {}),
  };
}

export function onIncelemeUyarla(x: unknown): OnInceleme | null {
  if (!nesneMi(x)) return null;
  const sorular = ilk(x, "questions", "sorular");
  return {
    verdict: x.verdict === "ready" ? "ready" : "needs_po",
    questions: Array.isArray(sorular) ? sorular.filter(nesneMi).map(soruUyarla) : [],
    jira_comment_id: metinYaDaNull(x.jira_comment_id),
    mode: modUyarla(ilk(x, "mode", "uretim_modu")),
    zaman: metin(ilk(x, "zaman", "olusturma")),
    ...("ozet" in x ? { ozet: metinYaDaNull(x.ozet) } : {}),
  };
}

export function gereksinimUyarla(g: Ham): Gereksinim {
  const acHam = ilk(g, "kabul_kriterleri", "ac");
  const acler = Array.isArray(acHam) ? acHam.map(kabulKriteriUyarla).filter((a): a is KabulKriteri => a !== null) : [];
  const s = nesneMi(g.sayaclar) ? g.sayaclar : g;
  return {
    id: kimlik(g.id),
    kaynak: g.kaynak === "free_text" ? "free_text" : "jira",
    jira_key: metinYaDaNull(g.jira_key),
    baslik: metin(g.baslik),
    aciklama: metin(g.aciklama),
    kabul_kriterleri: acler,
    ac_missing: typeof g.ac_missing === "boolean" ? g.ac_missing : acler.length === 0,
    durum: metin(g.durum, "new") as GereksinimDurumu,
    ...(typeof g.adim === "number" ? { adim: g.adim } : {}),
    cekim_zamani: metin(ilk(g, "cekim_zamani", "olusturma")),
    po: poUyarla(g),
    sayaclar: {
      bulgu_acik: sayi(s.bulgu_acik),
      case_toplam: sayi(s.case_toplam),
      case_onayli: sayi(s.case_onayli),
    },
  };
}

/** Son tutarlılık kontrolü (`son_kontrol`); yoksa null. Mod tanınmazsa null ("live" uydurulmaz). */
export function sonKontrolUyarla(x: unknown): SonKontrol | null {
  if (!nesneMi(x)) return null;
  return {
    mode: modUyarla(ilk(x, "mode", "uretim_modu")),
    bulgu: sayi(ilk(x, "bulgu", "bulgu_toplam")),
    dogrulanan: sayi(x.dogrulanan),
    elenen: sayi(x.elenen),
    zaman: metinYaDaNull(ilk(x, "zaman", "olusturma")),
  };
}

/** PO'nun Jira cevap yorumu (`po_cevaplari[]`: {id, yazar, metin, zaman}). Metni boş olan atlanır. */
export function poCevabiUyarla(x: unknown, jiraUrl: string | null): PoCevabi | null {
  if (typeof x === "string") return x.trim() ? { id: "", yazar: null, metin: x, zaman: null, url: jiraUrl } : null;
  if (!nesneMi(x)) return null;
  const m = metin(ilk(x, "metin", "body", "text"));
  if (!m.trim()) return null;
  const id = kimlik(x.id);
  const url =
    metinYaDaNull(x.url) ??
    (jiraUrl && id ? `${jiraUrl}?focusedCommentId=${encodeURIComponent(id)}#comment-${encodeURIComponent(id)}` : jiraUrl);
  return { id, yazar: metinYaDaNull(ilk(x, "yazar", "author")), metin: m, zaman: metinYaDaNull(ilk(x, "zaman", "created")), url };
}

export function gereksinimDetayUyarla(g: Ham): GereksinimDetay {
  const s = nesneMi(g.sayaclar) ? g.sayaclar : {};
  const kontrol = [g.son_kontrol, g.kontrol].find(nesneMi) ?? {};
  const jiraUrl = metinYaDaNull(ilk(g, "jira_url", "url"));
  const cevaplarHam = g.po_cevaplari;
  // Elenen (kanıtı doğrulanamayan) bulgu sayısı: üst alan, sayaçlar ya da son kontrol koşusu.
  const elenen = sayiYaDaNull(ilk(g, "elenen_bulgu")) ?? sayiYaDaNull(s.bulgu_elenen) ?? sayiYaDaNull(kontrol.elenen);
  return {
    ...gereksinimUyarla(g),
    icerik_hash: metin(g.icerik_hash),
    on_inceleme: onIncelemeUyarla(ilk(g, "on_inceleme", "review")),
    kontrol_turu: sayi(g.kontrol_turu),
    kontrol_turu_ust_sinir: sayi(g.kontrol_turu_ust_sinir, 3),
    jira_url: jiraUrl,
    uyarilar: Array.isArray(g.uyarilar) ? g.uyarilar.filter((u): u is string => typeof u === "string") : [],
    ...(elenen !== null ? { elenen_bulgu: elenen } : {}),
    ...(g.son_kontrol !== undefined || g.kontrol !== undefined
      ? { son_kontrol: sonKontrolUyarla([g.son_kontrol, g.kontrol].find(nesneMi)) }
      : {}),
    ...(Array.isArray(cevaplarHam)
      ? { po_cevaplari: cevaplarHam.map((c) => poCevabiUyarla(c, jiraUrl)).filter((c): c is PoCevabi => c !== null) }
      : {}),
    ...("denetim_guvenilmez" in g ? { denetim_guvenilmez: metinYaDaNull(g.denetim_guvenilmez) } : {}),
    ...("insan_karari_gerekli" in g ? { insan_karari_gerekli: g.insan_karari_gerekli === true } : {}),
  };
}

export function kanitUyarla(x: unknown): Kanit | null {
  if (!nesneMi(x)) return null;
  if (x.kind === "code") {
    return {
      kind: "code",
      repo: metin(x.repo, "demo-app"),
      path: metin(x.path),
      line: sayi(typeof x.line === "string" ? Number(x.line) : x.line),
      snippet: metin(x.snippet),
    };
  }
  if (x.kind === "data") {
    return {
      kind: "data",
      query: metin(x.query),
      result_digest: metin(x.result_digest),
      result_preview: metinYaDaNull(x.result_preview),
    };
  }
  return null;
}

const BULGU_KARARLARI = new Set<string>(["fix_doc", "code_defect", "accept_difference"]);

export function bulguUyarla(b: Ham): Bulgu {
  const karar = metin(ilk(b, "karar", "analist_karari"));
  const kararGecerli = BULGU_KARARLARI.has(karar) ? (karar as BulguKarari) : null;
  const kanitHam = ilk(b, "evidence", "kanitlar");
  const onerilen = metinYaDaNull(ilk(b, "suggested_doc_text", "onerilen_metin"));
  return {
    id: kimlik(b.id),
    requirement_id: kimlik(b.requirement_id),
    type: metin(ilk(b, "type", "tur"), "ambiguous") as BulguTuru,
    doc_ref: metin(b.doc_ref),
    ozet: metin(ilk(b, "ozet", "observed", "aciklama")),
    evidence: Array.isArray(kanitHam) ? kanitHam.map(kanitUyarla).filter((k): k is Kanit => k !== null) : [],
    kanit_dogrulandi: b.kanit_dogrulandi === true,
    severity: b.severity === "blocking" ? "blocking" : "warning",
    mevcut_doc_text: metinYaDaNull(ilk(b, "mevcut_doc_text", "mevcut_metin")),
    suggested_doc_text: onerilen,
    karar: kararGecerli,
    // core fix_doc düzenlemesini `onerilen_metin`'e yazar (DECISION_EDITS); ayrı alan yoksa odur.
    karar_metni: metinYaDaNull(b.karar_metni) ?? (kararGecerli === "fix_doc" && !("suggested_doc_text" in b) ? onerilen : null),
    gerekce: metinYaDaNull(b.gerekce),
    karar_veren: metinYaDaNull(ilk(b, "karar_veren", "karar_veren_adi")),
    karar_zamani: metinYaDaNull(b.karar_zamani),
    kontrol_turu: sayi(b.kontrol_turu, 1),
    durum: metin(b.durum, "unverified") as BulguDurumu,
    bug_draft_id: metinYaDaNull(b.bug_draft_id),
    icerik_hash: metin(b.icerik_hash),
    mode: modUyarla(ilk(b, "mode", "uretim_modu")),
    onceki_karar: oncekiKararUyarla(b.onceki_karar),
  };
}

function oncekiKararUyarla(x: unknown): Bulgu["onceki_karar"] {
  if (!nesneMi(x)) return null;
  const karar = metin(x.karar);
  return {
    finding_id: kimlik(x.finding_id),
    bulgu_no: typeof x.bulgu_no === "string" || typeof x.bulgu_no === "number" ? x.bulgu_no : null,
    kontrol_turu: sayi(x.kontrol_turu, 1),
    karar: BULGU_KARARLARI.has(karar) ? (karar as BulguKarari) : null,
    gerekce: metinYaDaNull(x.gerekce),
    karar_veren: metinYaDaNull(x.karar_veren),
    karar_zamani: metinYaDaNull(x.karar_zamani),
  };
}

function adimUyarla(x: unknown, i: number): TestAdimi | null {
  if (!nesneMi(x)) return null;
  return { id: metin(x.id, `S${i + 1}`), action: metin(x.action), data: metinYaDaNull(x.data), expected: metin(x.expected) };
}

const dizgeler = (x: unknown): string[] => (Array.isArray(x) ? x.filter((y): y is string => typeof y === "string") : []);

/** Case içeriği (şema §7). Eksik dizi alanları boş diziye tamamlanır (ekran çökmesin). */
export function caseIcerikUyarla(x: unknown): TestCaseIcerik {
  const i = nesneMi(x) ? x : {};
  return {
    title: metin(i.title),
    type: (metin(i.type, "positive") as TestCaseIcerik["type"]),
    risk: (metin(i.risk, "medium") as TestCaseIcerik["risk"]),
    acceptance_criteria_refs: dizgeler(i.acceptance_criteria_refs),
    preconditions: dizgeler(i.preconditions),
    steps: Array.isArray(i.steps) ? i.steps.map(adimUyarla).filter((a): a is TestAdimi => a !== null) : [],
    expected_result: metin(i.expected_result),
    tags: dizgeler(i.tags),
  };
}

export function caseUyarla(c: Ham): TestCase {
  const karar = metin(ilk(c, "karar", "son_karar"));
  return {
    id: kimlik(c.id),
    requirement_id: kimlik(c.requirement_id),
    jira_key: metinYaDaNull(c.jira_key),
    sira_no: sayi(c.sira_no),
    kanal: c.kanal === "ide" ? "ide" : "portal",
    surum: sayi(c.surum, 1),
    icerik: caseIcerikUyarla(c.icerik),
    durum: metin(c.durum, "draft") as CaseDurumu,
    karar: karar === "approve" || karar === "edit" || karar === "reject" ? karar : null,
    ret_nedeni: (metinYaDaNull(c.ret_nedeni) as RetNedeni | null),
    karar_veren: metinYaDaNull(c.karar_veren),
    karar_zamani: metinYaDaNull(c.karar_zamani),
    duzeltme_olcusu: sayiYaDaNull(c.duzeltme_olcusu),
    icerik_hash: metin(c.icerik_hash),
    onaylanan_hash: metinYaDaNull(c.onaylanan_hash),
    ai_generated: c.ai_generated !== false,
    ai_sure_ms: sayi(c.ai_sure_ms),
    review_sure_ms: sayiYaDaNull(c.review_sure_ms),
    maliyet_usd: sayi(c.maliyet_usd),
    jira_test_key: metinYaDaNull(ilk(c, "jira_test_key", "external_key")),
    goruntulenme: metinYaDaNull(c.goruntulenme),
    ...(c.jira_test_url !== undefined ? { jira_test_url: metinYaDaNull(c.jira_test_url) } : {}),
    ...(typeof c.kucuk_duzeltme === "boolean" ? { kucuk_duzeltme: c.kucuk_duzeltme } : {}),
    ...(Array.isArray(c.uyarilar) ? { uyarilar: dizgeler(c.uyarilar) } : {}),
    mode: modUyarla(ilk(c, "mode", "uretim_modu")),
  };
}

const ONIZLEME_ISLEMLERI = new Set(["create", "skip_existing", "blocked_hash_mismatch", "blocked_not_approved", "blocked_no_story"]);

function onizlemeKalemiUyarla(k: Ham): YayinOnizlemeKalemi {
  const link = nesneMi(k.link) ? k.link : {};
  const islem = metin(k.islem);
  return {
    case_id: kimlik(k.case_id),
    title: metin(k.title),
    issue_type: metin(k.issue_type, "Test"),
    summary: metin(k.summary, metin(k.title)),
    labels: dizgeler(k.labels),
    link: { type: metin(link.type), story_key: metinYaDaNull(link.story_key) },
    adim_sayisi: sayi(k.adim_sayisi),
    islem: (ONIZLEME_ISLEMLERI.has(islem) ? islem : "blocked_not_approved") as YayinOnizlemeKalemi["islem"],
    external_key: metinYaDaNull(k.external_key),
  };
}

export function yayinOnizlemeUyarla(govde: unknown): YayinOnizleme {
  if (!nesneMi(govde)) throw new Error("Beklenmeyen yayın önizleme yanıtı");
  const kalemler = ilk(govde, "kalemler", "items");
  const uyarilar = ilk(govde, "uyarilar", "warnings");
  return {
    requirement_id: kimlik(govde.requirement_id),
    hedef: ilk(govde, "hedef", "target") === "xray" ? "xray" : "jira",
    proje: metin(ilk(govde, "proje", "project")),
    kalemler: Array.isArray(kalemler) ? kalemler.filter(nesneMi).map(onizlemeKalemiUyarla) : [],
    uyarilar: dizgeler(uyarilar),
    jira_browse_url: metinYaDaNull(govde.jira_browse_url),
  };
}

function sonucKalemiUyarla(s: Ham): YayinSonucKalemi {
  const d = metin(s.durum);
  return {
    case_id: kimlik(s.case_id),
    durum: d === "created" || d === "exists" ? d : "failed",
    external_key: metinYaDaNull(s.external_key),
    url: metinYaDaNull(s.url),
    hata: metinYaDaNull(s.hata),
  };
}

/**
 * `POST /publish` yanıtı: senkron sonuç listesi ya da arka plan işi (`job_id`, sonuçlar `publish.*`
 * olaylarıyla gelir; o zaman `sonuclar` boş ve `job_id` dolu döner).
 */
export function yayinSonucuUyarla(govde: unknown): YayinSonucu & { job_id?: string | null } {
  if (!nesneMi(govde)) throw new Error("Beklenmeyen yayın yanıtı");
  const sonuclar = ilk(govde, "sonuclar", "results");
  return {
    hedef: ilk(govde, "hedef", "target") === "xray" ? "xray" : "jira",
    sonuclar: Array.isArray(sonuclar) ? sonuclar.filter(nesneMi).map(sonucKalemiUyarla) : [],
    ...(govde.job_id !== undefined ? { job_id: metinYaDaNull(kimlik(govde.job_id)) } : {}),
  };
}

/** Jira kaydının tarayıcı adresi: yanıttaki `url` > browse kökü > story adresinden türetme. */
export function jiraKayitAdresi(
  anahtar: string | null,
  { url, browseKoku, storyAdresi }: { url?: string | null; browseKoku?: string | null; storyAdresi?: string | null },
): string | null {
  if (url && /^https?:\/\//.test(url)) return url;
  if (!anahtar) return null;
  if (browseKoku && /^https?:\/\//.test(browseKoku)) return `${browseKoku.replace(/\/+$/, "").replace(/\/browse$/, "")}/browse/${encodeURIComponent(anahtar)}`;
  const e = storyAdresi ? /^(https?:\/\/.+\/browse\/)[^/]+$/.exec(storyAdresi) : null;
  return e ? `${e[1]}${encodeURIComponent(anahtar)}` : null;
}
