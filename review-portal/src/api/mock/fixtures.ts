// Örnek (mock) veri — docs/DEMO-VERISI.md ile birebir: TPD-1..4, 4 bilinçli uyumsuzluk,
// data-testid'ler, kampanya kırılması (BREAK_CAMPAIGN) ve locator kırılması (add-to-cart → cart-add).
//
// Kaynaklarla bağı (fixtures.test.ts hepsini kaynağa karşı doğrular, kayma derlemede yakalanır):
// - Story başlık/açıklama/AC'leri: sims/jira-sim seed.py; ön inceleme soruları:
//   rules/replay/requirement_review/golden; tutarlılık bulguları (tür, ref, gözlem, kanıt, önerilen
//   metin): rules/replay/consistency_check/golden. Hepsi golden/kaynaklar.json kopyasından okunur
//   (`npm run sozlesme:golden`); elle yazılmış model çıktısı yoktur.
// - Ana demo yolu REPLAY senaryosu `f2-kod-hatasi` (docs/DEMO-VERISI.md): analist F2 kampanya ve F4
//   kredi limitini "Kod hatalı" (code_defect), F1/F3'ü "Dokümanı düzelt" (fix_doc) seçer; AC2 özgün
//   kalır ("… (7 adette 1 bedava)"). 2. tur golden'ı f2-kod-hatasi/TPD-1-r2, case'ler
//   f2-kod-hatasi/TPD-1 (C3 = "6 adet … bedava ürün verilmez": Demo-B'nin defect adayı).
// - Case içerikleri: rules/replay/case_generation/golden/f2-kod-hatasi/TPD-1.json (başlık, AC, adımlar).
// - Bug taslakları: rules/replay/bug_draft/golden/*.json.
// - Jira anahtarları: sims/jira-sim seed (TPD-1..TPD-7 mevcut; kampanya mükerrer adayı TPD-5;
//   ürünün oluşturduğu ilk kayıt TPD-8).
// - Üretilen test kodu: demo-app/e2e/pages page object'leriyle tsc'den geçer.
// - Durumlar: core-api durum makinesi adları (tp_core/workflow/states.py).
// - Bağlantılar: her iç bağlantı bir portal ekranına çıkar; artifact/forge sunucusu olmadığı için
//   Allure/trace/PR adresleri null'dır (ekranda düz metin, ölü bağlantı yok).
// Örnek ek (ekran görüntüsü): data:image URI olarak gömülür (?inline). Ayrı dosya (/assets/…) olamaz:
// koşu uyarlayıcısı (uyumDemoB adresUyarla) "/" ile başlayan ek adresini core'un /api altına çevirir;
// data:image/ adresini olduğu gibi bırakır. CSP img-src 'self' data: buna izin verir (CSP değişmez).
import ORNEK_EK_EKRANI from "./ornek-ek-ekran.png?inline";
import type {
  AdimEslemesi,
  AjanAdimi,
  PrCheck,
  YerelKontrol,
  ManuelBaz,
  McpTokenKaydi,
  Bulgu,
  BulguTuru,
  BugTaslagi,
  GereksinimDetay,
  Kanit,
  OnIncelemeSorusu,
  SoruTuru,
  HataAnalizi,
  KosuDetay,
  ScriptDetay,
  TestCase,
  TestCaseIcerik,
} from "../types";
import { kanonikJson, sha256Hex } from "../../lib/sha256";
import { ekranGoruntusu } from "./ekran";
import { uygulamaHatalari, uygulamaKosulari, uygulamaScriptleri } from "./platformlar";
import kaynaklar from "./golden/kaynaklar.json";

export interface MockVeri {
  gereksinimler: GereksinimDetay[];
  bulgular: Bulgu[];
  caseler: TestCase[];
  scriptler: ScriptDetay[];
  kosular: KosuDetay[];
  hatalar: HataAnalizi[];
  bugTaslaklari: BugTaslagi[];
  denetim: { aktor: string; eylem: string; nesne: string; ozet: string; zaman: string }[];
  /** MCP token kayıtları (ham token saklanmaz; core gibi yalnızca oluşturulduğunda döner). */
  tokenlar?: McpTokenKaydi[];
  /**
   * Story başına ölçülmüş manuel baz değerler (gereksinim kimliği → kayıt). Örnek veri hiçbir
   * story için değer uydurmaz: başlangıçta boştur, yalnızca portaldan girilen değer saklanır.
   */
  manuelBazlar?: Record<string, ManuelBaz>;
  sayac: number;
}

/** Kanıtlardaki depo adı (golden kayıtlarla aynı: forge'daki demo-app deposu). */
const REPO = "demo-app";
const JIRA = "http://127.0.0.1:8090/browse";
/** jira-sim seed'indeki açık Bug'lar (mükerrer araması bunları döndürür). */
const SEED_BUG: Record<string, string> = {
  "TPD-5": "Kampanya indirimi sepette yanlış hesaplanıyor",
  "TPD-6": "Sipariş geçmişinde tarih sıralaması ters görünüyor",
};

export const t = (gun: number, saat: string) => `2026-10-${String(gun).padStart(2, "0")}T${saat}:00+03:00`;

// ------------------------------------------------------------------ bağlayıcı kaynaklar

type SeedStory = { summary: string; aciklama: string; ac: { ref: string; metin: string }[] };
type GoldenSoru = { id: string; type: SoruTuru; text: string; ac_ref: string | null };
type GoldenInceleme = { questions: GoldenSoru[]; verdict: "ready" | "needs_po"; summary: string };
export type GoldenBulgu = {
  id: string;
  type: BulguTuru;
  doc_ref: string;
  claim: string;
  observed: string;
  evidence: Kanit[];
  severity: "blocking" | "warning";
  suggested_doc_text: string | null;
};

/**
 * jira-sim seed'i ve golden REPLAY çıktılarının depodaki kopyası (scripts/golden_esitle.py üretir;
 * fixtures.test.ts kaynaklarla aynı olduğunu denetler).
 */
export const KAYNAK = kaynaklar as unknown as {
  jira_seed: Record<string, SeedStory>;
  requirement_review: Record<string, GoldenInceleme>;
  consistency_check: Record<string, { findings: GoldenBulgu[]; notes: string }>;
  /** consistency_check golden'larının girdi beyanındaki AC satırları (beyanı olanlar). */
  consistency_girdi: Record<string, string[]>;
  /** Serbest metin golden'ının (SERBEST) girdi beyanı: AC satırları ve açıklamada geçen metin. */
  serbest_girdi: { acceptance_criteria?: string[]; contains?: string[] };
  /** case_generation golden'ları: girdi AC satırları ("ACn: …") ve çıktı case'leri. */
  case_generation: Record<string, { girdi_ac: string[]; cases: TestCaseIcerik[] }>;
};

/**
 * Case üretimi golden'ı: kayıt kökü (goldenKoku) için kayıt varsa ve gereksinimin güncel AC'leri
 * golden girdisiyle birebir aynıysa case'ler (REPLAY); değilse undefined (REPLAY-MISS).
 */
export function goldenCaseler(g: { jira_key: string | null; aciklama: string; kabul_kriterleri: { ref: string; metin: string }[] }): TestCaseIcerik[] | undefined {
  const kok = goldenKoku(g);
  if (!kok) return undefined;
  const acler = acSatirlari(g.kabul_kriterleri);
  const ad = adaylar(kok, KAYNAK.case_generation).find((a) => ayniAc(KAYNAK.case_generation[a].girdi_ac, acler));
  return ad ? kopyala(KAYNAK.case_generation[ad].cases) : undefined;
}

/** Senaryo golden dizinleri (ör. `f2-kod-hatasi`), ada göre sıralı — core `ReplayStore` sırası. */
export const SENARYOLAR: string[] = [
  ...new Set(
    [...Object.keys(KAYNAK.consistency_check), ...Object.keys(KAYNAK.case_generation)].filter((a) => a.includes("/")).map((a) => a.split("/")[0]),
  ),
].sort();

/** Bir golden adı için aday kayıtlar: önce ana golden, sonra her senaryodaki aynı ad (core sırası). */
function adaylar(ad: string, kayitlar: Record<string, unknown>): string[] {
  return [ad, ...SENARYOLAR.map((s) => `${s}/${ad}`)].filter((a) => a in kayitlar);
}

const acSatirlari = (acs: { ref: string; metin: string }[]) => acs.map((a) => `${a.ref}: ${a.metin}`);
const ayniAc = (a: string[], b: string[]) => a.length === b.length && a.every((x, i) => x === b[i]);

/**
 * Kontrol turunun golden kayıt adı (core `golden_name` + senaryo seçimi): 1. tur `<kök>`, sonraki
 * turlar `<kök>-r<tur>`. Ana golden'ın girdi beyanı güncel AC'lere uymazsa girdisi uyan senaryo
 * golden'ı (ör. `f2-kod-hatasi/TPD-1-r2`: F2 code_defect, AC2 değişmedi) seçilir; hiçbiri uymazsa
 * ana ad döner (örnek veri eski davranışı korur). Kayıt yoksa undefined (REPLAY-MISS).
 */
export function turGoldenAdi(
  g: { jira_key: string | null; aciklama: string; kabul_kriterleri: { ref: string; metin: string }[] },
  tur: number,
): string | undefined {
  const kok = goldenKoku(g);
  if (!kok) return undefined;
  const ad = tur >= 2 ? `${kok}-r${tur}` : kok;
  const liste = adaylar(ad, KAYNAK.consistency_check);
  if (liste.length === 0) return undefined;
  const acler = acSatirlari(g.kabul_kriterleri);
  return liste.find((a) => KAYNAK.consistency_girdi[a] && ayniAc(KAYNAK.consistency_girdi[a], acler)) ?? liste[0];
}

/** Serbest metin golden kaydının adı (rules/replay/<amaç>/golden/SERBEST.json). */
export const SERBEST_GOLDEN = "SERBEST";

/**
 * Gereksinimin golden kayıt kökü: Jira story'sinde anahtarı; serbest metinde açıklaması golden'ın
 * girdi beyanını içeriyorsa `SERBEST` (core: input_match → REPLAY), değilse yok (REPLAY-MISS).
 * Açıklama düzeltmelerle değişmez (düzeltmeler AC'lere yazılır); 2. tur `SERBEST-r2` olur.
 */
export function goldenKoku(g: { jira_key: string | null; aciklama: string }): string | null {
  if (g.jira_key) return g.jira_key;
  const icerir = KAYNAK.serbest_girdi.contains ?? [];
  return icerir.length > 0 && icerir.every((m) => g.aciklama.includes(m)) ? SERBEST_GOLDEN : null;
}

/** Golden önerilerindeki "AC2: " öneki atılır: portal AC referansını ayrı alanda (`ref`) tutar. */
export const refsiz = (metin: string) => metin.replace(/^AC\d+:\s*/, "");

const kopyala = <T>(x: T): T => JSON.parse(JSON.stringify(x)) as T;

/** Seed'deki story: başlık, açıklama, kabul kriterleri (kopya). */
export function seedStory(anahtar: string): SeedStory {
  const s = KAYNAK.jira_seed[anahtar];
  if (!s) throw new Error(`jira-sim seed'inde story yok: ${anahtar}`);
  return kopyala(s);
}

/** Golden ön inceleme soruları; `cevaplar` yalnızca PO'nun verdiği cevaplardır (model çıktısı değil). */
export function goldenSorular(anahtar: string, cevaplar: Record<string, string> = {}): OnIncelemeSorusu[] {
  const g = KAYNAK.requirement_review[anahtar];
  if (!g) throw new Error(`requirement_review golden kaydı yok: ${anahtar}`);
  return g.questions.map((q) => ({ id: q.id, type: q.type, text: q.text, ac_ref: q.ac_ref, cevap: cevaplar[q.id] ?? null }));
}

export function goldenInceleme(anahtar: string): GoldenInceleme | undefined {
  return KAYNAK.requirement_review[anahtar];
}

/** consistency_check golden kaydının bulguları; kayıt yoksa undefined (REPLAY-MISS). */
export function goldenBulgular(golden: string): GoldenBulgu[] | undefined {
  const k = KAYNAK.consistency_check[golden];
  return k ? kopyala(k.findings) : undefined;
}

