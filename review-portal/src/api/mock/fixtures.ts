// Örnek (mock) veri — docs/DEMO-VERISI.md ile birebir: TPD-1..4, 4 bilinçli uyumsuzluk,
// data-testid'ler, kampanya kırılması (BREAK_CAMPAIGN) ve locator kırılması (add-to-cart → cart-add).
//
// Kaynaklarla bağı (fixtures.test.ts hepsini kaynağa karşı doğrular, kayma derlemede yakalanır):
// - Story başlık/açıklama/AC'leri: sims/jira-sim seed.py; ön inceleme soruları:
//   rules/replay/requirement_review/golden; tutarlılık bulguları (tür, ref, gözlem, kanıt, önerilen
//   metin): rules/replay/consistency_check/golden. Hepsi golden/kaynaklar.json kopyasından okunur
//   (`npm run sozlesme:golden`); elle yazılmış model çıktısı yoktur.
// - Case içerikleri: rules/replay/case_generation/golden/TPD-1.json (başlık, AC, adımlar).
// - Bug taslakları: rules/replay/bug_draft/golden/*.json.
// - Jira anahtarları: sims/jira-sim seed (TPD-1..TPD-7 mevcut; kampanya mükerrer adayı TPD-5;
//   ürünün oluşturduğu ilk kayıt TPD-8).
// - Üretilen test kodu: demo-app/e2e/pages page object'leriyle tsc'den geçer.
// - Durumlar: core-api durum makinesi adları (tp_core/workflow/states.py).
// - Bağlantılar: her iç bağlantı bir portal ekranına çıkar; artifact/forge sunucusu olmadığı için
//   Allure/trace/PR adresleri null'dır (ekranda düz metin, ölü bağlantı yok).
import type {
  AjanAdimi,
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
import kaynaklar from "./golden/kaynaklar.json";
import tpd1GoldenCaseler from "./golden/tpd1-caseler.json";

export interface MockVeri {
  gereksinimler: GereksinimDetay[];
  bulgular: Bulgu[];
  caseler: TestCase[];
  scriptler: ScriptDetay[];
  kosular: KosuDetay[];
  hatalar: HataAnalizi[];
  bugTaslaklari: BugTaslagi[];
  denetim: { aktor: string; eylem: string; nesne: string; ozet: string; zaman: string }[];
  sayac: number;
}

/** Kanıtlardaki depo adı (golden kayıtlarla aynı: forge'daki demo-app deposu). */
const REPO = "demo-app";
const JIRA = "http://127.0.0.1:8090/browse";

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
};

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

// TPD-1 tutarlılık turu 1 (golden TPD-1): F1 AC3↔AC6, F2 AC2 kod, F3 AC3 veri, F4 AC4 kod eksik.
const TPD1_SEED_AC = seedStory("TPD-1").ac;
const TPD1_F = {
  celiski: goldenBulgu("TPD-1", "F1"),
  kampanya: goldenBulgu("TPD-1", "F2"),
  minTutar: goldenBulgu("TPD-1", "F3"),
  krediLimiti: goldenBulgu("TPD-1", "F4"),
};

