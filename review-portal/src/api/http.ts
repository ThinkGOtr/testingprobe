// İnce fetch sarmalayıcısı: JSON, hata gövdesi ({"detail": "..."}), 401 bildirimi ve
// mock geri düşüşü.
//
// Mock modu üç yolla devreye girer:
//   1. VITE_MOCK=1 ile derlenmişse her uç mock'tan cevaplanır.
//   2. Aksi halde uygulama açılırken core-api'nin uç listesi bir kez okunur (FastAPI
//      `GET /openapi.json` — core'un kendi beyanı). Listede olmayan uçlar için ağ isteği hiç
//      yapılmaz, doğrudan örnek veriye gidilir (DevTools'ta 404 seli yok).
//   3. Uç listesi okunamazsa (eski core, kapalı openapi) eski davranış: genel 404'te
//      ({"detail":"Not Found"} veya JSON olmayan 404) o uç için mock'a düşülür. Gerçek "kayıt
//      bulunamadı" 404'leri (Türkçe detail) mock'a düşmez, hata olarak gösterilir.
// VITE_MOCK=0 ile derlenmişse (compose/canlı portal, Dockerfile varsayılanı) örnek veriye HİÇ
// düşülmez: uç listesi yine okunur, core'un sunmadığı uca istek atılmaz ve `BU_FAZDA_YOK` (501)
// döner; ekranlar "bu fazda yok" boş durumu gösterir, menüde o ekranlar pasiftir. Canlı demoda
// uydurma KPI (kazanç yüzdesi, baz değer, geçme oranı) asla gerçek veri gibi görünmez.
// Mock'tan gelen her veri arayüzde "ÖRNEK VERİ" olarak etiketlenir (sahte canlı gösterim yok).

import type { Kullanici } from "./types";
import { gorunenMetinEkle, hataAdayi, hataKaydet } from "../lib/sonHata";
import { yanitBasliklariniOku } from "../lib/kimlikKipi";

/** `ApiError`'ın isteğe bağlı ek alanları (AI-ASISTAN-PLANI §5.5). */
export interface ApiHataEki {
  /** Sunucunun makine okunur hata kodu (`{"detail", "kod"}` yanıtı; ör. `bekleyen_var`). */
  kod?: string;
  method?: string;
  /** `ucuNormallestir` ile kimlikleri `:id` yapılmış yol (ör. `/cases/:id/review`). */
  yol?: string;
  /** Başka bir hatadan dönüştürülen hata, son hata kaydının kimliğini taşır. */
  kayitId?: string;
  /** Doğrulama hatası listesi (`{"detail", "kod", "hatalar": [...]}`; ör. `karar_tablosu_gecersiz`). */
  hatalar?: string[];
  /** Hata yanıtının ayrıştırılmış JSON gövdesi (ör. 409'da atıf yapan case listesi). */
  govde?: unknown;
  /** Hata gövdesinin ek sayısal alanları (ör. 429 `donduruldu` → `kalan_s`); metin alanı taşınmaz. */
  ek?: Record<string, number>;
}

let kayitSayaci = 0;

function yeniKayitId(): string {
  kayitSayaci += 1;
  return `h-${kayitSayaci}-${Date.now().toString(36)}`;
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  kod?: string;
  method?: string;
  yol?: string;
  /** Son hata deposundaki kaydın kimliği ("Asistana sor" bu kaydın bağlamıyla açar). */
  readonly kayitId: string;
  /** Sunucunun alan bazlı doğrulama mesajları (varsa). */
  hatalar?: string[];
  /** Hata yanıtının JSON gövdesi (varsa). */
  readonly govde?: unknown;
  /** Gövdenin ek sayısal alanları (`ApiHataEki.ek`). */
  readonly ek: Readonly<Record<string, number>>;

  constructor(status: number, detail: string, ek: ApiHataEki = {}) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.kod = ek.kod;
    this.method = ek.method;
    this.yol = ek.yol;
    this.kayitId = ek.kayitId ?? yeniKayitId();
    this.hatalar = ek.hatalar;
    this.govde = ek.govde;
    this.ek = ek.ek ?? {};
  }
}

export type MockHandler = (
  method: string,
  path: string,
  query: URLSearchParams,
  body: unknown,
) => Promise<unknown>;

export type Sorgu = Record<string, string | number | boolean | null | undefined>;

interface Ayarlar {
  mockZorunlu: boolean;
  mockOtomatik: boolean;
  /** core'un uç listesini (openapi.json) okuyup olmayan uçlara hiç istek atmamak. */
  yetenekKesfi: boolean;
  temelYol: string;
}

