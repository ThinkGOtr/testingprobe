// MIMARI-SOZLESME §5'teki her uç için türlü istemci.
import { istek } from "./http";
import { denetimiUyarla } from "./uyum";
import type {
  Bulgu,
  BulguKararGirdisi,
  BugKararGirdisi,
  BugTaslagi,
  CaseKararGirdisi,
  DenetimYaniti,
  Gereksinim,
  GereksinimDetay,
  MergeGirdisi,
  HataAnalizi,
  IsYaniti,
  KontrolKulesi,
  Kosu,
  KosuDetay,
  Kullanici,
  McpToken,
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

export const api = {
  // Oturum
  login: (kullanici_adi: string, parola: string) =>
    istek<Kullanici>("POST", "/auth/login", { govde: { kullanici_adi, parola } }),
  logout: () => istek<void>("POST", "/auth/logout"),
  me: () => istek<Kullanici>("GET", "/auth/me"),

  // Gereksinimler
  gereksinimler: () => istek<Gereksinim[]>("GET", "/requirements"),
  jiradanCek: () => istek<IsYaniti>("POST", "/requirements/sync"),
  serbestMetin: (g: SerbestMetinGirdisi) => istek<Gereksinim>("POST", "/requirements/free-text", { govde: g }),
  gereksinim: (id: string) => istek<GereksinimDetay>("GET", `/requirements/${yol(id)}`),
  incelemeBaslat: (id: string) => istek<IsYaniti>("POST", `/requirements/${yol(id)}/review`),
  bulgular: (id: string) => istek<Bulgu[]>("GET", `/requirements/${yol(id)}/findings`),
  bulguKarari: (id: string, g: BulguKararGirdisi) => istek<Bulgu>("POST", `/findings/${yol(id)}/decision`, { govde: g }),
  duzeltmeleriUygula: (id: string) => istek<IsYaniti>("POST", `/requirements/${yol(id)}/apply-doc-fixes`),
  /** `g`: ekranda görülen gereksinim; `icerik_hash` aynen gönderilir (TOCTOU bağı). */
  poOnayla: (g: Pick<GereksinimDetay, "id" | "icerik_hash">) =>
    istek<GereksinimDetay>("POST", `/requirements/${yol(g.id)}/po-approve`, { govde: { icerik_hash: g.icerik_hash } }),
  caseUret: (id: string) => istek<IsYaniti>("POST", `/requirements/${yol(id)}/generate-cases`),

  // Case'ler
  caseler: (requirementId?: string) =>
    istek<TestCase[]>("GET", "/cases", { sorgu: { requirement_id: requirementId } }),
  caseKarari: (id: string, g: CaseKararGirdisi) => istek<TestCase>("POST", `/cases/${yol(id)}/decision`, { govde: g }),

  // Yayın
  yayinOnizleme: (requirementId: string) =>
    istek<YayinOnizleme>("GET", "/publish/preview", { sorgu: { requirement_id: requirementId } }),
  yayinla: (caseIds: string[]) => istek<YayinSonucu>("POST", "/publish", { govde: { case_ids: caseIds } }),

  // Kod üretimi
  kodUret: (caseIds: string[]) => istek<IsYaniti>("POST", "/code/generate", { govde: { case_ids: caseIds } }),
  scriptler: () => istek<Script[]>("GET", "/scripts"),
  script: (id: string) => istek<ScriptDetay>("GET", `/scripts/${yol(id)}`),
  kirarakDogrula: (id: string) => istek<IsYaniti>("POST", `/scripts/${yol(id)}/break-verify`),
  /** `pr`: incelenen PR; içerik hash'i ve head sha'sı merge'e bağlanır. */
  prBirlestir: (pr: Pick<PullRequest, "number"> & MergeGirdisi) =>
    istek<PullRequest>("POST", `/prs/${pr.number}/merge`, { govde: { icerik_hash: pr.icerik_hash, head_sha: pr.head_sha } }),

  // CI ve koşular
  ciTetikle: (tetik: "deploy" | "nightly") => istek<IsYaniti>("POST", "/ci/trigger", { govde: { tetik } }),
  kosular: () => istek<Kosu[]>("GET", "/runs"),
  kosu: (id: string) => istek<KosuDetay>("GET", `/runs/${yol(id)}`),

  // Triage
  hata: (id: string) => istek<HataAnalizi>("GET", `/failures/${yol(id)}`),
  onarimPrAc: (id: string) => istek<IsYaniti>("POST", `/failures/${yol(id)}/fix`),

  // Bug taslakları
  bugTaslaklari: () => istek<BugTaslagi[]>("GET", "/bug-drafts"),
  bugTaslagi: (id: string) => istek<BugTaslagi>("GET", `/bug-drafts/${yol(id)}`),
  bugKarari: (id: string, g: BugKararGirdisi) =>
    istek<BugTaslagi>("POST", `/bug-drafts/${yol(id)}/decision`, { govde: g }),

  // Kontrol Kulesi ve denetim
  kontrolKulesi: () => istek<KontrolKulesi>("GET", "/control-tower"),
  denetim: async (dogrula = true): Promise<DenetimYaniti> =>
    denetimiUyarla(await istek<unknown>("GET", "/audit", { sorgu: { verify: dogrula } })),

  // Claude Code kanalı
  tokenOlustur: (kapsam: TokenKapsami) => istek<McpToken>("POST", "/tokens", { govde: { kapsam } }),

  // Sunum
  demoKir: () => istek<IsYaniti>("POST", "/demo/break-locator"),
  demoSifirla: () => istek<IsYaniti>("POST", "/demo/reset"),
};

export type Api = typeof api;