/** Seed AC'leri + kabul edilen (fix_doc) golden önerileri: TPD-1'in Jira'ya yazılmış son hâli. */
const TPD1_AC = TPD1_SEED_AC.map((ac) => {
  if (ac.ref === "AC2") return { ...ac, metin: refsiz(TPD1_F.kampanya.suggested_doc_text!) };
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
          Q2: "Kod doğru: her 6 adette 1 bedava. AC2 buna göre düzeltilsin. (PO)",
          Q3: "İndirim düşülmüş toplam tutar üzerinden. (PO)",
        }),
      },
      kontrol_turu: 2,
      kontrol_turu_ust_sinir: 3,
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
      aciklama: "Bayi sepetteki bir ürün satırını kaldırabilmeli; toplamlar ve kampanya indirimi yeniden hesaplanmalıdır.",
      kabul_kriterleri: [
        { ref: "AC1", metin: "Satırdaki \"Kaldır\" butonuna basıldığında ürün sepetten çıkar ve sepet sayacı azalır." },
        { ref: "AC2", metin: "Kaldırma sonrası kampanya indirimi her 7 adette 1 bedava kuralıyla yeniden hesaplanır." },
        { ref: "AC3", metin: "Sepet tutarı 500,00 TL altına düşerse minimum tutar uyarısı gösterilir." },
      ],
      ac_missing: false,
      durum: "findings_open",
      cekim_zamani: t(30, "11:40"),
      po: { durum: "not_requested", onaylayan: null, zaman: null, kanal: "portal" },
      sayaclar: { bulgu_acik: 2, case_toplam: 0, case_onayli: 0 },
      on_inceleme: {
        verdict: "needs_po",
        mode: "replay_miss",
        zaman: t(30, "11:42"),
        jira_comment_id: null,
        questions: [
          {
            id: "Q1",
            type: "missing_ac",
            text: "Sepetteki son ürün kaldırıldığında boş sepet mesajı beklenmeli mi?",
            ac_ref: null,
            cevap: null,
          },
        ],
      },
      kontrol_turu: 1,
      kontrol_turu_ust_sinir: 3,
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
  const r2 = goldenBulgu("TPD-1-r2", "F1");
  const tpd3 = goldenBulgu("TPD-3", "F1");
  return [
    {
      ...ortak,
      ...bulguCiktisi(TPD1_F.kampanya, acMetni(TPD1_SEED_AC, "AC2")),
      evidence: [KAMPANYA_KOD],
      id: "fnd-1",
      karar: "fix_doc",
      karar_metni: acMetni(TPD1_AC, "AC2"),
      gerekce: null,
      karar_zamani: t(30, "09:41"),
      durum: "resolved", // fix_doc yazıldı (core: decided → resolved)
      bug_draft_id: null,
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
    // 2. kontrol turu (golden TPD-1-r2): yalnızca kredi limiti uyarısı kalır; önceki turun
    // code_defect kararı (bug-2) geçerli olduğu için analist aynı kararı verdi.
    {
      ...ortak,
      ...bulguCiktisi(r2, acMetni(TPD1_AC, "AC4")),
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
    // Serbest metin gereksinim: kararı bekleyen bulgular (karar düğmeleri burada denenir).
    {
      id: "fnd-5",
      requirement_id: "req-ft-1",
      type: "doc_vs_code",
      doc_ref: "AC2",
      ozet: "Doküman 7 adette 1 bedava diyor; kod her 6 adette 1 bedava uyguluyor.",
      evidence: [KAMPANYA_KOD],
      kanit_dogrulandi: true,
      severity: "blocking",
      mevcut_doc_text: "Kaldırma sonrası kampanya indirimi her 7 adette 1 bedava kuralıyla yeniden hesaplanır.",
      suggested_doc_text: "Kaldırma sonrası kampanya indirimi her 6 adette 1 bedava kuralıyla yeniden hesaplanır.",
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
    {
      id: "fnd-6",
      requirement_id: "req-ft-1",
      type: "doc_vs_data",
      doc_ref: "AC3",
      ozet: "Doküman minimum tutarı 500,00 TL diyor; ayar tablosunda 750,00 TL.",
      evidence: [MIN_SIPARIS_VERI],
      kanit_dogrulandi: true,
      severity: "warning",
      mevcut_doc_text: "Sepet tutarı 500,00 TL altına düşerse minimum tutar uyarısı gösterilir.",
      suggested_doc_text: "Sepet tutarı 750,00 TL altına düşerse minimum tutar uyarısı gösterilir.",
      karar: null,
      karar_metni: null,
      gerekce: null,
      karar_veren: null,
      karar_zamani: null,
      kontrol_turu: 1,
      durum: "open",
      bug_draft_id: null,
      icerik_hash: "",
      mode: "replay_miss",
    },
  ];
}

// ------------------------------------------------------------------ test case'ler

/**
 * TPD-1 case üretiminin golden çıktısı (rules/replay/case_generation/golden/TPD-1.json → output.cases),
 * sırasıyla. Portal imajı yalnızca review-portal/ ile derlendiği için kopya tutulur; fixtures.test.ts
 * kaynakla birebir aynı olduğunu doğrular. Golden değişince:
 *   python3 -c "import json;json.dump(json.load(open('rules/replay/case_generation/golden/TPD-1.json'))['output']['cases'],open('review-portal/src/api/mock/golden/tpd1-caseler.json','w'),ensure_ascii=False,indent=2)"
 */
export const TPD1_GOLDEN_CASELER: TestCaseIcerik[] = tpd1GoldenCaseler as TestCaseIcerik[];

/** Case içerik hash'i (handlers ile aynı biçim): onay kapısı bu değeri karşılaştırır. */
export function icerikHash(icerik: TestCaseIcerik): string {
  return `sha256:${sha256Hex(kanonikJson(icerik)).slice(0, 16)}`;
}

/** Analistin C3'te yaptığı küçük düzeltme (edit kararı): beklenen sonuca satır etiketi eklendi. */
function c3Duzeltilmis(): TestCaseIcerik {
  const g = JSON.parse(JSON.stringify(TPD1_GOLDEN_CASELER[2])) as TestCaseIcerik;
  g.expected_result = `${g.expected_result}; satırda "1 bedava" etiketi görünür`;
  return g;
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
    karar("case-1-3", 3, c3Duzeltilmis(), {
      ...analist,
      durum: "published",
      karar: "edit",
      surum: 2,
      karar_zamani: t(30, "10:37"),
      duzeltme_olcusu: 0.05,
      review_sure_ms: 95000,
      jira_test_key: "TPD-11",
    }),
    // İnsan kararı: 6 ve 7 adet case'leri kampanya sınırını zaten kapsıyor.
    karar("case-1-6", 4, G[3], { ...analist, durum: "rejected", karar: "reject", ret_nedeni: "duplicate", karar_zamani: t(30, "10:38"), review_sure_ms: 30000 }),
    karar("case-1-4", 5, G[4], { ...analist, durum: "approved", karar: "approve", karar_zamani: t(30, "10:41"), duzeltme_olcusu: 0, review_sure_ms: 52000 }),
    karar("case-1-7", 6, G[5], { durum: "draft" }),
    // Kredi limiti case'i bilinen kod hatasını hedefler (golden etiketi expected-code-defect).
    karar("case-1-5", 7, G[6], { durum: "draft", kanal: "ide", mode: "replay" }),
    karar("case-1-8", 8, G[7], { durum: "draft" }),
    karar("case-1-9", 9, G[8], { durum: "draft" }),
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
  };
}

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

function scriptler(): ScriptDetay[] {
  return [
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
      mode: "replay",
      olusturma: t(30, "11:05"),
      hata: null,
      kod: KAMPANYA_TEST_KODU,
      adimlar: kampanyaAdimlari(),
      yerel_kontrol: { tsc: true, eslint: true, ast_guard: true, tekrar: 3 },
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
      mode: "replay",
      olusturma: t(30, "10:45"),
      hata: "Zayıf test: BREAK_CAMPAIGN=1 ile uygulama kırıldığında da test yeşil kaldı (bu kırılma sepete eklemeyi etkilemiyor). Merge kapısı kapalı; mühendis kararı gerekir.",
      kod: SEPET_TEST_KODU,
      adimlar: sepetAdimlari(),
      yerel_kontrol: { tsc: true, eslint: true, ast_guard: true, tekrar: 3 },
    },
  ];
}