const ayarlar: Ayarlar = {
  mockZorunlu: import.meta.env.VITE_MOCK === "1",
  mockOtomatik: import.meta.env.VITE_MOCK !== "0",
  yetenekKesfi: true,
  temelYol: "/api",
};

/** core-api'nin sunduğu uçlar ("GET" + yol kalıbı). */
export interface Yetenekler {
  uclar: { method: string; kalip: RegExp; yol: string }[];
}

const HTTP_YONTEMLERI = new Set(["get", "post", "put", "patch", "delete", "head", "options"]);

let yetenekSozu: Promise<Yetenekler | null> | null = null;

/** OpenAPI belgesinden uç listesini çıkarır; `{param}` tek yol parçasıyla eşleşir. */
export function yetenekleriAyristir(belge: unknown): Yetenekler | null {
  if (!belge || typeof belge !== "object" || !("paths" in belge)) return null;
  const yollar = (belge as { paths: unknown }).paths;
  if (!yollar || typeof yollar !== "object") return null;
  const uclar: Yetenekler["uclar"] = [];
  for (const [yol, islemler] of Object.entries(yollar as Record<string, unknown>)) {
    if (!islemler || typeof islemler !== "object") continue;
    const kalip = new RegExp(
      `^${yol
        .split("/")
        .map((p) => (/^\{[^}]+\}$/.test(p) ? "[^/]+" : p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))
        .join("/")}$`,
    );
    for (const m of Object.keys(islemler)) {
      if (HTTP_YONTEMLERI.has(m.toLowerCase())) uclar.push({ method: m.toUpperCase(), kalip, yol });
    }
  }
  return { uclar };
}

/** Uç core'da var mı (sorgu dizgesi hariç yol). */
export function ucVar(y: Yetenekler, method: string, path: string): boolean {
  const yol = path.split("?")[0];
  return y.uclar.some((u) => u.method === method.toUpperCase() && u.kalip.test(yol));
}

/**
 * core'un uç listesi (bir kez okunur, sonuç önbellekte). `null`: bilinmiyor (mock zorunlu,
 * keşif kapalı ya da openapi okunamadı) — çağıran o zaman 404 geri düşüşüne güvenir.
 */
export function cekirdekYetenekleri(): Promise<Yetenekler | null> {
  if (ayarlar.mockZorunlu || !ayarlar.yetenekKesfi) return Promise.resolve(null);
  yetenekSozu ??= fetch(`${ayarlar.temelYol}/openapi.json`, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  })
    .then((r) => (r.ok ? r.json() : null))
    .then((b: unknown) => yetenekleriAyristir(b))
    .catch(() => null);
  return yetenekSozu;
}

let mockYukleyici: (() => Promise<MockHandler>) | null = () =>
  import("./mock/handlers").then((m) => m.mockIstek);

const mockUclar = new Set<string>();
const mockDinleyiciler = new Set<() => void>();
let yetkisizDinleyici: (() => void) | null = null;

/** Testler ve gelişmiş kullanım için ayarları değiştir. */
export function yapilandir(degisiklik: Partial<Ayarlar> & { mock?: MockHandler | null }): void {
  const { mock, ...geri } = degisiklik;
  Object.assign(ayarlar, geri);
  yetenekSozu = null;
  if (mock !== undefined) {
    mockYukleyici = mock ? () => Promise.resolve(mock) : null;
  }
}

export function mockZorunlu(): boolean {
  return ayarlar.mockZorunlu;
}

/** Canlı derleme (VITE_MOCK=0): örnek veriye hiç düşülmez. */
export function canliDerleme(): boolean {
  return !ayarlar.mockZorunlu && !ayarlar.mockOtomatik;
}

/** Mock'tan cevaplanmış uçlar (normalize edilmiş, ör. "GET /requirements/:id"). */
export function mockUclari(): string[] {
  return [...mockUclar].sort();
}

export function mockDegisikligineAbone(fn: () => void): () => void {
  mockDinleyiciler.add(fn);
  return () => mockDinleyiciler.delete(fn);
}

export function mockKayitlariniSifirla(): void {
  mockUclar.clear();
  mockDinleyiciler.forEach((fn) => fn());
}

export function yetkisizOlunca(fn: (() => void) | null): void {
  yetkisizDinleyici = fn;
}

