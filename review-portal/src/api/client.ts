// MIMARI-SOZLESME §5'teki her uç için türlü istemci.
import { istek } from "./http";
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
import { kontrolKulesiUyarla, kosuDetayUyarla, kosuUyarla, scriptDetayUyarla, scriptUyarla } from "./uyumDemoB";
import type {
  Bulgu,
  BulguKararGirdisi,
  BugKararGirdisi,
  BugTaslagi,
  CaseKararGirdisi,
  CaseMetrikleri,
  DenetimYaniti,
  Gereksinim,
  GereksinimDetay,
  MergeGirdisi,
  RetNedeni,
  HataAnalizi,
  IsYaniti,
  KontrolKulesi,
  Kosu,
  KosuDetay,
  Kullanici,
  McpToken,
  McpTokenKaydi,
  PullRequest,
  Script,
  ScriptDetay,
  SerbestMetinGirdisi,
  TestCase,
  TokenKapsami,
  YayinOnizleme,
  YayinSonucu,
} from "./types";

const yol = (s: string) => encodeURIComponent(s);
const nesne = (x: unknown) => (x && typeof x === "object" ? (x as Record<string, unknown>) : {});
/** Case işlemleri case listesine bağlıdır: liste çekirdekten geliyorsa işlem örnek veriye düşmez. */
const CASE_KAYNAGI = ["GET", "/cases"] as const;
/** Script işlemleri (kırarak doğrula, merge) script listesine bağlıdır (gerçek script örnek veriye düşmez). */
const SCRIPT_KAYNAGI = ["GET", "/scripts"] as const;

export const api = {
  // Oturum
  login: (kullanici_adi: string, parola: string) =>
    istek<Kullanici>("POST", "/auth/login", { govde: { kullanici_adi, parola } }),
  logout: () => istek<void>("POST", "/auth/logout"),
  me: () => istek<Kullanici>("GET", "/auth/me"),

  // Gereksinimler
  gereksinimler: async (): Promise<Gereksinim[]> => listeUyarla(await istek<unknown>("GET", "/requirements"), gereksinimUyarla),
  jiradanCek: () => istek<IsYaniti>("POST", "/requirements/sync"),
  serbestMetin: async (g: SerbestMetinGirdisi): Promise<Gereksinim> =>
    gereksinimUyarla(nesne(await istek<unknown>("POST", "/requirements/free-text", { govde: g }))),
  gereksinim: async (id: string): Promise<GereksinimDetay> =>
    gereksinimDetayUyarla(nesne(await istek<unknown>("GET", `/requirements/${yol(id)}`))),
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
    gereksinimDetayUyarla(
      nesne(await istek<unknown>("POST", `/requirements/${yol(g.id)}/po-approve`, { govde: { icerik_hash: g.icerik_hash } })),
    ),
  caseUret: (id: string) => istek<IsYaniti>("POST", `/requirements/${yol(id)}/generate-cases`),

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
  /** §12 ölçümleri (kabul oranı ilk karara göre, AI + review süresi, maliyet). */
  caseMetrikleri: (requirementId: string) =>
    istek<CaseMetrikleri>("GET", `/requirements/${yol(requirementId)}/case-metrics`, { kaynak: CASE_KAYNAGI }),

  // Yayın
  yayinOnizleme: async (requirementId: string): Promise<YayinOnizleme> =>
    yayinOnizlemeUyarla(await istek<unknown>("GET", "/publish/preview", { sorgu: { requirement_id: requirementId } })),
  yayinla: async (caseIds: string[]): Promise<YayinSonucu & { job_id?: string | null }> =>
    yayinSonucuUyarla(await istek<unknown>("POST", "/publish", { govde: { case_ids: caseIds }, kaynak: CASE_KAYNAGI })),

  // Kod üretimi
  kodUret: (caseIds: string[]) => istek<IsYaniti>("POST", "/code/generate", { govde: { case_ids: caseIds } }),
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

  // Triage
  hata: (id: string) => istek<HataAnalizi>("GET", `/failures/${yol(id)}`),
  onarimPrAc: (id: string) => istek<IsYaniti>("POST", `/failures/${yol(id)}/fix`),

  // Bug taslakları
  bugTaslaklari: () => istek<BugTaslagi[]>("GET", "/bug-drafts"),
  bugTaslagi: (id: string) => istek<BugTaslagi>("GET", `/bug-drafts/${yol(id)}`),
  bugKarari: (id: string, g: BugKararGirdisi) =>
    istek<BugTaslagi>("POST", `/bug-drafts/${yol(id)}/decision`, { govde: g }),

  // Kontrol Kulesi ve denetim
  kontrolKulesi: async (): Promise<KontrolKulesi> => kontrolKulesiUyarla(await istek<unknown>("GET", "/control-tower")),
  denetim: async (dogrula = true): Promise<DenetimYaniti> =>
    denetimiUyarla(await istek<unknown>("GET", "/audit", { sorgu: { verify: dogrula } })),

  // Claude Code kanalı
  tokenOlustur: (kapsam: TokenKapsami) => istek<McpToken>("POST", "/tokens", { govde: { kapsam } }),
  tokenlar: () => istek<McpTokenKaydi[]>("GET", "/tokens"),
  tokenIptal: (id: string) => istek<void>("DELETE", `/tokens/${yol(id)}`, { kaynak: ["GET", "/tokens"] }),

  // Sunum
  demoKir: () => istek<IsYaniti>("POST", "/demo/break-locator"),
  demoSifirla: () => istek<IsYaniti>("POST", "/demo/reset"),
};

export type Api = typeof api;
