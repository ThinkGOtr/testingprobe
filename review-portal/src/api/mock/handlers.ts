// Mock arka uç: §5 uçlarının süreç içi uygulaması. Durum makinesi kuralları ve rol kontrolleri
// gerçek API'yi taklit eder (insan kapıları atlanamaz), böylece ekranlar arka uç olmadan
// demo edilebilir ve ekran testine girebilir. Tüm üretilen çıktılar mode alanıyla işaretlidir.
import { ApiError, mockOturumu, mockOturumuAyarla } from "../http";
import type {
  Bulgu,
  BulguKararGirdisi,
  BugKararGirdisi,
  BugTaslagi,
  CaseKararGirdisi,
  DenetimOlayi,
  DenetimYaniti,
  GereksinimDetay,
  IsYaniti,
  KontrolKulesi,
  Kosu,
  KosuDetay,
  Kullanici,
  PullRequest,
  McpToken,
  Rol,
  ScriptDetay,
  SerbestMetinGirdisi,
  TestCase,
  TestCaseIcerik,
  YayinOnizleme,
  YayinSonucu,
} from "../types";
import { CASE_KARAR_HEDEFI, GECIS_YOK, type MakineAdi, yolGecerli } from "../sozlesme/durumMakinesi";
import { duzeltmeOlcusu } from "../../lib/diff";
import { kanonikJson, sha256Hex } from "../../lib/sha256";
import {
  bulguCiktisi,
  caseSayilari,
  goldenBulgular,
  goldenInceleme,
  goldenSorular,
  hashleriTazele,
  icerikHash,
  ilkVeri,
  KAMPANYA_KOD,
  kampanyaAdimlari,
  KAMPANYA_TEST_KODU,
  MIN_SIPARIS_VERI,
  TEST_C1,
  TEST_C2,
  type MockVeri,
} from "./fixtures";
import { mockOlayYayinla } from "./olaylar";

const KULLANICILAR: Record<string, Kullanici> = {
  analist: { id: "u-analist", kullanici_adi: "analist", rol: "analyst" },
  muhendis: { id: "u-muhendis", kullanici_adi: "muhendis", rol: "engineer" },
  sunucu: { id: "u-sunucu", kullanici_adi: "sunucu", rol: "presenter" },
  po: { id: "u-po", kullanici_adi: "po", rol: "po" },
  testci: { id: "u-testci", kullanici_adi: "testci", rol: "tester" },
};

const OTURUM_ANAHTARI = "tp-mock-oturum";
// v3: örnek veri simülatör seed'i ve golden çıktılarla hizalandı (eski oturum verisi okunmaz).
const VERI_ANAHTARI = "tp-mock-veri-v4";

const testModu = import.meta.env.MODE === "test";
const GECIKME_MS = testModu ? 0 : 120;
/** Arka plan işlerinin (ajan adımları, koşular) adım aralığı. */
export const ayar = { isAdimiMs: testModu ? 0 : 900 };

let veri: MockVeri = yukle();

function yukle(): MockVeri {
  try {
    const ham = sessionStorage.getItem(VERI_ANAHTARI);
    if (ham) return JSON.parse(ham) as MockVeri;
  } catch {
    /* depolama yok/erişilemez: ilk veriyle devam */
  }
  return ilkVeri();
}

function kaydet(): void {
  try {
    sessionStorage.setItem(VERI_ANAHTARI, JSON.stringify(veri));
  } catch {
    /* yoksay */
  }
}

/** Testler için: mock durumunu ilk haline getirir. */
export function mockSifirla(): void {
  veri = ilkVeri();
  mockOturumuAyarla(null);
  try {
    sessionStorage.removeItem(VERI_ANAHTARI);
    sessionStorage.removeItem(OTURUM_ANAHTARI);
  } catch {
    /* yoksay */
  }
}

export function mockVerisi(): MockVeri {
  return veri;
}

// Oturum: gerçek giriş yapılmışsa http modülündeki kullanıcı; değilse mock oturumu.
function oturum(): Kullanici | null {
  const k = mockOturumu();
  if (k) return k;
  try {
    const ham = sessionStorage.getItem(OTURUM_ANAHTARI);
    if (ham) {
      const kullanici = JSON.parse(ham) as Kullanici;
      mockOturumuAyarla(kullanici);
      return kullanici;
    }
  } catch {
    /* yoksay */
  }
  return null;
}

function girisGerekli(): Kullanici {
  const k = oturum();
  if (!k) throw new ApiError(401, "Oturum açmanız gerekiyor.");
  return k;
}

function rolGerekli(...roller: Rol[]): Kullanici {
  const k = girisGerekli();
  if (!roller.includes(k.rol)) {
    throw new ApiError(403, `Bu işlem için ${roller.join(" / ")} rolü gerekir.`);
  }
  return k;
}

function bul<T extends { id: string }>(liste: T[], id: string, ad: string): T {
  const x = liste.find((e) => e.id === id);
  if (!x) throw new ApiError(404, `${ad} bulunamadı: ${id}`);
  return x;
}

function yeniId(onek: string): string {
  veri.sayac += 1;
  return `${onek}-${veri.sayac}`;
}

const simdi = () => new Date().toISOString();
const kopya = <T>(x: T): T => JSON.parse(JSON.stringify(x)) as T;

/** Yanıt: içerik değişmiş olabilir, hash'ler güncel içerikten yeniden hesaplanıp kopya döner. */
function cikti<T>(x: T): T {
  hashleriTazele(veri);
  return kopya(x);
}

/** core `record_approval` ile aynı sözleşme: portal kararında hash zorunlu (422), eskiyse 409. */
export const ICERIK_DEGISMIS = "İçerik siz görüntüledikten sonra değişmiş; yenileyip tekrar karar verin.";

function hashGerekli(govde: unknown, guncel: string): void {
  const verilen = (govde as { icerik_hash?: unknown } | null | undefined)?.icerik_hash;
  if (typeof verilen !== "string" || !verilen) {
    throw new ApiError(422, "Karar, görüntülenen içeriğin hash'ini (icerik_hash) taşımalı.");
  }
  if (verilen !== guncel) throw new ApiError(409, ICERIK_DEGISMIS);
}
/**
 * core `transition` ile aynı kural: `nesne.durum`'u `yol` boyunca ilerletir; yoldaki her adım
 * `durum-makineleri.json`'da izinli olmalı, değilse hiçbir şey değişmez ve 409 döner.
 * Mock, core'un reddedeceği bir geçişi asla göstermez.
 */
function gecir<D extends string>(makine: MakineAdi, nesne: { durum: D }, ...yol: D[]): void {
  if (!yolGecerli(makine, nesne.durum, yol)) throw new ApiError(409, GECIS_YOK);
  nesne.durum = yol[yol.length - 1];
}

const bekle = (ms: number) => new Promise((r) => setTimeout(r, ms));

function denetimEkle(eylem: string, nesne: string, ozet: string, aktor?: string): void {
  veri.denetim.push({ aktor: aktor ?? oturum()?.kullanici_adi ?? "sistem", eylem, nesne, ozet, zaman: simdi() });
}

function sayaclariGuncelle(g: GereksinimDetay): void {
  const cs = caseSayilari(veri.caseler, g.id);
  g.sayaclar = {
    bulgu_acik: veri.bulgular.filter((b) => b.requirement_id === g.id && (b.durum === "open" || b.durum === "decided")).length,
    case_toplam: cs.toplam,
    case_onayli: cs.onayli,
  };
}

/** jira-sim seed'i TPD-1..TPD-7 ile gelir; ürünün oluşturduğu kayıtlar TPD-8'den başlar. */
export const JIRA_SIM_SON_NO = 7;