// ------------------------------------------------------------------ koşular ve triage

function sonuc(id: string, test_adi: string, durum: KosuDetay["sonuclar"][number]["durum"], sure_ms: number, ek: Partial<KosuDetay["sonuclar"][number]> = {}) {
  return { id, test_adi, durum, sure_ms, retry: 0, hata_mesaji: null, failure_id: null, case_id: null, ...ek };
}

export const TEST_C1 = `TPD-1 C1 · ${TPD1_GOLDEN_CASELER[0].title}`;
export const TEST_C2 = `TPD-1 C2 · ${TPD1_GOLDEN_CASELER[1].title}`;
const TEST_LOGIN = "Bayi girişi · hatalı parola mesajı (elle yazılmış)";

function kosu(
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
    sauce_url: null,
    ci_url: null,
    break_campaign: false,
    sonuclar,
    ...ek,
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
            "expect(getByTestId('cart-discount')).toHaveText(\"25,00 TL\")\nBeklenen: \"25,00 TL\"\nGerçekleşen: \"0,00 TL\"",
          failure_id: "fail-1",
          case_id: "case-1-2",
        }),
        sonuc("r107-3", TEST_LOGIN, "passed", 2200),
      ],
      { commit: "b7d1f05", break_campaign: true },
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
          case_id: "case-1-1",
        }),
        sonuc("r106-2", TEST_C2, "failed", 9800, {
          hata_mesaji: "locator.click: Timeout 5000ms exceeded. (aynı imza: add-to-cart)",
          failure_id: "fail-2",
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
    kosu("run-103", "pr", "local", t(30, "11:24"), [sonuc("r103-1", TEST_C2, "passed", 5900, { case_id: "case-1-2" })], {
      commit: "4ac0e11",
      pr_no: 12,
    }),
    kosu(
      "run-102",
      "pr",
      "local",
      t(30, "11:22"),
      [
        sonuc("r102-1", TEST_C2, "failed", 6100, {
          hata_mesaji: "Beklenen: \"25,00 TL\" · Gerçekleşen: \"0,00 TL\" (BREAK_CAMPAIGN=1)",
          case_id: "case-1-2",
        }),
      ],
      { commit: "4ac0e11", pr_no: 12, break_campaign: true },
    ),
    kosu("run-101", "pr", "local", t(30, "11:20"), [sonuc("r101-1", TEST_C2, "passed", 5800, { case_id: "case-1-2" })], {
      commit: "4ac0e11",
      pr_no: 12,
    }),
    // PR #11 (scr-1) kırarak doğrulama koşuları: kırılmada da yeşil → zayıf test.
    kosu("run-099", "pr", "local", t(30, "10:54"), [sonuc("r099-1", TEST_C1, "passed", 3200, { case_id: "case-1-1" })], {
      commit: "1b7d40a",
      pr_no: 11,
    }),
    kosu("run-098", "pr", "local", t(30, "10:52"), [sonuc("r098-1", TEST_C1, "passed", 3300, { case_id: "case-1-1" })], {
      commit: "1b7d40a",
      pr_no: 11,
      break_campaign: true,
    }),
    kosu("run-097", "pr", "local", t(30, "10:50"), [sonuc("r097-1", TEST_C1, "passed", 3100, { case_id: "case-1-1" })], {
      commit: "1b7d40a",
      pr_no: 11,
    }),
  ];
}