function goldenBulgu(golden: string, id: string): GoldenBulgu {
  const f = goldenBulgular(golden)?.find((x) => x.id === id);
  if (!f) throw new Error(`consistency_check golden ${golden} içinde ${id} yok`);
  return f;
}

/**
 * Golden bulgunun portalda gösterilen model çıktısı alanları. `ozet` = golden `observed` (gözlenen),
 * kanıt ve önerilen metin aynen; `mevcut_doc_text` bulgu anındaki doküman metnidir (çağıran verir).
 */
export function bulguCiktisi(f: GoldenBulgu, mevcutDocText: string | null) {
  return {
    type: f.type,
    doc_ref: f.doc_ref,
    ozet: f.observed,
    evidence: kopyala(f.evidence),
    severity: f.severity,
    mevcut_doc_text: mevcutDocText,
    suggested_doc_text: f.suggested_doc_text === null ? null : refsiz(f.suggested_doc_text),
  };
}

const acMetni = (acs: { ref: string; metin: string }[], ref: string) => acs.find((a) => a.ref === ref)?.metin ?? null;

/** Serbest metin demo gereksiniminin AC'leri: golden girdi beyanının kendisi ("ACn: …" satırları). */
const SERBEST_AC = (KAYNAK.serbest_girdi.acceptance_criteria ?? []).map((satir, i) => {
  const m = /^(AC\d+):\s*(.*)$/.exec(satir);
  return m ? { ref: m[1], metin: m[2] } : { ref: `AC${i + 1}`, metin: satir };
});
const SERBEST_ACIKLAMA = KAYNAK.serbest_girdi.contains?.[0] ?? "";

// TPD-1 tutarlılık turu 1 (golden TPD-1): F1 AC3↔AC6, F2 AC2 kod, F3 AC3 veri, F4 AC4 kod eksik.
const TPD1_SEED_AC = seedStory("TPD-1").ac;
/** Ana demo yolunun REPLAY senaryosu (docs/DEMO-VERISI.md). */
export const ANA_SENARYO = "f2-kod-hatasi";
const TPD1_F = {
  celiski: goldenBulgu("TPD-1", "F1"),
  kampanya: goldenBulgu("TPD-1", "F2"),
  minTutar: goldenBulgu("TPD-1", "F3"),
  krediLimiti: goldenBulgu("TPD-1", "F4"),
};

/**
 * Seed AC'leri + kabul edilen (fix_doc) golden önerileri: TPD-1'in Jira'ya yazılmış son hâli. Ana
 * yolda yalnızca F1/F3 (ikisi de aynı AC3 metnini önerir) dokümana yazılır; F2 kampanya code_defect
 * olduğundan AC2 özgün kalır: "… her 6 adet alımda 1 adet bedava verilir (7 adette 1 bedava)".
 */
const TPD1_AC = TPD1_SEED_AC.map((ac) => {
  if (ac.ref === "AC3") return { ...ac, metin: refsiz(TPD1_F.minTutar.suggested_doc_text!) };
  return ac;
});

function story(anahtar: string) {
  const s = seedStory(anahtar);
  return { jira_key: anahtar, baslik: s.summary, aciklama: s.aciklama, kabul_kriterleri: s.ac };
}

function gereksinimler(): GereksinimDetay[] {
  return [
    {
      id: "req-tpd-1",
      kaynak: "jira",
      ...story("TPD-1"),
      kabul_kriterleri: TPD1_AC,
      ac_missing: false,
      // core durum makinesi `done` ile biter (case'ler yayınlandı); akış kod review'da → ipucu 6.
      durum: "done",
      adim: 6,
      cekim_zamani: t(30, "09:12"),
      po: { durum: "approved", onaylayan: "po@sim.local", zaman: t(30, "10:05"), kanal: "jira" },
      sayaclar: { bulgu_acik: 0, case_toplam: 6, case_onayli: 4 },
      on_inceleme: {
        verdict: goldenInceleme("TPD-1")!.verdict,
        mode: "replay",
        zaman: t(30, "09:20"),
        jira_comment_id: "10021",
        // Sorular golden'dan aynen; cevaplar PO'nun Jira yorumundaki yanıtlarıdır.
        questions: goldenSorular("TPD-1", {
          Q1: "Kampanyalı siparişler muaf; AC3 kampanyasız siparişler için geçerli. (PO)",
          Q2: "Evet, story doğru: 6 adet öder, 7. adet bedava; 6 adette bedava yok, 14 adette 2 bedava. Kod farklıysa kod düzeltilsin. (PO)",
          Q3: "İndirim düşülmüş toplam tutar üzerinden. (PO)",
        }),
      },
      kontrol_turu: 2,
      kontrol_turu_ust_sinir: 3,
      // core `requirement_kontrol`: son tamamlanan koşu (golden f2-kod-hatasi/TPD-1-r2, 2 bulgu:
      // kampanya ve kredi limiti farkı kod tarafında kaldı; ikisi de önceki turda code_defect).
      son_kontrol: { mode: "replay", bulgu: 2, dogrulanan: 2, elenen: 0, zaman: t(30, "09:52") },
      elenen_bulgu: 0,
      icerik_hash: "", // hashleriTazele doldurur
      jira_url: `${JIRA}/TPD-1`,
      uyarilar: [],
    },
    {
      id: "req-tpd-2",
      kaynak: "jira",
      ...story("TPD-2"),
      ac_missing: true,
      durum: "new",
      cekim_zamani: t(30, "09:12"),
      po: { durum: "not_requested", onaylayan: null, zaman: null, kanal: "jira" },
      sayaclar: { bulgu_acik: 0, case_toplam: 0, case_onayli: 0 },
      on_inceleme: null,
      kontrol_turu: 0,
      kontrol_turu_ust_sinir: 3,
      icerik_hash: "", // hashleriTazele doldurur
      jira_url: `${JIRA}/TPD-2`,
      uyarilar: ["Kabul kriteri yok: story case üretimine gönderilmez. Analistten AC istenmeli."],
    },
    {
      id: "req-tpd-3",
      kaynak: "jira",
      ...story("TPD-3"),
      ac_missing: false,
      durum: "pending_po",
      cekim_zamani: t(30, "09:12"),
      po: { durum: "pending", onaylayan: null, zaman: null, kanal: "jira" },
      sayaclar: { bulgu_acik: 0, case_toplam: 0, case_onayli: 0 },
      on_inceleme: {
        verdict: goldenInceleme("TPD-3")!.verdict,
        mode: "replay",
        zaman: t(30, "09:31"),
        jira_comment_id: "10024",
        questions: goldenSorular("TPD-3"),
      },
      kontrol_turu: 1,
      kontrol_turu_ust_sinir: 3,
      son_kontrol: { mode: "replay", bulgu: 1, dogrulanan: 1, elenen: 0, zaman: t(30, "09:31") },
      elenen_bulgu: 0,
      icerik_hash: "", // hashleriTazele doldurur
      jira_url: `${JIRA}/TPD-3`,
      uyarilar: [
        "Açıklamada talimat benzeri metin bulundu (olası prompt injection). İçerik güvenilmeyen veri olarak işlendi; talimat uygulanmadı.",
      ],
    },
    {
      id: "req-tpd-4",
      kaynak: "jira",
      ...story("TPD-4"),
      ac_missing: false,
      durum: "new",
      cekim_zamani: t(30, "09:12"),
      po: { durum: "not_requested", onaylayan: null, zaman: null, kanal: "jira" },
      sayaclar: { bulgu_acik: 0, case_toplam: 0, case_onayli: 0 },
      on_inceleme: null,
      kontrol_turu: 0,
      kontrol_turu_ust_sinir: 3,
      icerik_hash: "", // hashleriTazele doldurur
      jira_url: `${JIRA}/TPD-4`,
      uyarilar: [],
    },
    {
      id: "req-ft-1",
      kaynak: "free_text",
      jira_key: null,
      baslik: "Sepetten ürün çıkarma",
      aciklama: SERBEST_ACIKLAMA,
      kabul_kriterleri: kopyala(SERBEST_AC),
      ac_missing: false,
      durum: "findings_open",
      cekim_zamani: t(30, "11:40"),
      po: { durum: "not_requested", onaylayan: null, zaman: null, kanal: "portal" },
      sayaclar: { bulgu_acik: 2, case_toplam: 0, case_onayli: 0 },
      // Serbest metin golden'ı (SERBEST, input_match bu metin): core REPLAY olarak gösterir.
      on_inceleme: {
        verdict: goldenInceleme(SERBEST_GOLDEN)!.verdict,
        mode: "replay",
        zaman: t(30, "11:42"),
        jira_comment_id: null,
        questions: goldenSorular(SERBEST_GOLDEN),
      },
      kontrol_turu: 1,
      kontrol_turu_ust_sinir: 3,
      son_kontrol: { mode: "replay", bulgu: 3, dogrulanan: 3, elenen: 0, zaman: t(30, "11:42") },
      elenen_bulgu: 0,
      icerik_hash: "", // hashleriTazele doldurur
      jira_url: null,
      uyarilar: [],
    },
  ];
}

// ------------------------------------------------------------------ tutarlılık bulguları

/** Kampanya kuralının koddaki satırı (golden TPD-1 F2 kanıtı; campaign.py). */
export const KAMPANYA_KOD: Kanit = TPD1_F.kampanya.evidence[0];

/** Minimum sipariş tutarı ayarı (golden TPD-1 F3 kanıtı). Önizleme: deterministik yeniden sorgu. */
export const MIN_SIPARIS_VERI: Kanit = {
  ...TPD1_F.minTutar.evidence[0],
  ...(TPD1_F.minTutar.evidence[0].kind === "data" ? { result_preview: "anahtar            | deger\nmin_siparis_tutari | 750.00" } : {}),
} as Kanit;

