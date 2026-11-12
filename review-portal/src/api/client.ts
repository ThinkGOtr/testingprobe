// MIMARI-SOZLESME §5'teki her uç için türlü istemci.
import { ApiError, istek } from "./http";
import {
  bulguUyarla,
  caseUyarla,
  denetimiUyarla,
  gereksinimDetayUyarla,
  gereksinimUyarla,
  listeUyarla,
  yayinOnizlemeUyarla,
  yayinSonucuUyarla,
} from "./uyum";
import { bugIcerikCoreBicimi, bugTaslagiUyarla, hataAnaliziUyarla } from "./uyumTriage";
import { nesneMi } from "./uyum";
import { dahaFazlaBasligiOku, kodDilleriUyarla, kodUretYanitiUyarla, kontrolKulesiUyarla, kosuDetayUyarla, kosuUyarla, scriptDetayUyarla, scriptListesiUyarla, scriptUyarla } from "./uyumDemoB";
import { bazYanitiUyarla, demoDurumuUyarla, gereksinimBazi } from "./uyumFaz5";
import {
  jiraTetikDurumuUyarla,
  kodUretimIsiUyarla,
  otomasyonAyarlariUyarla,
  surumlerUyarla,
  testVerileriUyarla,
  testVerisiUyarla,
  topluKararUyarla,
} from "./uyumOtomasyon";
import type {
  BazDegerGirdisi,
  Bulgu,
  BulguKararGirdisi,
  BugKararGirdisi,
  BugTaslagi,
  CaseKararGirdisi,
  CaseMetrikleri,
  DemoDurumu,
  DenetimYaniti,
  Dil,
  Gereksinim,
  GereksinimDetay,
  ManuelBaz,
  MergeGirdisi,
  RetNedeni,
  HataAnalizi,
  IsYaniti,
  KodDilleri,
  KodUretYaniti,
  ScriptListesi,
  KontrolKulesi,
  Kosu,
  KosuDetay,
  Kullanici,
  CikisYaniti,
  AiprobeHesaplari,
  McpToken,
  McpTokenKaydi,
  Platform,
  PullRequest,
  Script,
  ScriptDetay,
  SerbestMetinGirdisi,
  TestCase,
  TokenKapsami,
  YayinOnizleme,
  YayinSonucu,
  JiraTetikDurumu,
  KodUretimIsi,
  OtomasyonAyarAnahtari,
  OtomasyonAyarlari,
  TestVerisi,
  TestVerisiGirdisi,
  TestVerisiGuncelleme,
  TestVerisiSurumu,
  TopluKararYaniti,
} from "./types";

const yol = (s: string) => encodeURIComponent(s);
/** Gereksinim detayı + Faz 5 baz değeri (alan yoksa eklenmez: "çekirdek sunmuyor"). */
function detayUyarla(ham: Record<string, unknown>): GereksinimDetay {
  const baz = gereksinimBazi(ham);
  return { ...gereksinimDetayUyarla(ham), ...(baz !== undefined ? { manuel_baz: baz } : {}) };
}
/** Baz değer işlemleri gereksinime bağlıdır: gereksinim çekirdekten geliyorsa uç yokken örnek veriye düşülmez. */
const GEREKSINIM_KAYNAGI = ["GET", "/requirements"] as const;
export const HATA_BULUNAMADI = "Hata kaydı bulunamadı: bağlantı geçersiz ya da kayıt silinmiş.";
const nesne = (x: unknown) => (x && typeof x === "object" ? (x as Record<string, unknown>) : {});
/** Case işlemleri case listesine bağlıdır: liste çekirdekten geliyorsa işlem örnek veriye düşmez. */
const CASE_KAYNAGI = ["GET", "/cases"] as const;
/** Script işlemleri (kırarak doğrula, merge) script listesine bağlıdır (gerçek script örnek veriye düşmez). */
const SCRIPT_KAYNAGI = ["GET", "/scripts"] as const;
/** Onarım işlemi triage sonucuna bağlıdır ("1": herhangi bir kimlik; yol kalıbı ve mock anahtarı ":id" ile eşleşir). */
const HATA_KAYNAGI = ["GET", "/failures/1"] as const;
/** Test verisi işlemleri katalog listesine bağlıdır. */
const TESTVERI_KAYNAGI = ["GET", "/test-data"] as const;
/** Bug kararı taslak listesine bağlıdır. */
const BUG_KAYNAGI = ["GET", "/bug-drafts"] as const;