function hatalar(): HataAnalizi[] {
  return [
    {
      id: "fail-1",
      run_id: "run-107",
      test_adi: TEST_C2,
      hata_imzasi: "assertion:cart-discount:expected=25,00 TL:actual=0,00 TL",
      hata_mesaji: "Beklenen: \"25,00 TL\" · Gerçekleşen: \"0,00 TL\"",
      sinif: "product_defect",
      alt_tur: "assertion",
      eslesen_sinyaller: [
        { kod: "health_ok", aciklama: "Koşu öncesi sağlık kontrolü başarılı (ortam sorunu değil)", kaynak: "health" },
        { kod: "not_flaky", aciklama: "Yeniden denemede de aynı sonuç (flaky değil)", kaynak: "playwright-json" },
        { kod: "locator_resolved", aciklama: "Locator tek eleman buldu; sayfa yapısı beklenen", kaynak: "aria-snapshot" },
        { kod: "assertion_mismatch", aciklama: "cart-discount metni beklenen \"25,00 TL\", gerçekleşen \"0,00 TL\"", kaynak: "trace" },
      ],
      karar_kaynagi: "rule",
      llm_yorumu: null,
      oneri: { tur: "bug_draft", bug_draft_id: "bug-1" },
      kanit_linkleri: [
        { etiket: "Allure raporu (run-107)", url: null },
        { etiket: "Playwright trace (run-107)", url: null },
      ],
      mode: "replay",
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
      eslesen_sinyaller: [
        { kod: "health_ok", aciklama: "Koşu öncesi sağlık kontrolü başarılı", kaynak: "health" },
        { kod: "locator_zero", aciklama: "getByTestId('add-to-cart') 0 eleman döndürdü", kaynak: "playwright-json" },
        { kod: "intent_present", aciklama: "Niyete uyan eleman sayfada var: button \"Sepete ekle\"", kaynak: "aria-snapshot" },
        { kod: "testid_changed", aciklama: "DOM'daki data-testid farklı: cart-add", kaynak: "locator-probe" },
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
        dogrulama: [
          "Rol + ad eşleşmesi tek eleman verdi",
          "Son yeşil koşunun aria snapshot'ındaki rol + ad ile aynı",
          "AST koruması: yalnızca testId değeri değişiyor",
        ],
        durum: "proposed",
        pr: null,
      },
      kanit_linkleri: [
        { etiket: "Sauce video (run-106)", url: null },
        { etiket: "Allure raporu (run-106)", url: null },
      ],
      mode: "replay",
      zaman: t(29, "17:36"),
    },
  ];
}

// ------------------------------------------------------------------ bug taslakları