function bulgular(): Bulgu[] {
  const ortak = {
    requirement_id: "req-tpd-1",
    kontrol_turu: 1,
    kanit_dogrulandi: true,
    karar_veren: "analist",
    mode: "replay" as const,
  };
  // 2. tur: ana yolun senaryo golden'ı (AC2 değişmedi → kampanya farkı kodda kaldı).
  const r2Kampanya = goldenBulgu(`${ANA_SENARYO}/TPD-1-r2`, "F1");
  const r2Kredi = goldenBulgu(`${ANA_SENARYO}/TPD-1-r2`, "F2");
  const tpd3 = goldenBulgu("TPD-3", "F1");
  return [
    {
      ...ortak,
      ...bulguCiktisi(TPD1_F.kampanya, acMetni(TPD1_SEED_AC, "AC2")),
      evidence: [KAMPANYA_KOD],
      id: "fnd-1",
      // Ana yol: story doğru (PO, Q2), kod hatalı → bug taslağı; AC2 değişmez.
      karar: "code_defect",
      karar_metni: null,
      gerekce: "PO cevabı (Q2): story doğru, 7 adette 1 bedava. Kod 6 adette bedava veriyor; kod düzeltilmeli.",
      karar_zamani: t(30, "09:41"),
      durum: "resolved",
      bug_draft_id: "bug-3",
      icerik_hash: "",
    },
    {
      ...ortak,
      ...bulguCiktisi(TPD1_F.minTutar, acMetni(TPD1_SEED_AC, "AC3")),
      evidence: [MIN_SIPARIS_VERI],
      id: "fnd-2",
      karar: "fix_doc",
      karar_metni: acMetni(TPD1_AC, "AC3"),
      gerekce: null,
      karar_zamani: t(30, "09:43"),
      durum: "resolved", // fix_doc yazıldı (core: decided → resolved)
      bug_draft_id: null,
      icerik_hash: "",
    },
    {
      ...ortak,
      ...bulguCiktisi(TPD1_F.krediLimiti, null),
      id: "fnd-3",
      karar: "code_defect",
      karar_metni: null,
      gerekce: "Kural doğru; uygulamada eksik. Bug taslağı oluşturuldu.",
      karar_zamani: t(30, "09:45"),
      durum: "resolved",
      bug_draft_id: "bug-2",
      icerik_hash: "",
    },
    {
      ...ortak,
      ...bulguCiktisi(TPD1_F.celiski, acMetni(TPD1_SEED_AC, "AC3")),
      id: "fnd-4",
      karar: "fix_doc",
      karar_metni: acMetni(TPD1_AC, "AC3"),
      gerekce: null,
      karar_zamani: t(30, "09:47"),
      durum: "resolved", // fix_doc yazıldı (core: decided → resolved)
      bug_draft_id: null,
      icerik_hash: "",
    },
    // 2. kontrol turu (golden f2-kod-hatasi/TPD-1-r2): kampanya ve kredi limiti farkı kodda kaldı;
    // önceki turun code_defect kararları (bug-3, bug-2) geçerli, analist aynı kararı verdi.
    {
      ...ortak,
      ...bulguCiktisi(r2Kampanya, acMetni(TPD1_AC, "AC2")),
      evidence: [KAMPANYA_KOD],
      id: "fnd-10",
      kontrol_turu: 2,
      karar: "code_defect",
      karar_metni: null,
      gerekce: "Önceki turdaki kod hatası kararı geçerli; kampanya bug taslağı (bug-3) açık.",
      karar_zamani: t(30, "09:54"),
      durum: "resolved",
      bug_draft_id: "bug-3",
      icerik_hash: "",
    },
    {
      ...ortak,
      ...bulguCiktisi(r2Kredi, acMetni(TPD1_AC, "AC4")),
      id: "fnd-7",
      kontrol_turu: 2,
      karar: "code_defect",
      karar_metni: null,
      gerekce: "Önceki turdaki kod hatası kararı geçerli; bug-2 Jira'da açık.",
      karar_zamani: t(30, "09:55"),
      durum: "resolved",
      bug_draft_id: "bug-2",
      icerik_hash: "",
    },
    // TPD-3 (golden TPD-3): story henüz geliştirilmemiş arama özelliğini istiyor → uyarı (engellemez).
    {
      ...bulguCiktisi(tpd3, null),
      id: "fnd-8",
      requirement_id: "req-tpd-3",
      kanit_dogrulandi: true,
      karar: null,
      karar_metni: null,
      gerekce: null,
      karar_veren: null,
      karar_zamani: null,
      kontrol_turu: 1,
      durum: "open",
      bug_draft_id: null,
      icerik_hash: "",
      mode: "replay",
    },
    // Serbest metin gereksinim (golden SERBEST, 1. tur): kararı bekleyen bulgular (karar düğmeleri
    // burada denenir). F2 ve F3 aynı AC3 metnini önerir; hangisi kabul edilirse edilsin aynı sonuç.
    ...([
      ["fnd-5", "F1"],
      ["fnd-6", "F2"],
      ["fnd-9", "F3"],
    ] as const).map(([id, f]): Bulgu => {
      const gb = goldenBulgu(SERBEST_GOLDEN, f);
      const mevcut = acMetni(SERBEST_AC, gb.doc_ref);
      return {
        ...bulguCiktisi(gb, mevcut),
        ...(gb.evidence[0]?.kind === "data" ? { evidence: [MIN_SIPARIS_VERI] } : {}),
        id,
        requirement_id: "req-ft-1",
        kanit_dogrulandi: true,
        karar: null,
        karar_metni: null,
        gerekce: null,
        karar_veren: null,
        karar_zamani: null,
        kontrol_turu: 1,
        durum: "open",
        bug_draft_id: null,
        icerik_hash: "",
        mode: "replay",
      };
    }),
  ];
}

// ------------------------------------------------------------------ test case'ler

/**
 * TPD-1 case üretiminin ana demo yolundaki golden çıktısı
 * (rules/replay/case_generation/golden/f2-kod-hatasi/TPD-1.json → output.cases), sırasıyla. Girdi
 * beyanı AC2'nin özgün hâlidir (F2 code_defect). golden/kaynaklar.json kopyasından okunur
 * (`npm run sozlesme:golden`); fixtures.test.ts kaynakla birebir aynı olduğunu doğrular.
 */
export const TPD1_GOLDEN_CASELER: TestCaseIcerik[] = KAYNAK.case_generation[`${ANA_SENARYO}/TPD-1`].cases;

/** Case içerik hash'i (handlers ile aynı biçim): onay kapısı bu değeri karşılaştırır. */
export function icerikHash(icerik: TestCaseIcerik): string {
  return `sha256:${sha256Hex(kanonikJson(icerik)).slice(0, 16)}`;
}

function caseler(): TestCase[] {
  const ortak = {
    requirement_id: "req-tpd-1",
    jira_key: "TPD-1",
    kanal: "portal" as const,
    surum: 1,
    ai_generated: true,
    mode: "replay" as const,
    ai_sure_ms: 1130,
    maliyet_usd: 0,
  };
  const karar = (
    id: string,
    sira_no: number,
    icerik: TestCaseIcerik,
    ek: Partial<TestCase> & Pick<TestCase, "durum">,
  ): TestCase => {
    const hash = icerikHash(icerik);
    const onayli = ek.durum === "approved" || ek.durum === "published";
    return {
      ...ortak,
      id,
      sira_no,
      icerik,
      karar: null,
      ret_nedeni: null,
      karar_veren: null,
      karar_zamani: null,
      duzeltme_olcusu: null,
      icerik_hash: hash,
      onaylanan_hash: onayli ? hash : null,
      review_sure_ms: null,
      jira_test_key: null,
      ...ek,
    };
  };
  const G = TPD1_GOLDEN_CASELER;
  const analist = { karar_veren: "analist" };
  return [
    karar("case-1-1", 1, G[0], { ...analist, durum: "published", karar: "approve", karar_zamani: t(30, "10:31"), duzeltme_olcusu: 0, review_sure_ms: 41000, jira_test_key: "TPD-9" }),
    karar("case-1-2", 2, G[1], { ...analist, durum: "published", karar: "approve", karar_zamani: t(30, "10:34"), duzeltme_olcusu: 0, review_sure_ms: 58000, jira_test_key: "TPD-10" }),
    // C3: 6 adet sınırı (senaryo golden'ı story'yi esas alır: bedava 0). Bugünkü kod 1 bedava
    // verdiğinden Demo-B'de assertion kırmızı → defect adayı (scr-3).
    karar("case-1-3", 3, G[2], { ...analist, durum: "published", karar: "approve", karar_zamani: t(30, "10:37"), duzeltme_olcusu: 0, review_sure_ms: 64000, jira_test_key: "TPD-11" }),
    // İnsan kararı: 6 ve 7 adet case'leri kampanya sınırını zaten kapsıyor.
    karar("case-1-6", 4, G[3], { ...analist, durum: "rejected", karar: "reject", ret_nedeni: "duplicate", karar_zamani: t(30, "10:38"), review_sure_ms: 30000 }),
    karar("case-1-4", 5, G[4], { ...analist, durum: "approved", karar: "approve", karar_zamani: t(30, "10:41"), duzeltme_olcusu: 0, review_sure_ms: 52000 }),
    karar("case-1-7", 6, G[5], { durum: "draft" }),
    // Kredi limiti case'i bilinen kod hatasını hedefler (golden etiketi expected-code-defect).
    karar("case-1-5", 7, G[6], { durum: "draft", kanal: "ide", mode: "replay" }),
    karar("case-1-8", 8, G[7], { durum: "draft" }),
    karar("case-1-9", 9, G[8], { durum: "draft" }),
    // Golden C10 bilinçli olarak C2'nin tekrarı: analist "duplicate" gerekçesiyle reddeder.
    karar("case-1-10", 10, G[9], { ...analist, durum: "rejected", karar: "reject", ret_nedeni: "duplicate", karar_zamani: t(30, "10:44"), review_sure_ms: 21000 }),
  ];
}

/** Gereksinimin case sayaçları — liste, detay ve Kontrol Kulesi karnesi aynı hesabı kullanır. */
export function caseSayilari(tum: TestCase[], requirementId: string): { toplam: number; onayli: number } {
  // Reddedilen case'ler kapsamın parçası değildir; "toplam" süitteki (taslak dahil) case'lerdir.
  const gc = tum.filter((c) => c.requirement_id === requirementId && c.durum !== "rejected");
  return { toplam: gc.length, onayli: gc.filter((c) => c.durum === "approved" || c.durum === "published").length };
}

// ------------------------------------------------------------------ üretilen kod

// Şablonun ürettiği biçim: page object'ler pages/index.ts'ten, dosya tests/<story>/ altında.
// fixtures.test.ts bu metinleri demo-app/e2e page object'lerine karşı tsc ile derler.
export const KAMPANYA_TEST_KODU = `import { test } from "@playwright/test";
import { CartPage, CatalogPage, LoginPage } from "../../pages";

// AI-generated · TPD-1 · case 2 (onaylayan: analist)
// Şablondan üretildi; değerler onaylı case metninden JSON.stringify ile basıldı.
test("TPD-1 C2 · 7 adet kampanyalı üründe 1 adet bedava verilir", async ({ page }) => {
  const login = new LoginPage(page);
  const catalog = new CatalogPage(page);
  const cart = new CartPage(page);

  // S1: Giriş sayfasını aç
  await login.goto();
  // S2: Bayi kullanıcısıyla giriş yap
  await login.login("bayi1", "Demo123!");
  await login.expectLoggedIn("Merkez Bayi");
  // S3: "Portakal Gazozu 1L" (P-001) kartında adedi 7 yapıp "Sepete ekle" butonuna bas
  await catalog.addToCart("P-001", 7);
  await catalog.expectCartCount(7);
  // S4: Üst menüden sepete git
  await catalog.openCart();
  await cart.expectLineQuantity("P-001", 7);
  await cart.expectSubtotal("175,00 TL");
  await cart.expectDiscount("25,00 TL");
  await cart.expectTotal("150,00 TL");
  await cart.expectFreeQuantity("P-001", 1);
});
`;

export const SEPET_TEST_KODU = `import { test } from "@playwright/test";
import { CatalogPage, LoginPage } from "../../pages";

// AI-generated · TPD-1 · case 1 (onaylayan: analist)
// Şablondan üretildi; değerler onaylı case metninden JSON.stringify ile basıldı.
test("TPD-1 C1 · Sepete ekle ile ürün sepete eklenir ve sepet sayacı artar", async ({ page }) => {
  const login = new LoginPage(page);
  const catalog = new CatalogPage(page);

  // S1: Giriş sayfasını aç
  await login.goto();
  // S2: Bayi kullanıcısıyla giriş yap
  await login.login("bayi1", "Demo123!");
  await login.expectLoggedIn("Merkez Bayi");
  // S3: "Portakal Gazozu 1L" (P-001) kartında adedi 1 yapıp "Sepete ekle" butonuna bas
  await catalog.addToCart("P-001", 1);
  await catalog.expectCartCount(1);
});
`;

export const SINIR_TEST_KODU = `import { test } from "@playwright/test";
import { CartPage, CatalogPage, LoginPage } from "../../pages";

// AI-generated · TPD-1 · case 3 (onaylayan: analist)
// Şablondan üretildi; değerler onaylı case metninden JSON.stringify ile basıldı.
test("TPD-1 C3 · 6 adet kampanyalı üründe bedava ürün verilmez", async ({ page }) => {
  const login = new LoginPage(page);
  const catalog = new CatalogPage(page);
  const cart = new CartPage(page);

  // S1: Giriş sayfasını aç
  await login.goto();
  // S2: Bayi kullanıcısıyla giriş yap
  await login.login("bayi1", "Demo123!");
  await login.expectLoggedIn("Merkez Bayi");
  // S3: "Portakal Gazozu 1L" (P-001) kartında adedi 6 yapıp "Sepete ekle" butonuna bas
  await catalog.addToCart("P-001", 6);
  await catalog.expectCartCount(6);
  // S4: Üst menüden sepete git
  await catalog.openCart();
  await cart.expectLineQuantity("P-001", 6);
  await cart.expectFreeQuantity("P-001", 0);
  await cart.expectSubtotal("150,00 TL");
  await cart.expectDiscount("0,00 TL");
  await cart.expectTotal("150,00 TL");
});
`;