/** Sıradaki Jira anahtarı: simülatör seed'i + örnek veride oluşturulmuş kayıtların en büyüğü + 1. */
function yeniJiraAnahtari(): string {
  const nolar = [
    ...veri.caseler.map((c) => c.jira_test_key),
    // Bağlanan kayıtlar ürünün oluşturduğu kayıt değildir; yalnızca "new" ile açılanlar sayılır.
    ...veri.bugTaslaklari.filter((b) => b.durum === "published" && b.karar === "new").map((b) => b.jira_key),
  ]
    .map((k) => /^TPD-(\d+)$/.exec(k ?? "")?.[1])
    .filter((n): n is string => n !== undefined)
    .map(Number);
  return `TPD-${Math.max(JIRA_SIM_SON_NO, ...nolar) + 1}`;
}

/** Sıradaki PR numarası (LocalForge sayacını taklit eder). */
function yeniPrNo(): number {
  const nolar = [
    ...veri.scriptler.map((s) => s.pr?.number ?? 0),
    ...veri.hatalar.map((h) => (h.oneri?.tur === "locator_fix" ? (h.oneri.pr?.number ?? 0) : 0)),
  ];
  return Math.max(10, ...nolar) + 1;
}

function gereksinimOlayi(g: GereksinimDetay): void {
  sayaclariGuncelle(g);
  kaydet();
  mockOlayYayinla({ type: "requirement.updated", id: g.id, data: { durum: g.durum } });
}

/** Zamanlanmış arka plan işi (setTimeout zinciri). Hatalar yutulur ve denetime düşer. */
function arkaPlan(adimlar: (() => void)[]): void {
  let i = 0;
  const sonraki = () => {
    if (i >= adimlar.length) return;
    try {
      adimlar[i++]();
      kaydet();
    } catch (e) {
      denetimEkle("job.error", "mock", String(e), "core-worker");
    }
    setTimeout(sonraki, ayar.isAdimiMs);
  };
  setTimeout(sonraki, ayar.isAdimiMs);
}

function is(durum: string, mesaj?: string): IsYaniti {
  return { job_id: yeniId("job"), durum, mesaj };
}

// ------------------------------------------------------------------ uçlar

function login(govde: unknown): Kullanici {
  const g = (govde ?? {}) as { kullanici_adi?: string; parola?: string };
  const k = g.kullanici_adi ? KULLANICILAR[g.kullanici_adi.trim().toLowerCase()] : undefined;
  if (!k || !g.parola) throw new ApiError(401, "Kullanıcı adı veya parola hatalı.");
  mockOturumuAyarla(k);
  try {
    sessionStorage.setItem(OTURUM_ANAHTARI, JSON.stringify(k));
  } catch {
    /* yoksay */
  }
  denetimEkle("auth.login", k.kullanici_adi, "Oturum açıldı (örnek veri modu)", k.kullanici_adi);
  return k;
}

function logout(): void {
  mockOturumuAyarla(null);
  try {
    sessionStorage.removeItem(OTURUM_ANAHTARI);
  } catch {
    /* yoksay */
  }
}

function serbestMetin(govde: unknown): GereksinimDetay {
  rolGerekli("analyst");
  const g = (govde ?? {}) as Partial<SerbestMetinGirdisi>;
  const baslik = (g.baslik ?? "").trim();
  const aciklama = (g.aciklama ?? "").trim();
  const ac = (g.ac ?? []).map((x) => x.trim()).filter(Boolean);
  if (baslik.length < 3) throw new ApiError(422, "Başlık en az 3 karakter olmalı.");
  if (baslik.length > 200) throw new ApiError(422, "Başlık en fazla 200 karakter olabilir.");
  if (!aciklama) throw new ApiError(422, "Açıklama zorunlu.");
  const id = yeniId("req-ft");
  const yeni: GereksinimDetay = {
    id,
    kaynak: "free_text",
    jira_key: null,
    baslik,
    aciklama,
    kabul_kriterleri: ac.map((metin, i) => ({ ref: `AC${i + 1}`, metin })),
    ac_missing: ac.length === 0,
    durum: "new",
    cekim_zamani: simdi(),
    po: { durum: "not_requested", onaylayan: null, zaman: null, kanal: "portal" },
    sayaclar: { bulgu_acik: 0, case_toplam: 0, case_onayli: 0 },
    on_inceleme: null,
    kontrol_turu: 0,
    kontrol_turu_ust_sinir: 3,
    jira_url: null,
    uyarilar: ac.length === 0 ? ["Kabul kriteri yok: case üretimine gönderilmez."] : [],
    icerik_hash: "",
  };
  veri.gereksinimler.unshift(yeni);
  denetimEkle("requirements.free_text", id, baslik);
  kaydet();
  return cikti(yeni);
}

/**
 * Jira story'si için kontrol turunun golden REPLAY bulguları (consistency_check/golden/<anahtar>
 * ya da 2. ve sonraki turlarda <anahtar>-r<tur>). Golden kaydı yoksa null (REPLAY-MISS).
 */
function goldenTurBulgulari(g: GereksinimDetay): Bulgu[] | null {
  if (!g.jira_key) return null;
  const kayit = goldenBulgular(g.kontrol_turu >= 2 ? `${g.jira_key}-r${g.kontrol_turu}` : g.jira_key);
  if (!kayit) return null;
  return kayit.map((f) => {
    const tekAc = g.kabul_kriterleri.find((a) => a.ref === f.doc_ref);
    return {
      ...bulguCiktisi(f, tekAc?.metin ?? null),
      id: yeniId("fnd"),
      requirement_id: g.id,
      kanit_dogrulandi: true,
      karar: null,
      karar_metni: null,
      gerekce: null,
      karar_veren: null,
      karar_zamani: null,
      kontrol_turu: g.kontrol_turu,
      durum: "open" as const,
      bug_draft_id: null,
      icerik_hash: "",
      mode: "replay" as const,
    };
  });
}

/**
 * Tutarlılık "incelemesi": Jira story'lerinde golden REPLAY bulguları; serbest metinde (golden yok)
 * ölçülebilir iddiaları demo uygulamasıyla karşılaştıran deterministik kurallar.
 */
function incelemeBulgulari(g: GereksinimDetay): Bulgu[] {
  const golden = goldenTurBulgulari(g);
  if (golden) return golden;
  const bulgular: Bulgu[] = [];
  const ortak = {
    requirement_id: g.id,
    kanit_dogrulandi: true,
    karar: null,
    karar_metni: null,
    gerekce: null,
    karar_veren: null,
    karar_zamani: null,
    kontrol_turu: g.kontrol_turu,
    durum: "open" as const,
    bug_draft_id: null,
    icerik_hash: "",
    mode: "replay" as const,
  };
  for (const ac of g.kabul_kriterleri) {
    if (/7 adet/i.test(ac.metin)) {
      bulgular.push({
        ...ortak,
        id: yeniId("fnd"),
        type: "doc_vs_code",
        doc_ref: ac.ref,
        ozet: "Doküman 7 adette 1 bedava diyor; kod her 6 adette 1 bedava uyguluyor.",
        evidence: [KAMPANYA_KOD],
        severity: "blocking",
        mevcut_doc_text: ac.metin,
        suggested_doc_text: ac.metin.replace(/7 adet/gi, "6 adet"),
      });
    }
    if (/500,00 TL/.test(ac.metin)) {
      bulgular.push({
        ...ortak,
        id: yeniId("fnd"),
        type: "doc_vs_data",
        doc_ref: ac.ref,
        ozet: "Doküman minimum tutarı 500,00 TL diyor; ayar tablosunda 750,00 TL.",
        evidence: [MIN_SIPARIS_VERI],
        severity: "blocking",
        mevcut_doc_text: ac.metin,
        suggested_doc_text: ac.metin.replace(/500,00 TL/g, "750,00 TL"),
      });
    }
  }
  return bulgular;
}