/** Oturum sunucu tarafında bitti (ör. SSE `session.ended`): 401 ile aynı yol, giriş ekranına. */
export function oturumBitti(): void {
  yetkisizDinleyici?.();
}

/** Yol içindeki kimlikleri ":id" ile değiştirir (mock kayıtlarını gruplamak için). */
export function ucuNormallestir(method: string, path: string): string {
  const yol = path
    .split("/")
    .map((parca, i) => (i >= 2 && /[0-9]/.test(parca) ? ":id" : parca))
    .join("/");
  return `${method.toUpperCase()} ${yol}`;
}

function mockKaydet(method: string, path: string): void {
  const anahtar = ucuNormallestir(method, path);
  if (!mockUclar.has(anahtar)) {
    mockUclar.add(anahtar);
    mockDinleyiciler.forEach((fn) => fn());
  }
}

/** Mock tarafındaki "oturum" — gerçek giriş yapıldıysa rol kontrolü için kullanılır. */
let mockOturumKullanicisi: Kullanici | null = null;
export function mockOturumuAyarla(k: Kullanici | null): void {
  mockOturumKullanicisi = k;
}
export function mockOturumu(): Kullanici | null {
  return mockOturumKullanicisi;
}

function sorguMetni(sorgu?: Sorgu): URLSearchParams {
  const p = new URLSearchParams();
  if (sorgu) {
    for (const [k, v] of Object.entries(sorgu)) {
      if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
    }
  }
  return p;
}

/** Gövdenin üst düzey sonlu sayı alanları (`kalan_s` …); metin ve iç içe alanlar alınmaz. */
function sayisalEk(govde: object): Record<string, number> | undefined {
  const ek = Object.fromEntries(Object.entries(govde).filter(([, v]) => typeof v === "number" && Number.isFinite(v))) as Record<string, number>;
  return Object.keys(ek).length ? ek : undefined;
}

export async function detayOku(res: Response): Promise<{ detail: string | null; json: boolean; kod?: string; ek?: Record<string, number>; govde?: unknown; hatalar?: string[]; yolGecersiz?: boolean }> {
  const metin = await res.text().catch(() => "");
  if (!metin) return { detail: null, json: false };
  try {
    const govde = JSON.parse(metin) as unknown;
    if (govde && typeof govde === "object") {
      const hamKod = (govde as { kod?: unknown }).kod;
      const kod = typeof hamKod === "string" && hamKod ? hamKod : undefined;
      const ek = Array.isArray(govde) ? undefined : sayisalEk(govde);
      // Doğrulama listesi: `hatalar: [metin]` ya da `detail: [metin]` (ör. 422 `karar_tablosu_gecersiz`).
      const metinListesi = (x: unknown) => (Array.isArray(x) && x.length > 0 && x.every((m) => typeof m === "string") ? (x as string[]) : undefined);
      const hatalar = metinListesi((govde as { hatalar?: unknown }).hatalar) ?? metinListesi((govde as { detail?: unknown }).detail);
      if (hatalar && !("detail" in govde && typeof (govde as { detail: unknown }).detail === "string")) {
        return { detail: hatalar.join("; "), json: true, kod, hatalar, ek };
      }
      if ("detail" in govde) {
        const d = (govde as { detail: unknown }).detail;
        // Gövde yalnız detay/kod dışında alan taşıyorsa eklenir (ör. 409 + atıf yapan case listesi).
        const ekAlan = Object.keys(govde).some((k) => k !== "detail" && k !== "kod" && k !== "hatalar");
        if (typeof d === "string") return { detail: d, json: true, kod, ek, hatalar, ...(ekAlan ? { govde } : {}) };
        // Yapılı detay (`HTTPException(detail={...})`): içindeki Türkçe mesaj ve kod alınır, gövde korunur.
        if (d && typeof d === "object" && !Array.isArray(d)) {
          const o = d as Record<string, unknown>;
          const m = [o.detail, o.mesaj, o.message].find((x): x is string => typeof x === "string" && x !== "");
          const ic = typeof o.kod === "string" && o.kod ? o.kod : kod;
          return { detail: m ?? null, json: true, kod: ic, ek, govde };
        }
        // FastAPI doğrulama hataları: [{loc, msg, type}]
        if (Array.isArray(d)) {
          // Yol parametresi ayrıştırılamadı (ör. `/requirements/olmayan-id` → "req_id: Input should be a
          // valid UUID"): kayıt yoktur. Ham İngilizce Pydantic metni yerine "bulunamadı" (bkz. GECERSIZ_KIMLIK).
          if (d.length > 0 && d.every((x) => x && typeof x === "object" && Array.isArray((x as { loc?: unknown }).loc) && (x as { loc: unknown[] }).loc[0] === "path")) {
            return { detail: VARSAYILAN_HATA[404], json: true, kod, yolGecersiz: true };
          }
          const mesajlar = d
            .map((x) => (x && typeof x === "object" && "msg" in x ? String((x as { msg: unknown }).msg) : ""))
            .filter(Boolean);
          return { detail: mesajlar.join("; ") || "Geçersiz istek", json: true, kod, ek };
        }
      }
      return { detail: null, json: true, kod, ek, govde };
    }
    return { detail: null, json: true };
  } catch {
    return { detail: null, json: false };
  }
}