export const MIN_SIPARIS_TEST_KODU = `import { test } from "@playwright/test";
import { CartPage, CatalogPage, LoginPage } from "../../pages";

// AI-generated · TPD-1 · case 5 (onaylayan: analist)
// Şablondan üretildi; değerler onaylı case metninden JSON.stringify ile basıldı.
test("TPD-1 C5 · Kampanyasız siparişte minimum tutarın altında uyarı gösterilir ve onay pasif olur", async ({ page }) => {
  const login = new LoginPage(page);
  const catalog = new CatalogPage(page);
  const cart = new CartPage(page);

  // S1: Giriş sayfasını aç
  await login.goto();
  // S2: Bayi kullanıcısıyla giriş yap
  await login.login("bayi1", "Demo123!");
  await login.expectLoggedIn("Merkez Bayi");
  // S3: "Limonata 330ml" (P-002) kartında adedi 10 yapıp "Sepete ekle" butonuna bas
  await catalog.addToCart("P-002", 10);
  await catalog.expectCartCount(10);
  // S4: Üst menüden sepete git
  await catalog.openCart();
  await cart.expectTotal("150,00 TL");
  await cart.expectMinOrderWarning("Minimum sipariş tutarı 750,00 TL");
  await cart.expectCheckoutDisabled();
});
`;

function adim(
  sira: number,
  step_id: string,
  arac: string,
  aciklama: string,
  po: string | null,
  method: string | null,
  args: unknown[],
  ekran: string | null,
): AjanAdimi {
  return {
    sira,
    step_id,
    arac,
    aciklama,
    po,
    method,
    args,
    verified: true,
    ekran_goruntusu_url: ekran,
    zaman: t(30, `11:${String(sira).padStart(2, "0")}`),
    ham_cikti: hamCikti(arac, method, args),
  };
}

/**
 * Aracın temizlenmiş ham çıktısı (core `_adim`: temizlenir, parola maskelenir). Ajan uygulamayı
 * yalnızca MCP erişilebilirlik ağacı (snapshot) olarak görür; ekran görüntüsü modele gitmez.
 */
function hamCikti(arac: string, method: string | null, args: unknown[]): string {
  const deger = args.length ? String(args[args.length - 1]) : "";
  if (arac === "browser_navigate") return "- Page URL: http://demo-web:8080/login\n- Page Title: Bayi Portalı · Giriş";
  if (arac === "browser_type") return `- textbox "Kullanıcı adı" [ref=e3]: ${AJAN_BAYI}\n- textbox "Parola" [ref=e4]: ••••••\n- button "Giriş yap" [ref=e5] [cursor=pointer]`;
  if (arac === "browser_click") return `- button "${method === "openCart" ? "Sepet" : "Sepete ekle"}" [ref=e12] [cursor=pointer]\n- generic [ref=e14]: ${deger}`;
  return `- generic [ref=e21]: ${deger}`;
}

/** Kod üretimindeki doğrulama ajanının bayisi (docs/DEMO-VERISI.md); testler case bayisiyle koşar. */
const AJAN_BAYI = "bayi3";

/** C2 için ajan adımları: `sira` ajanın sıralı adım numarası, `step_id` case adımı referansı. */
export function kampanyaAdimlari(): AjanAdimi[] {
  return [
    adim(1, "S1", "browser_navigate", "Giriş sayfası açıldı", "LoginPage", "goto", [], ekranGoruntusu("login", "login-username")),
    adim(2, "S2", "browser_type", "bayi1 ile giriş yapıldı", "LoginPage", "login", ["bayi1", "Demo123!"], ekranGoruntusu("login", "login-submit")),
    adim(3, "S3", "browser_click", "P-001 adedi 7 girildi ve \"Sepete ekle\" tıklandı", "CatalogPage", "addToCart", ["P-001", 7], ekranGoruntusu("catalog", "add-to-cart", 7)),
    adim(4, "S3", "browser_snapshot", "Sepet sayacı doğrulandı: 7", "CatalogPage", "expectCartCount", [7], ekranGoruntusu("catalog", "qty-input-P-001", 7)),
    adim(5, "S4", "browser_click", "Üst menüden sepete gidildi", "CatalogPage", "openCart", [], ekranGoruntusu("cart", "cart-line-P-001", 7)),
    adim(6, "S4", "browser_snapshot", "Ara toplam doğrulandı: 175,00 TL", "CartPage", "expectSubtotal", ["175,00 TL"], ekranGoruntusu("cart", "cart-subtotal", 7)),
    adim(7, "S4", "browser_snapshot", "İndirim satırı doğrulandı: 25,00 TL", "CartPage", "expectDiscount", ["25,00 TL"], ekranGoruntusu("cart", "cart-discount", 7)),
    adim(8, "S4", "browser_snapshot", "Toplam doğrulandı: 150,00 TL", "CartPage", "expectTotal", ["150,00 TL"], ekranGoruntusu("cart", "cart-total", 7)),
  ];
}

function sepetAdimlari(): AjanAdimi[] {
  return [
    adim(1, "S1", "browser_navigate", "Giriş sayfası açıldı", "LoginPage", "goto", [], ekranGoruntusu("login", "login-username")),
    adim(2, "S2", "browser_type", "bayi1 ile giriş yapıldı", "LoginPage", "login", ["bayi1", "Demo123!"], ekranGoruntusu("login", "login-submit")),
    adim(3, "S3", "browser_click", "P-001 kartında \"Sepete ekle\" tıklandı", "CatalogPage", "addToCart", ["P-001", 1], ekranGoruntusu("catalog", "add-to-cart", 1)),
    adim(4, "S3", "browser_snapshot", "Sepet sayacı doğrulandı: 1", "CatalogPage", "expectCartCount", [1], ekranGoruntusu("catalog", "qty-input-P-001", 1)),
  ];
}

/** Ajan adımlarından doğrulanmış eşleme tablosu (core `step_mapping` şekli). */
export function eslemeler(adimlar: AjanAdimi[], kaynak: Record<string, string> = {}): AdimEslemesi[] {
  return adimlar
    .filter((a) => a.po && a.method)
    .map((a, i) => ({
      adim_no: i + 1,
      step_id: a.step_id || null,
      po: a.po!,
      method: a.method!,
      args: a.args,
      beklenen: a.method!.startsWith("expect"),
      verified: a.verified === true,
      kaynak_metin: a.method!.startsWith("expect") ? (kaynak[String(a.args[a.args.length - 1])] ?? null) : null,
      kanit_ref: `snapshot:${a.sira}`,
      // core `_dogrulama_notu`: giriş satırı ajan bayisiyle doğrulandı, test case bayisiyle koşar.
      dogrulama_notu:
        a.method === "login" && typeof a.args[0] === "string" ? `doğrulandı (ajan bayisi ${AJAN_BAYI} ile; test ${a.args[0]} ile koşar)` : null,
    }));
}

const C2_KAYNAK = {
  "7": "Sepet sayacı 7 olur",
  "175,00 TL": "ara toplam 175,00 TL",
  "25,00 TL": "indirim 25,00 TL",
  "150,00 TL": "toplam 150,00 TL",
};

/** C3 (6 adet, sınır) için ajan adımları: uygulamada adımlar doğrulanır, değerler case metninden. */
export function sinirAdimlari(): AjanAdimi[] {
  return [
    adim(1, "S1", "browser_navigate", "Giriş sayfası açıldı", "LoginPage", "goto", [], ekranGoruntusu("login", "login-username")),
    adim(2, "S2", "browser_type", "bayi1 ile giriş yapıldı", "LoginPage", "login", ["bayi1", "Demo123!"], ekranGoruntusu("login", "login-submit")),
    adim(3, "S3", "browser_click", "P-001 adedi 6 girildi ve \"Sepete ekle\" tıklandı", "CatalogPage", "addToCart", ["P-001", 6], ekranGoruntusu("catalog", "add-to-cart", 6)),
    adim(4, "S3", "browser_snapshot", "Sepet sayacı elemanı bulundu (beklenen 6)", "CatalogPage", "expectCartCount", [6], ekranGoruntusu("catalog", "qty-input-P-001", 6)),
    adim(5, "S4", "browser_click", "Üst menüden sepete gidildi", "CatalogPage", "openCart", [], ekranGoruntusu("cart", "cart-line-P-001", 6)),
    adim(6, "S4", "browser_snapshot", "İndirim satırı elemanı bulundu (beklenen 0,00 TL)", "CartPage", "expectDiscount", ["0,00 TL"], ekranGoruntusu("cart", "cart-discount", 6)),
    adim(7, "S4", "browser_snapshot", "Toplam elemanı bulundu (beklenen 150,00 TL)", "CartPage", "expectTotal", ["150,00 TL"], ekranGoruntusu("cart", "cart-total", 6)),
  ];
}

/** C5 (minimum sipariş, doküman düzeltmesi sonrası 750,00 TL) için ajan adımları. */
export function minSiparisAdimlari(): AjanAdimi[] {
  return [
    adim(1, "S1", "browser_navigate", "Giriş sayfası açıldı", "LoginPage", "goto", [], ekranGoruntusu("login", "login-username")),
    adim(2, "S2", "browser_type", "bayi1 ile giriş yapıldı", "LoginPage", "login", ["bayi1", "Demo123!"], ekranGoruntusu("login", "login-submit")),
    adim(3, "S3", "browser_click", "P-002 adedi 10 girildi ve \"Sepete ekle\" tıklandı", "CatalogPage", "addToCart", ["P-002", 10], ekranGoruntusu("catalog", "add-to-cart", 10)),
    adim(4, "S4", "browser_click", "Üst menüden sepete gidildi", "CatalogPage", "openCart", [], ekranGoruntusu("cart", "cart-total", 10)),
    adim(5, "S4", "browser_snapshot", "Minimum sipariş uyarısı doğrulandı", "CartPage", "expectMinOrderWarning", ["Minimum sipariş tutarı 750,00 TL"], ekranGoruntusu("cart", "cart-total", 10)),
    adim(6, "S4", "browser_snapshot", "\"Siparişi onayla\" pasif doğrulandı", "CartPage", "expectCheckoutDisabled", [], ekranGoruntusu("cart", "cart-total", 10)),
  ];
}

export const MIN_SIPARIS_KAYNAK = { "Minimum sipariş tutarı 750,00 TL": "\"Minimum sipariş tutarı 750,00 TL\" uyarısı gösterilir" };
export const C2_KAYNAK_METINLERI = C2_KAYNAK;

export function yerelGecti(run_id: string): YerelKontrol {
  return {
    tsc: true,
    eslint: true,
    ast_guard: true,
    tekrar: 3,
    sonuc: "passed",
    sinif: "gecti",
    aciklama: null,
    run_id,
    duzeltme_turu: 0,
    basarisiz: [],
    gecen: 3,
    toplam: 3,
    hata: null,
  };
}

/** LocalForge PR'ının check'leri: merge kapısı `local-ci` (TP_REQUIRED_CHECKS boş). */
function localCi(durum: PrCheck["durum"], aciklama: string): PrCheck[] {
  return [{ ad: "local-ci", durum, zorunlu: true, url: null, aciklama }];
}

