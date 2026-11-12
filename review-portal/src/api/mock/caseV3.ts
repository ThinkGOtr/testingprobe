// Case şeması v3 (011 §4.1) örnek verisi ve `case-summary` hesabı (core `coverage_matrix` /
// `set_problems` karşılığı). Golden'dan bağımsızdır: `golden/` dizini T4 şeridine aittir ve v3'e
// geçtiğinde TPD-1 case'leri de v3 içerik taşır; buradaki hesap her iki içerikle de çalışır.
import type {
  CaseKapsamOzeti,
  KapsamOrani,
  CaseUretimOzeti,
  GereksinimDetay,
  KabulKriteri,
  KapsamSatiri,
  TestCase,
  TestCaseIcerik,
} from "../types";
import { caseHazirlik, eskiIcerik, tutarlilikSorunlari } from "../../lib/caseV3";

export const V3_GEREKSINIM_ID = "req-ft-2";

export const V3_AC: KabulKriteri[] = [
  { ref: "AC1", metin: "Bayi sipariş onayı ekranında siparişe en fazla 250 karakterlik not ekleyebilir." },
  { ref: "AC2", metin: '250 karakteri aşan not kaydedilmez; "Not en fazla 250 karakter olabilir" uyarısı gösterilir.' },
  { ref: "AC3", metin: "Not sipariş detayında düz metin olarak gösterilir; nottaki HTML ya da betik çalıştırılmaz." },
  { ref: "AC4", metin: "Sipariş notunu yalnızca siparişi veren bayi görüntüleyebilir." },
];

export const V3_BASLIK = "Siparişe not ekleme";
export const V3_ACIKLAMA =
  "Bayi, sipariş onayı ekranında siparişine serbest metin not ekleyebilmelidir. Not sipariş detayında görüntülenir ve depo ekibine iletilir.";

/** Saldırı verisi (XSS): yalnız test verisi tablosunda, kod olarak gösterilir; hiçbir yerde işlenmez. */
export const V3_SALDIRI_VERISI = `<img src=x onerror="alert('tp-xss')">`;

/** Üretimin üst düzey listeleri (`case_uretim.ozet`): açık soru, varsayım, kapsam öğeleri, kararlar. */
export const V3_URETIM: CaseUretimOzeti = {
  uretim_no: 1,
  kanal: "portal",
  tur: "uretim",
  open_questions: [{ id: "Q1", question: "Yalnızca boşluk karakterlerinden oluşan not kaydedilir mi, yoksa not girilmemiş mi sayılır?", owner: "PO" }],
  assumptions: [{ id: "A1", statement: "250 karakter sınırı bayt değil, Unicode karakter sayısı olarak uygulanır.", owner: "analyst" }],
  coverage_items: [
    { id: "EP-V1", ac_ref: "AC1", definition: "1–250 karakter uzunluğunda not", valid: true },
    { id: "EP-I1", ac_ref: "AC2", definition: "250 karakterden uzun not", valid: false },
    { id: "EP-I2", ac_ref: "AC1", definition: "Yalnızca boşluk içeren not", valid: false },
    { id: "EP-I3", ac_ref: "AC4", definition: "Başka bayinin siparişine ait not", valid: false },
    { id: "BV-1", ac_ref: "AC1", definition: "250 karakter (üst sınır, kabul edilir)", valid: true },
    { id: "BV-2", ac_ref: "AC2", definition: "251 karakter (üst sınırın bir fazlası, reddedilir)", valid: false },
    { id: "UC-MF", ac_ref: "AC4", definition: "Bayi kendi siparişinin notunu görüntüler", valid: true },
    { id: "EG-1", ac_ref: "AC3", definition: "HTML/betik içeren not", valid: false },
    { id: "EG-2", ac_ref: "AC3", definition: "Çok satırlı not (satır sonu karakterleri)", valid: true },
    { id: "EG-3", ac_ref: "AC1", definition: "Kayıt sırasında ağ kesintisi", valid: false },
  ],
  negative_coverage: [
    { item: "EP-I1", decision: "tested", rationale: "251 karakterlik not case'i bölümü de çalıştırır." },
    { item: "EP-I2", decision: "tested", rationale: "Ayrı case; beklenen sonuç Q1 yanıtına bağlı." },
    { item: "EP-I3", decision: "tested", rationale: "Yetki case'i ile doğrulanır." },
    { item: "BV-2", decision: "tested", rationale: "Sınırın bir fazlası ayrı case ile denenir." },
    { item: "EG-1", decision: "tested", rationale: "Güvenlik testi girdisiyle denenir." },
    { item: "EG-3", decision: "out_of_scope", rationale: "Ağ hatası davranışı bu story'nin kapsamında tanımlı değil." },
  ],
  not_covered: [{ item: "EG-2", reason: "Story satır sonu davranışını tanımlamıyor; case sınırı nedeniyle ertelendi." }],
  observations: [{ standard_ref: "OWASP ASVS V5.3", note: "Çıktı kodlama notun gösterildiği tüm ekranlarda (sipariş detayı, depo ekranı) doğrulanmalı." }],
  automation_open_points: ["Sipariş detayındaki not alanının test kimliği (data-testid) tanımlı değil."],
  config_matrix: { parameters: [], constraints: [] },
  testability_gaps: [{ control: "Sipariş notu metin alanı", missing: "test_id" }],
};

