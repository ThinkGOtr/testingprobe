// AI Probe ortak kimliği (TEKNIK-TASARIM §8.14, specs/010-aiprobe-sso T040–T043).
//
// Portal kimlik kipini ayrı bir istek atmadan öğrenir: core `TP_AUTH_MODE=aiprobe|both` iken her
// yanıta `X-TP-Kimlik: kip=aiprobe; home=https://…; urun=testing-probe` ekler (401 dahil). `local`
// kipte başlık hiç gelmez; portal bugünkü gibi davranır (yerel giriş formu, değiştirici yok).
// `X-Aiprobe-Degraded: 1`: core AI Probe kimlik servisine ulaşamadı, oturum korundu (uyarı bandı).

import { useSyncExternalStore } from "react";

export type Kip = "local" | "aiprobe" | "both";

export interface KimlikKipi {
  kip: Kip;
  /** AI Probe başlangıç (home) adresi; değiştirici kataloğu ve çıkış sayfası buradan. */
  home: string | null;
  /** AI Probe katalogundaki ürün kimliği (`testing-probe`). */
  urun: string;
}

const YEREL: KimlikKipi = { kip: "local", home: null, urun: "testing-probe" };
const ORIGIN = /^(https:\/\/[a-z0-9.-]+(:\d+)?|http:\/\/(localhost|127\.0\.0\.1)(:\d+)?)$/;

let kipDurumu: KimlikKipi = YEREL;
let bozuk = false;
const dinleyiciler = new Set<() => void>();

function bildir(): void {
  dinleyiciler.forEach((fn) => fn());
}

function abone(fn: () => void): () => void {
  dinleyiciler.add(fn);
  return () => dinleyiciler.delete(fn);
}

/** `X-TP-Kimlik` değerini ayrıştırır; tanınmayan değer `local` sayılır (güvenli varsayılan). */
export function kimlikBasligiAyristir(deger: string | null | undefined): KimlikKipi {
  if (!deger) return YEREL;
  const alanlar = new Map<string, string>();
  for (const parca of deger.split(";")) {
    const [a, ...b] = parca.split("=");
    if (a && b.length) alanlar.set(a.trim().toLowerCase(), b.join("=").trim());
  }
  const kip = alanlar.get("kip");
  if (kip !== "aiprobe" && kip !== "both") return YEREL;
  const home = alanlar.get("home")?.toLowerCase().replace(/\/+$/, "") ?? "";
  const urun = alanlar.get("urun") ?? "";
  return { kip, home: ORIGIN.test(home) ? home : null, urun: /^[a-z0-9-]{1,64}$/.test(urun) ? urun : YEREL.urun };
}

function esit(a: KimlikKipi, b: KimlikKipi): boolean {
  return a.kip === b.kip && a.home === b.home && a.urun === b.urun;
}

/**
 * Her core yanıtında çağrılır (api/http.ts). Kip başlığı yanıtta yoksa da `local` sayılır: core
 * `local`'e dönerse portal da döner. `X-Aiprobe-Degraded` yalnız kullanıcı oturumunu doğrulayan
 * yanıtlarda anlamlıdır; `/auth/*` (giriş, çıkış) yanıtları bandı değiştirmez (`/auth/me` hariç).
 */
export function yanitBasliklariniOku(res: Pick<Response, "headers" | "ok">, yol: string): void {
  const basliklar = res.headers as Headers | undefined;
  if (!basliklar || typeof basliklar.get !== "function") return;
  const yeni = kimlikBasligiAyristir(basliklar.get("X-TP-Kimlik"));
  let degisti = false;
  if (!esit(yeni, kipDurumu)) {
    kipDurumu = yeni;
    degisti = true;
  }
  const yolYalin = yol.split("?")[0];
  if (res.ok && (!yolYalin.startsWith("/auth/") || yolYalin === "/auth/me")) {
    const b = yeni.kip !== "local" && basliklar.get("X-Aiprobe-Degraded") === "1";
    if (b !== bozuk) {
      bozuk = b;
      degisti = true;
    }
  }
  if (degisti) bildir();
}

export function kimlikKipi(): KimlikKipi {
  return kipDurumu;
}

export function aiprobeKipinde(): boolean {
  return kipDurumu.kip !== "local";
}

export function useKimlikKipi(): KimlikKipi {
  return useSyncExternalStore(abone, () => kipDurumu);
}