function scriptler(): ScriptDetay[] {
  return [
    {
      id: "scr-3",
      case_ids: ["case-1-3"],
      requirement_key: "TPD-1",
      baslik: "6 adet kampanyalı üründe bedava ürün verilmez",
      dosya_yolu: "demo-app/e2e/tests/tpd-1/c3-kampanya-6-adet-bedava-yok.spec.ts",
      branch: "tp/case-9e0c51d2",
      // Assertion kırmızı → otomatik onarım yok, PR açılmaz, insana düşer (script: checking → blocked).
      durum: "blocked",
      pr: null,
      failure_id: "fail-4",
      pass_at_1: false,
      zayif_test: false,
      break_verify: {
        durum: "not_started",
        asamalar: (["baseline", "broken", "restored"] as const).map((ad) => ({ ad, sonuc: "pending" as const, run_id: null, zaman: null })),
      },
      yerel_sinif: "defect_adayi",
      mode: "replay",
      olusturma: t(30, "11:35"),
      hata: null,
      kod: SINIR_TEST_KODU,
      adimlar: sinirAdimlari(),
      eslemeler: eslemeler(sinirAdimlari(), { "6": "Sepet sayacı 6 olur", "0,00 TL": "indirim 0,00 TL", "150,00 TL": "toplam 150,00 TL" }),
      yerel_kontrol: {
        tsc: true,
        eslint: true,
        ast_guard: true,
        tekrar: 3,
        sonuc: "failed",
        sinif: "defect_adayi",
        aciklama:
          "Assertion hatası: uygulama onaylı case'in beklenen değerini vermiyor (3/3 tekrarda aynı). Locator ve eşleme doğru; otomatik düzeltme yapılmaz, beklenen değer değiştirilmez. İnsan incelemesine gider; Faz 4 triage bunu bug taslağına çevirir.",
        run_id: "run-108",
        duzeltme_turu: 0,
        basarisiz: [
          {
            test_adi: "TPD-1 C3 · 6 adet kampanyalı üründe bedava ürün verilmez",
            hata_mesaji: "expect(getByTestId('cart-line-P-001').getByTestId('free-qty')).toHaveText(\"0\")",
            beklenen: "bedava adet 0 · indirim 0,00 TL",
            gerceklesen: "bedava adet 1 · indirim 25,00 TL",
            adim: "S4: Üst menüden sepete git",
            // Core repeat-each tekrarlarını tek satıra toplar: 3 tekrarın 3'ünde aynı fark (triage sinyaliyle aynı).
            tekrar: 3,
          },
        ],
        gecen: 0,
        toplam: 3,
        hata: null,
      },
      merge_engelleri: null,
      uyarilar: [],
      engel: { tur: "defect_candidate", neden: "Yerel kontrolde assertion kırmızı: defect adayı (onarım yok)." },
    },
    {
      id: "scr-2",
      case_ids: ["case-1-2"],
      requirement_key: "TPD-1",
      baslik: TPD1_GOLDEN_CASELER[1].title,
      dosya_yolu: "demo-app/e2e/tests/tpd-1/c2-kampanya-7-adet-1-bedava.spec.ts",
      branch: "tp/case-3f2a9c1e",
      // core: pr_open; "merge'e hazır" PR + CI + kırarak doğrulamadan türetilir.
      durum: "pr_open",
      pr: {
        number: 12,
        // LocalForge'un tarayıcıda açılan bir PR sayfası yok: PR numarası düz metin gösterilir.
        url: null,
        baslik: "test(TPD-1): 7 adet kampanyalı üründe 1 adet bedava [AI-generated]",
        branch: "tp/case-3f2a9c1e",
        durum: "open",
        ci: "passed",
        icerik_hash: "",
        head_sha: "",
        checks: localCi("passed", "tsc ✓ · eslint ✓ · AST koruması ✓ · Playwright 3/3"),
        forge: "local",
        // core `pull_request.govde` (codegen prbody): izlenebilirlik, eşleme, yerel kontrol, denetim.
        govde: [
          "## İzlenebilirlik",
          "- Story: `TPD-1` · Case: C2 (onaylı hash `3f2a9c1e`)",
          "- Üretim: **REPLAY** (golden `f2-kod-hatasi/TPD-1-C2`)",
          "## Eşleme",
          "| Adım | Page object | Metot |",
          "|---|---|---|",
          "| S1 | LoginPage | login |",
          "| S2 | CatalogPage | addToCart |",
          "| S3 | CartPage | expectFreeQuantity |",
          "## Yerel kontrol",
          "- tsc ✓ · eslint ✓ · AST koruması ✓ · Playwright `--repeat-each=3` 3/3",
          "## Denetim",
          "- Zincir başı: `9c1e3f2a…`",
        ].join("\n"),
        dal: { geride: false, guncelleme: null, neden: null },
      },
      pass_at_1: true,
      zayif_test: false,
      break_verify: {
        durum: "passed",
        asamalar: [
          { ad: "baseline", sonuc: "passed", run_id: "run-101", zaman: t(30, "11:20") },
          { ad: "broken", sonuc: "failed", run_id: "run-102", zaman: t(30, "11:22") },
          { ad: "restored", sonuc: "passed", run_id: "run-103", zaman: t(30, "11:24") },
        ],
      },
      yerel_sinif: "gecti",
      mode: "replay",
      olusturma: t(30, "11:05"),
      hata: null,
      kod: KAMPANYA_TEST_KODU,
      adimlar: kampanyaAdimlari(),
      eslemeler: eslemeler(kampanyaAdimlari(), C2_KAYNAK),
      yerel_kontrol: yerelGecti("run-100"),
      merge_engelleri: null,
      uyarilar: [],
      engel: null,
    },
    {
      id: "scr-1",
      case_ids: ["case-1-1"],
      requirement_key: "TPD-1",
      baslik: TPD1_GOLDEN_CASELER[0].title,
      dosya_yolu: "demo-app/e2e/tests/tpd-1/c1-sepete-ekle.spec.ts",
      branch: "tp/case-1b7d40aa",
      // Sepete ekleme testi kampanyaya bağlı değil: BREAK_CAMPAIGN=1 ile de yeşil kaldı → zayıf
      // test işareti, merge kapısı kapalı (sahte "kırmızı" gösterilmez).
      durum: "pr_open",
      pr: {
        number: 11,
        url: null,
        baslik: "test(TPD-1): sepete ekle ile sepet sayacı artar [AI-generated]",
        branch: "tp/case-1b7d40aa",
        durum: "open",
        ci: "passed",
        icerik_hash: "",
        head_sha: "",
        checks: localCi("passed", "tsc ✓ · eslint ✓ · AST koruması ✓ · Playwright 3/3"),
        forge: "local",
      },
      pass_at_1: true,
      zayif_test: true,
      break_verify: {
        durum: "weak",
        asamalar: [
          { ad: "baseline", sonuc: "passed", run_id: "run-097", zaman: t(30, "10:50") },
          { ad: "broken", sonuc: "passed", run_id: "run-098", zaman: t(30, "10:52") },
          { ad: "restored", sonuc: "passed", run_id: "run-099", zaman: t(30, "10:54") },
        ],
      },
      yerel_sinif: "gecti",
      mode: "replay",
      olusturma: t(30, "10:45"),
      hata: null,
      kod: SEPET_TEST_KODU,
      adimlar: sepetAdimlari(),
      eslemeler: eslemeler(sepetAdimlari(), { "1": "Sepet sayacı 1 olur" }),
      yerel_kontrol: yerelGecti("run-096"),
      merge_engelleri: null,
      uyarilar: [],
      engel: null,
    },
    // 009: aynı onaylı case (C2) Android, iOS ve Windows'ta: platform başına ayrı script ve PR.
    ...uygulamaScriptleri(),
  ];
}

// ------------------------------------------------------------------ koşular ve triage

export function sonuc(id: string, test_adi: string, durum: KosuDetay["sonuclar"][number]["durum"], sure_ms: number, ek: Partial<KosuDetay["sonuclar"][number]> = {}) {
  return { id, test_adi, durum, sure_ms, retry: 0, hata_mesaji: null, failure_id: null, case_id: null, ...ek };
}

export const TEST_C1 = `TPD-1 C1 · ${TPD1_GOLDEN_CASELER[0].title}`;
export const TEST_C2 = `TPD-1 C2 · ${TPD1_GOLDEN_CASELER[1].title}`;
export const TEST_C3 = "TPD-1 C3 · 6 adet kampanyalı üründe bedava ürün verilmez";
const TEST_LOGIN = "Bayi girişi · hatalı parola mesajı (elle yazılmış)";

export function kosu(
  id: string,
  tetik: KosuDetay["tetik"],
  kaynak: KosuDetay["kaynak"],
  baslangic: string,
  sonuclar: KosuDetay["sonuclar"],
  ek: Partial<KosuDetay> = {},
): KosuDetay {
  const basarisiz = sonuclar.filter((s) => s.durum === "failed").length;
  return {
    id,
    tetik,
    kaynak,
    commit: "9c41e2b",
    pr_no: null,
    durum: basarisiz ? "failed" : "passed",
    baslangic,
    sure_ms: sonuclar.reduce((a, s) => a + s.sure_ms, 0) + 14000,
    toplam: sonuclar.length,
    gecen: sonuclar.filter((s) => s.durum === "passed" || s.durum === "flaky").length,
    basarisiz,
    flaky: sonuclar.filter((s) => s.durum === "flaky").length,
    atlanan: sonuclar.filter((s) => s.durum === "skipped").length,
    // Artifact (Allure/trace) sunucusu ve Sauce hesabı henüz yok: sahte adres verilmez.
    allure_url: null,
    rapor_url: null,
    sauce_url: null,
    ci_url: null,
    break_campaign: false,
    script_id: null,
    saglik_hatasi: null,
    log_url: null,
    hata: null,
    uyarilar: [],
    sonuclar,
    // 009: örnek verideki mevcut koşular web (Playwright) koşularıdır; uygulama koşuları platformlar.ts'te.
    platform: "web",
    ...ek,
  };
}

/**
 * Koşu detayının okunur test sonucu ekranı (KosuSonuclari) için örnek ayrıntı: iki deneme, Playwright
 * adım ağacı (hatalı yol), hata konumu/snippet/stack, stdout ve ekler (gömülü küçük bir ekran
 * görüntüsü; trace dosyası sunulmuyor). Yalnız görünüm verisi: sayımlar (retry hariç
 * durum/süre) değişmez. Tasarım planı Ek B2.
 */
function r107C2Ayrintisi(): Partial<KosuDetay["sonuclar"][number]> {
  const HATA = "expect(getByTestId('cart-line-free-P-001')).toHaveText(\"1\")\nBeklenen: \"1\"\nGerçekleşen: \"0\"";
  const KONUM = "tests/tpd-1/c2-kampanya-7-adet-1-bedava.spec.ts:24:5";
  const deneme = (n: number, sure_ms: number) => ({
    deneme: n,
    sonuc: "failed",
    sure_ms,
    hata: {
      mesaj: HATA,
      konum: KONUM,
      snippet: "  22 |   await cart.open();\n  23 |   // 7 adette 1 bedava (AC2)\n> 24 |   await cart.expectFreeQty(\"P-001\", \"1\");\n     |     ^",
      stack: `Error: ${HATA.split("\n")[0]}\n    at CartPage.expectFreeQty (pages/CartPage.ts:41:7)\n    at ${KONUM}`,
    },
    adimlar: [
      { baslik: "Bayi olarak giriş yap", sure_ms: 820 },
      { baslik: "Kataloğu aç", sure_ms: 410 },
      {
        baslik: "Kampanyalı üründen 7 adet sepete ekle",
        sure_ms: 1900,
        adimlar: [
          { baslik: "Adet: 7", sure_ms: 300 },
          { baslik: "Sepete ekle", sure_ms: 1600 },
        ],
      },
      {
        baslik: "Sepette bedava ürün satırını doğrula",
        sure_ms: sure_ms - 3130,
        adimlar: [{ baslik: "expect.toHaveText", sure_ms: sure_ms - 3130, hata: HATA }],
      },
    ],
    stdout: n === 0 ? "[sepet] P-001 × 7 eklendi\n[sepet] bedava satırı: 0 adet" : null,
    stderr: null,
  });
  return {
    retry: 1,
    dosya: "tests/tpd-1/c2-kampanya-7-adet-1-bedava.spec.ts",
    denemeler: [deneme(0, 6200), deneme(1, 6150)],
    ekler: [
      { ad: "screenshot", tur: "image/png", url: ORNEK_EK_EKRANI, deneme: 1 },
      { ad: "trace", tur: "application/zip", url: null, deneme: 1 },
    ],
  };
}

/** Yerel CI adımları (toolchain `/check` şekli): run kırmızı, AST koruması bu koşuda atlandı. */
function r107CiAdimlari(): KosuDetay["adimlar"] {
  return {
    deps: { ok: true, atlandi: false },
    tsc: { ok: true, atlandi: false },
    eslint: { ok: true, atlandi: false },
    ast_guard: { ok: true, atlandi: true, reason: "gece koşusunda kod değişikliği yok" },
    run: { ok: false, atlandi: false, error: "1 test başarısız (TPD-1 C2)" },
  };
}