/**
 * Yol parametresi geçersiz (core 422, `loc: ["path", …]`): istemci bunu 404 "Kayıt bulunamadı." olarak
 * görür — geçersiz kimlikli kayıt yoktur; ekran bulunamadı görünümünü gösterir, "Tekrar dene" anlamsızdır.
 */
export const GECERSIZ_KIMLIK = "gecersiz_kimlik";

/** Kayıt bulunamadı (404 ya da geçersiz kimlik): yeniden denemek sonucu değiştirmez. */
export function bulunamadi(e: unknown): boolean {
  return e instanceof ApiError && e.status === 404 && e.detail !== "Not Found";
}

const VARSAYILAN_HATA: Record<number, string> = {
  400: "İstek geçersiz.",
  401: "Oturum açmanız gerekiyor.",
  403: "Bu işlem için yetkiniz yok.",
  404: "Kayıt bulunamadı.",
  409: "İşlem mevcut durumla çakışıyor.",
  422: "Gönderilen veri doğrulanamadı.",
  429: "Çok fazla istek; biraz sonra tekrar deneyin.",
  501: "Bu işlem çekirdekte henüz etkin değil.",
  502: "Çekirdek servise ulaşılamıyor.",
  503: "Servis şu anda kullanılamıyor.",
  504: "Çekirdek servis zamanında yanıt vermedi.",
};

async function mockaDus<T>(method: string, path: string, q: URLSearchParams, body: unknown): Promise<T> {
  if (!mockYukleyici) throw new ApiError(404, "Bu uç henüz mevcut değil.");
  const handler = await mockYukleyici();
  mockKaydet(method, path);
  return (await handler(method, path, q, body)) as T;
}

/** Çekirdekte henüz olmayan bir işlem (kaynağı gerçek, işlem ucu yok): mock'a düşülmez. */
export const UC_YOK = "Bu işlem çekirdekte henüz yok.";

/** Canlı derlemede core'un sunmadığı ekran/uç (sonraki faz): örnek veri gösterilmez. */
export const BU_FAZDA_YOK = "Bu ekran bu fazda yok: çekirdek bu veriyi henüz sunmuyor (örnek veri gösterilmez).";

export function buFazdaYok(e: unknown): boolean {
  return (e instanceof ApiError && e.status === 501 && e.detail === BU_FAZDA_YOK) || e === BU_FAZDA_YOK;
}

export interface IstekSecenegi {
  sorgu?: Sorgu;
  govde?: unknown;
  signal?: AbortSignal;
  /**
   * İşlemin ait olduğu kaynak ucu (ör. `["GET", "/cases"]`). Kaynak çekirdekten geliyorsa bu
   * işlem ucu çekirdekte yokken örnek veriye DÜŞÜLMEZ (gerçek bir case'in örnek veride karşılığı
   * yoktur; sahte başarı gösterilmez), 501 `UC_YOK` döner. Kaynak da örnek veriyse işlem de oraya gider.
   */
  kaynak?: readonly [string, string];
  /** Yanıt JSON değil düz metindir (ör. `cases.feature`): gövde ayrıştırılmadan döner. */
  metin?: boolean;
  /** Başarılı core yanıtının başlıkları (ör. `GET /scripts` liste sınırı); örnek veride çağrılmaz. */
  basliklar?: (h: Headers) => void;
}

/**
 * Uç çağrısı. Hata `ApiError` ise uç bilgisi (method, normalleştirilmiş yol) eklenir ve son hata
 * deposuna yazılır: GET dışı hatalar hemen, GET hataları yalnızca ekranda gösterilince
 * (`HataKutusu`); `/assistant/*`, `/auth/*` ve 501 hiç yazılmaz (lib/sonHata.ts).
 */