function bugTaslaklari(): BugTaslagi[] {
  return [
    {
      // rules/replay/bug_draft/golden/break-campaign.json
      id: "bug-1",
      kaynak: "triage",
      failure_id: "fail-1",
      finding_id: null,
      icerik: {
        summary: "Sepet: \"6 al 1 bedava\" kampanya indirimi uygulanmıyor",
        steps: [
          "bayi1 / Demo123! ile giriş yap",
          "\"Portakal Gazozu 1L\" için 7 adet gir ve sepete ekle",
          "Sepete git ve indirim tutarını kontrol et",
        ],
        expected: "Kampanya indirimi 25,00 TL",
        actual: "Kampanya indirimi 0,00 TL",
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
      // jira-sim seed: TPD-5 aynı kampanya hatasını anlatan açık Bug (JQL araması bunu döndürür).
      mukerrer_adaylari: [
        {
          key: "TPD-5",
          summary: "Kampanya indirimi sepette yanlış hesaplanıyor",
          durum: "To Do",
          gerekce:
            "Aynı ürün (Portakal Gazozu 1L, 7 adet) ve aynı alan (sepetteki indirim satırı); TPD-5 beklenen 25,00 TL indirimin farklı göründüğünü anlatıyor.",
          sinyaller: ["Aynı ürün: P-001", "Aynı alan: cart-discount", "Aynı adımlar: 7 adet sepete ekle"],
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
      // rules/replay/bug_draft/golden/credit-limit.json
      id: "bug-2",
      kaynak: "consistency",
      failure_id: null,
      finding_id: "fnd-3",
      icerik: {
        summary: "Sepet: Kredi limiti aşımında \"Kredi limiti aşıldı\" uyarısı gösterilmiyor",
        steps: [
          "bayi2 / Demo123! (kredi limiti 500,00 TL) ile giriş yap",
          "\"Şeftalili Soğuk Çay 1L\" için 25 adet gir ve sepete ekle (toplam 750,00 TL: minimum sipariş tutarını karşılar, kredi limitini aşar)",
          "Sepete git",
          "\"Siparişi onayla\" butonuna bas",
        ],
        expected: "Sepette \"Kredi limiti aşıldı\" uyarısı gösterilir ve sipariş onaylanamaz",
        actual: "Uyarı gösterilmiyor, \"Siparişi onayla\" butonu aktif ve sipariş oluşturuluyor; kredi limiti kontrolü yapılmıyor",
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
      mode: "replay",
      olusturma: t(30, "09:46"),
    },
  ];
}

function denetim(): MockVeri["denetim"] {
  return [
    { aktor: "analist", eylem: "requirements.sync", nesne: "TPD", ozet: "Jira'dan 4 story çekildi", zaman: t(30, "09:12") },
    { aktor: "core-worker", eylem: "ai_call", nesne: "req-tpd-1", ozet: "Ön inceleme + tutarlılık (claude-sonnet, REPLAY, 0 USD)", zaman: t(30, "09:20") },
    { aktor: "analist", eylem: "finding.decision", nesne: "fnd-1", ozet: "fix_doc", zaman: t(30, "09:41") },
    { aktor: "analist", eylem: "finding.decision", nesne: "fnd-2", ozet: "fix_doc", zaman: t(30, "09:43") },
    { aktor: "analist", eylem: "finding.decision", nesne: "fnd-3", ozet: "code_defect → bug-2", zaman: t(30, "09:45") },
    { aktor: "analist", eylem: "finding.decision", nesne: "fnd-4", ozet: "fix_doc", zaman: t(30, "09:47") },
    { aktor: "core-worker", eylem: "jira.update", nesne: "TPD-1", ozet: "Açıklama/AC güncellendi, tp-po-pending etiketi", zaman: t(30, "09:50") },
    { aktor: "testci", eylem: "bug.publish", nesne: "bug-2", ozet: "Jira'da TPD-8 açıldı", zaman: t(30, "09:58") },
    { aktor: "po@sim.local", eylem: "po.approve", nesne: "TPD-1", ozet: "tp-po-approved etiketi okundu", zaman: t(30, "10:05") },
    { aktor: "core-worker", eylem: "ai_call", nesne: "req-tpd-1", ozet: "Case üretimi: 9 case (REPLAY, 0 USD)", zaman: t(30, "10:20") },
    { aktor: "analist", eylem: "case.decision", nesne: "case-1-1", ozet: "approve", zaman: t(30, "10:31") },
    { aktor: "analist", eylem: "case.decision", nesne: "case-1-2", ozet: "approve", zaman: t(30, "10:34") },
    { aktor: "analist", eylem: "case.decision", nesne: "case-1-3", ozet: "edit (ölçü 0,05)", zaman: t(30, "10:37") },
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