function kosular(): KosuDetay[] {
  return [
    kosu(
      "run-107",
      "nightly",
      "local",
      t(30, "02:00"),
      [
        sonuc("r107-1", TEST_C1, "passed", 3100, { case_id: "case-1-1" }),
        sonuc("r107-2", TEST_C2, "failed", 6200, {
          hata_mesaji:
            "expect(getByTestId('cart-line-free-P-001')).toHaveText(\"1\")\nBeklenen: \"1\"\nGerçekleşen: \"0\"",
          failure_id: "fail-1",
          triage_sinifi: "product_defect",
          triage_alt_tur: "assertion",
          case_id: "case-1-2",
          ...r107C2Ayrintisi(),
        }),
        sonuc("r107-3", TEST_LOGIN, "passed", 2200),
      ],
      { commit: "b7d1f05", break_campaign: true, adimlar: r107CiAdimlari() },
    ),
    kosu(
      "run-106",
      "deploy",
      "sauce",
      t(29, "17:30"),
      [
        sonuc("r106-1", TEST_C1, "failed", 9800, {
          hata_mesaji:
            "locator.click: Timeout 5000ms exceeded.\nwaiting for getByTestId('product-card-P-001').getByTestId('add-to-cart')",
          failure_id: "fail-2",
          triage_sinifi: "test_maintenance",
          triage_alt_tur: "locator",
          case_id: "case-1-1",
        }),
        sonuc("r106-2", TEST_C2, "failed", 9800, {
          hata_mesaji: "locator.click: Timeout 5000ms exceeded. (aynı imza: add-to-cart)",
          failure_id: "fail-2",
          triage_sinifi: "test_maintenance",
          triage_alt_tur: "locator",
          case_id: "case-1-2",
        }),
        sonuc("r106-3", TEST_LOGIN, "passed", 2600),
      ],
      { commit: "e03a7c9" },
    ),
    kosu(
      "run-105",
      "nightly",
      "sauce",
      t(29, "02:00"),
      [
        sonuc("r105-1", TEST_C1, "passed", 3400, { case_id: "case-1-1" }),
        sonuc("r105-2", TEST_C2, "flaky", 7200, { retry: 1, case_id: "case-1-2" }),
        sonuc("r105-3", TEST_LOGIN, "passed", 2500),
      ],
      { commit: "9c41e2b" },
    ),
    kosu("run-104", "push", "local", t(28, "16:12"), [sonuc("r104-1", TEST_C1, "passed", 3000, { case_id: "case-1-1" }), sonuc("r104-2", TEST_LOGIN, "passed", 2100)], {
      commit: "9c41e2b",
    }),
    // Yerel kontrol (toolchain-worker + test-runner, repeat-each 3): C3 assertion'da kırmızı → defect adayı.
    kosu(
      "run-108",
      "local_check",
      "local",
      t(30, "11:38"),
      [
        sonuc("r108-1", TEST_C3, "failed", 6400, {
          hata_mesaji:
            "expect(getByTestId('cart-line-P-001').getByTestId('free-qty')).toHaveText(\"0\")\nBeklenen: \"0\"\nGerçekleşen: \"1\"",
          failure_id: "fail-4",
          triage_sinifi: "product_defect",
          triage_alt_tur: "assertion",
          case_id: "case-1-3",
        }),
      ],
      // Sauce çipi örneği (tasarım planı Ek B2): run-107'ye konamaz — gece koşusu CI tetiği olduğundan yol
      // haritasının 9. adımını (Sauce/yerel yedek) değiştirirdi; yerel kontrol CI sayımına girmez.
      { commit: "9e0c51d", script_id: "scr-3", sauce_durum: "error", sauce_neden: "oturum sınırı dolu" },
    ),
    // Ortam hatası: sağlık yoklaması başarısız, Playwright başlamadı (tests=[]); triage environment.
    kosu("run-109", "manual", "local", t(30, "03:00"), [], {
      commit: "9c41e2b",
      durum: "error",
      saglik_hatasi: "web yanıt vermedi (http://demo-web:8080/: bağlantı reddedildi)",
      hatalar: [{ id: "fail-3", test_adi: "Koşu öncesi sağlık yoklaması", sinif: "environment", alt_tur: "saglik", ozet: "Onarım/bug yok" }],
    }),
    kosu("run-103", "break_verify", "local", t(30, "11:24"), [sonuc("r103-1", TEST_C2, "passed", 5900, { case_id: "case-1-2" })], {
      commit: "4ac0e11",
      pr_no: 12,
      script_id: "scr-2",
    }),
    kosu(
      "run-102",
      "break_verify",
      "local",
      t(30, "11:22"),
      [
        sonuc("r102-1", TEST_C2, "failed", 6100, {
          hata_mesaji: "Beklenen: \"25,00 TL\" · Gerçekleşen: \"0,00 TL\" (BREAK_CAMPAIGN=1)",
          case_id: "case-1-2",
        }),
      ],
      { commit: "4ac0e11", pr_no: 12, break_campaign: true, script_id: "scr-2" },
    ),
    kosu("run-101", "break_verify", "local", t(30, "11:20"), [sonuc("r101-1", TEST_C2, "passed", 5800, { case_id: "case-1-2" })], {
      commit: "4ac0e11",
      pr_no: 12,
      script_id: "scr-2",
    }),
    kosu("run-100", "local_check", "local", t(30, "11:12"), [sonuc("r100-1", TEST_C2, "passed", 5700, { case_id: "case-1-2" })], {
      commit: "4ac0e11",
      script_id: "scr-2",
    }),
    // PR #11 (scr-1) kırarak doğrulama koşuları: kırılmada da yeşil → zayıf test.
    kosu("run-099", "break_verify", "local", t(30, "10:54"), [sonuc("r099-1", TEST_C1, "passed", 3200, { case_id: "case-1-1" })], {
      commit: "1b7d40a",
      pr_no: 11,
      script_id: "scr-1",
    }),
    kosu("run-098", "break_verify", "local", t(30, "10:52"), [sonuc("r098-1", TEST_C1, "passed", 3300, { case_id: "case-1-1" })], {
      commit: "1b7d40a",
      pr_no: 11,
      break_campaign: true,
      script_id: "scr-1",
    }),
    kosu("run-097", "break_verify", "local", t(30, "10:50"), [sonuc("r097-1", TEST_C1, "passed", 3100, { case_id: "case-1-1" })], {
      commit: "1b7d40a",
      pr_no: 11,
      script_id: "scr-1",
    }),
    kosu("run-096", "local_check", "local", t(30, "10:47"), [sonuc("r096-1", TEST_C1, "passed", 3000, { case_id: "case-1-1" })], {
      commit: "1b7d40a",
      script_id: "scr-1",
    }),
    // 009: Android gece koşusu (platform kontrolü + sayfa kaynağı kanıtlı triage).
    ...uygulamaKosulari(),
  ];
}

export const SAGLIK_OK = {
  ok: true,
  zaman: t(30, "02:00"),
  web: { url: "http://demo-web:8080/", status: 200, ms: 41, hata: null },
  api: { url: "http://demo-api:8000/health", status: 200, ms: 12, hata: null },
  hata: null,
};

function hatalar(): HataAnalizi[] {
  return [
    {
      id: "fail-1",
      run_id: "run-107",
      test_adi: TEST_C2,
      hata_imzasi: "assertion:cart-line-free-P-001:expected=1:actual=0",
      hata_mesaji: "Beklenen: \"1\" · Gerçekleşen: \"0\"",
      sinif: "product_defect",
      alt_tur: "assertion",
      kural: "product_defect",
      eslesen_sinyaller: [
        { kod: "health_ok", aciklama: "Koşu öncesi sağlık kontrolü başarılı (ortam sorunu değil)", kaynak: "saglik", kanit: "web 200 · api 200" },
        { kod: "not_flaky", aciklama: "Yeniden denemede de aynı sonuç (flaky değil)", kaynak: "playwright-json", kanit: "retry 1: failed · retry 2: failed" },
        { kod: "locator_resolved", aciklama: "Locator tek eleman buldu; sayfa yapısı beklenen", kaynak: "aria-snapshot", kanit: '- row "Portakal Gazozu 1L 7 adet":\n  - status "Bedava": 0 adet' },
        { kod: "assertion_mismatch", aciklama: "cart-line-free-P-001 beklenen \"1\", gerçekleşen \"0\"", kaynak: "trace", kanit: "expect(getByTestId('cart-line-free-P-001')).toHaveText('1')" },
      ],
      karar_kaynagi: "rule",
      llm_yorumu: null,
      oneri: { tur: "bug_draft", bug_draft_id: "bug-1" },
      kanit: {
        hata_mesaji: "Error: expect(locator).toHaveText(expected)\n\nLocator: getByTestId('cart-line-free-P-001')\nExpected: \"1\"\nReceived: \"0\"",
        beklenen: "1",
        gerceklesen: "0",
        konum: "tests/generated/kampanya-7-adet.spec.ts:24",
        aria_snippet: '- region "Sepet":\n  - row "Portakal Gazozu 1L 7 adet"\n  - status "Bedava": 0 adet\n  - status "Kampanya indirimi": 0,00 TL',
        locator_probe: null,
        saglik: SAGLIK_OK,
      },
      kanit_linkleri: [
        { etiket: "Allure raporu (run-107)", url: null },
        { etiket: "Playwright trace (run-107)", url: null },
      ],
      // Kural kararı: model çağrısı yok ("live"/"replay" yazılmaz).
      mode: null,
      zaman: t(30, "02:06"),
    },
    {
      id: "fail-2",
      run_id: "run-106",
      test_adi: TEST_C1,
      hata_imzasi: "locator:getByTestId(add-to-cart):0-match",
      hata_mesaji: "locator.click: Timeout 5000ms exceeded. waiting for getByTestId('add-to-cart')",
      sinif: "test_maintenance",
      alt_tur: "locator",
      kural: "test_maintenance/locator",
      eslesen_sinyaller: [
        { kod: "health_ok", aciklama: "Koşu öncesi sağlık kontrolü başarılı", kaynak: "saglik", kanit: "web 200 · api 200" },
        { kod: "locator_zero", aciklama: "getByTestId('add-to-cart') 0 eleman döndürdü", kaynak: "playwright-json", kanit: "waiting for getByTestId('add-to-cart')" },
        { kod: "intent_present", aciklama: "Niyete uyan eleman ürün kartında var: button \"Sepete ekle\"", kaynak: "aria-snapshot", kanit: '- article "Portakal Gazozu 1L":\n  - button "Sepete ekle"' },
        { kod: "testid_changed", aciklama: "DOM'daki data-testid farklı: cart-add", kaynak: "locator-probe", kanit: "matches=1 · test_id=cart-add · scope=product-card-P-001" },
      ],
      karar_kaynagi: "rule",
      llm_yorumu: null,
      oneri: {
        tur: "locator_fix",
        dosya: "demo-app/e2e/pages/catalog/locators.ts",
        anahtar: "addToCart",
        eski_test_id: "add-to-cart",
        yeni_test_id: "cart-add",
        rol: "button",
        ad: "Sepete ekle",
        within: "product-card-",
        scope_test_id: "product-card-P-001",
        dogrulama: [
          "Rol + ad eşleşmesi kapsayıcıda (product-card-P-001) tek eleman verdi",
          "Son yeşil koşunun aria snapshot'ındaki rol + ad ile aynı",
          "Ölçüm çalışan uygulamada, commit eşleşiyor",
        ],
        aria_dogrulama: { eslesti: true, aciklama: "run-105 (son yeşil): button \"Sepete ekle\" ürün kartında mevcut", run_id: "run-105" },
        ast_guard: null,
        yerel_kontrol: null,
        etkilenen_testler: [
          { test_adi: TEST_C1, durum: null },
          { test_adi: TEST_C2, durum: null },
          { test_adi: "Sepete ekle · sepet sayacı artar (elle yazılmış)", durum: null },
        ],
        degisen_dosyalar: [],
        yama: null,
        neden: null,
        durum: "proposed",
        pr: null,
      },
      kanit: {
        hata_mesaji: "locator.click: Timeout 5000ms exceeded.\nCall log:\n  - waiting for getByTestId('product-card-P-001').getByTestId('add-to-cart')",
        beklenen: null,
        gerceklesen: null,
        konum: "e2e/pages/catalog/CatalogPage.ts:18",
        aria_snippet: '- article "Portakal Gazozu 1L":\n  - heading "Portakal Gazozu 1L" [level=3]\n  - spinbutton "Adet"\n  - button "Sepete ekle"',
        locator_probe: {
          rol: "button",
          ad: "Sepete ekle",
          scope_test_id: "product-card-P-001",
          matches: 1,
          test_id: "cart-add",
          olculen: "calisan_uygulama",
          uygulama_sha: "9c1e44b2a7d0",
          sha_eslesmesi: "eslesiyor",
          uyari: null,
          oneri_uretilebilir: true,
        },
        saglik: SAGLIK_OK,
      },
      kanit_linkleri: [
        { etiket: "Sauce video (run-106)", url: null },
        { etiket: "Allure raporu (run-106)", url: null },
      ],
      mode: null,
      zaman: t(29, "17:36"),
    },
    {
      // Ana yol (f2-kod-hatasi): kod üretiminin C3 defect adayı. Test onaylı case'i (6 adette bedava
      // yok) doğruluyor, uygulama bedava veriyor → assertion farkı, sayfa yapısı beklenen.
      id: "fail-4",
      run_id: "run-108",
      test_adi: TEST_C3,
      hata_imzasi: "assertion:cart-line-free-P-001:expected=0:actual=1",
      hata_mesaji: "Beklenen: \"0\" · Gerçekleşen: \"1\"",
      sinif: "product_defect",
      alt_tur: "assertion",
      kural: "product_defect",
      eslesen_sinyaller: [
        { kod: "health_ok", aciklama: "Koşu öncesi sağlık kontrolü başarılı", kaynak: "saglik", kanit: "web 200 · api 200" },
        { kod: "consistent", aciklama: "3 tekrarın 3'ünde aynı assertion farkı (flaky değil)", kaynak: "playwright-json", kanit: "repeat-each 3: failed ×3" },
        { kod: "locator_resolved", aciklama: "Locator tek eleman buldu; sayfa yapısı beklenen", kaynak: "aria-snapshot", kanit: '- row "Portakal Gazozu 1L 6 adet":\n  - status "Bedava": 1 adet' },
        { kod: "assertion_mismatch", aciklama: "cart-line-free-P-001 beklenen \"0\", gerçekleşen \"1\"", kaynak: "trace", kanit: "expect(getByTestId('cart-line-free-P-001')).toHaveText('0')" },
      ],
      karar_kaynagi: "rule",
      llm_yorumu: null,
      oneri: { tur: "bug_draft", bug_draft_id: "bug-4" },
      kanit: {
        hata_mesaji: "Error: expect(locator).toHaveText(expected)\n\nLocator: getByTestId('cart-line-free-P-001')\nExpected: \"0\"\nReceived: \"1\"",
        beklenen: "0",
        gerceklesen: "1",
        konum: "tests/generated/kampanya-6-adet.spec.ts:21",
        aria_snippet: '- row "Portakal Gazozu 1L 6 adet":\n  - status "Bedava": 1 adet\n  - status "Kampanya indirimi": 25,00 TL',
        locator_probe: null,
        saglik: SAGLIK_OK,
      },
      kanit_linkleri: [{ etiket: "Yerel kontrol koşusu (run-108)", url: null }],
      mode: null,
      zaman: t(30, "11:39"),
      script_id: "scr-3",
    },
    {
      // Ortam: sağlık yoklaması başarısız → kural 1, onarım/bug yok (LLM ezemez).
      id: "fail-3",
      run_id: "run-109",
      test_adi: TEST_C1,
      hata_imzasi: "environment:saglik:web",
      hata_mesaji: "Koşu öncesi sağlık yoklaması başarısız: http://demo-web:8080/ yanıt vermedi",
      sinif: "environment",
      alt_tur: "saglik",
      kural: "environment",
      eslesen_sinyaller: [
        { kod: "health_failed", aciklama: "Sağlık yoklaması başarısız (saglik.ok=false); Playwright başlatılmadı", kaynak: "saglik", kanit: "web: bağlantı reddedildi · api 200" },
      ],
      karar_kaynagi: "rule",
      llm_yorumu: null,
      oneri: null,
      kanit: {
        hata_mesaji: null,
        beklenen: null,
        gerceklesen: null,
        konum: null,
        aria_snippet: null,
        locator_probe: null,
        saglik: {
          ok: false,
          zaman: t(30, "03:00"),
          web: { url: "http://demo-web:8080/", status: null, ms: 5000, hata: "bağlantı reddedildi" },
          api: { url: "http://demo-api:8000/health", status: 200, ms: 14, hata: null },
          hata: "web yanıt vermedi",
        },
      },
      kanit_linkleri: [{ etiket: "Koşu günlüğü (run-109)", url: null }],
      mode: null,
      zaman: t(30, "03:00"),
    },
    // 009: Android kimlik değişikliği (hata anı sayfa kaynağı) → kimlik onarım önerisi.
    ...uygulamaHatalari(),
  ];
}