const GIRIS = { id: "S1", action: "Bayi kullanıcısıyla giriş yap ve sepete bir ürün ekle", data: "bayi1 / Demo123!", expected: "Sepette 1 ürün görünür" };

const ortak = {
  risk: "medium" as const,
  platform: "Web",
  test_level: "SYSTEM",
  requires_real_device: false,
  standard_refs: [] as string[],
  assumption_refs: [] as string[],
  open_question_refs: [] as string[],
  preconditions: ["bayi1 kullanıcısı aktif", "Katalogda en az bir ürün var"],
  teardown: ["Oluşturulan siparişi iptal et"],
  tags: ["AI-generated"],
};

/** v3 örnek case içerikleri: hazır, varsayıma bağlı, soru bekliyor, saldırı verili güvenlik, yetki, varsayıma bağlı. */
export const V3_ICERIKLER: TestCaseIcerik[] = [
  {
    ...ortak,
    title: "250 karakterlik not siparişle birlikte kaydedilir",
    type: "boundary",
    technique: ["EP", "BVA"],
    covers: ["EP-V1", "BV-1"],
    risk: "high",
    priority: "P1",
    priority_rationale: "Ana akış ve üst sınır: not kaydedilmezse özellik kullanılamaz.",
    acceptance_criteria_refs: ["AC1"],
    verification_point: "UI",
    readiness: "ready",
    test_data: [{ name: "not_250", value: "a".repeat(250), class: "BV-1", synthetic: true, is_attack_payload: false }],
    steps: [
      GIRIS,
      { id: "S2", action: "Sipariş onayı ekranında not alanına not_250 verisini gir", data: "not_250", expected: "Karakter sayacı 250/250 gösterir" },
      { id: "S3", action: '"Siparişi onayla" butonuna bas', data: null, expected: "Sipariş oluşturulur ve sipariş detayı açılır" },
    ],
    expected_result: "Sipariş detayında 250 karakterlik not eksiksiz görünür",
  },
  {
    ...ortak,
    title: "251 karakterlik not kaydedilmez",
    type: "negative",
    technique: ["BVA", "EP"],
    covers: ["BV-2", "EP-I1"],
    priority: "P1",
    priority_rationale: "Sınır ihlali sessizce kabul edilirse veri kırpılır ya da kayıt hatası oluşur.",
    acceptance_criteria_refs: ["AC2"],
    verification_point: "UI",
    readiness: "assumption_dependent",
    assumption_refs: ["A1"],
    test_data: [{ name: "not_251", value: "a".repeat(251), class: "BV-2", synthetic: true, is_attack_payload: false }],
    steps: [
      GIRIS,
      { id: "S2", action: "Sipariş onayı ekranında not alanına not_251 verisini gir", data: "not_251", expected: '"Not en fazla 250 karakter olabilir" uyarısı gösterilir' },
      { id: "S3", action: '"Siparişi onayla" butonuna bas', data: null, expected: "Sipariş oluşturulmaz" },
    ],
    expected_result: "Not kaydedilmez ve uyarı görünür kalır",
    teardown: [],
  },
  {
    ...ortak,
    title: "Yalnızca boşluk içeren not",
    type: "negative",
    technique: ["EP"],
    covers: ["EP-I2"],
    risk: "low",
    priority: "P3",
    priority_rationale: "Kenar durum; davranış story'de tanımlı değil.",
    acceptance_criteria_refs: ["AC1"],
    verification_point: "UI",
    readiness: "blocked",
    open_question_refs: ["Q1"],
    test_data: [{ name: "not_bosluk", value: "     ", class: "EP-I2", synthetic: true, is_attack_payload: false }],
    steps: [
      GIRIS,
      { id: "S2", action: "Sipariş onayı ekranında not alanına not_bosluk verisini gir", data: "not_bosluk", expected: "" },
      { id: "S3", action: '"Siparişi onayla" butonuna bas', data: null, expected: "" },
    ],
    expected_result: "",
  },
  {
    ...ortak,
    title: "Nottaki betik sipariş detayında çalıştırılmaz",
    type: "negative",
    technique: ["EG"],
    covers: ["EG-1"],
    risk: "high",
    priority: "P1",
    priority_rationale: "Kalıcı XSS: not depo ekibinin ekranında da gösterilir.",
    acceptance_criteria_refs: ["AC3"],
    verification_point: "UI",
    readiness: "ready",
    standard_refs: ["OWASP ASVS V5.3"],
    test_data: [{ name: "xss_notu", value: V3_SALDIRI_VERISI, class: "EG-1", synthetic: true, is_attack_payload: true }],
    steps: [
      GIRIS,
      { id: "S2", action: "Sipariş onayı ekranında not alanına xss_notu verisini gir ve siparişi onayla", data: "xss_notu", expected: "Sipariş oluşturulur" },
      { id: "S3", action: "Sipariş detayını aç", data: null, expected: "Not düz metin olarak görünür; tarayıcı uyarı penceresi açılmaz" },
    ],
    expected_result: "Girilen metin sipariş detayında harfi harfine düz metin olarak gösterilir ve betik çalışmaz",
    tags: ["AI-generated", "security"],
  },
  {
    ...ortak,
    title: "Başka bayinin sipariş notu görüntülenemez",
    type: "authorization",
    technique: ["UC", "EP"],
    covers: ["UC-MF", "EP-I3"],
    risk: "high",
    priority: "P2",
    priority_rationale: "Bayiler arası veri sızıntısı; arayüzde bağlantı yok ama API doğrudan çağrılabilir.",
    acceptance_criteria_refs: ["AC4"],
    verification_point: "API",
    test_level: "INTEGRATION",
    readiness: "ready",
    test_data: [{ name: "diger_bayi_siparisi", value: "SIP-SENTETIK-0002", class: "EP-I3", synthetic: true, is_attack_payload: false }],
    steps: [
      { id: "S1", action: "bayi1 ile giriş yap ve notlu bir sipariş oluştur", data: "bayi1 / Demo123!", expected: "Sipariş detayında not görünür" },
      { id: "S2", action: "bayi2 oturumuyla diger_bayi_siparisi kimlikli siparişin detayını iste", data: "diger_bayi_siparisi", expected: "İstek 403 ile reddedilir" },
    ],
    expected_result: "bayi2 başka bayinin sipariş notunu göremez",
    teardown: ["Oluşturulan siparişi iptal et", "bayi2 oturumunu kapat"],
  },
  {
    ...ortak,
    title: "Türkçe karakterli 250 karakterlik not eksiksiz görünür",
    type: "positive",
    technique: ["BVA"],
    covers: ["BV-1"],
    priority: "P2",
    priority_rationale: "Çok baytlı karakterlerde sınırın yanlış hesaplanma riski.",
    acceptance_criteria_refs: ["AC1", "AC3"],
    verification_point: "UI",
    readiness: "assumption_dependent",
    assumption_refs: ["A1"],
    test_data: [{ name: "not_250_tr", value: "ğ".repeat(250), class: "BV-1", synthetic: true, is_attack_payload: false }],
    steps: [
      GIRIS,
      { id: "S2", action: "Sipariş onayı ekranında not alanına not_250_tr verisini gir ve siparişi onayla", data: "not_250_tr", expected: "Sipariş oluşturulur" },
    ],
    expected_result: "Sipariş detayında 250 karakterin tamamı bozulmadan görünür",
  },
];

