// Mock arka uç: §5 uçlarının süreç içi uygulaması. Durum makinesi kuralları ve rol kontrolleri
// gerçek API'yi taklit eder (insan kapıları atlanamaz), böylece ekranlar arka uç olmadan
// demo edilebilir ve ekran testine girebilir. Tüm üretilen çıktılar mode alanıyla işaretlidir.
import { ApiError, mockOturumu, mockOturumuAyarla } from "../http";
import type {
  AjanAdimi,
  Bulgu,
  BulguKararGirdisi,
  BugKararGirdisi,
  BugTaslagi,
  CaseKararGirdisi,
  CaseMetrikleri,
  CiktiModu,
  DenetimOlayi,
  DenetimYaniti,
  GereksinimDetay,
  IsYaniti,
  KontrolKulesi,
  Kosu,
  KosuDetay,
  Kullanici,
  ManuelBaz,
  PullRequest,
  McpToken,
  McpTokenKaydi,
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
import { caseHazirlik, eskiIcerik, tutarlilikSorunlari } from "../../lib/caseV3";
import { CASE_HAZIRLIK } from "../../lib/etiketler";
import { birlesikOzet, caseKapsamOzeti, caseV3Alanlari } from "./caseV3";
import { kanonikJson, sha256Hex } from "../../lib/sha256";
import {
  bulguCiktisi,
  caseSayilari,
  goldenBulgular,
  goldenCaseKaydi,
  goldenCaseler,
  goldenUretimOzeti,
  turGoldenAdi,
  goldenInceleme,
  goldenKoku,
  goldenSorular,
  hashleriTazele,
  icerikHash,
  ilkVeri,
  KAMPANYA_KOD,
  kampanyaAdimlari,
  KAMPANYA_TEST_KODU,
  C2_KAYNAK_METINLERI,
  eslemeler,
  MIN_SIPARIS_KAYNAK,
  MIN_SIPARIS_TEST_KODU,
  MIN_SIPARIS_VERI,
  minSiparisAdimlari,
  SINIR_TEST_KODU,
  sinirAdimlari,
  TEST_C1,
  yerelGecti,
  type MockVeri,
} from "./fixtures";
import { mockOlayYayinla } from "./olaylar";
import { denetimBaslat, denetimGorunumu, denetimTamamla, gonderEngeli, reviewCalistir, reviewGorunumu, setImzasi, yayinEngeli } from "./kalite";
import { javaDosyaYolu, javaTestKodu, uygulamayaCevir } from "./platformlar";
import { PLATFORMLAR, platformUyarla, type Platform } from "../../lib/platform";
import { asistanMockSifirla, asistanRotalari } from "./asistan";
import { modelUretimiBaslat, onayliModel, tasarimModeliRotalari, type ModelBaglami } from "./tasarimModeli";
import { derinlestirmeRotalari, PLATFORM_REPLAY_MISS, platformGoldenAdi, platformGoldeni, uretimGovdesiniDogrula } from "./derinlestirme";
import { oneriKuleOlcumu, oneriMockSifirla, oneriRotalari } from "./oneri";
import type { AsistanliKule } from "../../components/asistan/OnerilerOlcumKarti";
import { kirmaTaslagiMi } from "../../lib/yolHaritasi";
import { BAZ_NOT_EN_AZ, BAZ_NOT_EN_COK, BAZ_UST_SINIR_S, kazancOzeti } from "../uyumFaz5";

// core `auth/display.py` + `seed.GORUNEN_ADLAR` demo varsayılanlarıyla aynı (yalnızca gösterim).
const KISILER: Record<string, string> = {
  analist: "Cengizhan Gunaydin · Analist",
  muhendis: "Gokhan Sipahi · Mühendis",
  sunucu: "Sunucu",
  po: "Cengizhan Gunaydin · PO",
  testci: "Fatih Arslan · Testçi",
};

function mockKullanici(kullanici_adi: string, rol: Kullanici["rol"], ad_soyad: string | null): Kullanici {
  return { id: `u-${kullanici_adi}`, kullanici_adi, rol, gorunen_ad: KISILER[kullanici_adi], ad_soyad, kisiler: KISILER };
}

const KULLANICILAR: Record<string, Kullanici> = {
  analist: mockKullanici("analist", "analyst", "Cengizhan Gunaydin"),
  muhendis: mockKullanici("muhendis", "engineer", "Gokhan Sipahi"),
  sunucu: mockKullanici("sunucu", "presenter", null),
  po: mockKullanici("po", "po", "Cengizhan Gunaydin"),
  testci: mockKullanici("testci", "tester", "Fatih Arslan"),
};

const OTURUM_ANAHTARI = "tp-mock-oturum";
// v3: örnek veri simülatör seed'i ve golden çıktılarla hizalandı (eski oturum verisi okunmaz).
const VERI_ANAHTARI = "tp-mock-veri-v6";

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
  demoKirik = false;
  asistanMockSifirla();
  oneriMockSifirla();
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
/**
 * core `merge_kabul_gerekceleri` ile aynı metinler: merge'i engellemeyen ama açık insan kabulü
 * (`onay_notu`) isteyen gerekçeler. Yalnızca `pr_open` script'te; durum değişince yeniden hesaplanır.
 */
export function mergeKabulGerekli(s: Pick<ScriptDetay, "durum" | "zayif_test" | "break_verify">): string[] {
  if (s.durum !== "pr_open") return [];
  const bv = s.break_verify.durum;
  if (bv === "weak" || s.zayif_test) return ["Zayıf test: BREAK_CAMPAIGN ile kırılan uygulamada da yeşil kaldı (açık kabul gerekir)."];
  if (bv === "failed") return ["Kırarak doğrulama tamamlanamadı: testin hata yakaladığına dair kanıt yok."];
  if (bv === "not_started") return ["Kırarak doğrulama yapılmadı (yeşil → kırmızı → yeşil kanıtı yok)."];
  return [];
}

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
let suredenIs = 0;
/** Bitmemiş mock arka plan işi sayısı (testler sabit süre yerine bunu bekler). */
export function bekleyenMockIs(): number {
  return suredenIs;
}

function arkaPlan(adimlar: (() => void)[]): void {
  let i = 0;
  suredenIs++;
  const sonraki = () => {
    if (i >= adimlar.length) {
      suredenIs--;
      return;
    }
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
 * Kontrol turunun golden REPLAY bulguları (consistency_check/golden/<kök> ya da 2. ve sonraki
 * turlarda <kök>-r<tur>; kök Jira anahtarı veya serbest metin golden'ı SERBEST). Golden kaydı
 * yoksa null (REPLAY-MISS).
 */
function goldenTurBulgulari(g: GereksinimDetay): Bulgu[] | null {
  // Ana golden'ın girdisi uymazsa girdisi uyan senaryo golden'ı (ör. f2-kod-hatasi/TPD-1-r2).
  const ad = turGoldenAdi(g, g.kontrol_turu);
  if (!ad) return null;
  const kayit = goldenBulgular(ad);
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
    // Golden kayıt yok: kural tabanlı yedek çıktı → REPLAY-MISS (canlı model çıktısı değil).
    mode: "replay_miss" as const,
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
  // core flow.start_review kabul kriteri eksik story'yi de kabul eder: ön inceleme eksik AC'leri
  // PO'ya sorar (TPD-2 golden'ı). Yalnızca case üretimi kapalıdır (generate-cases 422).
  if (!["new", "findings_open", "failed"].includes(g.durum)) {
    throw new ApiError(409, "Bu durumda ön inceleme başlatılamaz.");
  }
  gecir("requirement", g, "in_review");
  g.kontrol_turu = Math.max(1, g.kontrol_turu + (g.kontrol_turu === 0 ? 1 : 0));
  denetimEkle("requirement.review", g.jira_key ?? g.id, "Ön inceleme + tutarlılık denetimi başlatıldı");
  gereksinimOlayi(g);
  arkaPlan([
    () => {
      // Golden kaydı (Jira anahtarı ya da eşleşen serbest metin SERBEST) → REPLAY; yoksa REPLAY-MISS.
      const kok = goldenKoku(g);
      const golden = kok ? goldenInceleme(kok) : undefined;
      g.on_inceleme = {
        verdict: golden?.verdict ?? "needs_po",
        mode: golden ? "replay" : "replay_miss",
        zaman: simdi(),
        jira_comment_id: g.kaynak === "jira" ? yeniId("cmt") : null,
        questions: golden
          ? goldenSorular(kok!)
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
      sonKontrolYaz(g, yeni);
      // core: her bulgu unverified → open geçişinde (kanıt deterministik doğrulandı) olay yayımlar.
      for (const b of yeni) mockOlayYayinla({ type: "finding.verified", id: b.id, data: { requirement_id: g.id } });
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

/** core `requirement_kontrol` kaydı: tamamlanan kontrol koşusunun modu ve sayıları (`son_kontrol`). */
function sonKontrolYaz(g: GereksinimDetay, yeni: Bulgu[], mod?: CiktiModu): void {
  const dogrulanan = yeni.filter((b) => b.kanit_dogrulandi).length;
  g.son_kontrol = {
    mode: mod ?? (yeni.some((b) => b.mode === "replay_miss") || !goldenKoku(g) ? "replay_miss" : "replay"),
    bulgu: yeni.length,
    dogrulanan,
    elenen: yeni.length - dogrulanan,
    zaman: simdi(),
  };
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
      mode: b.mode ?? "replay",
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
      // Yeni tur önceki turun karar verilmemiş bulgularını geçersiz kılar (core: open → stale).
      for (const b of veri.bulgular) {
        if (b.requirement_id === id && b.durum === "open" && b.kontrol_turu < g.kontrol_turu) gecir("consistency_finding", b, "stale");
      }
      // Yeniden kontrol: bu tur için golden kayıt varsa onun bulguları (ör. TPD-1-r2) eklenir.
      const yeniTur = goldenTurBulgulari(g);
      if (yeniTur) veri.bulgular.push(...yeniTur);
      sonKontrolYaz(g, yeniTur ?? [], yeniTur ? "replay" : "replay_miss");
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
  g.po.onaylanan_hash = g.icerik_hash;
  denetimEkle("po.approve", g.id, `PO teyidi (portal) · ${g.icerik_hash}`);
  gereksinimOlayi(g);
  mockOlayYayinla({ type: "po.approved", id: g.id, data: { onaylayan: k.kullanici_adi, kanal: "portal" } });
  return cikti(g);
}

function caseUret(id: string, govde?: unknown): IsYaniti {
  rolGerekli("analyst");
  const g = bul(veri.gereksinimler, id, "Gereksinim");
  // 011 K1: gövdesiz çağrı tek tur (geriye uyum); iki turda model onayından önce model üretilir.
  const kip = (govde as { kip?: unknown } | null | undefined)?.kip === "iki_tur" ? "iki_tur" : "tek_tur";
  // 011 K5: gövdedeki üretim seçenekleri (isteğe bağlı) önce doğrulanır (422); gövdesiz çağrı eski davranış.
  const secenekler = uretimGovdesiniDogrula(govde);
  if (kip === "iki_tur" && g.durum !== "model_ready") {
    // core gibi: seçenekler model aşamasında da saklanır; tur 2 aynı seçenekleri kullanır.
    const sonuc = modelUretimiBaslat(modelBaglami, g);
    if (secenekler) (veri.uretimSecenekleri ??= {})[id] = secenekler;
    return sonuc;
  }
  if (kip === "iki_tur" && !onayliModel(veri, g)) {
    throw new ApiError(409, "Onaylı ve güncel tasarım modeli yok; önce modeli onaylayın ya da yeniden üretin.");
  }
  if (g.po.durum !== "approved") throw new ApiError(409, "PO teyidi olmadan case üretilemez.");
  if (g.ac_missing) throw new ApiError(409, "Kabul kriteri olmayan story case üretimine gönderilmez.");
  // core URETIM_BASLANGIC: düşen case üretimi (failed) yeniden denenebilir; PO güncelliği yukarıda.
  const uretimHatasi = g.durum === "failed" && ["cases.generate", "model.generate"].includes(g.son_hata?.job_tur ?? "");
  if (!["po_approved", "cases_ready", "model_ready"].includes(g.durum) && !uretimHatasi) throw new ApiError(409, "Bu durumda case üretilemez.");
  if (g.po.onaylanan_hash && g.icerik_hash && g.po.onaylanan_hash !== g.icerik_hash) {
    throw new ApiError(409, "İçerik PO onayından sonra değişmiş; yeniden PO teyidi gerekir.");
  }
  // Seçenekler gereksinimde saklanır; sonraki generation-options'ta `secenekler` olarak döner.
  if (secenekler) (veri.uretimSecenekleri ??= {})[id] = secenekler;
  gecir("requirement", g, "generating");
  delete g.son_hata;
  gereksinimOlayi(g);
  const mevcut = veri.caseler.filter((c) => c.requirement_id === id).length;
  // Platform seçildiyse golden `platform-<ekler>/<kök>`; kayıt yoksa core gibi REPLAY-MISS: iş
  // başarısız, gereksinim `failed` (case üretimi yeniden denenebilir), case eklenmez.
  const platformAdi = secenekler ? platformGoldenAdi(g, secenekler.platformlar) : null;
  const platformCaseleri = platformAdi ? platformGoldeni(platformAdi, g) : undefined;
  if (platformAdi && !platformCaseleri) {
    arkaPlan([
      () => {
        gecir("requirement", g, "failed");
        const neden = PLATFORM_REPLAY_MISS(platformAdi);
        g.son_hata = { neden, zaman: simdi(), job_tur: "cases.generate", is_hatasi: neden, oneri: "Aynı girdiyle yeniden denemek sonucu değiştirmez.", yeniden_denemek_ise_yarar: false };
        denetimEkle("ai_call", g.id, `Case üretimi: ${neden}`, "core-worker");
        gereksinimOlayi(g);
      },
    ]);
    return is("started", "Case üretimi başlatıldı.");
  }
  // Golden kaydı güncel AC'lerle birebir eşleşirse onun case'leri (REPLAY); değilse kural tabanlı
  // yedek iskelet (REPLAY-MISS: canlı model çıktısı değil, öyle de gösterilmez).
  const golden = platformCaseleri ?? goldenCaseler(g);
  const mod = golden ? ("replay" as const) : ("replay_miss" as const);
  // Golden v3 ise üretimin üst düzey listeleri (core `case_uretim.ozet`) de saklanır: case-summary bunlardan hesaplanır.
  const goldenAdi = platformCaseleri ? platformAdi! : golden ? goldenCaseKaydi(g) : undefined;
  const uretimNo = (veri.caseUretimleri?.[id]?.length ?? 0) + 1;
  const uretimOzeti = goldenAdi ? goldenUretimOzeti(goldenAdi, uretimNo) : undefined;
  const uretilecek: { ref: string; metin: string; golden?: TestCaseIcerik }[] = golden
    ? golden.map((c) => ({ ref: c.acceptance_criteria_refs[0] ?? "", metin: c.title, golden: c }))
    : g.kabul_kriterleri.slice(0, 4);
  arkaPlan([
    ...uretilecek.map((ac, i) => () => {
      const icerik: TestCaseIcerik = ac.golden ?? {
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
        mode: mod,
      };
      veri.caseler.push(tc);
      mockOlayYayinla({ type: "case.generated", id: tc.id, data: { requirement_id: id, title: icerik.title } });
    }),
    () => {
      if (uretimOzeti) (veri.caseUretimleri ??= {})[id] = [...(veri.caseUretimleri?.[id] ?? []), uretimOzeti];
      gecir("requirement", g, "cases_ready");
      denetimEkle("ai_call", g.id, `Case üretimi: ${uretilecek.length} case (${mod})`, "core-worker");
      // P8 review (011 F2): üretimden sonra otomatik; golden'ı üretim golden'ı adıyla eşlenir.
      (veri.kalite ??= {})[id] = { golden: goldenAdi, uretimImzasi: setImzasi(veri.caseler, id), denetimler: [] };
      gereksinimOlayi(g);
    },
    () => {
      const k = veri.kalite?.[id];
      if (!k) return;
      const r = reviewCalistir(k, veri.caseler, id, simdi());
      denetimEkle(r.durum === "tamamlandi" ? "cases.reviewed" : "cases.review_failed", g.id, r.durum === "tamamlandi" ? `Review ${r.skor}/12` : (r.hata ?? ""), "core-worker");
      mockOlayYayinla({ type: "case.review", id, data: { requirement_id: id, durum: r.durum } });
    },
  ]);
  return {
    ...is("started", kip === "iki_tur" ? "Onaylı tasarım modelinden case üretimi başlatıldı." : "Case üretimi başlatıldı."),
    kip,
    asama: "case",
    uretim_no: (veri.caseUretimleri?.[id]?.length ?? 0) + 1,
  };
}

/** Tasarım modeli mock'u (api/mock/tasarimModeli.ts) için iç yardımcılar. */
const modelBaglami: ModelBaglami = {
  veri: () => veri,
  girisGerekli,
  rolGerekli,
  gecir: (g, ...yol) => gecir("requirement", g, ...yol),
  arkaPlan,
  yeniId,
  simdi,
  denetimEkle,
  gereksinimOlayi,
  is,
};

function caseKarari(id: string, govde: unknown): TestCase {
  const k = rolGerekli("analyst");
  const c = bul(veri.caseler, id, "Case");
  // core: "Taslağa al" aynı karar ucunda `karar: "reopen"` ile verilir.
  if ((govde as { karar?: unknown } | null)?.karar === "reopen") return caseYenidenAc(id, govde);
  const g = (govde ?? {}) as Partial<CaseKararGirdisi>;
  if (!g.karar || !["approve", "edit", "reject"].includes(g.karar)) {
    throw new ApiError(422, "Karar approve, edit, reject veya reopen olmalı.");
  }
  hashGerekli(govde, c.icerik_hash);
  if (c.durum === "published") throw new ApiError(409, "Yayınlanmış case değiştirilemez.");
  if (c.durum === "superseded") throw new ApiError(409, "Bu case'in yerini yenisi aldı; karar verilemez.");
  // core test_case makinesi: kararlar yalnızca draft'tan (draft → approved | rejected).
  const hedef = CASE_KARAR_HEDEFI[g.karar];
  if (!yolGecerli("test_case", c.durum, [hedef])) throw new ApiError(409, GECIS_YOK);
  const uretimler = veri.caseUretimleri?.[c.requirement_id];
  if (g.karar === "approve") {
    // K6 (011 §4.2): hazır olmayan ya da tutarlılık uyarısı olan case onaylanamaz (core 422).
    const v3 = caseV3Alanlari(c, uretimler);
    if (v3.onay_engeli) {
      const ayrinti = v3.readiness !== "ready" ? [`readiness: ${v3.readiness}`] : (v3.uyarilar ?? []);
      throw new ApiError(422, `${v3.onay_engeli} — ${JSON.stringify(ayrinti)}`);
    }
  }
  if (g.karar === "reject") {
    if (!g.ret_nedeni) throw new ApiError(422, "Ret için neden seçilmelidir.");
    gecir("test_case", c, "rejected");
    c.ret_nedeni = g.ret_nedeni;
    c.onaylanan_hash = null;
  } else if (g.karar === "edit") {
    if (!g.icerik) throw new ApiError(422, "Düzeltme için içerik zorunludur.");
    if (!g.icerik.title.trim() || g.icerik.steps.length === 0) throw new ApiError(422, "Başlık ve en az bir adım zorunlu.");
    // K9: eski case eski alan kümesiyle kalır; v3 case'in düzeltmesi tutarlılık kurallarından geçer (422).
    if (eskiIcerik(c.icerik) !== eskiIcerik(g.icerik)) {
      throw new ApiError(422, eskiIcerik(c.icerik) ? "Eski şemalı case'e v3 alanı eklenemez." : "v3 case'in düzeltmesi v3 alanlarını (readiness …) taşımalı.");
    }
    const sorunlar = tutarlilikSorunlari(g.icerik, birlesikOzet(uretimler));
    if (sorunlar.length) {
      throw new ApiError(422, `Düzenlenen case şemaya uymuyor ya da üretim özetiyle tutarsız — ${JSON.stringify(sorunlar)}`);
    }
    // core: düzeltme case'i onaylar (draft → approved); hazır olmayan içerik onaylanamaz (K6).
    const hazirlik = g.icerik.readiness ?? "ready";
    if (hazirlik !== "ready") {
      throw new ApiError(
        422,
        `Düzeltme case'i onaylar; içerik hazır değil (${CASE_HAZIRLIK[hazirlik].etiket}). Varsayımı / açık soruyu çözüp beklenen sonucu yazın ve hazır olma durumunu "Hazır" yapın ya da case'i reddedin — ${JSON.stringify([`readiness: ${hazirlik}`])}`,
      );
    }
    const once = kanonikJson(c.icerik);
    // core metrics.edit_metrics: insan beyanı varsa o; yoksa beklenen sonuç metni karşılaştırılır.
    const beklenenDegisti =
      typeof g.beklenen_anlam_degisti === "boolean" ? g.beklenen_anlam_degisti : c.icerik.expected_result !== g.icerik.expected_result;
    const kaynakInsan = typeof g.beklenen_anlam_degisti === "boolean";
    c.icerik = g.icerik;
    c.surum += 1;
    c.icerik_hash = icerikHash(g.icerik);
    c.onaylanan_hash = c.icerik_hash;
    c.duzeltme_olcusu = Math.round(duzeltmeOlcusu(once, kanonikJson(g.icerik)) * 100) / 100;
    c.kucuk_duzeltme = c.duzeltme_olcusu <= 0.15 && !beklenenDegisti;
    const olcuMetni = (x: number) => x.toFixed(3).replace(".", ",");
    c.duzeltme_nedeni = c.kucuk_duzeltme
      ? `Küçük düzeltme sayıldı: düzeltme ölçüsü ${olcuMetni(c.duzeltme_olcusu)} ≤ 0,150 ve beklenen sonuç değişmedi (ilk karar kabul sayılır).`
      : `Küçük düzeltme sayılmadı: ${[
          beklenenDegisti ? `beklenen sonuç anlamca değişti (${kaynakInsan ? "analistin beyanı" : "beklenen sonuç metni değişti"})` : null,
          c.duzeltme_olcusu > 0.15 ? `düzeltme ölçüsü ${olcuMetni(c.duzeltme_olcusu)} > eşik 0,150` : null,
        ]
          .filter(Boolean)
          .join(" ve ")} (ilk karar kabul oranına girmez).`;
    gecir("test_case", c, "approved");
    c.ret_nedeni = null;
  } else {
    gecir("test_case", c, "approved");
    c.onaylanan_hash = c.icerik_hash;
    c.duzeltme_olcusu = 0;
    c.ret_nedeni = null;
  }
  if (g.karar !== "edit") {
    c.kucuk_duzeltme = null;
    c.duzeltme_nedeni = null;
  }
  c.karar = g.karar;
  c.karar_veren = k.kullanici_adi;
  c.karar_zamani = simdi();
  // core gibi: review süresi ilk görüntülemeden (POST /cases/{id}/view) karara kadar ölçülür.
  c.review_sure_ms = c.goruntulenme ? Math.max(0, Date.parse(c.karar_zamani) - Date.parse(c.goruntulenme)) : null;
  denetimEkle("case.decision", c.id, g.karar === "reject" ? `reject: ${g.ret_nedeni}` : g.karar);
  const req = veri.gereksinimler.find((r) => r.id === c.requirement_id);
  if (req) gereksinimOlayi(req);
  else kaydet();
  return caseCikti(c);
}

/**
 * core `POST /cases/{id}/viewed`: kullanıcının son karardan sonraki ilk görüntülemesi (idempotent).
 * Review süresi bu andan karara kadar ölçülür.
 */
function caseGoruntulendi(id: string): { case_id: string; ilk_goruntuleme: string; yeni: boolean } {
  girisGerekli();
  const c = bul(veri.caseler, id, "Case");
  const yeni = !c.goruntulenme;
  if (yeni) {
    c.goruntulenme = simdi();
    kaydet();
  }
  return { case_id: c.id, ilk_goruntuleme: c.goruntulenme!, yeni };
}

/**
 * core "Taslağa al" (`karar: "reopen"`): approved | rejected → draft. İçerik değişmez, yeni karar
 * gerekir. core karar kaydı yazmaz: son karar (`karar`) önceki karar olarak kalır; ekran durumdan
 * (`draft`) karar beklediğini anlar.
 */
function caseYenidenAc(id: string, govde: unknown): TestCase {
  rolGerekli("analyst");
  const c = bul(veri.caseler, id, "Case");
  if (c.durum !== "approved" && c.durum !== "rejected") {
    throw new ApiError(409, `Yalnızca onaylı veya reddedilmiş case taslağa alınabilir (durum: ${c.durum})`);
  }
  hashGerekli(govde, c.icerik_hash);
  gecir("test_case", c, "draft");
  const onceki = c.karar;
  c.onaylanan_hash = null;
  c.goruntulenme = null;
  denetimEkle("case.reopen", c.id, `Taslağa alındı (önceki karar: ${onceki ?? "—"})`);
  const req = veri.gereksinimler.find((r) => r.id === c.requirement_id);
  if (req) gereksinimOlayi(req);
  else kaydet();
  return caseCikti(c);
}

/** core `serialize_cases`: case + readiness, legacy, çözülmüş açık soru/varsayım atıfları, tutarlılık uyarıları. */
function caseCikti(c: TestCase): TestCase {
  return cikti({ ...c, ...caseV3Alanlari(c, veri.caseUretimleri?.[c.requirement_id]) });
}

// ------------------------------------------------- 011 D: review (P8) ve denetim (P9)

function caseReviewGor(rid: string) {
  girisGerekli();
  const g = bul(veri.gereksinimler, rid, "Gereksinim");
  return cikti(reviewGorunumu(veri.kalite?.[rid], veri.caseler, rid, g.durum));
}

function caseReviewCalistir(rid: string) {
  const k = rolGerekli("analyst");
  const g = bul(veri.gereksinimler, rid, "Gereksinim");
  if (!["cases_ready", "done"].includes(g.durum)) throw new ApiError(409, `Review yalnızca case'leri hazır gereksinimde çalıştırılır (durum: ${g.durum})`);
  if (!setImzasi(veri.caseler, rid)) throw new ApiError(409, "Gereksinimin güncel v3 case'i yok; review edilecek set boş");
  const kayit = ((veri.kalite ??= {})[rid] ??= { denetimler: [] });
  kayit.review = { ...(kayit.review ?? reviewCalistir(kayit, veri.caseler, rid, simdi())), durum: "bekliyor", hata: null };
  denetimEkle("cases.review_requested", rid, "Review yeniden istendi", k.kullanici_adi);
  arkaPlan([
    () => {
      reviewCalistir(kayit, veri.caseler, rid, simdi(), k.kullanici_adi);
      mockOlayYayinla({ type: "case.review", id: rid, data: { requirement_id: rid, durum: kayit.review?.durum } });
    },
  ]);
  kaydet();
  return cikti(reviewGorunumu(kayit, veri.caseler, rid, g.durum));
}

function caseDenetimGor(rid: string) {
  girisGerekli();
  const g = bul(veri.gereksinimler, rid, "Gereksinim");
  return cikti(denetimGorunumu(veri.kalite?.[rid], veri.caseler, rid, g.durum));
}

function caseDenetimGonder(rid: string) {
  const k = rolGerekli("analyst");
  const g = bul(veri.gereksinimler, rid, "Gereksinim");
  const kayit = ((veri.kalite ??= {})[rid] ??= { denetimler: [] });
  const gor = denetimGorunumu(kayit, veri.caseler, rid, g.durum);
  if (gor.calisiyor) return cikti(gor);
  const engel = gonderEngeli(kayit, veri.caseler, rid, g.durum);
  if (engel) throw new ApiError(409, engel);
  const d = denetimBaslat(kayit, veri.caseler, rid, simdi(), k.kullanici_adi);
  denetimEkle("cases.audit_requested", rid, `Denetime gönderildi · ${d.set_hash}`, k.kullanici_adi);
  arkaPlan([
    () => {
      denetimTamamla(kayit, d, veri.caseler, rid, simdi());
      denetimEkle(d.durum === "tamamlandi" ? "cases.audited" : "cases.audit_failed", rid, d.karar ?? d.hata ?? "", "core-worker");
      mockOlayYayinla({ type: "case.audit", id: rid, data: { requirement_id: rid, durum: d.durum, karar: d.karar } });
    },
  ]);
  kaydet();
  return cikti(denetimGorunumu(kayit, veri.caseler, rid, g.durum));
}

/**
 * v3 hazır onaylı case için denetim kapısı (core `gate_check`; eski case'e uygulanmaz). Örnek
 * verinin önceden hazırlanmış gereksinimleri (kalite kaydı yok: D şeridinden önceki durumun
 * anlık görüntüsü, core'da `TP_DENETIM_KAPISI=off` ile hazırlanmış sayılır) kapıya girmez; kapı
 * bu oturumda üretilen setlerde uygulanır.
 */
function denetimKapisi(c: TestCase): string | null {
  if (eskiIcerik(c.icerik) || !veri.kalite?.[c.requirement_id]) return null;
  return yayinEngeli(veri.kalite?.[c.requirement_id], veri.caseler, c.requirement_id);
}

/** core `GET /requirements/{id}/case-summary` (011 §4.4). */
function caseSummary(rid: string) {
  girisGerekli();
  const g = bul(veri.gereksinimler, rid, "Gereksinim");
  const o = caseKapsamOzeti(g, veri.caseler, veri.caseUretimleri?.[rid]);
  // Yanıt core biçiminde: kapsayan case'ler `covered_by_cases` adıyla (portal `kapsayanlar`a uyarlar).
  return cikti({
    ...o,
    kapsam_matrisi: o.kapsam_matrisi.map(({ kapsayanlar, ...satir }) => ({ ...satir, covered_by_cases: kapsayanlar ?? [] })),
  });
}

/**
 * core `GET /requirements/{id}/cases.feature` (011 F8). Dönüşüm yalnız çekirdektedir; örnek veri
 * katmanı uygun case sayısını denetler ve SABİT küçük bir örnek döner (case içeriğinden üretmez).
 */
function gherkinOrnegi(rid: string, q: URLSearchParams): string {
  girisGerekli();
  const g = bul(veri.gereksinimler, rid, "Gereksinim");
  const yalnizYayinlanan = q.get("yalniz_yayinlanan") === "1";
  const uygun = veri.caseler.filter(
    (c) =>
      c.requirement_id === rid &&
      (yalnizYayinlanan ? c.durum === "published" : c.durum === "approved" || c.durum === "published") &&
      (c.readiness ?? c.icerik.readiness ?? "ready") === "ready",
  );
  if (!uygun.length) {
    throw new ApiError(404, "Gherkin'e aktarılacak case yok: yalnız onaylı (ya da yayınlanmış) ve hazır olan güncel case'ler dahil edilir.");
  }
  return GHERKIN_ORNEGI(g.jira_key ?? g.id, g.baslik, uygun.length);
}

const GHERKIN_ORNEGI = (anahtar: string, baslik: string, n: number) =>
  [
    "# language: tr",
    "# Örnek veri: dönüşüm çekirdekte yapılır; bu sabit bir örnektir.",
    `# ${n} case`,
    `Özellik: ${anahtar} — ${baslik}`,
    "",
    "  @AC1 @EP @P1 @pozitif @tp-ornek",
    "  Senaryo: Geçerli bilgilerle giriş",
    "    Diyelim ki bayi1 kullanıcısı tanımlı",
    "    Eğer ki Giriş sayfasını aç",
    "    O zaman Giriş formu görüntülenir",
    "",
  ].join("\n");

const acAnahtari = (r: string) => r.replace(/\s/g, "").toUpperCase();

/** core `GET /requirements/{id}/case-metrics` ile aynı alanlar (mock son karara göre sayar). */
function caseMetrikleri(rid: string): CaseMetrikleri {
  girisGerekli();
  const g = bul(veri.gereksinimler, rid, "Gereksinim");
  // core coverage_gaps: güncel (superseded/ret olmayan) case'lerin hiçbirinin atıf yapmadığı AC'ler.
  const atiflar = new Set(
    veri.caseler
      .filter((c) => c.requirement_id === rid && c.durum !== "superseded" && c.durum !== "rejected")
      .flatMap((c) => c.icerik.acceptance_criteria_refs.map(acAnahtari)),
  );
  const kapsanmayan = g.kabul_kriterleri.map((a) => a.ref).filter((r) => !atiflar.has(acAnahtari(r)));
  const cs = veri.caseler.filter((c) => c.requirement_id === rid && c.ai_generated && c.durum !== "superseded");
  const kararli = cs.filter((c) => c.karar !== null);
  const kabul = kararli.filter((c) => c.karar === "approve" || (c.karar === "edit" && (c.kucuk_duzeltme ?? (c.duzeltme_olcusu ?? 1) <= 0.15))).length;
  const sureler = cs.map((c) => c.review_sure_ms).filter((x): x is number => x !== null);
  const say = (anahtar: (c: TestCase) => string | null) =>
    kararli.reduce<Record<string, number>>((a, c) => {
      const k = anahtar(c);
      if (k) a[k] = (a[k] ?? 0) + 1;
      return a;
    }, {});
  return {
    requirement_id: rid,
    uretilen: cs.length,
    karar_verilen: kararli.length,
    bekleyen: cs.length - kararli.length,
    kabul,
    kabul_orani: cs.length ? kabul / cs.length : null,
    kabul_hedefi: 0.7,
    ilk_kararlar: say((c) => c.karar),
    ret_nedenleri: say((c) => c.ret_nedeni),
    ai_sure_ms: cs.reduce((a, c) => a + c.ai_sure_ms, 0),
    review_sure_ms: sureler.reduce((a, x) => a + x, 0),
    ort_review_sure_ms: sureler.length ? Math.round(sureler.reduce((a, x) => a + x, 0) / sureler.length) : null,
    maliyet_usd: cs.reduce((a, c) => a + c.maliyet_usd, 0),
    // Örnek veride her case üretimi golden kayıttan: yalnızca replay/replay_miss (asla live).
    ai_cagri_modlari: cs.reduce<Record<string, number>>((a, c) => {
      if (c.mode) a[c.mode] = (a[c.mode] ?? 0) + 1;
      return a;
    }, {}),
    kapsanmayan_ac: kapsanmayan,
    // v3 (011 §4.9): case-summary ile aynı hesap.
    ...(() => {
      const o = caseKapsamOzeti(g, veri.caseler, veri.caseUretimleri?.[rid]);
      return { teknik_dagilimi: o.teknik_dagilimi, readiness_dagilimi: o.readiness_dagilimi, kapsam_oranlari: o.oranlar };
    })(),
    // core ile aynı: story ölçümü → (mock'ta varsayılan yok) → ölçülmedi; kaynak her zaman bildirilir.
    ...(() => {
      const b = manuelBaz(rid);
      return {
        manuel_baz_ms: b.deger_s === null ? null : b.deger_s * 1000,
        manuel_baz_kaynagi: b.kaynak === "olculmedi" ? null : b.kaynak,
        manuel_baz: b,
      };
    })(),
  };
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
    jira_browse_url: "http://127.0.0.1:8090",
    // core ile aynı: story'siz (serbest metin) gereksinimin Test issue'ı bağlanamaz; yayın engellenir.
    uyarilar: g.jira_key ? [] : ["Serbest metin gereksinimin Jira story'si yok; Test issue story'ye bağlanamaz; yayın engellenir."],
    kalemler: caseler.map((c) => ({
      case_id: c.id,
      title: c.icerik.title,
      issue_type: "Test",
      summary: `[${g.jira_key ?? "FT"}] ${c.icerik.title}`,
      labels: ["AI-generated", `tp-${c.id}`],
      link: { type: "is tested by", story_key: g.jira_key },
      adim_sayisi: c.icerik.steps.length,
      // core engel sırası (011 §4.7): onaylı → hash → hazır olma → story bağı.
      islem:
        c.durum === "published"
          ? "skip_existing"
          : c.durum !== "approved"
            ? "blocked_not_approved"
            : c.onaylanan_hash !== c.icerik_hash
              ? "blocked_hash_mismatch"
              : caseHazirlik(c) !== "ready"
                ? "blocked_not_ready"
                : denetimKapisi(c)
                  ? "blocked_gate"
                  : !g.jira_key
                    ? "blocked_no_story"
                    : "create",
      external_key: c.jira_test_key,
      neden:
        c.durum === "approved" && c.onaylanan_hash === c.icerik_hash && caseHazirlik(c) !== "ready"
          ? `Case hazır değil (${CASE_HAZIRLIK[caseHazirlik(c)].etiket.toLocaleLowerCase("tr-TR")}); yalnız hazır case yayınlanır.`
          : c.durum === "approved" && c.onaylanan_hash === c.icerik_hash
            ? denetimKapisi(c)
            : null,
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
    if (caseHazirlik(c) !== "ready") return { case_id: id, durum: "failed" as const, external_key: null, hata: "Case hazır değil" };
    const kapi = denetimKapisi(c);
    if (kapi) return { case_id: id, durum: "failed" as const, external_key: null, hata: kapi };
    if (!veri.gereksinimler.find((r) => r.id === c.requirement_id)?.jira_key) {
      return { case_id: id, durum: "failed" as const, external_key: null, hata: "Serbest metin gereksinimin Jira story'si yok; Test issue story'ye bağlanamaz" };
    }
    gecir("test_case", c, "published");
    c.jira_test_key = yeniJiraAnahtari();
    mockOlayYayinla({ type: "publish.progress", id: c.id, data: { case_id: c.id, external_key: c.jira_test_key } });
    return { case_id: id, durum: "created" as const, external_key: c.jira_test_key, url: `http://127.0.0.1:8090/browse/${c.jira_test_key}`, hata: null };
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
  mockOlayYayinla({
    type: "publish.completed",
    data: { olusan: olusan.length, basarisiz: sonuclar.filter((s) => s.durum === "failed").length },
  });
  return { hedef: "jira", sonuclar };
}

/**
 * Örnek veride golden'ı olan case'ler (TPD-1): ajan adımları, eşleme kaynağı, şablon çıktısı ve
 * yerel kontrolün sonucu. C3 (6 adet sınır) bugünkü koda karşı assertion'da kırmızıdır → defect adayı.
 */
const KOD_GOLDEN: Record<string, { adimlar: () => AjanAdimi[]; kaynak: Record<string, string>; kod: string; defect: boolean }> = {
  "case-1-2": { adimlar: kampanyaAdimlari, kaynak: C2_KAYNAK_METINLERI, kod: KAMPANYA_TEST_KODU, defect: false },
  "case-1-3": {
    adimlar: sinirAdimlari,
    kaynak: { "6": "Sepet sayacı 6 olur", "0,00 TL": "indirim 0,00 TL", "150,00 TL": "toplam 150,00 TL" },
    kod: SINIR_TEST_KODU,
    defect: true,
  },
  "case-1-4": { adimlar: minSiparisAdimlari, kaynak: MIN_SIPARIS_KAYNAK, kod: MIN_SIPARIS_TEST_KODU, defect: false },
};

function kodUret(govde: unknown): IsYaniti {
  rolGerekli("engineer");
  const g = (govde ?? {}) as { case_ids?: string[]; platform?: unknown };
  const ids = g.case_ids ?? [];
  if (!Array.isArray(ids) || ids.length === 0) throw new ApiError(422, "En az bir case seçilmeli.");
  // 009 §2.9: platform yoksa web; bilinmeyen değer 422 (core ile aynı).
  const platform: Platform | null = g.platform === undefined || g.platform === null ? "web" : platformUyarla(g.platform);
  if (!platform) throw new ApiError(422, `platform yalnızca ${PLATFORMLAR.join(", ")} olabilir.`);
  const app = platform !== "web";
  const caseler = ids.map((id) => bul(veri.caseler, id, "Case"));
  const onaysiz = caseler.filter((c) => c.durum !== "approved" && c.durum !== "published");
  if (onaysiz.length) throw new ApiError(409, "Yalnızca onaylı case'ler için kod üretilebilir.");
  for (const c of caseler) {
    const id = yeniId("scr");
    const kisa = sha256Hex(c.id).slice(0, 8);
    // Uygulama dalı web dalıyla önek çakışmaz: tp/case-<platform>-<uuid> (aynı case'in platformları ayrı PR).
    const branch = app ? `tp/case-${platform}-${kisa}` : `tp/case-${kisa}`;
    const golden = KOD_GOLDEN[c.id];
    const java = app ? javaDosyaYolu(platform, c.jira_key ?? "SERBEST", c.sira_no, kisa) : null;
    const s: ScriptDetay = {
      id,
      case_ids: [c.id],
      requirement_key: c.jira_key,
      baslik: c.icerik.title,
      dosya_yolu: java ? java.yol : `demo-app/e2e/tests/${(c.jira_key ?? "ft").toLowerCase()}/c${c.sira_no}.spec.ts`,
      branch,
      platform,
      durum: "pending",
      pr: null,
      pass_at_1: null,
      zayif_test: false,
      break_verify: {
        durum: "not_started",
        asamalar: (["baseline", "broken", "restored"] as const).map((ad) => ({ ad, sonuc: "pending", run_id: null, zaman: null })),
      },
      yerel_sinif: null,
      // Golden kaydı olmayan case'te replay ıskalar: sessiz geçmez, REPLAY-MISS olarak işaretlenir (§8.8).
      mode: golden ? "replay" : "replay_miss",
      olusturma: simdi(),
      hata: null,
      kod: null,
      adimlar: [],
      eslemeler: [],
      yerel_kontrol: null,
      merge_engelleri: null,
      uyarilar: [],
      engel: null,
    };
    veri.scriptler.unshift(s);
    if (!golden) {
      arkaPlan([
        () => {
          gecir("script", s, "failed");
          s.hata =
            "REPLAY-MISS: bu case için kayıtlı doğrulama/eşleme çıktısı yok; kod üretilmedi, PR açılmadı. Canlı model (ANTHROPIC_API_KEY) gerekir.";
          denetimEkle("code.generate", s.id, "REPLAY-MISS: kod üretilmedi", "core-worker");
          mockOlayYayinla({ type: "ci.status", id: s.id, data: { durum: "failed" } });
        },
      ]);
      continue;
    }
    const adimlar = platform === "web" ? golden.adimlar() : uygulamayaCevir(golden.adimlar(), platform);
    let kontrolKosusu: KosuDetay | null = null;
    arkaPlan([
      ...adimlar.map((a) => () => {
        if (s.durum !== "verifying") gecir("script", s, "verifying");
        const yeniAdim = { ...a, zaman: simdi() };
        s.adimlar.push(yeniAdim);
        mockOlayYayinla({ type: "agent.step", id: s.id, data: { ...yeniAdim, platform } });
      }),
      () => {
        // Deterministik kontroller geçti: eşleme kaydı + şablondan kod; yerel kontrol başlar.
        gecir("script", s, "checking");
        s.eslemeler = eslemeler(adimlar, golden.kaynak);
        s.kod = java ? javaTestKodu(platform as Exclude<Platform, "web">, java.sinif, c.icerik.title, adimlar) : golden.kod;
        kontrolKosusu = kosuOlustur("local_check", "local", false, null);
        kontrolKosusu.script_id = s.id;
        kontrolKosusu.platform = platform;
        kontrolKosusu.durum = "running";
        s.yerel_kontrol = { ...yerelGecti(kontrolKosusu.id), sonuc: null, sinif: null };
        mockOlayYayinla({ type: "ci.status", id: s.id, data: { durum: "checking" } });
      },
      () => {
        const k = kontrolKosusu;
        if (k) kosuBitir(k, !golden.defect, `${c.jira_key ?? "FT"} C${c.sira_no} · ${c.icerik.title}`, golden.defect ? "Beklenen: \"0\" · Gerçekleşen: \"1\" (bedava adet)" : undefined);
        if (golden.defect) {
          s.pass_at_1 = false;
          s.yerel_sinif = "defect_adayi";
          s.yerel_kontrol = {
            ...yerelGecti(k?.id ?? ""),
            sonuc: "failed",
            sinif: "defect_adayi",
            gecen: 0,
            aciklama:
              "Assertion hatası: uygulama onaylı case'in beklenen değerini vermiyor (3/3 tekrarda aynı). Otomatik düzeltme yapılmaz; insan incelemesine gider.",
            basarisiz: [
              { test_adi: c.icerik.title, hata_mesaji: "toHaveText(\"0\") · bedava adet", beklenen: "bedava adet 0 · indirim 0,00 TL", gerceklesen: "bedava adet 1 · indirim 25,00 TL", adim: "S4", tekrar: 3 },
            ],
          };
          s.engel = { tur: "defect_candidate", neden: "Yerel kontrolde assertion kırmızı: defect adayı (onarım yok)." };
          gecir("script", s, "blocked");
          denetimEkle("code.local_check", s.id, "Assertion kırmızı: defect adayı, insana düştü (PR açılmadı)", "core-worker");
          mockOlayYayinla({ type: "ci.status", id: s.id, data: { durum: "blocked" } });
          return;
        }
        s.yerel_kontrol = yerelGecti(k?.id ?? "");
        s.yerel_sinif = "gecti";
        const prNo = yeniPrNo();
        gecir("script", s, "pr_open");
        s.pass_at_1 = true;
        s.pr = {
          number: prNo,
          url: null,
          baslik: app
            ? `[${c.jira_key ?? "SERBEST"}-C${c.sira_no} · ${platform}] ${c.icerik.title} [AI-generated]`
            : `test(${c.jira_key ?? "FT"}): ${c.icerik.title} [AI-generated]`,
          branch,
          durum: "open",
          ci: "passed",
          icerik_hash: "", // hashleriTazele: dosya + kod
          head_sha: "",
          // 009 §2.7: uygulama PR'ında platformun zorunlu check'i `local-ci-<platform>`.
          checks: [
            app
              ? { ad: `local-ci-${platform}`, durum: "passed", zorunlu: true, url: null, aciklama: "javac ✓ · AST koruması ✓ · Appium 3/3 (cihazda)" }
              : { ad: "local-ci", durum: "passed", zorunlu: true, url: null, aciklama: "tsc ✓ · eslint ✓ · AST koruması ✓ · Playwright 3/3" },
          ],
          forge: "local",
        };
        denetimEkle("pr.open", `PR #${prNo}`, branch, "core-worker");
        mockOlayYayinla({ type: "pr.opened", id: s.id, data: { number: prNo, platform } });
      },
    ]);
  }
  denetimEkle("code.generate", ids.join(","), app ? `CasesToCode başlatıldı (${platform})` : "CasesToCode başlatıldı");
  kaydet();
  return is("started", `${caseler.length} case için kod üretimi başladı${app ? ` (${platform})` : ""}.`);
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
    rapor_url: null,
    sauce_url: null,
    ci_url: null,
    break_campaign,
    script_id: null,
    saglik_hatasi: null,
    log_url: null,
    hata: null,
    uyarilar: [],
    sonuclar: [],
    // Örnek verideki CI tetikleri web paketini koşar; uygulama kontrol koşusu çağıranda platformu alır.
    platform: "web",
  };
  veri.kosular.unshift(k);
  return k;
}

function kosuBitir(k: KosuDetay, gecti: boolean, testAdi: string, hata?: string): void {
  k.durum = gecti ? "passed" : "failed";
  k.sure_ms = 48000 + Math.round(Math.random() * 20000);
  k.sonuclar = [
    {
      id: `${k.id}-1`,
      test_adi: testAdi,
      durum: gecti ? "passed" : "failed",
      sure_ms: 6000,
      retry: 0,
      hata_mesaji: gecti ? null : (hata ?? "Beklenen: \"25,00 TL\" · Gerçekleşen: \"0,00 TL\" (BREAK_CAMPAIGN=1)"),
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
      const k = kosuOlustur("break_verify", "local", kir, s.pr?.number ?? null);
      k.script_id = s.id;
      k.platform = s.platform ?? "web";
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
    // core request_merge ile aynı kapı: zayıf test / kırma yapılmadı kapı değil (insan kabulüyle
    // merge, not denetime yazılır); yalnızca sürmekte olan kırarak doğrulama ve zorunlu check engeller.
    if (s.break_verify.durum === "running") throw new ApiError(409, "Kırarak doğrulama sürüyor; bitince merge edin");
    if (s.pr.ci !== "passed") throw new ApiError(409, "Zorunlu kontrol 'local-ci' yeşil değil.");
    if (!yolGecerli("script", s.durum, ["merged"])) throw new ApiError(409, GECIS_YOK);
    const not = (govde as { onay_notu?: unknown } | null | undefined)?.onay_notu;
    s.pr.durum = "merged";
    s.pr.merge_sha = `m${s.pr.head_sha.slice(0, 6)}`;
    s.pr.merge_eden = oturum()?.kullanici_adi ?? null;
    s.pr.merge_zamani = simdi();
    gecir("script", s, "merged");
    denetimEkle(
      "pr.merge",
      `PR #${no}`,
      `İnsan onaylı merge (LocalForge) · head ${s.pr.head_sha.slice(0, 7)}${typeof not === "string" && not ? ` · ${not.slice(0, 200)}` : ""}`,
    );
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

const RET_NEDENLERI = new Set(["hallucinated_step", "missing_ac", "wrong_test_data", "out_of_scope", "duplicate", "wrong_element"]);

/** core POST /prs/{n}/review: değişiklik iste / reddet → script kapanır, PR kapatılır. */
function prReview(no: number, govde: unknown) {
  rolGerekli("engineer");
  const s = veri.scriptler.find((x) => x.pr?.number === no);
  if (!s?.pr) throw new ApiError(404, `PR bulunamadı: #${no}`);
  const g = (govde ?? {}) as { karar?: unknown; ret_nedeni?: unknown; not?: unknown };
  if (g.karar !== "degisiklik_iste" && g.karar !== "reddet") throw new ApiError(422, "karar degisiklik_iste veya reddet olmalı.");
  if (typeof g.ret_nedeni !== "string" || !RET_NEDENLERI.has(g.ret_nedeni)) throw new ApiError(422, "ret nedeni sabit taksonomiden olmalı.");
  mergeBagi(govde, s.pr);
  if (s.pr.durum !== "open") throw new ApiError(409, `PR #${no} açık değil.`);
  s.pr.durum = "closed";
  const sonuc = g.karar === "reddet" ? "reddedildi" : "degisiklik_istendi";
  s.engel = { tur: "human_rejected", neden: `İnsan review: ${g.karar} (${g.ret_nedeni})` };
  gecir("script", s, "closed");
  denetimEkle("codegen.review_rejected", `PR #${no}`, `${g.karar} · ${g.ret_nedeni}${typeof g.not === "string" && g.not ? ` · ${g.not.slice(0, 200)}` : ""}`);
  kaydet();
  return { ...cikti(s.pr), insan_review_sonucu: sonuc };
}

/** core POST /prs/{n}/update-branch: geride kalan bot dalını main'e taşır (202). */
function prDaliGuncelle(no: number): IsYaniti {
  rolGerekli("engineer");
  const s = veri.scriptler.find((x) => x.pr?.number === no);
  if (!s?.pr) throw new ApiError(404, `PR bulunamadı: #${no}`);
  if (s.pr.durum !== "open") throw new ApiError(409, `PR #${no} açık değil.`);
  s.pr.dal = { geride: false, guncelleme: null, neden: null };
  kaydet();
  return { job_id: `job-dal-${no}`, durum: "queued", mesaj: "Dal güncellemesi kuyruğa alındı." };
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

/**
 * core POST /demo/break-locator: demo/break-locator dalı demo-admin bypass'ıyla main'e merge edilir
 * (denetim: "demo kırılması"), çalışan demo uygulaması main'den yeniden kurulur, CI koşar → kırmızı →
 * triage test_maintenance/locator. Mock aynı sırayı olaylarla canlandırır.
 */
let demoKirik = false;

function demoKir(): IsYaniti {
  rolGerekli("presenter");
  if (demoKirik) throw new ApiError(409, "Buton kimliği zaten değişti (main'de cart-add); önce demoyu sıfırlayın.");
  demoKirik = true;
  denetimEkle("demo.break_locator", "demo-app-web", "demo kırılması: demo/break-locator merge (demo-admin bypass) · add-to-cart → cart-add");
  const k = kosuOlustur("push", "local", false, null);
  kaydet();
  const ilerleme = (asama: string, mesaj: string) => mockOlayYayinla({ type: "demo.progress", id: "demo", data: { asama, mesaj, run_id: k.id } });
  arkaPlan([
    () => ilerleme("merge", "demo/break-locator main'e merge edildi (demo-admin bypass, denetlendi)."),
    () => ilerleme("deploy", "Demo uygulaması main'den yeniden kuruldu."),
    () => {
      k.durum = "running";
      mockOlayYayinla({ type: "ci.status", id: k.id, data: { durum: "running" } });
      ilerleme("ci", "CI koşusu başladı.");
    },
    () => {
      kosuBitir(k, false, TEST_C1, "locator.click: Timeout 5000ms exceeded.\nwaiting for getByTestId('product-card-P-001').getByTestId('add-to-cart')");
      const h = veri.hatalar.find((x) => x.id === "fail-2");
      if (h?.oneri?.tur === "locator_fix") {
        k.sonuclar[0].failure_id = h.id;
        k.sonuclar[0].triage_sinifi = "test_maintenance";
        k.sonuclar[0].triage_alt_tur = "locator";
      }
      mockOlayYayinla({ type: "failure.classified", id: "fail-2", data: { failure_id: "fail-2", run_id: k.id, sinif: "test_maintenance" } });
      ilerleme("triage", "Triage: test bakımı / locator; onarım önerisi hazır.");
    },
  ]);
  return is("started", `Buton kimliği değiştiriliyor: merge → yeniden kurulum → CI (${k.id}).`);
}

function onarimPr(id: string): IsYaniti {
  rolGerekli("engineer");
  const h = bul(veri.hatalar, id, "Hata analizi");
  if (h.sinif === "environment") throw new ApiError(409, "Ortam hatası için onarım yapılmaz.");
  if (h.oneri?.tur !== "locator_fix") throw new ApiError(409, "Bu hata için locator onarım önerisi yok.");
  const o = h.oneri;
  if (o.durum !== "proposed") throw new ApiError(409, "Onarım PR'ı zaten açılmış.");
  // core FailureToFix: yama → AST koruması (onarım modu) → etkilenen tüm testlerde yerel kontrol → bot PR.
  o.durum = "checking";
  o.yerel_kontrol = { sonuc: "pending", run_id: null, gecen: null, toplam: null };
  denetimEkle("failure.fix", h.id, `Onarım işi başladı (yalnızca ${o.dosya} testId)`);
  kaydet();
  const olay = () => mockOlayYayinla({ type: "failure.updated", id: h.id, data: { failure_id: h.id, durum: o.durum } });
  arkaPlan([
    () => {
      o.degisen_dosyalar = [o.dosya];
      o.yama = `--- a/${o.dosya}\n+++ b/${o.dosya}\n@@\n   ${o.anahtar}: {\n-    testId: '${o.eski_test_id}',\n+    testId: '${o.yeni_test_id}',\n     role: '${o.rol}',\n     name: '${o.ad}',`;
      o.ast_guard = { ok: true, ihlaller: [] };
      olay();
    },
    () => {
      const testler = o.etkilenen_testler ?? [];
      o.etkilenen_testler = testler.map((t) => ({ ...t, durum: "passed" as const }));
      o.yerel_kontrol = { sonuc: "passed", run_id: "run-108", gecen: testler.length, toplam: testler.length };
      olay();
    },
    () => {
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
      denetimEkle("pr.open", `PR #${prNo}`, `tp/repair-${o.anahtar} (tp-repair)`, "core-worker");
      olay();
    },
    () => {
      if (o.pr) o.pr.ci = "passed";
      mockOlayYayinla({ type: "ci.status", id: h.id, data: { failure_id: h.id, pr: o.pr?.number, ci: "passed" } });
    },
  ]);
  return is("started", "Onarım işi başladı: AST koruması ve etkilenen testlerde yerel kontrol sonrası bot PR açılır.");
}

function bugKarari(id: string, govde: unknown): BugTaslagi {
  const k = rolGerekli("tester");
  const b = bul(veri.bugTaslaklari, id, "Bug taslağı");
  const g = (govde ?? {}) as Partial<BugKararGirdisi>;
  if (!["new", "link", "dismiss", "edit", "reopen"].includes(g.karar ?? "")) {
    throw new ApiError(422, "Karar new, link, edit, dismiss veya reopen olmalı.");
  }
  hashGerekli(govde, b.icerik_hash);
  if (g.karar === "reopen") {
    if (b.durum !== "dismissed") throw new ApiError(409, `Yalnızca reddedilmiş taslak taslağa alınır (${b.durum})`);
    gecir("bug_draft", b, "draft");
    b.karar = null;
    b.ret_gerekcesi = null;
    denetimEkle("bug.reopen", b.id, "Taslağa alındı");
    kaydet();
    return cikti(b);
  }
  if (b.durum !== "draft") throw new ApiError(409, "Taslak için karar zaten verilmiş.");
  if (g.karar === "edit") {
    if (!g.icerik || !g.icerik.summary.trim()) throw new ApiError(422, "Düzenleme kararı değişmiş içerik ister");
    b.icerik = g.icerik;
    denetimEkle("bug_draft.edited", b.id, "Taslak düzenlendi (onay değil)");
    kaydet();
    mockOlayYayinla({ type: "bug.draft_edited", id: b.id, data: { bug_draft_id: b.id } });
    return cikti(b);
  }
  if (g.karar === "dismiss" && !(g.gerekce ?? "").trim()) throw new ApiError(422, "Taslağı reddetmek için gerekçe zorunludur");
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
    b.jira_url = b.jira_browse_url ? `${b.jira_browse_url}/${anahtar}` : null;
  } else if (g.karar === "new") {
    if (g.icerik) {
      if (!g.icerik.summary.trim()) throw new ApiError(422, "Özet boş olamaz.");
      b.icerik = g.icerik;
    }
    gecir("bug_draft", b, "approved", "published");
    b.jira_key = yeniJiraAnahtari();
    b.jira_url = b.jira_browse_url ? `${b.jira_browse_url}/${b.jira_key}` : null;
  } else {
    gecir("bug_draft", b, "dismissed");
    b.ret_gerekcesi = (g.gerekce ?? "").trim();
  }
  b.karar = g.karar as "new" | "link" | "dismiss";
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

/** Kontrol Kulesi KPI kaynakları (core'un `kaynaklar` alanıyla aynı biçim). */
const KULE_KAYNAKLARI: KontrolKulesi["kaynaklar"] = {
  gecme_orani: "test_result (JUnit XML) · son 7 gün · kasıtlı kırma (BREAK_CAMPAIGN) koşuları hariç",
  flaky: "test_result: retry ile geçen ya da aynı commit'te sonucu değişen testler",
  karne: "requirement + test_case + script (merge edilmiş) + son koşu sonucu + yayınlanmış bug",
  kabul_orani: "review: ilk karar approve ya da küçük düzeltmeli edit / üretilen case (§12)",
  script_ilk_review: "script: değişiklik istenmeden kabul edilen ve CI'da geçen / üretilen (pass@1 ayrı)",
  hazirlik_suresi: "ai_call.sure_ms (AI) + case_goruntuleme→karar aralıkları (review)",
  manuel_baz: "story başına requirement_baz_deger (giren, zaman, not) → yoksa TP_MANUAL_BASELINE_S 'varsayılan' etiketiyle → ikisi de yoksa ölçülmedi",
  kazanc_orani: "1 − Σ(AI + review süresi) / Σ(manuel baz), yalnızca story'ye özel ölçülmüş baz değerli (kaynak 'olcum'; varsayılan kazanca girmez) story'ler",
  maliyet: "ai_call.maliyet_usd (REPLAY çağrıları 0)",
  a11y: "@axe-core/playwright · WCAG 2.2 AA · demo story sayfaları",
  asistan: "asistan_mesaj (Neden? Sor) + asistan_oneri_geri_bildirim (Faydalı/Gizle/Yaptım) · ai_call assistant* amaçları",
  son_kosular: "run tablosu (yerel test-runner, GitHub Actions, Sauce Labs)",
};

function kontrolKulesi(): KontrolKulesi & AsistanliKule {
  girisGerekli();
  // core gibi: Kontrol Kulesi yalnızca CI koşularını sayar (yerel kontrol ve kırarak doğrula hariç).
  const ciKosulari = veri.kosular.filter((k) => ["pr", "push", "nightly", "deploy", "manual"].includes(k.tetik));
  const sonuclar = ciKosulari.flatMap((k) => k.sonuclar.map((s) => ({ ...s, kosu: k })));
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
  const kabul = karar.filter((c) => c.karar === "approve" || (c.karar === "edit" && (c.kucuk_duzeltme ?? (c.duzeltme_olcusu ?? 1) <= 0.15))).length;
  const reviewlar = karar.filter((c) => c.review_sure_ms !== null);
  const scriptler = veri.scriptler.filter((s) => s.pass_at_1 !== null);
  const flaky = new Map<string, { sayi: number; son: string }>();
  for (const s of sonuclar.filter((x) => x.durum === "flaky")) {
    const e = flaky.get(s.test_adi) ?? { sayi: 0, son: s.kosu.baslangic };
    e.sayi += 1;
    if (s.kosu.baslangic > e.son) e.son = s.kosu.baslangic;
    flaky.set(s.test_adi, e);
  }
  return {
    son_kosular: ciKosulari.slice(0, 6).map(ozetKosu),
    gecme_orani: { oran: sayilan.length ? gecen / sayilan.length : null, toplam: sayilan.length, gecen, donem_gun: 7, son_n: null, birim: "test", test: null },
    // Hedef çizgisi yalnızca core bir hedef bildirirse çizilir (tasarımda geçme oranı hedefi yok).
    gecme_hedefi: null,
    gunluk_gecme: [...gunler.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([tarih, e]) => ({ tarih, oran: e.t ? e.g / e.t : 0, kosu: e.k.size }))
      .slice(-7),
    flaky: [...flaky.entries()].map(([test_adi, e]) => ({ test_adi, neden: "retry" as const, sayi: e.sayi, son_gorulme: e.son })),
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
          otomasyon_kapsami: gc.length ? otomatik / gc.length : null,
          son_sonuc: son ? (son.durum === "failed" ? "failed" : "passed") : "none",
          acik_bug: veri.bugTaslaklari.filter((b) => b.icerik.story_key === g.jira_key && b.durum === "published").length,
          // core: yayınlanmamış (taslak/onaylı), kasıtlı kırma koşusundan gelmeyen taslaklar.
          bug_taslagi: veri.bugTaslaklari.filter(
            (b) =>
              b.icerik.story_key === g.jira_key &&
              (b.durum === "draft" || b.durum === "approved") &&
              !kirmaTaslagiMi(b, veri.hatalar, veri.kosular),
          ).length,
          // core `_acik_defect_adayi`: case'in en son script'i defect adayı (blocked) ise sayılır.
          acik_defect_adayi: gc.filter((c) => {
            const son = veri.scriptler
              .filter((s) => s.case_ids.includes(c.id))
              .sort((a, b) => b.olusturma.localeCompare(a.olusturma))[0];
            return son?.durum === "blocked" && son.engel?.tur === "defect_candidate";
          }).length,
        };
      }),
    ai_katkisi: {
      kabul_orani: caseler.length && karar.length ? kabul / caseler.length : null,
      kabul_hedefi: 0.7,
      script_ilk_review: null,
      script_hedefi: 0.6,
      pass_at_1: scriptler.length ? scriptler.filter((s) => s.pass_at_1).length / scriptler.length : null,
      duzeltme_sonrasi: null,
      // core eşi: REPLAY'de model süresi ölçülmez (0/kayıt süresi ölçüm değil) — yalnız canlı case'lerden; hazirlik
      // satırları (ai_olculmedi) ile aynı kural. Hepsi REPLAY ise null → Kule "Case başına AI + review" ölçülmedi.
      ort_ai_sure_ms: (() => {
        const canli = caseler.filter((c) => c.mode === "live");
        return canli.length ? canli.reduce((a, c) => a + c.ai_sure_ms, 0) / canli.length : null;
      })(),
      ort_review_sure_ms: reviewlar.length ? reviewlar.reduce((a, c) => a + (c.review_sure_ms ?? 0), 0) / reviewlar.length : null,
      // Baz değer F0'da ölçülür; ölçülmemiş baz değer ve ondan türeyen "kazanç" uydurulmaz.
      manuel_baz_ms: null,
      maliyet_usd_toplam: caseler.reduce((a, c) => a + c.maliyet_usd, 0),
      maliyet_usd_bugun: 0,
      gunluk_butce_usd: 30,
      cagri_sayisi: 14 + caseler.length,
      replay_cagri: caseler.filter((c) => c.mode !== "live").length + 14,
    },
    hazirlik: hazirlikSatirlari(),
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
    kaynaklar: KULE_KAYNAKLARI,
    // Asistan dışı AI işleri: AI katkısı kartındaki toplamlarla aynı (core `amac_gruplari.diger`).
    asistan: oneriKuleOlcumu({ cagri: 14 + caseler.length, maliyet_usd: caseler.reduce((a, c) => a + c.maliyet_usd, 0), maliyet_usd_bugun: 0, amaclar: [] }),
    uyarilar: [
      kazancOzeti(hazirlikSatirlari()).hesaplanan
        ? "Kazanç yalnızca story için ölçülmüş baz değerden hesaplanır."
        : "Story için ölçülmüş manuel baz değer yok; hazırlık süresi kazancı hesaplanmaz.",
      "AI süresi REPLAY'de ölçülmez; 'AI + review' süresi yalnız review süresidir.",
    ],
  };
}

// ------------------------------------------------------------------ manuel baz değer (Faz 5)

/** Story'nin baz değeri: yalnızca portaldan girilmiş ölçüm; örnek veride varsayılan (ortam) değer yok. */
function manuelBaz(id: string): ManuelBaz {
  return veri.manuelBazlar?.[id] ?? { deger_s: null, kaynak: "olculmedi", giren: null, zaman: null, not: null };
}

function bazDegerKaydet(id: string, govde: unknown): ManuelBaz {
  const k = rolGerekli("analyst", "po");
  const g = bul(veri.gereksinimler, id, "Gereksinim");
  const b = (govde && typeof govde === "object" ? govde : {}) as Record<string, unknown>;
  const deger = b.deger_s;
  if (typeof deger !== "number" || !Number.isInteger(deger) || deger < 1 || deger > BAZ_UST_SINIR_S) {
    throw new ApiError(422, `Baz değer 1 sn ile ${BAZ_UST_SINIR_S / 3600} saat arasında tam saniye olmalı.`);
  }
  const not = typeof b.not === "string" ? b.not.trim() : "";
  if (not.replace(/\s/g, "").length < BAZ_NOT_EN_AZ || not.length > BAZ_NOT_EN_COK) {
    throw new ApiError(422, `Ölçüm notu ${BAZ_NOT_EN_AZ}–${BAZ_NOT_EN_COK} karakter olmalı (kim, nasıl ölçtü).`);
  }
  const kayit: ManuelBaz = { deger_s: deger, kaynak: "olcum", giren: k.kullanici_adi, zaman: simdi(), not };
  veri.manuelBazlar = { ...(veri.manuelBazlar ?? {}), [g.id]: kayit };
  denetimEkle("requirement.baseline_set", g.jira_key ?? g.id, `Manuel baz değer: ${deger} sn (${not})`);
  kaydet();
  mockOlayYayinla({ type: "requirement.updated", id: g.id, data: { requirement_id: g.id } });
  return kayit;
}

function bazDegerSil(id: string): ManuelBaz {
  rolGerekli("analyst", "po");
  const g = bul(veri.gereksinimler, id, "Gereksinim");
  if (!veri.manuelBazlar?.[g.id]) throw new ApiError(404, "Bu story için girilmiş baz değer yok.");
  const { [g.id]: _silinen, ...kalan } = veri.manuelBazlar;
  veri.manuelBazlar = kalan;
  denetimEkle("requirement.baseline_cleared", g.jira_key ?? g.id, "Manuel baz değer silindi");
  kaydet();
  mockOlayYayinla({ type: "requirement.updated", id: g.id, data: { requirement_id: g.id } });
  return manuelBaz(g.id);
}

/** core `hazirlik` eşi: case üretilmiş her story için AI + review süresi ve baz değer. */
function hazirlikSatirlari(): KontrolKulesi["hazirlik"] {
  return veri.gereksinimler
    .filter((g) => veri.caseler.some((c) => c.requirement_id === g.id && c.ai_generated))
    .map((g) => {
      const cs = veri.caseler.filter((c) => c.requirement_id === g.id && c.ai_generated);
      const replay = cs.every((c) => c.mode !== "live");
      const ai = replay ? null : cs.reduce((a, c) => a + c.ai_sure_ms, 0);
      const rv = cs.some((c) => c.review_sure_ms !== null) ? cs.reduce((a, c) => a + (c.review_sure_ms ?? 0), 0) : null;
      const b = manuelBaz(g.id);
      const baz = b.deger_s !== null ? b.deger_s * 1000 : null;
      const toplam = ai !== null && rv !== null ? ai + rv : null;
      return {
        requirement_id: g.id,
        story_key: g.jira_key,
        ai_sure_ms: ai,
        review_sure_ms: rv,
        toplam_ms: toplam,
        ai_olculmedi: ai === null,
        review_olculmedi: rv === null,
        manuel_baz_ms: baz,
        baz_kaynagi: b.kaynak,
        kazanc_orani: baz && toplam !== null ? 1 - toplam / baz : null,
        // Core ile aynı: yalnızca ölçülmüş baz + AI + review başlık kazancına girer (REPLAY girmez).
        kazanca_girer: !!(baz && b.kaynak === "olcum" && toplam !== null && !replay),
      };
    });
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
  const kayit: McpTokenKaydi = {
    id: yeniId("tok"),
    kapsam,
    son_kullanma: new Date(Date.now() + 8 * 3600 * 1000).toISOString(),
    iptal: false,
    son_kullanim: null,
    olusturma: simdi(),
  };
  veri.tokenlar = [kayit, ...(veri.tokenlar ?? [])];
  denetimEkle("token.create", kapsam, "8 saatlik MCP token'ı oluşturuldu");
  kaydet();
  return { id: kayit.id, token, kapsam, son_kullanma: kayit.son_kullanma, mcp_url: "http://127.0.0.1:8000/mcp" };
}

function tokenIptal(id: string): void {
  girisGerekli();
  const t = (veri.tokenlar ?? []).find((x) => x.id === id);
  if (!t) throw new ApiError(404, "Token bulunamadı");
  t.iptal = true;
  denetimEkle("token.revoke", t.kapsam, "MCP token'ı iptal edildi");
  kaydet();
}

// ------------------------------------------------------------------ yönlendirme

type Rota = [string, RegExp, (m: RegExpMatchArray, q: URLSearchParams, govde: unknown) => unknown];

const ROTALAR: Rota[] = [
  // Portal asistanı (AI-ASISTAN-PLANI §9): api/mock/asistan.ts.
  ...asistanRotalari(girisGerekli),
  // Öneri düğmesi (§17, uç 10–11): api/mock/oneri.ts.
  ...oneriRotalari(girisGerekli, () => veri),
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
      // Kanıtı doğrulanamayıp elenen bulgular gösterilmez; yalnızca sayısı (core ile aynı alan).
      return {
        ...g,
        elenen_bulgu: veri.bulgular.filter((b) => b.requirement_id === g.id && b.durum === "discarded").length,
        manuel_baz: manuelBaz(g.id),
      };
    },
  ],
  ["PUT", /^\/requirements\/([^/]+)\/baseline$/, (m, _q, g) => bazDegerKaydet(decodeURIComponent(m[1]), g)],
  ["DELETE", /^\/requirements\/([^/]+)\/baseline$/, (m) => bazDegerSil(decodeURIComponent(m[1]))],
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
  ["POST", /^\/requirements\/([^/]+)\/generate-cases$/, (m, _q, govde) => caseUret(decodeURIComponent(m[1]), govde)],
  // Test tasarım modeli (011 F3, iki tur): api/mock/tasarimModeli.ts.
  ...tasarimModeliRotalari(modelBaglami),
  // Üretim seçenekleri ve derinleştirme (011 K5, P5/P6): api/mock/derinlestirme.ts.
  ...derinlestirmeRotalari({
    veri: () => veri,
    girisGerekli,
    rolGerekli,
    gereksinim: (id) => bul(veri.gereksinimler, id, "Gereksinim"),
    arkaPlan,
    yeniId,
    kaydet,
    denetimEkle,
    gereksinimOlayi,
  }),
  [
    "GET",
    /^\/cases$/,
    (_m, q) => {
      girisGerekli();
      const rid = q.get("requirement_id");
      return veri.caseler
        .filter((c) => !rid || c.requirement_id === rid)
        .sort((a, b) => a.sira_no - b.sira_no)
        .map((c) => ({ ...c, ...caseV3Alanlari(c, veri.caseUretimleri?.[c.requirement_id]) }));
    },
  ],
  ["POST", /^\/cases\/([^/]+)\/decision$/, (m, _q, g) => caseKarari(decodeURIComponent(m[1]), g)],
  ["POST", /^\/cases\/([^/]+)\/viewed$/, (m) => caseGoruntulendi(decodeURIComponent(m[1]))],
  ["GET", /^\/requirements\/([^/]+)\/case-metrics$/, (m) => caseMetrikleri(decodeURIComponent(m[1]))],
  ["GET", /^\/requirements\/([^/]+)\/case-summary$/, (m) => caseSummary(decodeURIComponent(m[1]))],
  ["GET", /^\/requirements\/([^/]+)\/cases\.feature$/, (m, q) => gherkinOrnegi(decodeURIComponent(m[1]), q)],
  ["GET", /^\/requirements\/([^/]+)\/case-review$/, (m) => caseReviewGor(decodeURIComponent(m[1]))],
  ["POST", /^\/requirements\/([^/]+)\/case-review$/, (m) => caseReviewCalistir(decodeURIComponent(m[1]))],
  ["GET", /^\/requirements\/([^/]+)\/case-audit$/, (m) => caseDenetimGor(decodeURIComponent(m[1]))],
  ["POST", /^\/requirements\/([^/]+)\/case-audit$/, (m) => caseDenetimGonder(decodeURIComponent(m[1]))],
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
      const s = bul(veri.scriptler, decodeURIComponent(m[1]), "Script");
      return { ...s, merge_kabul_gerekli: mergeKabulGerekli(s) };
    },
  ],
  ["POST", /^\/scripts\/([^/]+)\/break-verify$/, (m) => kirarakDogrula(decodeURIComponent(m[1]))],
  ["POST", /^\/prs\/(\d+)\/merge$/, (m, _q, g) => prBirlestir(Number(m[1]), g)],
  ["POST", /^\/prs\/(\d+)\/review$/, (m, _q, g) => prReview(Number(m[1]), g)],
  ["POST", /^\/prs\/(\d+)\/update-branch$/, (m) => prDaliGuncelle(Number(m[1]))],
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
    /^\/failures$/,
    (_m, q) => {
      girisGerekli();
      const sinif = q.get("sinif");
      const script = q.get("script_id");
      const limit = Math.min(200, Number(q.get("limit") ?? 50) || 50);
      return veri.hatalar
        .filter((h) => (!sinif || h.sinif === sinif) && (!script || h.script_id === script))
        .sort((a, b) => b.zaman.localeCompare(a.zaman))
        .slice(0, limit);
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
  [
    "POST",
    /^\/bug-drafts\/([^/]+)\/prepare$/,
    (m) => {
      rolGerekli("tester");
      const b = bul(veri.bugTaslaklari, decodeURIComponent(m[1]), "Bug taslağı");
      if (b.durum !== "draft") throw new ApiError(409, "Taslak karar beklemiyor");
      const onceki = b.mukerrer_arama ?? null;
      b.mukerrer_arama = { durum: "suruyor", jql: onceki?.jql ?? null, oneri: null, oneri_link_key: null, mode: null, hata: null };
      kaydet();
      arkaPlan([
        () => {
          b.mukerrer_arama = onceki ?? { durum: "yapildi", jql: null, oneri: "new", oneri_link_key: null, mode: "replay", hata: null };
          if (b.mukerrer_arama.durum !== "yapildi") b.mukerrer_arama = { ...b.mukerrer_arama, durum: "yapildi" };
          mockOlayYayinla({ type: "bug.draft_ready", id: b.id, data: { bug_draft_id: b.id } });
        },
      ]);
      return is("queued", "Mükerrer araması ve taslak hazırlanıyor");
    },
  ],
  ["GET", /^\/control-tower$/, () => kontrolKulesi()],
  ["GET", /^\/audit$/, (_m, q) => denetim(q)],
  ["POST", /^\/tokens$/, (_m, _q, g) => tokenOlustur(g)],
  [
    "GET",
    /^\/tokens$/,
    () => {
      girisGerekli();
      return veri.tokenlar ?? [];
    },
  ],
  ["DELETE", /^\/tokens\/([^/]+)$/, (m) => tokenIptal(decodeURIComponent(m[1]))],
  [
    "POST",
    /^\/demo\/break-locator$/,
    () => demoKir(),
  ],
  [
    "POST",
    /^\/demo\/reset$/,
    () => {
      const k = rolGerekli("presenter");
      veri = ilkVeri();
      demoKirik = false;
      mockOturumuAyarla(k);
      kaydet();
      mockOlayYayinla({ type: "demo.reset", id: "demo", data: { eylem: "reset" } });
      return is("done", "Demo verisi sıfırlandı.");
    },
  ],
  [
    "GET",
    /^\/demo\/status$/,
    () => {
      girisGerekli();
      return {
        forge: { main: demoKirik ? "d3b1c0ffee42" : "9c41e2b07a11", testid: demoKirik ? "cart-add" : "add-to-cart", baseline: "9c41e2b07a11", main_baseline_mi: !demoKirik },
        uygulama: { sha: demoKirik ? "d3b1c0ffee42" : "9c41e2b07a11", kaynak: "build.json", main_ile_eslesiyor: true, neden: null },
        web_yenileme_istegi: null,
        locator_demo: { destekleniyor: true, neden: null },
        onarim_on_kosulu: { hazir: true, son_yesil_kosu: null, yonerge: null },
        // Örnek veri: model çağrısı yok; tüm çıktılar kayıtlı (REPLAY) golden'lardan.
        model: { mod: "replay", replay_strict: false, anahtar_var: false, aciklama: "Örnek veri: model çağrısı yapılmaz." },
        degerlendirme: ["requirement-review", "consistency-check", "case-generation", "verify-and-map", "triage", "bug-draft", "dup-rank"].map((paket) => ({
          paket,
          surum: null,
          durum: "pending",
          etiket: "canlı değerlendirme bekliyor",
        })),
      };
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
