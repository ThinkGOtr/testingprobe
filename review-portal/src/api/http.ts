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
// VITE_MOCK=0 ile derlenmişse 2 ve 3 kapalıdır: her istek core'a gider.
// Mock'tan gelen her veri arayüzde "ÖRNEK VERİ" olarak etiketlenir (sahte canlı gösterim yok).

import type { Kullanici } from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
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
  if (ayarlar.mockZorunlu || !ayarlar.mockOtomatik || !ayarlar.yetenekKesfi) return Promise.resolve(null);
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

async function detayOku(res: Response): Promise<{ detail: string | null; json: boolean }> {
  const metin = await res.text().catch(() => "");
  if (!metin) return { detail: null, json: false };
  try {
    const govde = JSON.parse(metin) as unknown;
    if (govde && typeof govde === "object" && "detail" in govde) {
      const d = (govde as { detail: unknown }).detail;
      if (typeof d === "string") return { detail: d, json: true };
      // FastAPI doğrulama hataları: [{loc, msg, type}]
      if (Array.isArray(d)) {
        const mesajlar = d
          .map((x) => (x && typeof x === "object" && "msg" in x ? String((x as { msg: unknown }).msg) : ""))
          .filter(Boolean);
        return { detail: mesajlar.join("; ") || "Geçersiz istek", json: true };
      }
    }
    return { detail: null, json: true };
  } catch {
    return { detail: null, json: false };
  }
}

const VARSAYILAN_HATA: Record<number, string> = {
  400: "İstek geçersiz.",
  401: "Oturum açmanız gerekiyor.",
  403: "Bu işlem için yetkiniz yok.",
  404: "Kayıt bulunamadı.",
  409: "İşlem mevcut durumla çakışıyor.",
  422: "Gönderilen veri doğrulanamadı.",
  429: "Çok fazla istek; biraz sonra tekrar deneyin.",
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

export async function istek<T>(
  method: "GET" | "POST",
  path: string,
  secenek: { sorgu?: Sorgu; govde?: unknown; signal?: AbortSignal } = {},
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
    return mockaDus<T>(method, path, q, secenek.govde);
  }

  const url = `${ayarlar.temelYol}${path}${q.toString() ? `?${q.toString()}` : ""}`;
  let res: Response;
  try {
    res = await fetch(url, {
      method,
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(secenek.govde !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: secenek.govde !== undefined ? JSON.stringify(secenek.govde) : undefined,
      signal: secenek.signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "Sunucuya bağlanılamadı. Ağ bağlantısını ve core-api'yi kontrol edin.");
  }

  if (res.ok) {
    if (res.status === 204) return undefined as T;
    const metin = await res.text();
    if (!metin) return undefined as T;
    try {
      return JSON.parse(metin) as T;
    } catch {
      throw new ApiError(res.status, "Sunucudan beklenmeyen yanıt (JSON değil).");
    }
  }

  const { detail, json } = await detayOku(res);
  if (res.status === 404 && ayarlar.mockOtomatik && (detail === "Not Found" || !json)) {
    return mockaDus<T>(method, path, q, secenek.govde);
  }
  if (res.status === 401 && !path.startsWith("/auth/")) yetkisizDinleyici?.();
  throw new ApiError(res.status, detail ?? VARSAYILAN_HATA[res.status] ?? `Beklenmeyen hata (HTTP ${res.status}).`);
}

/** Karar uçlarında 409'un kullanıcıya gösterilen hâli (içerik görüntülendikten sonra değişti). */
export const ICERIK_DEGISTI = "İçerik değişti, yeniden inceleyin.";

/** İnsan kararı uçlarından dönen çakışma (409): ekran eski içeriği gösteriyor, yeniden yüklenmeli. */
export function kararCakismasi(e: unknown): e is ApiError {
  return e instanceof ApiError && e.status === 409;
}

/**
 * 409 mesajı: içerik hash'i tutmadıysa (core: "içerik ... değişmiş", head sha farklı) sabit
 * Türkçe metin; başka bir durum çakışmasıysa (ör. "PR açık değil") metin + sunucunun gerekçesi.
 */
export function cakismaMesaji(e: ApiError): string {
  if (/[iİ]çerik[^.]*değiş|head sha|hash/.test(e.detail)) return ICERIK_DEGISTI;
  return `${ICERIK_DEGISTI} ${e.detail}`;
}

export function hataMesaji(e: unknown): string {
  if (e instanceof ApiError) return e.detail;
  if (e instanceof Error) return e.message;
  return "Beklenmeyen bir hata oluştu.";
}