// ------------------------------------------------------------------ bug taslakları

function bugTaslaklari(): BugTaslagi[] {
  return [
    {
      // rules/replay/bug_draft/golden/kirma-kampanya/HATA.json
      id: "bug-1",
      kaynak: "triage",
      failure_id: "fail-1",
      finding_id: null,
      icerik: {
        summary: "Sepet: 7 adet Portakal Gazozu sepete eklendiğinde bedava adet 1 beklenirken 0 görünüyor",
        steps: ["bayi1 / Demo123! ile giriş yap", "\"Portakal Gazozu 1L\" için 7 adet gir ve \"Sepete ekle\" butonuna bas", "Üst menüden sepete git", "P-001 satırındaki bedava adedi kontrol et"],
        expected: "P-001 satırında bedava adet 1 (TPD-1 AC2: 7 adette 1 bedava)",
        actual: "P-001 satırında bedava adet 0 görünüyor (assertion: beklenen \"1\", gerçekleşen \"0\")",
        environment: "Yerel demo ortamı, Chromium · gece koşusu run-107 · commit b7d1f05",
        evidence: [
          { tur: "trace", url: null, etiket: "Playwright trace (run-107)" },
          { tur: "allure", url: null, etiket: "Allure raporu (run-107)" },
        ],
        story_key: "TPD-1",
        test_case_key: "TPD-10",
        severity_suggestion: "critical",
        labels: ["AI-generated"],
      },
      // jira-sim seed: TPD-5 6 adet sınır hatasını anlatan açık Bug (JQL "kampanya indirimi" bunu döndürür).
      mukerrer_arama: {
        durum: "yapildi",
        jql: 'project = TPD AND issuetype = Bug AND statusCategory != Done AND text ~ "kampanya indirimi"',
        oneri: "new",
        oneri_link_key: null,
        mode: "replay",
        degerlendirme: { durum: "pending", etiket: "canlı değerlendirme bekliyor" },
        hata: null,
      },
      jira_browse_url: JIRA,
      degerlendirme: { durum: "pending", etiket: "canlı değerlendirme bekliyor" },
      mukerrer_adaylari: [
        {
          key: "TPD-5",
          summary: SEED_BUG["TPD-5"],
          durum: "To Do",
          olasilik: "medium",
          sira: 1,
          url: `${JIRA}/TPD-5`,
          gerekce: "Aynı ürün ve aynı kampanya satırı ama ters belirti: TPD-5'te 6 adette erken bedava var, bu koşuda 7 adette bedava hiç verilmiyor (kampanya kırılması açık).",
          sinyaller: [],
        },
        {
          key: "TPD-6",
          summary: SEED_BUG["TPD-6"],
          durum: "In Progress",
          olasilik: "low",
          sira: 2,
          url: `${JIRA}/TPD-6`,
          gerekce: "Farklı alan: sipariş geçmişindeki tarih sıralaması; sepet ve kampanya hesabıyla ilgisi yok.",
          sinyaller: [],
        },
      ],
      karar: null,
      durum: "draft",
      link_key: null,
      icerik_hash: "",
      onaylayan: null,
      onay_zamani: null,
      jira_key: null,
      mode: "replay",
      olusturma: t(30, "02:07"),
    },
    {
      // rules/replay/bug_draft/golden/f4-kredi-limiti/HATA.json
      id: "bug-2",
      kaynak: "consistency",
      failure_id: null,
      finding_id: "fnd-3",
      icerik: {
        summary: "Sepet: Kredi limiti aşıldığında \"Kredi limiti aşıldı\" uyarısı gösterilmiyor ve sipariş onaylanabiliyor",
        steps: ["bayi2 / Demo123! (kredi limiti 500,00 TL) ile giriş yap", "\"Şeftalili Soğuk Çay 1L\" için 25 adet gir ve \"Sepete ekle\" butonuna bas (toplam 750,00 TL: minimum sipariş tutarını karşılar, kredi limitini aşar)", "Üst menüden sepete git", "Uyarıları ve \"Siparişi onayla\" butonunu kontrol et"],
        expected: "Sepette \"Kredi limiti aşıldı\" uyarısı gösterilir ve sipariş onaylanamaz (TPD-1 AC4)",
        actual: "Kredi limiti uyarısı yok ve \"Siparişi onayla\" butonu aktif; sepet hesabı yalnızca minimum sipariş uyarısı üretiyor, kredi limiti kontrolü yok (pricing.py:97)",
        environment: "Yerel demo ortamı · tutarlılık denetimi",
        evidence: [
          { tur: "code", url: null, etiket: `${REPO} · api/src/demoapp_api/pricing.py:97` },
          { tur: "data", url: "#fnd-3", etiket: "bayi.kredi_limiti sorgusu" },
        ],
        story_key: "TPD-1",
        test_case_key: null,
        severity_suggestion: "critical",
        labels: ["AI-generated"],
      },
      mukerrer_adaylari: [],
      karar: "new",
      durum: "published",
      link_key: null,
      icerik_hash: "",
      onaylayan: "testci",
      onay_zamani: t(30, "09:58"),
      // Simülatörde ürünün oluşturduğu ilk kayıt (seed TPD-1..TPD-7).
      jira_key: "TPD-8",
      jira_url: `${JIRA}/TPD-8`,
      jira_browse_url: JIRA,
      mukerrer_arama: { durum: "yapildi", jql: 'project = TPD AND issuetype = Bug AND statusCategory != Done AND text ~ "kredi limiti"', oneri: "new", oneri_link_key: null, mode: "replay", hata: null },
      mode: "replay",
      olusturma: t(30, "09:46"),
    },
    kampanyaKodHatasiTaslagi(),
    c3DefectTaslagi(),
  ];
}

/**
 * Ana yol: F2 kampanya bulgusuna "Kod hatalı" (fnd-1) → bug taslağı. Core `ensure_bug_draft` gibi
 * şablonla, bulgunun doğrulanmış kanıtından üretilir (model çağrısı yok: `mode: null`). Taslak onay
 * bekler; Faz 4'te C3 defect adayının triage taslağı ise jira-sim TPD-5'i mükerrer adayı bulur.
 */