export const api = {
  // Oturum
  login: (kullanici_adi: string, parola: string) =>
    istek<Kullanici>("POST", "/auth/login", { govde: { kullanici_adi, parola } }),
  /** AI Probe oturumunda yanıt `redirect` taşır (tüm ürünlerden çıkış sayfası; TEKNIK-TASARIM §8.14). */
  logout: () => istek<CikisYaniti | undefined>("POST", "/auth/logout"),
  me: () => istek<Kullanici>("GET", "/auth/me"),
  // AI Probe ortak girişi (yalnız TP_AUTH_MODE=aiprobe|both; specs/010-aiprobe-sso)
  aiprobeHesaplar: () => istek<AiprobeHesaplari>("GET", "/auth/aiprobe/hesaplar"),
  aiprobeRolSec: (app_user_id: string) =>
    istek<Kullanici & { continue?: string }>("POST", "/auth/aiprobe/rol-sec", { govde: { app_user_id } }),
  aiprobeRolDegistir: (app_user_id: string) =>
    istek<Kullanici>("POST", "/auth/aiprobe/rol-degistir", { govde: { app_user_id } }),

  // Gereksinimler
  gereksinimler: async (): Promise<Gereksinim[]> => listeUyarla(await istek<unknown>("GET", "/requirements"), gereksinimUyarla),
  jiradanCek: () => istek<IsYaniti>("POST", "/requirements/sync"),
  serbestMetin: async (g: SerbestMetinGirdisi): Promise<Gereksinim> =>
    gereksinimUyarla(nesne(await istek<unknown>("POST", "/requirements/free-text", { govde: g }))),
  gereksinim: async (id: string): Promise<GereksinimDetay> => detayUyarla(nesne(await istek<unknown>("GET", `/requirements/${yol(id)}`))),
  incelemeBaslat: (id: string) => istek<IsYaniti>("POST", `/requirements/${yol(id)}/review`),
  bulgular: async (id: string): Promise<Bulgu[]> =>
    listeUyarla(await istek<unknown>("GET", `/requirements/${yol(id)}/findings`), bulguUyarla),
  bulguKarari: async (id: string, g: BulguKararGirdisi): Promise<Bulgu> =>
    bulguUyarla(nesne(await istek<unknown>("POST", `/findings/${yol(id)}/decision`, { govde: g }))),
  /** `cakismayiOnayla`: düzeltme bir 'bilinçli fark' kararıyla çelişiyorsa (409) yine de uygula (denetlenir). */
  duzeltmeleriUygula: (id: string, cakismayiOnayla = false) =>
    istek<IsYaniti>("POST", `/requirements/${yol(id)}/apply-doc-fixes`, cakismayiOnayla ? { govde: { cakismayi_onayla: true } } : {}),
  /** `g`: ekranda görülen gereksinim; `icerik_hash` aynen gönderilir (TOCTOU bağı). */
  poOnayla: async (g: Pick<GereksinimDetay, "id" | "icerik_hash">): Promise<GereksinimDetay> =>
    detayUyarla(
      nesne(await istek<unknown>("POST", `/requirements/${yol(g.id)}/po-approve`, { govde: { icerik_hash: g.icerik_hash } })),
    ),
  caseUret: (id: string) => istek<IsYaniti>("POST", `/requirements/${yol(id)}/generate-cases`),
  /**
   * Story başına manuel baz değer (Faz 5; analyst | po). Yanıt baz değer ya da gereksinim
   * detayıdır; ikisi de yoksa `undefined` (çağıran detayı yeniden okur).
   */
  bazDegerKaydet: async (id: string, g: BazDegerGirdisi): Promise<ManuelBaz | undefined> =>
    bazYanitiUyarla(await istek<unknown>("PUT", `/requirements/${yol(id)}/baseline`, { govde: g, kaynak: GEREKSINIM_KAYNAGI })),
  bazDegerSil: async (id: string): Promise<ManuelBaz | undefined> =>
    bazYanitiUyarla(await istek<unknown>("DELETE", `/requirements/${yol(id)}/baseline`, { kaynak: GEREKSINIM_KAYNAGI })),

  // Case'ler
  caseler: async (requirementId?: string): Promise<TestCase[]> =>
    listeUyarla(await istek<unknown>("GET", "/cases", { sorgu: { requirement_id: requirementId } }), caseUyarla).sort(
      (a, b) => a.sira_no - b.sira_no,
    ),
  caseKarari: async (id: string, g: CaseKararGirdisi): Promise<TestCase> =>
    caseUyarla(nesne(await istek<unknown>("POST", `/cases/${yol(id)}/decision`, { govde: g, kaynak: CASE_KAYNAGI }))),
  /**
   * "Taslağa al": onaylı/reddedilmiş case'i yeniden taslağa alır (test_case: approved|rejected →
   * draft; core karar ucunda `karar: "reopen"`). Gövde ekranda görülen içeriğin hash'ini taşır.
   */
  caseYenidenAc: async (tc: Pick<TestCase, "id" | "icerik_hash">): Promise<TestCase> =>
    caseUyarla(
      nesne(
        await istek<unknown>("POST", `/cases/${yol(tc.id)}/decision`, {
          govde: { karar: "reopen", icerik_hash: tc.icerik_hash },
          kaynak: CASE_KAYNAGI,
        }),
      ),
    ),
  /**
   * 013 §3.2 toplu onay (analyst): her öğe ekranda görülen kendi hash'iyle onaylanır; sunucu görülmeyeni
   * atlar. 1..200 öğe (çağıran böler).
   */
  topluOnay: async (ogeler: Pick<TestCase, "id" | "icerik_hash">[]): Promise<TopluKararYaniti> =>
    topluKararUyarla(
      await istek<unknown>("POST", "/cases/bulk-decision", {
        govde: { karar: "approve", ogeler: ogeler.map((c) => ({ case_id: c.id, icerik_hash: c.icerik_hash })) },
        kaynak: CASE_KAYNAGI,
      }),
    ),
  /** Analist case'i ilk kez gördü: review süresi (`review_sure_ms`) sunucuda bu andan ölçülür. */
  caseGoruntulendi: (id: string) => istek<unknown>("POST", `/cases/${yol(id)}/viewed`, { kaynak: CASE_KAYNAGI }),
  /** §12 ölçümleri (kabul oranı ilk karara göre, AI + review süresi, maliyet). */
  caseMetrikleri: (requirementId: string) =>
    istek<CaseMetrikleri>("GET", `/requirements/${yol(requirementId)}/case-metrics`, { kaynak: CASE_KAYNAGI }),

  // Yayın
  yayinOnizleme: async (requirementId: string): Promise<YayinOnizleme> =>
    yayinOnizlemeUyarla(await istek<unknown>("GET", "/publish/preview", { sorgu: { requirement_id: requirementId } })),
  yayinla: async (caseIds: string[]): Promise<YayinSonucu & { job_id?: string | null }> =>
    yayinSonucuUyarla(await istek<unknown>("POST", "/publish", { govde: { case_ids: caseIds }, kaynak: CASE_KAYNAGI })),

  // Kod üretimi
  /**
   * 009 §2.9: `platform` (web | android | ios | windows; varsayılan web). Aynı case için platform başına ayrı script/PR.
   * 011 §2.3: `dil` yalnız kullanıcı elle seçtiyse gönderilir (core `dil_kaynagi="secildi"` yazar);
   * gönderilmezse core repodan algılanan dili kullanır. Alan yokken gövde 011 öncesiyle aynıdır.
   */
  kodUret: async (caseIds: string[], platform: Platform = "web", dil?: Dil | null): Promise<KodUretYaniti> =>
    kodUretYanitiUyarla(await istek<unknown>("POST", "/code/generate", { govde: { case_ids: caseIds, platform, ...(dil ? { dil } : {}) } })),
  /**
   * 011 §2.3: platformun dil seçenekleri ve repodan algılanan dil. Uç yoksa (011 öncesi core) `null`:
   * dil seçici çizilmez, üretim bugünkü gibi sürer. Script'ler çekirdekten geliyorsa örnek veriye düşülmez.
   */
  kodDilleri: async (platform: Platform): Promise<KodDilleri | null> => {
    try {
      return kodDilleriUyarla(await istek<unknown>("GET", "/code/languages", { sorgu: { platform }, kaynak: SCRIPT_KAYNAGI }), platform);
    } catch (e) {
      // 501: uç yok (011 öncesi core). 403: uç yalnız engineer|presenter'a açık (011 K-T8); diğer roller
      // Kod üretimi ekranını zaten görmez — seçici sessizce gizlenir, üretim algılanan dille sürer.
      if (e instanceof ApiError && (e.status === 501 || e.status === 403)) return null;
      throw e;
    }
  },
  scriptler: async (): Promise<Script[]> => listeUyarla(await istek<unknown>("GET", "/scripts"), scriptUyarla),
  /** `GET /scripts` + liste sınırına ulaşıldı mı (core en yeni 200 kayıt; QA-Y4). */
  scriptListesi: async (): Promise<ScriptListesi> => {
    let dahaFazla: boolean | null = null;
    const govde = await istek<unknown>("GET", "/scripts", { basliklar: (h) => (dahaFazla = dahaFazlaBasligiOku(h)) });
    return scriptListesiUyarla(govde, dahaFazla);
  },
  script: async (id: string): Promise<ScriptDetay> => scriptDetayUyarla(nesne(await istek<unknown>("GET", `/scripts/${yol(id)}`))),
  kirarakDogrula: (id: string) => istek<IsYaniti>("POST", `/scripts/${yol(id)}/break-verify`, { kaynak: SCRIPT_KAYNAGI }),
  /** `pr`: incelenen PR; içerik hash'i ve head sha'sı merge'e bağlanır. */
  /**
   * İnsan onaylı merge. core merge'i iş olarak yapar (`codegen.merge`; 202 `{job_id, durum, mesaj}`)
   * ya da PR'ı döner; ikisi de `{number, birlesti, mesaj}`'a indirgenir. "Birleştirildi" yalnızca
   * yanıt PR'ın merged olduğunu söylüyorsa denir; iş kuyruğa alındıysa SSE `pr.merged` beklenir.
   */
  /** Geride kalan bot PR dalını main'e taşır (`codegen.update_branch`; 202). */
  prDaliGuncelle: (number: number) => istek<IsYaniti>("POST", `/prs/${number}/update-branch`, { kaynak: SCRIPT_KAYNAGI }),
  /** Script review reddi: değişiklik iste / reddet (ret nedeni sabit taksonomiden). */
  prReview: (
    number: number,
    g: { karar: "degisiklik_iste" | "reddet"; ret_nedeni: RetNedeni; icerik_hash: string; head_sha: string; not?: string | null },
  ) => istek<unknown>("POST", `/prs/${number}/review`, { govde: g, kaynak: SCRIPT_KAYNAGI }),
  prBirlestir: async (pr: Pick<PullRequest, "number"> & MergeGirdisi): Promise<{ number: number; birlesti: boolean; mesaj: string }> => {
    const g = nesne(
      await istek<unknown>("POST", `/prs/${pr.number}/merge`, {
        govde: { icerik_hash: pr.icerik_hash, head_sha: pr.head_sha, ...(pr.onay_notu ? { onay_notu: pr.onay_notu } : {}) },
        kaynak: SCRIPT_KAYNAGI,
      }),
    );
    const ham = nesne(g.pr).number !== undefined ? nesne(g.pr) : g;
    const birlesti = ham.durum === "merged" || ham.state === "merged" || g.durum === "merged";
    const mesaj = typeof g.mesaj === "string" && g.mesaj
      ? g.mesaj
      : birlesti
        ? `PR #${pr.number} birleştirildi.`
        : `PR #${pr.number} için merge isteği alındı; forge birleştirince ekran güncellenir.`;
    return { number: pr.number, birlesti, mesaj };
  },

  // CI ve koşular
  ciTetikle: (tetik: "deploy" | "nightly") => istek<IsYaniti>("POST", "/ci/trigger", { govde: { tetik } }),
  kosular: async (): Promise<Kosu[]> => listeUyarla(await istek<unknown>("GET", "/runs"), kosuUyarla),
  kosu: async (id: string): Promise<KosuDetay> => kosuDetayUyarla(nesne(await istek<unknown>("GET", `/runs/${yol(id)}`))),

  /** Triage sonuçları listesi (`GET /failures`, limit ≤200; core her satırı tekil görünümle döner). */
  hatalar: async (sorgu: { script_id?: string; sinif?: string; kaynak?: string; limit?: number } = {}): Promise<HataAnalizi[]> =>
    listeUyarla(await istek<unknown>("GET", "/failures", { sorgu: { limit: 200, ...sorgu } }), hataAnaliziUyarla),

  // Triage
  /**
   * Triage sonucu. Locator önerisinde onarım başladıysa repair şeridinin kaydı (`GET /failures/{id}/fix`:
   * AST koruması, etkilenen testler, PR) öneriyle birleştirilir; uç yoksa/onarım yoksa triage önerisi kalır.
   */
  hata: async (id: string): Promise<HataAnalizi> => {
    let ham: Record<string, unknown>;
    try {
      ham = nesne(await istek<unknown>("GET", `/failures/${yol(id)}`));
    } catch (e) {
      // Geçersiz kimlik (core 422: pydantic UUID metni) ya da yok (404): "bulunamadı" (ham doğrulama metni gösterilmez).
      // Dönüşen hata son hata kaydının kimliğini taşır (asistan bağlamı aynı kayda bağlanır).
      if (e instanceof ApiError && (e.status === 422 || e.status === 404)) {
        throw new ApiError(404, HATA_BULUNAMADI, { kod: e.kod, method: e.method, yol: e.yol, kayitId: e.kayitId });
      }
      throw e;
    }
    const oneri = nesne(ham.oneri);
    // Core triage yanıtı onarım kaydını zaten `oneri`ye katar (`script_durumu`) ve `oneri_durumu` taşır:
    // o zaman ayrı `GET /fix` gereksizdir (onarım yokken 404 → konsol hatası). Yalnızca eski biçimde çağrılır.
    const birlesik = "script_durumu" in oneri || typeof ham.oneri_durumu === "string";
    if (oneri.tur === "locator_fix" && !nesneMi(oneri.pr) && !birlesik) {
      try {
        const fix = nesne(await istek<unknown>("GET", `/failures/${yol(id)}/fix`, { kaynak: HATA_KAYNAGI }));
        const dolu = Object.fromEntries(Object.entries(fix).filter(([, v]) => v !== null && v !== undefined && !(Array.isArray(v) && v.length === 0)));
        ham.oneri = { ...oneri, ...dolu };
      } catch {
        /* onarım başlamadı (404) ya da uç yok: triage önerisi gösterilir */
      }
    }
    return hataAnaliziUyarla(ham);
  },
  /**
   * Locator onarım PR'ı (engineer): core `FailureToFix` işi → AST koruması → etkilenen tüm testlerde
   * yerel kontrol → bot PR (202). Kaynağı (triage sonucu) çekirdekteyse uç yokken örnek veriye düşülmez.
   */
  onarimPrAc: (id: string) => istek<IsYaniti>("POST", `/failures/${yol(id)}/fix`, { kaynak: HATA_KAYNAGI }),

  // Bug taslakları
  bugTaslaklari: async (): Promise<BugTaslagi[]> => listeUyarla(await istek<unknown>("GET", "/bug-drafts"), bugTaslagiUyarla),
  bugTaslagi: async (id: string): Promise<BugTaslagi> => bugTaslagiUyarla(nesne(await istek<unknown>("GET", `/bug-drafts/${yol(id)}`))),
  /** Testçi kararı → `publish_bug` (yeni kayıt / mevcut kayda bağla) ya da ret; içerik hash'ine bağlı. */
  /** Mükerrer aramasını ve AI taslağını yeniden hazırla (tester; 202). */
  bugHazirla: (id: string) => istek<IsYaniti>("POST", `/bug-drafts/${yol(id)}/prepare`, { kaynak: BUG_KAYNAGI }),
  /** Onaylı taslağın Jira yayınını yeniden dene (tester). */
  bugYayiniYinele: async (id: string): Promise<BugTaslagi> =>
    bugTaslagiUyarla(nesne(await istek<unknown>("POST", `/bug-drafts/${yol(id)}/publish`, { kaynak: BUG_KAYNAGI }))),
  bugKarari: async (id: string, g: BugKararGirdisi): Promise<BugTaslagi> => {
    const govde = g.icerik ? { ...g, icerik: bugIcerikCoreBicimi(g.icerik) } : g;
    const y = await istek<unknown>("POST", `/bug-drafts/${yol(id)}/decision`, { govde, kaynak: BUG_KAYNAGI });
    const n = nesne(y);
    // Core taslağı ya da 202 `{job_id, durum, taslak?}` döndürebilir: taslak yoksa yeniden okunur.
    if (n.id !== undefined && n.icerik !== undefined) return bugTaslagiUyarla(n);
    if (nesneMi(n.taslak)) return bugTaslagiUyarla(n.taslak);
    return bugTaslagiUyarla(nesne(await istek<unknown>("GET", `/bug-drafts/${yol(id)}`)));
  },

  // Kontrol Kulesi ve denetim
  kontrolKulesi: async (): Promise<KontrolKulesi> => kontrolKulesiUyarla(await istek<unknown>("GET", "/control-tower")),
  denetim: async (dogrula = true): Promise<DenetimYaniti> =>
    denetimiUyarla(await istek<unknown>("GET", "/audit", { sorgu: { verify: dogrula } })),

  // Claude Code kanalı
  tokenOlustur: (kapsam: TokenKapsami) => istek<McpToken>("POST", "/tokens", { govde: { kapsam } }),
  tokenlar: () => istek<McpTokenKaydi[]>("GET", "/tokens"),
  tokenIptal: (id: string) => istek<void>("DELETE", `/tokens/${yol(id)}`, { kaynak: ["GET", "/tokens"] }),

  // Test verisi kataloğu (013 §3.3)
  testVerileri: async (): Promise<TestVerisi[]> => testVerileriUyarla(await istek<unknown>("GET", "/test-data")),
  testVerisiEkle: async (g: TestVerisiGirdisi): Promise<TestVerisi> =>
    testVerisiUyarla(nesne(await istek<unknown>("POST", "/test-data", { govde: g, kaynak: TESTVERI_KAYNAGI }))),
  testVerisiGuncelle: async (id: string, g: TestVerisiGuncelleme): Promise<TestVerisi> =>
    testVerisiUyarla(nesne(await istek<unknown>("PUT", `/test-data/${yol(id)}`, { govde: g, kaynak: TESTVERI_KAYNAGI }))),
  /** 409: sürüm uyuşmazlığı ya da atıf yapan etkin case var (`ApiError.govde` listeyi taşır). */
  testVerisiSil: (id: string, beklenen_surum: number) =>
    istek<unknown>("DELETE", `/test-data/${yol(id)}`, { sorgu: { beklenen_surum }, kaynak: TESTVERI_KAYNAGI }),
  testVerisiGecmisi: async (id: string): Promise<TestVerisiSurumu[]> =>
    surumlerUyarla(await istek<unknown>("GET", `/test-data/${yol(id)}/history`, { kaynak: TESTVERI_KAYNAGI })),

  // Otomasyon ayarları ve Jira tetiği (013 §3.1, §3.4)
  otomasyonAyarlari: async (): Promise<OtomasyonAyarlari> => otomasyonAyarlariUyarla(await istek<unknown>("GET", "/automation-settings")),
  /** Kısmi nesne; yanıt güncel tüm ayarlardır. */
  otomasyonAyariKaydet: async <K extends OtomasyonAyarAnahtari>(
    anahtar: K,
    deger: Partial<Omit<OtomasyonAyarlari[K], "guncelleyen" | "guncelleme">>,
  ): Promise<OtomasyonAyarlari> =>
    otomasyonAyarlariUyarla(
      await istek<unknown>("PUT", `/automation-settings/${yol(anahtar)}`, { govde: deger, kaynak: ["GET", "/automation-settings"] }),
    ),
  /** Toplu onayın kod üretimi işi (`otomatik_kod.job_id`); case başına sonuç. */
  kodUretimIsi: async (jobId: string): Promise<KodUretimIsi> =>
    kodUretimIsiUyarla(await istek<unknown>("GET", `/automation/codegen-jobs/${yol(jobId)}`), jobId),
  jiraTetikDurumu: async (): Promise<JiraTetikDurumu> => jiraTetikDurumuUyarla(await istek<unknown>("GET", "/automation/jira-trigger")),

  // Sunum
  /** jira-sim'de story durumunu değiştirir (yalnız demo/sim; gerçek Jira'da 409). */
  demoJiraDurumu: (jira_key: string, durum: string) =>
    istek<{ mesaj?: string; jira_key?: string; durum?: string; degisti?: boolean } | undefined>("POST", "/demo/jira-status", { govde: { jira_key, durum } }),
  demoKir: () => istek<IsYaniti>("POST", "/demo/break-locator"),
  demoSifirla: () => istek<IsYaniti>("POST", "/demo/reset"),
  /** Forge main / çalışan demo uygulaması eşleşmesi (salt okuma). */
  demoDurumu: async (): Promise<DemoDurumu> => demoDurumuUyarla(await istek<unknown>("GET", "/demo/status")),
};

export type Api = typeof api;