function incelemeBaslat(id: string): IsYaniti {
  rolGerekli("analyst");
  const g = bul(veri.gereksinimler, id, "Gereksinim");
  if (g.ac_missing) throw new ApiError(409, "Kabul kriteri olmayan story incelemeye alınmaz.");
  if (!["new", "findings_open", "failed"].includes(g.durum)) {
    throw new ApiError(409, "Bu durumda ön inceleme başlatılamaz.");
  }
  gecir("requirement", g, "in_review");
  g.kontrol_turu = Math.max(1, g.kontrol_turu + (g.kontrol_turu === 0 ? 1 : 0));
  denetimEkle("requirement.review", g.jira_key ?? g.id, "Ön inceleme + tutarlılık denetimi başlatıldı");
  gereksinimOlayi(g);
  arkaPlan([
    () => {
      // Jira story'sinde golden REPLAY ön inceleme; serbest metinde kayıt yok → REPLAY-MISS.
      const golden = g.jira_key ? goldenInceleme(g.jira_key) : undefined;
      g.on_inceleme = {
        verdict: golden?.verdict ?? "needs_po",
        mode: golden ? "replay" : "replay_miss",
        zaman: simdi(),
        jira_comment_id: g.kaynak === "jira" ? yeniId("cmt") : null,
        questions: golden
          ? goldenSorular(g.jira_key!)
          : [
              {
                id: "Q1",
                type: "ambiguity",
                text: "Kabul kriterlerinde belirtilmeyen hata durumunda kullanıcıya hangi mesaj gösterilmeli?",
                ac_ref: g.kabul_kriterleri[0]?.ref ?? null,
                cevap: null,
              },
            ],
      };
      const yeni = incelemeBulgulari(g);
      veri.bulgular = veri.bulgular.filter((b) => !(b.requirement_id === g.id && b.durum === "open"));
      veri.bulgular.push(...yeni);
      if (yeni.some((b) => b.severity === "blocking")) {
        gecir("requirement", g, "findings_open");
      } else {
        poBekle(g);
      }
      denetimEkle("ai_call", g.id, `Ön inceleme: ${yeni.length} bulgu (replay)`, "core-worker");
      gereksinimOlayi(g);
    },
  ]);
  return is("started", "Ön inceleme başlatıldı.");
}

/** core: in_review → doc_final (bulgu kalmadı, doküman son hâlinde) → pending_po. */
function poBekle(g: GereksinimDetay): void {
  gecir("requirement", g, "doc_final", "pending_po");
  g.po = { durum: "pending", onaylayan: null, zaman: null, kanal: g.kaynak === "jira" ? "jira" : "portal" };
}

function bulguKarari(id: string, govde: unknown): Bulgu {
  const k = rolGerekli("analyst");
  const b = bul(veri.bulgular, id, "Bulgu");
  const g = (govde ?? {}) as Partial<BulguKararGirdisi>;
  if (!g.karar || !["fix_doc", "code_defect", "accept_difference"].includes(g.karar)) {
    throw new ApiError(422, "Karar fix_doc, code_defect veya accept_difference olmalı.");
  }
  hashGerekli(govde, b.icerik_hash);
  // core: kapı yalnızca open → decided (decided → open → decided ile karar değiştirilebilir).
  if (b.durum === "unverified") throw new ApiError(409, "Kanıtı doğrulanmamış bulgu için karar verilemez.");
  if (b.durum !== "open" && b.durum !== "decided") throw new ApiError(409, "Bu bulgu için karar zaten uygulanmış.");
  if (g.karar === "accept_difference" && !(g.gerekce ?? "").trim()) {
    throw new ApiError(422, "Bilinçli fark kararı için gerekçe zorunludur.");
  }
  if (g.karar === "fix_doc" && !(g.metin ?? b.suggested_doc_text ?? "").trim()) {
    throw new ApiError(422, "Düzeltilmiş doküman metni boş olamaz.");
  }
  // core: open → decided (kapı); kararı değiştirmek decided → open → decided. fix_doc, düzeltme
  // dokümana yazılana dek decided kalır; code_defect / accept_difference hemen decided → resolved.
  const yol: Bulgu["durum"][] = [...(b.durum === "decided" ? (["open"] as const) : []), "decided"];
  if (g.karar !== "fix_doc") yol.push("resolved");
  gecir("consistency_finding", b, ...yol);
  b.karar = g.karar;
  b.karar_veren = k.kullanici_adi;
  b.karar_zamani = simdi();
  b.gerekce = g.gerekce?.trim() || null;
  b.karar_metni = g.karar === "fix_doc" ? (g.metin ?? b.suggested_doc_text ?? "").trim() : null;
  if (g.karar === "code_defect" && !b.bug_draft_id) {
    const req = bul(veri.gereksinimler, b.requirement_id, "Gereksinim");
    const taslak: BugTaslagi = {
      id: yeniId("bug"),
      kaynak: "consistency",
      failure_id: null,
      finding_id: b.id,
      icerik: {
        summary: `${req.jira_key ?? req.baslik} ${b.doc_ref}: ${b.ozet}`.slice(0, 200),
        steps: ["Bulgudaki kanıtı inceleyin", `${b.doc_ref} için beklenen davranışı uygulamada deneyin`],
        expected: b.mevcut_doc_text ?? "Dokümandaki davranış",
        actual: b.ozet,
        environment: "Tutarlılık denetimi · demo-app main",
        evidence: b.evidence.map((e) =>
          e.kind === "code"
            ? { tur: "code" as const, url: null, etiket: `${e.repo} · ${e.path}:${e.line}` }
            : { tur: "data" as const, url: `#${b.id}`, etiket: e.query },
        ),
        story_key: req.jira_key,
        test_case_key: null,
        severity_suggestion: "major",
        labels: ["AI-generated"],
      },
      mukerrer_adaylari: [],
      karar: null,
      durum: "draft",
      link_key: null,
      icerik_hash: "",
      onaylayan: null,
      onay_zamani: null,
      jira_key: null,
      mode: b.mode,
      olusturma: simdi(),
    };
    veri.bugTaslaklari.unshift(taslak);
    b.bug_draft_id = taslak.id;
  }
  denetimEkle("finding.decision", b.id, `${g.karar}${b.gerekce ? `: ${b.gerekce}` : ""}`);
  const req = bul(veri.gereksinimler, b.requirement_id, "Gereksinim");
  gereksinimOlayi(req);
  mockOlayYayinla({ type: "finding.updated", id: b.id, data: { karar: b.karar } });
  return cikti(b);
}

function duzeltmeleriUygula(id: string): IsYaniti {
  rolGerekli("analyst");
  const g = bul(veri.gereksinimler, id, "Gereksinim");
  const uygulanacak = veri.bulgular.filter((b) => b.requirement_id === id && b.karar === "fix_doc" && b.durum === "decided");
  if (uygulanacak.length === 0) throw new ApiError(409, "Uygulanacak onaylı doküman düzeltmesi yok.");
  if (g.kontrol_turu >= g.kontrol_turu_ust_sinir) {
    throw new ApiError(409, "Kontrol turu sınırına ulaşıldı (3); insan kararı gerekiyor.");
  }
  // core: findings_open → in_review (onaylı düzeltmeler yazılır, ardından yeniden kontrol).
  gecir("requirement", g, "in_review");
  gereksinimOlayi(g);
  arkaPlan([
    () => {
      for (const b of uygulanacak) {
        const ac = g.kabul_kriterleri.find((a) => b.doc_ref.split(/\s|↔/).includes(a.ref));
        if (ac && b.karar_metni) ac.metin = b.karar_metni;
        gecir("consistency_finding", b, "resolved"); // core: decided → resolved (düzeltme dokümana yazıldı)
      }
      g.kontrol_turu += 1;
      // Yeniden kontrol: bu tur için golden kayıt varsa onun bulguları (ör. TPD-1-r2) eklenir.
      const yeniTur = goldenTurBulgulari(g);
      if (yeniTur) veri.bulgular.push(...yeniTur);
      const acikEngelleyici = veri.bulgular.some(
        (b) => b.requirement_id === id && b.severity === "blocking" && (b.durum === "open" || b.durum === "decided"),
      );
      if (acikEngelleyici) {
        gecir("requirement", g, "findings_open");
      } else {
        poBekle(g);
      }
      denetimEkle(
        g.kaynak === "jira" ? "jira.update" : "requirement.update",
        g.jira_key ?? g.id,
        `${uygulanacak.length} düzeltme yazıldı; yeniden kontrol turu ${g.kontrol_turu}`,
        "core-worker",
      );
      gereksinimOlayi(g);
    },
  ]);
  return is("started", `${uygulanacak.length} düzeltme yazılıyor.`);
}