/** Yanıt zenginleştirme (core `serialize_cases`): readiness, legacy, çözülmüş atıflar, tutarlılık uyarıları. */
export function caseV3Alanlari(
  c: TestCase,
  uretimler: CaseUretimOzeti[] | undefined,
): Pick<TestCase, "readiness" | "legacy" | "acik_sorular" | "varsayimlar" | "uyarilar" | "onay_engeli" | "po_sorulari"> {
  const legacy = eskiIcerik(c.icerik);
  if (legacy) return { readiness: "ready", legacy: true, acik_sorular: [], varsayimlar: [], onay_engeli: null, ...(c.uyarilar ? { uyarilar: c.uyarilar } : {}) };
  const ozet = birlesikOzet(uretimler);
  const sorular = new Map((ozet?.open_questions ?? []).map((q) => [q.id, q]));
  const varsayimlar = new Map((ozet?.assumptions ?? []).map((a) => [a.id, a]));
  const sorunlar = tutarlilikSorunlari(c.icerik, ozet);
  const hazirlik = caseHazirlik(c);
  return {
    onay_engeli:
      hazirlik !== "ready"
        ? `Hazır olmayan case onaylanamaz (${hazirlik === "blocked" ? "açık soru bekliyor" : "varsayıma bağlı"})`
        : sorunlar.length
          ? "Tutarlılık ihlali olan case onaylanamaz"
          : null,
    readiness: hazirlik,
    legacy: false,
    acik_sorular: (c.icerik.open_question_refs ?? []).flatMap((r) => sorular.get(r) ?? []),
    varsayimlar: (c.icerik.assumption_refs ?? []).flatMap((r) => varsayimlar.get(r) ?? []),
    uyarilar: [...new Set([...(c.uyarilar ?? []), ...sorunlar])],
    // D6 biçimi: atıf yapılan sorular örnekte henüz PO'ya gönderilmemiştir (mevcut kayıt korunur).
    po_sorulari:
      c.po_sorulari ??
      Object.fromEntries(
        (c.icerik.open_question_refs ?? []).map((r, i) => [r, { tur: "soru" as const, po_etiketi: `CQ${i + 1}`, po_durumu: "gonderilmedi" as const, po_yaniti: null }]),
      ),
  };
}

