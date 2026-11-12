// MIMARI-SOZLESME §5'teki her uç için türlü istemci.
import { ApiError, istek } from "./http";
import {
  bulguUyarla,
  caseKapsamOzetiUyarla,
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
import { kontrolKulesiUyarla, kosuDetayUyarla, kosuUyarla, scriptDetayUyarla, scriptUyarla } from "./uyumDemoB";
import { bazYanitiUyarla, demoDurumuUyarla, gereksinimBazi } from "./uyumFaz5";
import { caseKalitesiUyarla } from "./uyumCaseKalitesi";
import type { CaseKalitesi } from "./types";
import type { TopluOnayKalemi, TopluOnaySonucu, VarsayimDogrulamaGirdisi } from "./types";
import type {
  AjanTestiGorunumu,
  AjanUrunleriYaniti,
  BazDegerGirdisi,
  Bulgu,
  BulguKararGirdisi,
  BugKararGirdisi,
  BugTaslagi,
  CaseDenetimGorunumu,
  CaseKapsamOzeti,
  CaseKararGirdisi,
  CaseMetrikleri,
  CaseReviewGorunumu,
  DemoDurumu,
  DenetimYaniti,
  Gereksinim,
  GereksinimDetay,
  ManuelBaz,
  MergeGirdisi,
  RetNedeni,
  HataAnalizi,
  IsYaniti,
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
  DerinlestirmeDurumu,
  DerinlestirmeGirdisi,
  DerinlestirmeYaniti,
  UretimGovdesi,
  UretimSecenekleriYaniti,
} from "./types";
import { uretimSecenekleriYanitiUyarla } from "../lib/uretimSecenekleri";
import { tur2Uyarla, type Tur2Bilgisi } from "../lib/tasarimModeli";
import { derinlestirmeDurumuUyarla } from "../lib/derinlestirme";

import type {
  TasarimModeliKaydi,
  TasarimModeliKararGirdisi,
  TasarimModeliYaniti,
  UretimBaslatGirdisi,
  UretimKipi,
} from "./tasarimModeliTipleri";
import { tasarimModeliKaydiUyarla, tasarimModeliYanitiUyarla } from "./uyumTasarimModeli";

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
  /**
   * Üretimi başlatır. `kip` (011 K1) ve `secenekler` (011 K5) gövdede gider (`UretimBaslatGirdisi`);
   * portal kipi her zaman açıkça gönderir. Gövdesiz çağrı core'da tek tur, kayıtlı seçeneklerle.
   */
  caseUret: (id: string, kip?: UretimKipi, secenekler?: UretimGovdesi) => {
    const govde = { ...(secenekler ?? {}), ...(kip ? { kip } : {}) } satisfies Partial<UretimBaslatGirdisi> & UretimGovdesi;
    return istek<IsYaniti>("POST", `/requirements/${yol(id)}/generate-cases`, Object.keys(govde).length ? { govde } : {});
  },
  /** Test tasarım modeli (iki tur, 011 F3): son model + geçmiş özeti. */
  tasarimModeli: async (id: string): Promise<TasarimModeliYaniti> =>
    tasarimModeliYanitiUyarla(await istek<unknown>("GET", `/requirements/${yol(id)}/design-model`, { kaynak: GEREKSINIM_KAYNAGI })),
  /** Modeli yeniden üret (reddedilmiş/onaysız model; 202, asama "model"). */
  tasarimModeliUret: (id: string) => istek<IsYaniti>("POST", `/requirements/${yol(id)}/design-model`, { kaynak: GEREKSINIM_KAYNAGI }),
  /** approve | edit | reject; gövde ekranda görülen içeriğin hash'ini taşır. */
  /** D1/K20: yanıt `tur2` (ya da `tur2_basladi`) taşıyorsa onay tur 2'yi otomatik başlatmıştır; yoksa `tur2: null`. */
  tasarimModeliKarari: async (modelId: string, g: TasarimModeliKararGirdisi): Promise<TasarimModeliKaydi & { tur2: Tur2Bilgisi | null }> => {
    const ham = nesne(await istek<unknown>("POST", `/design-models/${yol(modelId)}/decision`, { govde: g, kaynak: GEREKSINIM_KAYNAGI }));
    return { ...tasarimModeliKaydiUyarla(ham), tur2: tur2Uyarla(ham) };
  },
  /** Üretim formu: kayıtlı son seçenekler, varsayılan ve ek bilgi alanı kataloğu (011 §4.4). */
  uretimSecenekleri: async (id: string): Promise<UretimSecenekleriYaniti> =>
    uretimSecenekleriYanitiUyarla(
      await istek<unknown>("GET", `/requirements/${yol(id)}/generation-options`, { kaynak: GEREKSINIM_KAYNAGI }),
    ),
  /** Derinleştirme (P5 negatif / P6 teknik; K7): mevcut sete ek taslaklar (202). */
  derinlestir: (id: string, g: DerinlestirmeGirdisi) =>
    istek<DerinlestirmeYaniti>("POST", `/requirements/${yol(id)}/deepen`, { govde: g, kaynak: GEREKSINIM_KAYNAGI }),
  derinlestirmeDurumu: async (id: string): Promise<DerinlestirmeDurumu> =>
    derinlestirmeDurumuUyarla(await istek<unknown>("GET", `/requirements/${yol(id)}/deepen`, { kaynak: GEREKSINIM_KAYNAGI })),
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
  /** Analist case'i ilk kez gördü: review süresi (`review_sure_ms`) sunucuda bu andan ölçülür. */
  caseGoruntulendi: (id: string) => istek<unknown>("POST", `/cases/${yol(id)}/viewed`, { kaynak: CASE_KAYNAGI }),
  /**
   * K20 "Varsayım doğrulandı": analist varsayımı doğruladı; case görülen içeriğiyle (hash) hazır
   * yapılıp onaylanır (review kaydı düzeltme). Başka atıf kalırsa 422, içerik değiştiyse 409.
   */
  varsayimDogrulandi: async (caseId: string, g: VarsayimDogrulamaGirdisi): Promise<TestCase> =>
    caseUyarla(nesne(await istek<unknown>("POST", `/cases/${yol(caseId)}/assumption-verified`, { govde: g, kaynak: CASE_KAYNAGI }))),
  /** K20 toplu onay: kalem bazlı (her case ayrı review kaydı ve kendi hash'i); kalem hataları sonuçta döner. */
  topluOnay: async (kalemler: TopluOnayKalemi[]): Promise<TopluOnaySonucu> => {
    const ham = nesne(await istek<unknown>("POST", "/cases/bulk-decision", { govde: { karar: "approve", kalemler }, kaynak: CASE_KAYNAGI }));
    const sonuclar = (Array.isArray(ham.sonuclar) ? ham.sonuclar : []).map((x) => {
      const k = nesne(x);
      return {
        case_id: String(k.case_id ?? ""),
        basarili: k.basarili === true,
        hata: typeof k.hata === "string" ? k.hata : null,
        kod: typeof k.kod === "number" ? k.kod : null,
        case: k.case && typeof k.case === "object" ? caseUyarla(nesne(k.case)) : null,
      };
    });
    const onaylanan = sonuclar.filter((k) => k.basarili).length;
    return {
      karar: "approve",
      onaylanan: typeof ham.onaylanan === "number" ? ham.onaylanan : onaylanan,
      basarisiz: typeof ham.basarisiz === "number" ? ham.basarisiz : sonuclar.length - onaylanan,
      sonuclar,
    };
  },
  /** §12 ölçümleri (kabul oranı ilk karara göre, AI + review süresi, maliyet). */
  caseMetrikleri: (requirementId: string) =>
    istek<CaseMetrikleri>("GET", `/requirements/${yol(requirementId)}/case-metrics`, { kaynak: CASE_KAYNAGI }),
  /**
   * Kapsam ve açık noktalar özeti (011 §4.4): üretim başına üst listeler + hesaplanan kapsam
   * matrisi + teknik/readiness dağılımı. Yalnız eski şemalı case'i olan gereksinimde `uretimler` boştur.
   */
  caseSummary: async (requirementId: string): Promise<CaseKapsamOzeti | null> =>
    caseKapsamOzetiUyarla(await istek<unknown>("GET", `/requirements/${yol(requirementId)}/case-summary`, { kaynak: CASE_KAYNAGI })),

  /**
   * Onaylı ve hazır case'lerin Türkçe Gherkin'i (011 F8; `text/plain`). Uygun case yoksa 404.
   * Dönüşüm yalnız çekirdektedir; örnek veri katmanı sabit bir örnek döner.
   */
  gherkin: (requirementId: string, yalnizYayinlanan = false) =>
    istek<string>("GET", `/requirements/${yol(requirementId)}/cases.feature`, {
      sorgu: yalnizYayinlanan ? { yalniz_yayinlanan: 1 } : undefined,
      kaynak: CASE_KAYNAGI,
      metin: true,
    }),
  /** P8 review (011 F2): son review + güncel set hash'i + bayat mı. */
  caseReview: (requirementId: string) =>
    istek<CaseReviewGorunumu>("GET", `/requirements/${yol(requirementId)}/case-review`, { kaynak: CASE_KAYNAGI }),
  /** Review'u yeniden çalıştır (analist; tavsiye niteliğinde). */
  caseReviewCalistir: (requirementId: string) =>
    istek<CaseReviewGorunumu>("POST", `/requirements/${yol(requirementId)}/case-review`, { kaynak: CASE_KAYNAGI }),
  /** P9 denetim (011 F5): son karar, güncel set, yayın kapısı durumu. */
  caseDenetim: (requirementId: string) =>
    istek<CaseDenetimGorunumu>("GET", `/requirements/${yol(requirementId)}/case-audit`, { kaynak: CASE_KAYNAGI }),
  /** "Agent Probe'a gönder" (analist). */
  caseDenetimGonder: (requirementId: string) =>
    istek<CaseDenetimGorunumu>("POST", `/requirements/${yol(requirementId)}/case-audit`, { kaynak: CASE_KAYNAGI }),

  // Yayın
  yayinOnizleme: async (requirementId: string): Promise<YayinOnizleme> =>
    yayinOnizlemeUyarla(await istek<unknown>("GET", "/publish/preview", { sorgu: { requirement_id: requirementId } })),
  yayinla: async (caseIds: string[]): Promise<YayinSonucu & { job_id?: string | null }> =>
    yayinSonucuUyarla(await istek<unknown>("POST", "/publish", { govde: { case_ids: caseIds }, kaynak: CASE_KAYNAGI })),

  // Kod üretimi
  /** 009 §2.9: `platform` (web | android | ios | windows; varsayılan web). Aynı case için platform başına ayrı script/PR. */
  kodUret: (caseIds: string[], platform: Platform = "web") =>
    istek<IsYaniti>("POST", "/code/generate", { govde: { case_ids: caseIds, platform } }),
  scriptler: async (): Promise<Script[]> => listeUyarla(await istek<unknown>("GET", "/scripts"), scriptUyarla),
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
  /** K21 Case kalitesi; `requirementId` verilirse yalnız o gereksinim. Eski core'da 404 (bölüm gizlenir). */
  caseKalitesi: async (requirementId?: string): Promise<CaseKalitesi> =>
    caseKalitesiUyarla(
      await istek<unknown>("GET", "/control-tower/case-quality", { sorgu: requirementId ? { requirement_id: requirementId } : undefined }),
    ),
  denetim: async (dogrula = true): Promise<DenetimYaniti> =>
    denetimiUyarla(await istek<unknown>("GET", "/audit", { sorgu: { verify: dogrula } })),

  // Agent Probe: AI ajan ürünleri ve ajan testi talepleri (011 F6; bu sürümde simülasyon)
  ajanUrunleri: () => istek<AjanUrunleriYaniti>("GET", "/agent-probe/products"),
  ajanTesti: (id: string) => istek<AjanTestiGorunumu>("GET", `/requirements/${yol(id)}/agent-test`),
  /**
   * D4: talebin sonucunu işletip görünümü döndürür (`POST …/agent-test/refresh`). Uç yoksa (eski
   * core: 404/405, uç listesinde yok: 501) eski `GET …/agent-test` ile devam edilir.
   */
  ajanTestiYenile: async (id: string): Promise<AjanTestiGorunumu> => {
    try {
      return await istek<AjanTestiGorunumu>("POST", `/requirements/${yol(id)}/agent-test/refresh`, {
        kaynak: ["GET", `/requirements/${yol(id)}/agent-test`],
      });
    } catch (e) {
      if (e instanceof ApiError && [404, 405, 501].includes(e.status)) return api.ajanTesti(id);
      throw e;
    }
  },
  ajanUrunuBagla: (id: string, urunKodu: string | null) =>
    istek<AjanTestiGorunumu>("PUT", `/requirements/${yol(id)}/agent-product`, { govde: { urun_kodu: urunKodu } }),
  ajanTestiBaslat: (id: string) => istek<AjanTestiGorunumu>("POST", `/requirements/${yol(id)}/agent-test`),

  // Claude Code kanalı
  tokenOlustur: (kapsam: TokenKapsami) => istek<McpToken>("POST", "/tokens", { govde: { kapsam } }),
  tokenlar: () => istek<McpTokenKaydi[]>("GET", "/tokens"),
  tokenIptal: (id: string) => istek<void>("DELETE", `/tokens/${yol(id)}`, { kaynak: ["GET", "/tokens"] }),

  // Sunum
  demoKir: () => istek<IsYaniti>("POST", "/demo/break-locator"),
  demoSifirla: () => istek<IsYaniti>("POST", "/demo/reset"),
  /** Forge main / çalışan demo uygulaması eşleşmesi (salt okuma). */
  demoDurumu: async (): Promise<DemoDurumu> => demoDurumuUyarla(await istek<unknown>("GET", "/demo/status")),
};

export type Api = typeof api;