/** AI Probe kimlik servisine ulaşılamıyor mu (son kullanıcı isteğinde `X-Aiprobe-Degraded: 1`)? */
export function useKimlikServisiErisilemez(): boolean {
  return useSyncExternalStore(abone, () => bozuk);
}

/** Testler için: kipi ve uyarıyı sıfırlar ya da verilen değere ayarlar. */
export function kimlikKipiniAyarla(k: Partial<KimlikKipi> | null, erisilemez = false): void {
  kipDurumu = k ? { ...YEREL, ...k } : YEREL;
  bozuk = erisilemez;
  bildir();
}

/** Portal içi yol: yalnız `/` ile başlayan göreli yol (core `guvenli_continue` ile aynı kural). */
export function guvenliDevam(yol: string | null | undefined): string {
  if (!yol || yol.length > 2048) return "/";
  if (!yol.startsWith("/") || yol.startsWith("//") || yol.includes("\\") || /[\x00-\x1f\x7f]/.test(yol)) return "/";
  if (yol.split(/[?#]/, 1)[0].includes(":")) return "/";
  return yol;
}

/** AI Probe giriş ucu (portal önekiyle; core `continue`'yu ayrıca doğrular). */
export function aiprobeGirisAdresi(devam: string | null | undefined): string {
  return `/api/auth/aiprobe/login?continue=${encodeURIComponent(guvenliDevam(devam))}`;
}

/**
 * AI Probe çıkış sayfası (core çıkış yanıtında `redirect` yoksa yedek). `auto=1`: yerel çıkış
 * yapıldı, home onay tıklaması istemeden tüm ürünlerden çıkarır.
 */
export function aiprobeCikisAdresi(): string | null {
  const { home, urun } = kipDurumu;
  return home ? `${home}/logout?product=${encodeURIComponent(urun)}&auto=1` : null;
}

/**
 * Çıkış yanıtındaki `redirect` yalnız AI Probe kökeninde (ya da aynı kökende) https adresiyse
 * izlenir; başka her değer yok sayılır (açık yönlendirme yok).
 */
export function cikisYonlendirmesi(redirect: unknown): string | null {
  if (typeof redirect !== "string" || !redirect) return null;
  try {
    const u = new URL(redirect, window.location.origin);
    const izinli = new Set([window.location.origin, kipDurumu.home].filter(Boolean));
    if (!izinli.has(u.origin)) return null;
    if (u.protocol !== "https:" && !/^(localhost|127\.0\.0\.1)$/.test(u.hostname)) return null;
    return u.href;
  } catch {
    return null;
  }
}

// ------------------------------------------------------------ yönlendirme döngüsü koruması

const DONGU_ANAHTARI = "tp-aiprobe-yonlendirme";
const DONGU_PENCERE_MS = 60_000;
const DONGU_SINIRI = 3;

/**
 * Girişten dönüşte oturum yine açılamıyorsa (ör. çerez yazılamadı) portal ile AI Probe girişi
 * arasında sonsuz yönlendirme olmasın: 60 sn'de 3'ten fazla yönlendirme yapılmaz. Kayıt
 * yoksa/okunamazsa izin verilir.
 */
export function yonlendirmeyeIzinVar(simdi = Date.now()): boolean {
  let gecmis: number[] = [];
  try {
    const ham = sessionStorage.getItem(DONGU_ANAHTARI);
    const dizi: unknown = ham ? JSON.parse(ham) : [];
    if (Array.isArray(dizi)) gecmis = dizi.filter((t): t is number => typeof t === "number" && simdi - t < DONGU_PENCERE_MS);
  } catch {
    gecmis = [];
  }
  if (gecmis.length >= DONGU_SINIRI) return false;
  try {
    sessionStorage.setItem(DONGU_ANAHTARI, JSON.stringify([...gecmis, simdi]));
  } catch {
    /* depolama yok: koruma yok, yönlendirme yapılır */
  }
  return true;
}

/** Oturum açıldı: döngü sayacı sıfırlanır. */
export function yonlendirmeSayaciniSifirla(): void {
  try {
    sessionStorage.removeItem(DONGU_ANAHTARI);
  } catch {
    /* yok say */
  }
}

/** Tam sayfa gezinti (testte değiştirilebilir). */
export const gezinti = {
  git(url: string): void {
    window.location.assign(url);
  },
};