function poOnayla(id: string, govde: unknown): GereksinimDetay {
  const k = rolGerekli("po");
  const g = bul(veri.gereksinimler, id, "Gereksinim");
  if (g.kaynak === "jira") {
    throw new ApiError(409, "Jira yolunda PO teyidi Jira'daki tp-po-approved etiketiyle verilir.");
  }
  hashGerekli(govde, g.icerik_hash);
  if (g.durum !== "pending_po") throw new ApiError(409, "Gereksinim PO teyidi beklemiyor.");
  gecir("requirement", g, "po_approved");
  g.po = { durum: "approved", onaylayan: k.kullanici_adi, zaman: simdi(), kanal: "portal" };
  denetimEkle("po.approve", g.id, `PO teyidi (portal) · ${g.icerik_hash}`);
  gereksinimOlayi(g);
  return cikti(g);
}

function caseUret(id: string): IsYaniti {
  rolGerekli("analyst");
  const g = bul(veri.gereksinimler, id, "Gereksinim");
  if (g.po.durum !== "approved") throw new ApiError(409, "PO teyidi olmadan case üretilemez.");
  if (g.ac_missing) throw new ApiError(409, "Kabul kriteri olmayan story case üretimine gönderilmez.");
  if (!["po_approved", "cases_ready"].includes(g.durum)) throw new ApiError(409, "Bu durumda case üretilemez.");
  gecir("requirement", g, "generating");
  gereksinimOlayi(g);
  const mevcut = veri.caseler.filter((c) => c.requirement_id === id).length;
  const uretilecek = g.kabul_kriterleri.slice(0, 4);
  arkaPlan([
    ...uretilecek.map((ac, i) => () => {
      const icerik: TestCaseIcerik = {
        title: `${ac.ref}: ${ac.metin}`.slice(0, 120),
        type: i % 3 === 0 ? "positive" : i % 3 === 1 ? "negative" : "boundary",
        risk: i === 0 ? "high" : "medium",
        acceptance_criteria_refs: [ac.ref],
        preconditions: ["bayi1 / Demo123! ile giriş yapılmış"],
        steps: [
          { id: "S1", action: "Kataloğa git", data: null, expected: "Ürünler listelenir" },
          { id: "S2", action: `${ac.ref} koşulunu oluştur`, data: null, expected: ac.metin },
        ],
        expected_result: ac.metin,
        tags: ["AI-generated"],
      };
      const tc: TestCase = {
        id: yeniId("case"),
        requirement_id: id,
        jira_key: g.jira_key,
        sira_no: mevcut + i + 1,
        kanal: "portal",
        surum: 1,
        icerik,
        durum: "draft",
        karar: null,
        ret_nedeni: null,
        karar_veren: null,
        karar_zamani: null,
        duzeltme_olcusu: null,
        icerik_hash: icerikHash(icerik),
        onaylanan_hash: null,
        ai_generated: true,
        ai_sure_ms: 5200 + i * 300,
        review_sure_ms: null,
        maliyet_usd: 0,
        jira_test_key: null,
        mode: "replay",
      };
      veri.caseler.push(tc);
      mockOlayYayinla({ type: "case.generated", id: tc.id, data: { requirement_id: id, title: icerik.title } });
    }),
    () => {
      gecir("requirement", g, "cases_ready");
      denetimEkle("ai_call", g.id, `Case üretimi: ${uretilecek.length} case (replay)`, "core-worker");
      gereksinimOlayi(g);
    },
  ]);
  return is("started", "Case üretimi başlatıldı.");
}

function caseKarari(id: string, govde: unknown): TestCase {
  const k = rolGerekli("analyst");
  const c = bul(veri.caseler, id, "Case");
  const g = (govde ?? {}) as Partial<CaseKararGirdisi>;
  if (!g.karar || !["approve", "edit", "reject"].includes(g.karar)) {
    throw new ApiError(422, "Karar approve, edit veya reject olmalı.");
  }
  hashGerekli(govde, c.icerik_hash);
  if (c.durum === "published") throw new ApiError(409, "Yayınlanmış case değiştirilemez.");
  if (c.durum === "superseded") throw new ApiError(409, "Bu case'in yerini yenisi aldı; karar verilemez.");
  // core test_case makinesi: kararlar yalnızca draft'tan (draft → approved | rejected).
  const hedef = CASE_KARAR_HEDEFI[g.karar];
  if (!yolGecerli("test_case", c.durum, [hedef])) throw new ApiError(409, GECIS_YOK);
  if (g.karar === "reject") {
    if (!g.ret_nedeni) throw new ApiError(422, "Ret için neden seçilmelidir.");
    gecir("test_case", c, "rejected");
    c.ret_nedeni = g.ret_nedeni;
    c.onaylanan_hash = null;
  } else if (g.karar === "edit") {
    if (!g.icerik) throw new ApiError(422, "Düzeltme için içerik zorunludur.");
    if (!g.icerik.title.trim() || g.icerik.steps.length === 0) throw new ApiError(422, "Başlık ve en az bir adım zorunlu.");
    const once = kanonikJson(c.icerik);
    c.icerik = g.icerik;
    c.surum += 1;
    c.icerik_hash = icerikHash(g.icerik);
    c.onaylanan_hash = c.icerik_hash;
    c.duzeltme_olcusu = Math.round(duzeltmeOlcusu(once, kanonikJson(g.icerik)) * 100) / 100;
    gecir("test_case", c, "approved");
    c.ret_nedeni = null;
  } else {
    gecir("test_case", c, "approved");
    c.onaylanan_hash = c.icerik_hash;
    c.duzeltme_olcusu = 0;
    c.ret_nedeni = null;
  }
  c.karar = g.karar;
  c.karar_veren = k.kullanici_adi;
  c.karar_zamani = simdi();
  c.review_sure_ms = 20000 + Math.round(Math.random() * 40000);
  denetimEkle("case.decision", c.id, g.karar === "reject" ? `reject: ${g.ret_nedeni}` : g.karar);
  const req = veri.gereksinimler.find((r) => r.id === c.requirement_id);
  if (req) gereksinimOlayi(req);
  else kaydet();
  return cikti(c);
}

function yayinOnizleme(q: URLSearchParams): YayinOnizleme {
  rolGerekli("analyst");
  const rid = q.get("requirement_id");
  if (!rid) throw new ApiError(422, "requirement_id zorunlu.");
  const g = bul(veri.gereksinimler, rid, "Gereksinim");
  const caseler = veri.caseler.filter((c) => c.requirement_id === rid && c.durum !== "rejected");
  return {
    requirement_id: rid,
    hedef: "jira",
    proje: "TPD",
    uyarilar: g.kaynak === "free_text" ? ["Serbest metin gereksinim: Test issue'ları story bağlantısı olmadan oluşturulur."] : [],
    kalemler: caseler.map((c) => ({
      case_id: c.id,
      title: c.icerik.title,
      issue_type: "Test",
      summary: `[${g.jira_key ?? "FT"}] ${c.icerik.title}`,
      labels: ["AI-generated", `tp-${c.id}`],
      link: { type: "is tested by", story_key: g.jira_key },
      adim_sayisi: c.icerik.steps.length,
      islem:
        c.durum === "published"
          ? "skip_existing"
          : c.durum !== "approved"
            ? "blocked_not_approved"
            : c.onaylanan_hash !== c.icerik_hash
              ? "blocked_hash_mismatch"
              : "create",
      external_key: c.jira_test_key,
    })),
  };
}