function kampanyaKodHatasiTaslagi(): BugTaslagi {
  const f = TPD1_F.kampanya;
  const kod = KAMPANYA_KOD.kind === "code" ? KAMPANYA_KOD : null;
  const yer = kod ? `${kod.repo} · ${kod.path}:${kod.line}` : "kanıt";
  const ac2 = acMetni(TPD1_SEED_AC, "AC2") ?? "AC2";
  return {
    id: "bug-3",
    kaynak: "consistency",
    failure_id: null,
    finding_id: "fnd-1",
    icerik: {
      summary: `TPD-1 AC2: ${f.claim}`.slice(0, 200),
      steps: [
        `Kodda ${yer} (commit main) satırını açın${kod ? `: \`${kod.snippet.trim()}\`` : ""}`,
        `Dokümandaki beklenen davranışı (${ac2}) uygulamada deneyin`,
        `Gözlenen: ${f.observed.slice(0, 300)}`,
      ],
      expected: ac2,
      actual: f.observed,
      environment: "Tutarlılık denetimi · demo-app@main",
      evidence: [{ tur: "code", url: null, etiket: yer }],
      story_key: "TPD-1",
      test_case_key: null,
      severity_suggestion: "major",
      labels: ["AI-generated"],
    },
    // Faz 4: tutarlılık taslakları da aynı JQL + dup_rank aramasından geçer. F2 (6 adette erken
    // bedava) jira-sim TPD-5'in ta kendisidir: öneri "bağla".
    mukerrer_arama: {
      durum: "yapildi",
      jql: 'project = TPD AND issuetype = Bug AND statusCategory != Done AND text ~ "kampanya"',
      oneri: "link",
      oneri_link_key: "TPD-5",
      mode: "replay",
      degerlendirme: { durum: "pending", etiket: "canlı değerlendirme bekliyor" },
      hata: null,
    },
    mukerrer_adaylari: [
        {
          key: "TPD-5",
          summary: SEED_BUG["TPD-5"],
          durum: "To Do",
          olasilik: "high",
          sira: 1,
          url: `${JIRA}/TPD-5`,
          gerekce: "Aynı kural farkı: bulgu kodun 6 adette 1 bedava verdiğini (campaign.py:23) söylüyor; TPD-5 de kampanyanın bir adet erken, 6. adette başladığını anlatıyor.",
          sinyaller: [],
        },
        {
          key: "TPD-6",
          summary: SEED_BUG["TPD-6"],
          durum: "In Progress",
          olasilik: "low",
          sira: 2,
          url: `${JIRA}/TPD-6`,
          gerekce: "Farklı alan: sipariş geçmişindeki tarih sıralaması; sepet ve kampanya hesabıyla ilgisi yok.",
          sinyaller: [],
        },
      ],
    jira_browse_url: JIRA,
    karar: null,
    durum: "draft",
    link_key: null,
    icerik_hash: "",
    onaylayan: null,
    onay_zamani: null,
    jira_key: null,
    mode: null,
    olusturma: t(30, "09:41"),
  };
}

/** C3 defect adayının triage taslağı: JQL + dup_rank TPD-5'i en olası aday bulur (öneri: bağla). */
function c3DefectTaslagi(): BugTaslagi {
  return {
    id: "bug-4",
    kaynak: "triage",
    failure_id: "fail-4",
    finding_id: null,
    icerik: {
      summary: "Sepet: 6 adet Portakal Gazozu sepete eklendiğinde bedava adet 0 beklenirken 1 görünüyor",
        steps: ["bayi1 / Demo123! ile giriş yap", "\"Portakal Gazozu 1L\" için 6 adet gir ve \"Sepete ekle\" butonuna bas", "Üst menüden sepete git", "P-001 satırındaki bedava adedi, indirimi ve toplamı kontrol et"],
        expected: "P-001 satırında bedava adet 0; indirim 0,00 TL, toplam 150,00 TL (TPD-1 AC2: bedava 7. adette başlar)",
        actual: "P-001 satırında bedava adet 1 görünüyor (assertion: beklenen \"0\", gerçekleşen \"1\")",
        environment: "Yerel demo ortamı, Chromium · yerel kontrol run-108 · commit 9e0c51d",
      evidence: [
        { tur: "trace", url: null, etiket: "Playwright trace (run-108)" },
        { tur: "screenshot", url: null, etiket: "Hata anı ekran görüntüsü (run-108)" },
      ],
      story_key: "TPD-1",
      test_case_key: "TPD-11",
      severity_suggestion: "critical",
      labels: ["AI-generated"],
    },
    mukerrer_arama: {
      durum: "yapildi",
      jql: 'project = TPD AND issuetype = Bug AND statusCategory != Done AND text ~ "kampanya indirimi"',
      oneri: "link",
      oneri_link_key: "TPD-5",
      mode: "replay",
      degerlendirme: { durum: "pending", etiket: "canlı değerlendirme bekliyor" },
      hata: null,
    },
    mukerrer_adaylari: [
        {
          key: "TPD-5",
          summary: SEED_BUG["TPD-5"],
          durum: "To Do",
          olasilik: "high",
          sira: 1,
          url: `${JIRA}/TPD-5`,
          gerekce: "Aynı belirti: TPD-5 de Portakal Gazozu 1L'de 6 adette 1 bedava verildiğini, beklenenin bedava 0 / toplam 150,00 TL olduğunu anlatıyor.",
          sinyaller: [],
        },
        {
          key: "TPD-6",
          summary: SEED_BUG["TPD-6"],
          durum: "In Progress",
          olasilik: "low",
          sira: 2,
          url: `${JIRA}/TPD-6`,
          gerekce: "Farklı alan: sipariş geçmişindeki tarih sıralaması; sepet ve kampanya hesabıyla ilgisi yok.",
          sinyaller: [],
        },
      ],
    jira_browse_url: JIRA,
    karar: null,
    durum: "draft",
    link_key: null,
    icerik_hash: "",
    onaylayan: null,
    onay_zamani: null,
    jira_key: null,
    mode: "replay",
    degerlendirme: { durum: "pending", etiket: "canlı değerlendirme bekliyor" },
    olusturma: t(30, "11:40"),
  };
}

function denetim(): MockVeri["denetim"] {
  return [
    { aktor: "analist", eylem: "requirements.sync", nesne: "TPD", ozet: "Jira'dan 4 story çekildi", zaman: t(30, "09:12") },
    { aktor: "core-worker", eylem: "ai_call", nesne: "req-tpd-1", ozet: "Ön inceleme + tutarlılık (claude-sonnet, REPLAY, 0 USD)", zaman: t(30, "09:20") },
    { aktor: "analist", eylem: "finding.decision", nesne: "fnd-1", ozet: "code_defect → bug-3", zaman: t(30, "09:41") },
    { aktor: "analist", eylem: "finding.decision", nesne: "fnd-2", ozet: "fix_doc", zaman: t(30, "09:43") },
    { aktor: "analist", eylem: "finding.decision", nesne: "fnd-3", ozet: "code_defect → bug-2", zaman: t(30, "09:45") },
    { aktor: "analist", eylem: "finding.decision", nesne: "fnd-4", ozet: "fix_doc", zaman: t(30, "09:47") },
    { aktor: "core-worker", eylem: "jira.update", nesne: "TPD-1", ozet: "Açıklama/AC güncellendi, tp-po-pending etiketi", zaman: t(30, "09:50") },
    { aktor: "testci", eylem: "bug.publish", nesne: "bug-2", ozet: "Jira'da TPD-8 açıldı", zaman: t(30, "09:58") },
    { aktor: "po@sim.local", eylem: "po.approve", nesne: "TPD-1", ozet: "tp-po-approved etiketi okundu", zaman: t(30, "10:05") },
    { aktor: "core-worker", eylem: "ai_call", nesne: "req-tpd-1", ozet: "Case üretimi: 9 case (REPLAY, 0 USD)", zaman: t(30, "10:20") },
    { aktor: "analist", eylem: "case.decision", nesne: "case-1-1", ozet: "approve", zaman: t(30, "10:31") },
    { aktor: "analist", eylem: "case.decision", nesne: "case-1-2", ozet: "approve", zaman: t(30, "10:34") },
    { aktor: "analist", eylem: "case.decision", nesne: "case-1-3", ozet: "approve", zaman: t(30, "10:37") },
    { aktor: "analist", eylem: "case.decision", nesne: "case-1-6", ozet: "reject: duplicate", zaman: t(30, "10:38") },
    { aktor: "analist", eylem: "case.decision", nesne: "case-1-4", ozet: "approve", zaman: t(30, "10:41") },
    { aktor: "analist", eylem: "publish", nesne: "TPD-1", ozet: "3 Test issue: TPD-9, TPD-10, TPD-11", zaman: t(30, "10:44") },
    { aktor: "muhendis", eylem: "code.generate", nesne: "case-1-1", ozet: "CasesToCode başlatıldı", zaman: t(30, "10:45") },
    { aktor: "core-worker", eylem: "pr.open", nesne: "PR #11", ozet: "tp/case-1b7d40aa", zaman: t(30, "10:48") },
    { aktor: "muhendis", eylem: "script.break_verify", nesne: "scr-1", ozet: "yeşil → yeşil → yeşil: zayıf test, merge kapalı", zaman: t(30, "10:54") },
    { aktor: "muhendis", eylem: "code.generate", nesne: "case-1-2", ozet: "CasesToCode başlatıldı", zaman: t(30, "11:05") },
    { aktor: "core-worker", eylem: "pr.open", nesne: "PR #12", ozet: "tp/case-3f2a9c1e", zaman: t(30, "11:18") },
    { aktor: "muhendis", eylem: "script.break_verify", nesne: "scr-2", ozet: "yeşil → kırmızı → yeşil", zaman: t(30, "11:24") },
  ];
}

// ------------------------------------------------------------------ içerik hash'leri

const h = (x: unknown) => `sha256:${sha256Hex(kanonikJson(x)).slice(0, 16)}`;

/** Gereksinimin PO'ya sunulan içeriği: başlık, açıklama, kabul kriterleri. */
export function gereksinimHash(g: Pick<GereksinimDetay, "baslik" | "aciklama" | "kabul_kriterleri">): string {
  return h({ baslik: g.baslik, aciklama: g.aciklama, kabul_kriterleri: g.kabul_kriterleri });
}

/** Bulgunun analiste gösterilen içeriği (karar alanları hariç). */
export function bulguHash(b: Bulgu): string {
  return h({
    type: b.type,
    doc_ref: b.doc_ref,
    ozet: b.ozet,
    evidence: b.evidence,
    severity: b.severity,
    mevcut_doc_text: b.mevcut_doc_text,
    suggested_doc_text: b.suggested_doc_text,
  });
}

export function bugHash(b: BugTaslagi): string {
  return h(b.icerik);
}

/** PR'daki içerik: üretilen test kodu ya da locator onarımının tek değişikliği. */
export function prIcerikHash(icerik: unknown): string {
  return h(icerik);
}

/** LocalForge head sha'sını taklit eder: dal + içerik hash'inden türetilmiş 40 haneli değer. */
export function headSha(branch: string, icerikHash: string): string {
  return sha256Hex(`${branch}\n${icerikHash}`).slice(0, 40);
}

/**
 * Tüm içerik hash'lerini güncel içerikten yeniden hesaplar (core'da her okuma güncel hash'i döner).
 * Mock her istekte çağırır; böylece içerik değişince eski hash'le gelen karar 409 alır.
 */
export function hashleriTazele(v: MockVeri): void {
  for (const g of v.gereksinimler) g.icerik_hash = gereksinimHash(g);
  for (const b of v.bulgular) b.icerik_hash = bulguHash(b);
  for (const b of v.bugTaslaklari) b.icerik_hash = bugHash(b);
  for (const s of v.scriptler) {
    if (s.pr) {
      s.pr.icerik_hash = prIcerikHash({ dosya: s.dosya_yolu, kod: s.kod });
      s.pr.head_sha = headSha(s.pr.branch, s.pr.icerik_hash);
    }
  }
  for (const f of v.hatalar) {
    const o = f.oneri;
    if (o?.tur === "locator_fix" && o.pr) {
      o.pr.icerik_hash = prIcerikHash({ dosya: o.dosya, anahtar: o.anahtar, eski: o.eski_test_id, yeni: o.yeni_test_id });
      o.pr.head_sha = headSha(o.pr.branch, o.pr.icerik_hash);
    }
  }
}

export function ilkVeri(): MockVeri {
  const v: MockVeri = {
    gereksinimler: gereksinimler(),
    bulgular: bulgular(),
    caseler: caseler(),
    scriptler: scriptler(),
    kosular: kosular(),
    hatalar: hatalar(),
    bugTaslaklari: bugTaslaklari(),
    denetim: denetim(),
    sayac: 200,
  };
  // Sayaçlar elle yazılmaz: liste, detay ve karne aynı koleksiyondan hesaplar.
  for (const g of v.gereksinimler) {
    const cs = caseSayilari(v.caseler, g.id);
    g.sayaclar = {
      bulgu_acik: v.bulgular.filter((b) => b.requirement_id === g.id && (b.durum === "open" || b.durum === "decided")).length,
      case_toplam: cs.toplam,
      case_onayli: cs.onayli,
    };
  }
  hashleriTazele(v);
  return v;
}