export async function istek<T>(
  method: "GET" | "POST" | "PUT" | "DELETE",
  path: string,
  secenek: IstekSecenegi = {},
): Promise<T> {
  try {
    return await istekGonder<T>(method, path, secenek);
  } catch (e) {
    if (e instanceof ApiError) {
      e.method ??= method;
      e.yol ??= ucuNormallestir(method, path.split("?")[0]).slice(method.length + 1);
      if (method === "GET") hataAdayi(e);
      else hataKaydet(e);
    }
    throw e;
  }
}

async function istekGonder<T>(
  method: "GET" | "POST" | "PUT" | "DELETE",
  path: string,
  secenek: IstekSecenegi,
): Promise<T> {
  const q = sorguMetni(secenek.sorgu);
  if (ayarlar.mockZorunlu) {
    try {
      return await mockaDus<T>(method, path, q, secenek.govde);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401 && !path.startsWith("/auth/")) yetkisizDinleyici?.();
      throw e;
    }
  }

  // core bu ucu sunmuyorsa ağa hiç çıkmadan örnek veriye git (planlı karar, 404 değil).
  const yetenekler = await cekirdekYetenekleri();
  if (yetenekler && !ucVar(yetenekler, method, path)) {
    if (secenek.kaynak && ucVar(yetenekler, ...secenek.kaynak)) throw new ApiError(501, UC_YOK);
    if (!ayarlar.mockOtomatik) throw new ApiError(501, BU_FAZDA_YOK);
    return mockaDus<T>(method, path, q, secenek.govde);
  }

  const url = `${ayarlar.temelYol}${path}${q.toString() ? `?${q.toString()}` : ""}`;
  let res: Response;
  try {
    res = await fetch(url, {
      method,
      credentials: "same-origin",
      headers: {
        Accept: secenek.metin ? "text/plain" : "application/json",
        ...(secenek.govde !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: secenek.govde !== undefined ? JSON.stringify(secenek.govde) : undefined,
      signal: secenek.signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "Sunucuya bağlanılamadı. Ağ bağlantısını ve core-api'yi kontrol edin.");
  }
  // AI Probe kipi (`X-TP-Kimlik`) ve kimlik servisi uyarısı (`X-Aiprobe-Degraded`); local'de başlık yok.
  yanitBasliklariniOku(res, path);

  if (res.ok) {
    secenek.basliklar?.(res.headers);
    if (res.status === 204) return undefined as T;
    const metin = await res.text();
    if (secenek.metin) return metin as T;
    if (!metin) return undefined as T;
    try {
      return JSON.parse(metin) as T;
    } catch {
      throw new ApiError(res.status, "Sunucudan beklenmeyen yanıt (JSON değil).");
    }
  }

  const { detail, json, kod, ek, govde, hatalar, yolGecersiz } = await detayOku(res);
  if (res.status === 404 && ayarlar.mockOtomatik && (detail === "Not Found" || !json)) {
    // Kaynağı çekirdekten gelen bir işlem örnek veriye düşmez (bkz. IstekSecenegi.kaynak).
    if (secenek.kaynak && !mockUclar.has(ucuNormallestir(...secenek.kaynak))) throw new ApiError(501, UC_YOK);
    return mockaDus<T>(method, path, q, secenek.govde);
  }
  // Canlı derlemede genel 404 (FastAPI'de rota yok) "bu fazda yok" demektir; ham "Not Found" gösterilmez.
  if (res.status === 404 && !ayarlar.mockOtomatik && (detail === "Not Found" || !json)) throw new ApiError(501, BU_FAZDA_YOK);
  if (res.status === 401 && !path.startsWith("/auth/")) yetkisizDinleyici?.();
  // Gövde kendi kodunu taşıyorsa korunur (asistan son hata bağlamı); yoksa `gecersiz_kimlik`.
  if (res.status === 422 && yolGecersiz) throw new ApiError(404, VARSAYILAN_HATA[404], { kod: kod ?? GECERSIZ_KIMLIK });
  // Demo kipi kapalı (core 403 `demo_kapali`): genel "yetkiniz yok" yerine nedeni söylenir.
  if (kod === "demo_kapali") throw new ApiError(res.status, detail && detail !== VARSAYILAN_HATA[403] ? detail : DEMO_KAPALI, { kod, ek, govde, hatalar });
  throw new ApiError(res.status, detail ?? VARSAYILAN_HATA[res.status] ?? `Beklenmeyen hata (HTTP ${res.status}).`, { kod, ek, govde, hatalar });
}

/** core 403 `demo_kapali` iletisi (TP_DEMO_MODE=0). */
export const DEMO_KAPALI = "Demo kipi kapalı (TP_DEMO_MODE=0)";

/** Karar uçlarında 409'un kullanıcıya gösterilen hâli (içerik görüntülendikten sonra değişti). */
export const ICERIK_DEGISTI = "İçerik değişti, yeniden inceleyin.";
/** Tur 2 (Y9): 409 `oracle_kayit_degisti` — karar, analistin gördüğü kontrol kaydına bağlıdır. */
export const ORACLE_KAYIT_DEGISTI = "Kontrol sonucu siz bakarken değişti; yeniden gözden geçirin.";

/** İnsan kararı uçlarından dönen çakışma (409): ekran eski içeriği gösteriyor, yeniden yüklenmeli. */
export function kararCakismasi(e: unknown): e is ApiError {
  return e instanceof ApiError && e.status === 409;
}

/**
 * 409 mesajı: içerik hash'i tutmadıysa (core: "içerik ... değişmiş", head sha farklı) sabit
 * Türkçe metin; başka bir durum çakışmasıysa (ör. "PR açık değil", "Gereksinim karar beklemiyor")
 * yalnızca sunucunun gerekçesi — içerik değişmediği için "İçerik değişti" denmez.
 */
export function cakismaMesaji(e: ApiError): string {
  const metin = e.kod === "oracle_kayit_degisti" ? ORACLE_KAYIT_DEGISTI : /[iİ]çerik[^.]*değiş|head sha|hash/.test(e.detail) ? ICERIK_DEGISTI : e.detail;
  // Kullanıcının gördüğü metin son hata kaydına eklenir (asistan bağlamı, §5.5).
  gorunenMetinEkle(e.kayitId, metin);
  return metin;
}

/**
 * Kullanıcı metninde ortam değişkeni adı (ör. `TP_DENETIM_KAPISI`, hız sınırı ayarı) gösterilmez:
 * adı geçen cümle atılır. Geriye bir şey kalmazsa genel ama anlamlı bir metin döner.
 */
export function ortamAdiniAyikla(metin: string, yedek = "İşlem şu an yapılamıyor; yöneticinize başvurun."): string {
  if (!/\bTP_[A-Z0-9_]+/.test(metin)) return metin;
  const cumleler = metin.split(/(?<=[.;!?])\s+/).filter((c) => !/\bTP_[A-Z0-9_]+/.test(c));
  const kalan = cumleler.join(" ").trim();
  return kalan || yedek;
}

/** Son kullanıcı metninde gizlenen ortam değişkeni adları (TP_*, entegrasyon kimlikleri). */
const ORTAM_ADI = /`?\b(?:TP|GITHUB|JIRA|XRAY|ANTHROPIC|SAUCE)_[A-Z0-9_]+(?:=[^\s,;)`]+)?`?/g;

/**
 * Metni bozmadan ortam değişkeni adlarını gizler (B16): denetim kaydı özeti, yol haritası kanıtı
 * gibi cümlenin atılamayacağı yerler için (`ortamAdiniAyikla` cümleyi atar). Parantez başındaki
 * ad atılır ("(TP_REPLAY_STRICT=1, prova kipi)" → "(prova kipi)"), içi boşalan parantez silinir,
 * cümle içindeki ad "bir sunucu ayarı" olur.
 */
export function ortamAdlariniGizle(metin: string): string {
  if (!metin || !new RegExp(ORTAM_ADI.source).test(metin)) return metin;
  return metin
    .replace(new RegExp(`\\(\\s*\\+?\\s*(?:salt okunur\\s+)?(?:${ORTAM_ADI.source})\\s*[,;]?\\s*`, "g"), "(")
    .replace(/\s*\(\s*[+,;:-]?\s*\)/g, "")
    .replace(ORTAM_ADI, "bir sunucu ayarı")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/\s+([.,;:!?])/g, "$1");
}

export function hataMesaji(e: unknown): string {
  if (e instanceof ApiError) {
    // D1: 429 `hiz_siniri` ("Bu gereksinim için son 24 saatte en çok N review|denetim…").
    if (e.status === 429 || e.kod === "hiz_siniri") return ortamAdiniAyikla(e.detail, "Bu işlem için kısa sürede çok fazla istek gönderildi; daha sonra yeniden deneyin.");
    return ortamAdiniAyikla(e.detail);
  }
  if (e instanceof Error) return e.message;
  return "Beklenmeyen bir hata oluştu.";
}