function yayinla(govde: unknown): YayinSonucu {
  rolGerekli("analyst");
  const ids = ((govde ?? {}) as { case_ids?: string[] }).case_ids ?? [];
  if (!Array.isArray(ids) || ids.length === 0) throw new ApiError(422, "En az bir case seçilmeli.");
  const sonuclar = ids.map((id) => {
    const c = veri.caseler.find((x) => x.id === id);
    if (!c) return { case_id: id, durum: "failed" as const, external_key: null, hata: "Case bulunamadı" };
    if (c.durum === "published") return { case_id: id, durum: "exists" as const, external_key: c.jira_test_key, hata: null };
    if (c.durum !== "approved") return { case_id: id, durum: "failed" as const, external_key: null, hata: "Onaylı değil" };
    if (c.onaylanan_hash !== c.icerik_hash) {
      return { case_id: id, durum: "failed" as const, external_key: null, hata: "İçerik onaydan sonra değişmiş" };
    }
    gecir("test_case", c, "published");
    c.jira_test_key = yeniJiraAnahtari();
    return { case_id: id, durum: "created" as const, external_key: c.jira_test_key, hata: null };
  });
  const olusan = sonuclar.filter((s) => s.durum === "created");
  for (const r of veri.gereksinimler) {
    // core: cases_ready → done (case'ler yayınlandı; akış koda geçer).
    if (r.durum === "cases_ready" && veri.caseler.some((c) => c.requirement_id === r.id && c.durum === "published")) {
      gecir("requirement", r, "done");
    }
    sayaclariGuncelle(r);
  }
  denetimEkle("publish", "jira", `${olusan.length} Test issue: ${olusan.map((s) => s.external_key).join(", ") || "—"}`);
  kaydet();
  return { hedef: "jira", sonuclar };
}

function kodUret(govde: unknown): IsYaniti {
  rolGerekli("engineer");
  const ids = ((govde ?? {}) as { case_ids?: string[] }).case_ids ?? [];
  if (!Array.isArray(ids) || ids.length === 0) throw new ApiError(422, "En az bir case seçilmeli.");
  const caseler = ids.map((id) => bul(veri.caseler, id, "Case"));
  const onaysiz = caseler.filter((c) => c.durum !== "approved" && c.durum !== "published");
  if (onaysiz.length) throw new ApiError(409, "Yalnızca onaylı case'ler için kod üretilebilir.");
  for (const c of caseler) {
    const id = yeniId("scr");
    const branch = `tp/case-${sha256Hex(c.id).slice(0, 8)}`;
    const s: ScriptDetay = {
      id,
      case_ids: [c.id],
      requirement_key: c.jira_key,
      baslik: c.icerik.title,
      dosya_yolu: `demo-app/e2e/tests/${(c.jira_key ?? "ft").toLowerCase()}/c${c.sira_no}.spec.ts`,
      branch,
      durum: "pending",
      pr: null,
      pass_at_1: null,
      zayif_test: false,
      break_verify: {
        durum: "not_started",
        asamalar: (["baseline", "broken", "restored"] as const).map((ad) => ({ ad, sonuc: "pending", run_id: null, zaman: null })),
      },
      // Tek golden kayıt (TPD-1 C2 kampanya testi) var; diğer case'ler için replay ıskalar ve
      // adlandırılmış golden kayda düşülür — bu sessiz geçmez, REPLAY-MISS olarak işaretlenir (§8.8).
      mode: c.id === "case-1-2" ? "replay" : "replay_miss",
      olusturma: simdi(),
      hata: null,
      kod: null,
      adimlar: [],
      yerel_kontrol: null,
    };
    veri.scriptler.unshift(s);
    const adimlar = kampanyaAdimlari();
    arkaPlan([
      ...adimlar.map((a) => () => {
        if (s.durum !== "verifying") gecir("script", s, "verifying");
        const yeniAdim = { ...a, zaman: simdi() };
        s.adimlar.push(yeniAdim);
        mockOlayYayinla({ type: "agent.step", id: s.id, data: { ...yeniAdim } });
      }),
      () => {
        gecir("script", s, "checking");
        s.kod = KAMPANYA_TEST_KODU;
        if (s.mode === "replay_miss") {
          s.hata =
            "REPLAY-MISS: bu case için kayıtlı çıktı yok; adlandırılmış golden kayıt (TPD-1 C2) yalnızca referans olarak gösteriliyor. PR açılmadı; canlı model gerekir.";
        }
        s.yerel_kontrol = { tsc: true, eslint: true, ast_guard: true, tekrar: 3 };
        mockOlayYayinla({ type: "ci.status", id: s.id, data: { durum: "checking" } });
      },
      () => {
        if (s.mode === "replay_miss") {
          // Golden kayıt başka bir case'e ait: PR açılmaz, insana düşer (sahte başarı yok).
          gecir("script", s, "failed");
          denetimEkle("code.generate", s.id, "REPLAY-MISS: PR açılmadı", "core-worker");
          mockOlayYayinla({ type: "ci.status", id: s.id, data: { durum: "failed" } });
          return;
        }
        const prNo = yeniPrNo();
        gecir("script", s, "pr_open");
        s.pass_at_1 = true;
        s.pr = {
          number: prNo,
          url: null,
          baslik: `test(${c.jira_key ?? "FT"}): ${c.icerik.title} [AI-generated]`,
          branch,
          durum: "open",
          ci: "passed",
          icerik_hash: "", // hashleriTazele: dosya + kod
          head_sha: "",
        };
        denetimEkle("pr.open", `PR #${prNo}`, branch, "core-worker");
        mockOlayYayinla({ type: "pr.opened", id: s.id, data: { number: prNo } });
      },
    ]);
  }
  denetimEkle("code.generate", ids.join(","), "CasesToCode başlatıldı");
  kaydet();
  return is("started", `${caseler.length} case için kod üretimi başladı.`);
}

function ozetKosu(k: KosuDetay): Kosu {
  const { sonuclar: _s, ...ozet } = k;
  void _s;
  return ozet;
}

function kosuOlustur(tetik: Kosu["tetik"], kaynak: Kosu["kaynak"], break_campaign: boolean, pr_no: number | null): KosuDetay {
  const k: KosuDetay = {
    id: yeniId("run"),
    tetik,
    kaynak,
    commit: sha256Hex(String(veri.sayac)).slice(0, 7),
    pr_no,
    durum: "queued",
    baslangic: simdi(),
    sure_ms: null,
    toplam: 0,
    gecen: 0,
    basarisiz: 0,
    flaky: 0,
    atlanan: 0,
    allure_url: null,
    sauce_url: null,
    ci_url: null,
    break_campaign,
    sonuclar: [],
  };
  veri.kosular.unshift(k);
  return k;
}