/** Gereksinimin üretimlerinin birleşik üst listeleri (atıf çözümü ve tutarlılık için). */
export function birlesikOzet(uretimler: CaseUretimOzeti[] | undefined): Pick<CaseUretimOzeti, "coverage_items" | "open_questions" | "assumptions"> | null {
  if (!uretimler || uretimler.length === 0) return null;
  return {
    coverage_items: uretimler.flatMap((u) => u.coverage_items),
    open_questions: uretimler.flatMap((u) => u.open_questions),
    assumptions: uretimler.flatMap((u) => u.assumptions),
  };
}

const oran = (kapsanan: number, toplam: number): KapsamOrani => ({ kapsanan, toplam, oran: toplam > 0 ? kapsanan / toplam : null });

/** `GET /requirements/{id}/case-summary`: üretim listeleri + kodda hesaplanan matris, oranlar, dağılımlar. */
export function caseKapsamOzeti(g: Pick<GereksinimDetay, "id" | "jira_key" | "kabul_kriterleri">, tumCaseler: TestCase[], uretimler: CaseUretimOzeti[] | undefined): CaseKapsamOzeti {
  // Güncel case'ler (core `_coverage_state`): reddedilen ve yerini yenisi alan case kapsam hesabına girmez.
  const caseler = tumCaseler.filter((c) => c.requirement_id === g.id && c.durum !== "rejected" && c.durum !== "superseded");
  const us = (uretimler ?? []).map((u) => ({ ...u, ozet_var: true }));
  const bos: CaseKapsamOzeti = {
    requirement_id: g.id,
    jira_key: g.jira_key,
    uretimler: us,
    kapsam_matrisi: [],
    oranlar: { gereksinim_kapsami: oran(0, 0), oge_kapsami: oran(0, 0), negatif_karar_kapsami: oran(0, 0) },
    guncel_case_sayisi: caseler.length,
    legacy_case_sayisi: caseler.filter((c) => eskiIcerik(c.icerik)).length,
    teknik_dagilimi: {},
    readiness_dagilimi: {},
    kapsanmayan: [],
    uyarilar: [],
  };
  if (caseler.length === 0) return bos;

  const kapsanmayanNeden = new Map(us.flatMap((u) => u.not_covered).map((n) => [n.item, n.reason]));
  const kararlar = new Map(us.flatMap((u) => u.negative_coverage).map((k) => [k.item, k]));
  const ogeler = [...new Map(us.flatMap((u) => u.coverage_items).map((o) => [o.id, o])).values()];
  const kapsayan = (secici: (i: TestCaseIcerik) => string[] | undefined, kimlik: string) =>
    caseler.filter((c) => (secici(c.icerik) ?? []).includes(kimlik)).map((c) => c.sira_no).sort((a, b) => a - b);
  // D3: hazır (readiness ready) case'lerle kapsam: satırda `covered_by_ready`, oranlarda `hazir_*`.
  const hazirSiralar = new Set(caseler.filter((c) => caseHazirlik(c) === "ready").map((c) => c.sira_no));
  const hazirlar = (covered_by: number[]) => covered_by.filter((n) => hazirSiralar.has(n));

  const acSatirlari: KapsamSatiri[] = g.kabul_kriterleri.map((ac) => {
    const covered_by = kapsayan((i) => i.acceptance_criteria_refs, ac.ref);
    return { item: ac.ref, tur: "ac", tanim: ac.metin, valid: null, ac_ref: ac.ref, karar: null, covered_by, covered_by_ready: hazirlar(covered_by), gerekce: covered_by.length ? null : (kapsanmayanNeden.get(ac.ref) ?? null) };
  });
  const ogeSatirlari: KapsamSatiri[] = ogeler.map((o) => {
    const covered_by = kapsayan((i) => i.covers, o.id);
    const karar = kararlar.get(o.id);
    const gerekce = covered_by.length ? null : (kapsanmayanNeden.get(o.id) ?? (karar?.decision === "out_of_scope" ? karar.rationale : null));
    return { item: o.id, tur: "oge", tanim: o.definition, valid: o.valid, ac_ref: o.ac_ref, covered_by, covered_by_ready: hazirlar(covered_by), gerekce, karar: karar?.decision ?? null };
  });
  // core `covered_by_cases`: kimlik, sıra no, üretim no, başlık (sıra no üretimler arasında tekil değil).
  const siradan = new Map(caseler.map((c) => [c.sira_no, c]));
  const matris = [...acSatirlari, ...ogeSatirlari].map((s) => ({
    ...s,
    kapsayanlar: s.covered_by.flatMap((n) => {
      const c = siradan.get(n);
      return c ? [{ id: c.id, sira_no: c.sira_no, uretim_no: c.uretim_no ?? 1, title: c.icerik.title }] : [];
    }),
  }));

  const uyarilar: string[] = [];
  const gecersiz = ogeler.filter((o) => !o.valid);
  for (const o of gecersiz) if (!kararlar.has(o.id)) uyarilar.push(`Geçersiz öğe ${o.id} için negatif kapsam kararı yok.`);
  for (const s of ogeSatirlari) {
    const k = kararlar.get(s.item);
    if (k && k.decision !== "out_of_scope" && s.covered_by.length === 0) uyarilar.push(`${s.item}: karar "${k.decision}" ama hiçbir güncel case kapsamıyor.`);
  }
  for (const s of matris) if (s.covered_by.length === 0 && !s.gerekce) uyarilar.push(`${s.item} kapsanmıyor ve gerekçesi yazılmamış.`);

  const say = (anahtarlar: string[]) => anahtarlar.reduce<Record<string, number>>((a, k) => ((a[k] = (a[k] ?? 0) + 1), a), {});
  return {
    ...bos,
    kapsam_matrisi: matris,
    oranlar: {
      gereksinim_kapsami: oran(acSatirlari.filter((s) => s.covered_by.length).length, acSatirlari.length),
      oge_kapsami: oran(ogeSatirlari.filter((s) => s.covered_by.length).length, ogeSatirlari.length),
      negatif_karar_kapsami: oran(gecersiz.filter((o) => kararlar.has(o.id)).length, gecersiz.length),
      hazir_gereksinim_kapsami: oran(acSatirlari.filter((s) => (s.covered_by_ready ?? []).length).length, acSatirlari.length),
      hazir_oge_kapsami: oran(ogeSatirlari.filter((s) => (s.covered_by_ready ?? []).length).length, ogeSatirlari.length),
    },
    teknik_dagilimi: say(caseler.flatMap((c) => c.icerik.technique ?? [])),
    // Eski case hazır sayılır (K9).
    readiness_dagilimi: say(caseler.map((c) => caseHazirlik(c))),
    kapsanmayan: matris.filter((s) => s.covered_by.length === 0).map((s) => ({ item: s.item, tur: s.tur, tanim: s.tanim, karar: s.karar ?? null, gerekce: s.gerekce ?? "" })),
    uyarilar,
  };
}