function kosuBitir(k: KosuDetay, gecti: boolean, testAdi: string): void {
  k.durum = gecti ? "passed" : "failed";
  k.sure_ms = 48000 + Math.round(Math.random() * 20000);
  k.sonuclar = [
    {
      id: `${k.id}-1`,
      test_adi: testAdi,
      durum: gecti ? "passed" : "failed",
      sure_ms: 6000,
      retry: 0,
      hata_mesaji: gecti ? null : "Beklenen: \"25,00 TL\" · Gerçekleşen: \"0,00 TL\" (BREAK_CAMPAIGN=1)",
      failure_id: null,
      case_id: null,
    },
  ];
  k.toplam = 1;
  k.gecen = gecti ? 1 : 0;
  k.basarisiz = gecti ? 0 : 1;
  mockOlayYayinla({ type: "ci.status", id: k.id, data: { durum: k.durum } });
}

function kirarakDogrula(id: string): IsYaniti {
  rolGerekli("engineer");
  const s = bul(veri.scriptler, id, "Script");
  if (!s.pr || s.pr.durum !== "open") throw new ApiError(409, "Kırarak doğrulama için açık PR gerekir.");
  if (s.break_verify.durum === "running") throw new ApiError(409, "Kırarak doğrulama zaten sürüyor.");
  const bv = s.break_verify;
  bv.durum = "running";
  bv.asamalar = (["baseline", "broken", "restored"] as const).map((ad) => ({ ad, sonuc: "pending", run_id: null, zaman: null }));
  denetimEkle("script.break_verify", s.id, "BREAK_CAMPAIGN ile doğrulama başlatıldı");
  kaydet();
  const asama = (i: number, kir: boolean) => [
    () => {
      const k = kosuOlustur("pr", "local", kir, s.pr?.number ?? null);
      k.durum = "running";
      bv.asamalar[i] = { ...bv.asamalar[i], sonuc: "running", run_id: k.id, zaman: simdi() };
      mockOlayYayinla({ type: "ci.status", id: s.id, data: { asama: bv.asamalar[i].ad, sonuc: "running" } });
    },
    () => {
      const k = veri.kosular.find((x) => x.id === bv.asamalar[i].run_id);
      if (k) kosuBitir(k, !kir, s.baslik);
      bv.asamalar[i] = { ...bv.asamalar[i], sonuc: kir ? "failed" : "passed", zaman: simdi() };
      mockOlayYayinla({ type: "ci.status", id: s.id, data: { asama: bv.asamalar[i].ad, sonuc: bv.asamalar[i].sonuc } });
    },
  ];
  arkaPlan([
    ...asama(0, false),
    ...asama(1, true),
    ...asama(2, false),
    () => {
      bv.durum = "passed";
      // Durum pr_open kalır (core); "merge'e hazır" PR + CI + kırma sonucundan türetilir.
      s.zayif_test = false;
      denetimEkle("script.break_verify", s.id, "yeşil → kırmızı → yeşil: test hata yakalıyor", "core-worker");
      mockOlayYayinla({ type: "ci.status", id: s.id, data: { break_verify: "passed" } });
    },
  ]);
  return is("started", "Kırarak doğrulama başladı.");
}

/** Merge gövdesi: incelenen içerik hash'i ve head sha (core ForgePort.merge_pr expected_head_sha). */
function mergeBagi(govde: unknown, pr: PullRequest): void {
  hashGerekli(govde, pr.icerik_hash);
  const head = (govde as { head_sha?: unknown } | null | undefined)?.head_sha;
  if (typeof head !== "string" || !head) throw new ApiError(422, "Merge, incelenen head sha'yı (head_sha) taşımalı.");
  if (head !== pr.head_sha) throw new ApiError(409, "PR head sha'sı siz incelediğinizden beri değişmiş; yenileyip tekrar inceleyin.");
}

function prBirlestir(no: number, govde: unknown) {
  rolGerekli("engineer");
  const s = veri.scriptler.find((x) => x.pr?.number === no);
  const h = veri.hatalar.find((x) => x.oneri?.tur === "locator_fix" && x.oneri.pr?.number === no);
  if (s?.pr) {
    mergeBagi(govde, s.pr);
    if (s.pr.durum !== "open") throw new ApiError(409, "PR açık değil.");
    if (s.zayif_test) throw new ApiError(409, "Zayıf test: kırarak doğrulamada hata yakalamadı; merge kapalı.");
    if (s.break_verify.durum !== "passed") {
      throw new ApiError(409, "Merge için önce \"Kırarak doğrula\" yeşil → kırmızı → yeşil tamamlanmalı.");
    }
    if (s.pr.ci !== "passed") throw new ApiError(409, "CI yeşil değil.");
    if (!yolGecerli("script", s.durum, ["merged"])) throw new ApiError(409, GECIS_YOK);
    s.pr.durum = "merged";
    gecir("script", s, "merged");
    denetimEkle("pr.merge", `PR #${no}`, `İnsan onaylı merge (LocalForge) · head ${s.pr.head_sha.slice(0, 7)}`);
    kaydet();
    return cikti(s.pr);
  }
  if (h && h.oneri?.tur === "locator_fix" && h.oneri.pr) {
    mergeBagi(govde, h.oneri.pr);
    if (h.oneri.pr.durum !== "open") throw new ApiError(409, "PR açık değil.");
    h.oneri.pr.durum = "merged";
    h.oneri.durum = "merged";
    denetimEkle("pr.merge", `PR #${no}`, "Locator onarımı birleştirildi");
    kaydet();
    return cikti(h.oneri.pr);
  }
  throw new ApiError(404, `PR bulunamadı: #${no}`);
}

function ciTetikle(govde: unknown): IsYaniti {
  rolGerekli("presenter");
  const tetik = ((govde ?? {}) as { tetik?: string }).tetik;
  if (tetik !== "deploy" && tetik !== "nightly") throw new ApiError(422, "tetik deploy veya nightly olmalı.");
  const k = kosuOlustur(tetik, "local", false, null);
  denetimEkle("ci.trigger", k.id, tetik === "deploy" ? "Deploy tetiklendi (repository_dispatch)" : "Gece koşusu tetiklendi");
  kaydet();
  arkaPlan([
    () => {
      k.durum = "running";
      mockOlayYayinla({ type: "ci.status", id: k.id, data: { durum: "running" } });
    },
    () => kosuBitir(k, true, TEST_C1),
  ]);
  return is("queued", `${tetik === "deploy" ? "Deploy" : "Gece"} koşusu sıraya alındı (${k.id}).`);
}

function onarimPr(id: string): IsYaniti {
  rolGerekli("engineer");
  const h = bul(veri.hatalar, id, "Hata analizi");
  if (h.oneri?.tur !== "locator_fix") throw new ApiError(409, "Bu hata için locator onarım önerisi yok.");
  const o = h.oneri;
  if (o.durum !== "proposed") throw new ApiError(409, "Onarım PR'ı zaten açılmış.");
  const prNo = yeniPrNo();
  o.durum = "pr_open";
  o.pr = {
    number: prNo,
    url: null,
    baslik: `fix(locators): ${o.anahtar} testId ${o.eski_test_id} → ${o.yeni_test_id}`,
    branch: `tp/repair-${o.anahtar}`,
    durum: "open",
    ci: "pending",
    icerik_hash: "", // hashleriTazele: dosya + anahtar + eski/yeni testId
    head_sha: "",
  };
  denetimEkle("failure.fix", h.id, `Onarım PR #${prNo} (yalnızca locators.ts testId)`);
  kaydet();
  arkaPlan([
    () => {
      if (o.pr) o.pr.ci = "passed";
      mockOlayYayinla({ type: "ci.status", id: h.id, data: { pr: o.pr?.number, ci: "passed" } });
    },
  ]);
  return is("started", `Onarım PR'ı #${prNo} açıldı.`);
}

function bugKarari(id: string, govde: unknown): BugTaslagi {
  const k = rolGerekli("tester");
  const b = bul(veri.bugTaslaklari, id, "Bug taslağı");
  const g = (govde ?? {}) as Partial<BugKararGirdisi>;
  if (g.karar !== "new" && g.karar !== "link" && g.karar !== "dismiss") {
    throw new ApiError(422, "Karar new, link veya dismiss olmalı.");
  }
  hashGerekli(govde, b.icerik_hash);
  if (b.durum !== "draft") throw new ApiError(409, "Taslak için karar zaten verilmiş.");
  if (!yolGecerli("bug_draft", b.durum, g.karar === "dismiss" ? ["dismissed"] : ["approved", "published"])) {
    throw new ApiError(409, GECIS_YOK);
  }
  // core: draft → approved (kapı) → published (Jira'ya yazıldı); mock iki geçişi tek adımda yapar.
  if (g.karar === "link") {
    const anahtar = (g.link_key ?? "").trim().toUpperCase();
    if (!/^[A-Z][A-Z0-9]+-\d+$/.test(anahtar)) throw new ApiError(422, "Bağlanacak Jira anahtarı geçersiz.");
    gecir("bug_draft", b, "approved", "published");
    b.link_key = anahtar;
    b.jira_key = anahtar;
  } else if (g.karar === "new") {
    if (g.icerik) {
      if (!g.icerik.summary.trim()) throw new ApiError(422, "Özet boş olamaz.");
      b.icerik = g.icerik;
    }
    gecir("bug_draft", b, "approved", "published");
    b.jira_key = yeniJiraAnahtari();
  } else {
    gecir("bug_draft", b, "dismissed");
  }
  b.karar = g.karar;
  b.onaylayan = k.kullanici_adi;
  b.onay_zamani = simdi();
  if (g.karar === "dismiss") {
    denetimEkle("bug.dismiss", b.id, "Taslak reddedildi (Jira'ya yazılmadı)");
  } else {
    denetimEkle("bug.publish", b.id, g.karar === "link" ? `${b.jira_key} kaydına bağlandı` : `Jira'da ${b.jira_key} açıldı`);
  }
  kaydet();
  mockOlayYayinla({ type: "bug.published", id: b.id, data: { jira_key: b.jira_key, durum: b.durum } });
  return cikti(b);
}

function kontrolKulesi(): KontrolKulesi {
  girisGerekli();
  const sonuclar = veri.kosular.flatMap((k) => k.sonuclar.map((s) => ({ ...s, kosu: k })));
  const sayilan = sonuclar.filter((s) => s.durum !== "skipped" && !s.kosu.break_campaign);
  const gecen = sayilan.filter((s) => s.durum === "passed" || s.durum === "flaky").length;
  const gunler = new Map<string, { g: number; t: number; k: Set<string> }>();
  for (const s of sayilan) {
    const gun = s.kosu.baslangic.slice(0, 10);
    const e = gunler.get(gun) ?? { g: 0, t: 0, k: new Set<string>() };
    e.t += 1;
    if (s.durum === "passed" || s.durum === "flaky") e.g += 1;
    e.k.add(s.kosu.id);
    gunler.set(gun, e);
  }
  const caseler = veri.caseler;
  const karar = caseler.filter((c) => c.karar);
  const kabul = karar.filter((c) => c.karar === "approve" || (c.karar === "edit" && (c.duzeltme_olcusu ?? 1) <= 0.15)).length;
  const reviewlar = karar.filter((c) => c.review_sure_ms !== null);
  const scriptler = veri.scriptler.filter((s) => s.pass_at_1 !== null);
  return {
    son_kosular: veri.kosular.slice(0, 6).map(ozetKosu),
    gecme_orani: { oran: sayilan.length ? gecen / sayilan.length : 0, toplam: sayilan.length, gecen, donem_gun: 7 },
    gunluk_gecme: [
      { tarih: "2026-10-24", oran: 1, kosu: 2 },
      { tarih: "2026-10-25", oran: 1, kosu: 1 },
      { tarih: "2026-10-26", oran: 0.9, kosu: 3 },
      { tarih: "2026-10-27", oran: 1, kosu: 2 },
      ...[...gunler.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([tarih, e]) => ({ tarih, oran: e.t ? e.g / e.t : 0, kosu: e.k.size })),
    ].slice(-7),
    flaky: [
      { test_adi: TEST_C2, neden: "retry", sayi: 1, son_gorulme: "2026-10-29T02:00:00+03:00" },
    ],
    karne: veri.gereksinimler
      .filter((g) => g.jira_key)
      .map((g) => {
        // Case sayısı gereksinim listesiyle aynı hesaptan (caseSayilari): reddedilenler hariç.
        const gc = caseler.filter((c) => c.requirement_id === g.id && c.durum !== "rejected");
        const otomatik = gc.filter((c) => veri.scriptler.some((s) => s.case_ids.includes(c.id) && s.durum === "merged")).length;
        const ilgili = sonuclar.filter((s) => s.test_adi.startsWith(`${g.jira_key} `) && !s.kosu.break_campaign);
        const son = ilgili[0];
        return {
          story_key: g.jira_key ?? g.id,
          baslik: g.baslik,
          alan: g.jira_key === "TPD-4" ? "Giriş" : g.jira_key === "TPD-2" ? "Sipariş geçmişi" : g.jira_key === "TPD-3" ? "Katalog" : "Sepet ve sipariş",
          case_sayisi: caseSayilari(caseler, g.id).toplam,
          otomasyon_kapsami: gc.length ? otomatik / gc.length : 0,
          son_sonuc: son ? (son.durum === "failed" ? "failed" : "passed") : "none",
          acik_bug: veri.bugTaslaklari.filter((b) => b.icerik.story_key === g.jira_key && b.durum === "published").length,
        };
      }),
    ai_katkisi: {
      kabul_orani: karar.length ? kabul / caseler.length : 0,
      kabul_hedefi: 0.7,
      script_ilk_review: scriptler.length ? scriptler.filter((s) => s.pass_at_1).length / scriptler.length : 0,
      script_hedefi: 0.6,
      ort_ai_sure_ms: caseler.length ? caseler.reduce((a, c) => a + c.ai_sure_ms, 0) / caseler.length : 0,
      ort_review_sure_ms: reviewlar.length ? reviewlar.reduce((a, c) => a + (c.review_sure_ms ?? 0), 0) / reviewlar.length : 0,
      manuel_baz_ms: 6 * 60 * 1000,
      maliyet_usd_toplam: caseler.reduce((a, c) => a + c.maliyet_usd, 0),
      maliyet_usd_bugun: 0,
      gunluk_butce_usd: 30,
      cagri_sayisi: 14 + caseler.length,
      replay_cagri: caseler.filter((c) => c.mode !== "live").length + 14,
    },
    a11y: {
      ihlal: 3,
      kritik: 1,
      son_tarama: "2026-10-30T02:04:00+03:00",
      sayfalar: [
        { yol: "/katalog", ihlal: 1, kritik: 0 },
        { yol: "/sepet", ihlal: 2, kritik: 1 },
        { yol: "/siparisler", ihlal: 0, kritik: 0 },
      ],
    },
  };
}

function denetim(q: URLSearchParams): DenetimYaniti {
  girisGerekli();
  let onceki = "0".repeat(64);
  const olaylar: DenetimOlayi[] = veri.denetim.map((o, i) => {
    const hash = sha256Hex(onceki + kanonikJson(o));
    const olay: DenetimOlayi = { id: `aud-${i + 1}`, sira: i + 1, ...o, prev_hash: onceki, hash };
    onceki = hash;
    return olay;
  });
  const dogrula = q.get("verify") === "true";
  return {
    olaylar: olaylar.slice().reverse(),
    dogrulama: dogrula
      ? { gecerli: true, kontrol_edilen: olaylar.length, ilk_kirik_id: null, son_hash: onceki, zaman: simdi() }
      : null,
  };
}

function tokenOlustur(govde: unknown): McpToken {
  rolGerekli("analyst");
  const kapsam = ((govde ?? {}) as { kapsam?: string }).kapsam;
  if (kapsam !== "submit" && kapsam !== "publish") throw new ApiError(422, "Kapsam submit veya publish olmalı.");
  const rastgele = new Uint8Array(24);
  crypto.getRandomValues(rastgele);
  const token = `tpk_mock_${Array.from(rastgele, (b) => b.toString(16).padStart(2, "0")).join("")}`;
  denetimEkle("token.create", kapsam, "8 saatlik MCP token'ı oluşturuldu");
  kaydet();
  return {
    token,
    kapsam,
    son_kullanma: new Date(Date.now() + 8 * 3600 * 1000).toISOString(),
    mcp_url: "http://127.0.0.1:8000/mcp",
  };
}

// ------------------------------------------------------------------ yönlendirme

type Rota = [string, RegExp, (m: RegExpMatchArray, q: URLSearchParams, govde: unknown) => unknown];

const ROTALAR: Rota[] = [
  ["POST", /^\/auth\/login$/, (_m, _q, g) => login(g)],
  ["POST", /^\/auth\/logout$/, () => logout()],
  ["GET", /^\/auth\/me$/, () => girisGerekli()],
  [
    "GET",
    /^\/requirements$/,
    () => {
      girisGerekli();
      return veri.gereksinimler.map((g) => {
        sayaclariGuncelle(g);
        const { on_inceleme: _o, kontrol_turu: _k, kontrol_turu_ust_sinir: _u, jira_url: _j, uyarilar: _w, ...ozet } = g;
        return ozet;
      });
    },
  ],
  [
    "POST",
    /^\/requirements\/sync$/,
    () => {
      rolGerekli("analyst");
      denetimEkle("requirements.sync", "TPD", "Jira'dan çekim (örnek veri: değişiklik yok)");
      kaydet();
      return is("done", "Jira'dan 4 story çekildi; yeni değişiklik yok.");
    },
  ],
  ["POST", /^\/requirements\/free-text$/, (_m, _q, g) => serbestMetin(g)],
  [
    "GET",
    /^\/requirements\/([^/]+)$/,
    (m) => {
      girisGerekli();
      const g = bul(veri.gereksinimler, decodeURIComponent(m[1]), "Gereksinim");
      sayaclariGuncelle(g);
      return g;
    },
  ],
  ["POST", /^\/requirements\/([^/]+)\/review$/, (m) => incelemeBaslat(decodeURIComponent(m[1]))],
  [
    "GET",
    /^\/requirements\/([^/]+)\/findings$/,
    (m) => {
      girisGerekli();
      const id = decodeURIComponent(m[1]);
      bul(veri.gereksinimler, id, "Gereksinim");
      return veri.bulgular.filter((b) => b.requirement_id === id);
    },
  ],
  ["POST", /^\/findings\/([^/]+)\/decision$/, (m, _q, g) => bulguKarari(decodeURIComponent(m[1]), g)],
  ["POST", /^\/requirements\/([^/]+)\/apply-doc-fixes$/, (m) => duzeltmeleriUygula(decodeURIComponent(m[1]))],
  ["POST", /^\/requirements\/([^/]+)\/po-approve$/, (m, _q, g) => poOnayla(decodeURIComponent(m[1]), g)],
  ["POST", /^\/requirements\/([^/]+)\/generate-cases$/, (m) => caseUret(decodeURIComponent(m[1]))],
  [
    "GET",
    /^\/cases$/,
    (_m, q) => {
      girisGerekli();
      const rid = q.get("requirement_id");
      return veri.caseler.filter((c) => !rid || c.requirement_id === rid).sort((a, b) => a.sira_no - b.sira_no);
    },
  ],
  ["POST", /^\/cases\/([^/]+)\/decision$/, (m, _q, g) => caseKarari(decodeURIComponent(m[1]), g)],
  ["GET", /^\/publish\/preview$/, (_m, q) => yayinOnizleme(q)],
  ["POST", /^\/publish$/, (_m, _q, g) => yayinla(g)],
  ["POST", /^\/code\/generate$/, (_m, _q, g) => kodUret(g)],
  [
    "GET",
    /^\/scripts$/,
    () => {
      girisGerekli();
      return veri.scriptler.map((s) => {
        const { kod: _k, adimlar: _a, yerel_kontrol: _y, ...ozet } = s;
        return ozet;
      });
    },
  ],
  [
    "GET",
    /^\/scripts\/([^/]+)$/,
    (m) => {
      girisGerekli();
      return bul(veri.scriptler, decodeURIComponent(m[1]), "Script");
    },
  ],
  ["POST", /^\/scripts\/([^/]+)\/break-verify$/, (m) => kirarakDogrula(decodeURIComponent(m[1]))],
  ["POST", /^\/prs\/(\d+)\/merge$/, (m, _q, g) => prBirlestir(Number(m[1]), g)],
  ["POST", /^\/ci\/trigger$/, (_m, _q, g) => ciTetikle(g)],
  [
    "GET",
    /^\/runs$/,
    () => {
      girisGerekli();
      return veri.kosular.map(ozetKosu);
    },
  ],
  [
    "GET",
    /^\/runs\/([^/]+)$/,
    (m) => {
      girisGerekli();
      return bul(veri.kosular, decodeURIComponent(m[1]), "Koşu");
    },
  ],
  [
    "GET",
    /^\/failures\/([^/]+)$/,
    (m) => {
      girisGerekli();
      return bul(veri.hatalar, decodeURIComponent(m[1]), "Hata analizi");
    },
  ],
  ["POST", /^\/failures\/([^/]+)\/fix$/, (m) => onarimPr(decodeURIComponent(m[1]))],
  [
    "GET",
    /^\/bug-drafts$/,
    () => {
      girisGerekli();
      return veri.bugTaslaklari;
    },
  ],
  [
    "GET",
    /^\/bug-drafts\/([^/]+)$/,
    (m) => {
      girisGerekli();
      return bul(veri.bugTaslaklari, decodeURIComponent(m[1]), "Bug taslağı");
    },
  ],
  ["POST", /^\/bug-drafts\/([^/]+)\/decision$/, (m, _q, g) => bugKarari(decodeURIComponent(m[1]), g)],
  ["GET", /^\/control-tower$/, () => kontrolKulesi()],
  ["GET", /^\/audit$/, (_m, q) => denetim(q)],
  ["POST", /^\/tokens$/, (_m, _q, g) => tokenOlustur(g)],
  [
    "POST",
    /^\/demo\/break-locator$/,
    () => {
      rolGerekli("presenter");
      denetimEkle("demo.break_locator", "demo-app-web", "add-to-cart → cart-add");
      kaydet();
      return is("done", "Locator kırıldı: add-to-cart → cart-add (örnek veri).");
    },
  ],
  [
    "POST",
    /^\/demo\/reset$/,
    () => {
      const k = rolGerekli("presenter");
      veri = ilkVeri();
      mockOturumuAyarla(k);
      kaydet();
      return is("done", "Demo verisi sıfırlandı.");
    },
  ],
];

export async function mockIstek(method: string, path: string, query: URLSearchParams, body: unknown): Promise<unknown> {
  if (GECIKME_MS) await bekle(GECIKME_MS);
  // Arka plan işleri içeriği değiştirmiş olabilir: her istek güncel içerik hash'iyle başlar.
  hashleriTazele(veri);
  for (const [m, re, fn] of ROTALAR) {
    if (m !== method) continue;
    const eslesme = path.match(re);
    if (eslesme) {
      const yanit = fn(eslesme, query, body);
      hashleriTazele(veri); // uç içeriği değiştirdiyse yanıttaki hash güncel olsun
      return kopya(yanit ?? null);
    }
  }
  throw new ApiError(404, `Uç bulunamadı: ${method} ${path}`);
}
