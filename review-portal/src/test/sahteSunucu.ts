// Gerçek mod (VITE_MOCK=0) testleri için yol tabanlı fetch sahtesi + EventSource sahtesi.
import { vi } from "vitest";
import { yapilandir } from "../api/http";

export interface SahteCevap {
  status?: number;
  govde?: unknown;
  basliklar?: Record<string, string>;
}

export type SahteYol = SahteCevap | ((init: RequestInit) => SahteCevap);

/** `X-TP-Kimlik` başlıkları (core `api/kimlik_kipi.py` biçimi). */
export const AIPROBE_KIPI = { "X-TP-Kimlik": "kip=aiprobe; home=https://home.test; urun=testing-probe" };
export const BOTH_KIPI = { "X-TP-Kimlik": "kip=both; home=https://home.test; urun=testing-probe" };

class SahteEventSource {
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: (() => void) | null = null;
  addEventListener(): void {}
  removeEventListener(): void {}
  close(): void {}
}

/**
 * `"<METHOD> <yol>"` → cevap. Listede olmayan uç FastAPI'nin genel 404'ünü döner (canlı derlemede
 * "bu fazda yok"). `ortak` başlıklar her yanıta eklenir (core'un `X-TP-Kimlik` ara katmanı gibi).
 */
export function sahteSunucu(yollar: Record<string, SahteYol>, ortak: Record<string, string> = {}) {
  yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: false });
  vi.stubGlobal("EventSource", SahteEventSource);
  const f = vi.fn((url: string, init: RequestInit = {}) => {
    const yol = url.replace(/^\/api/, "").split("?")[0];
    const giris = yollar[`${init.method ?? "GET"} ${yol}`];
    const c = typeof giris === "function" ? giris(init) : (giris ?? { status: 404, govde: { detail: "Not Found" } });
    return Promise.resolve(
      new Response(JSON.stringify(c.govde ?? {}), {
        status: c.status ?? 200,
        headers: { "Content-Type": "application/json", ...ortak, ...c.basliklar },
      }),
    );
  });
  vi.stubGlobal("fetch", f);
  return f;
}

export function cagrildi(f: ReturnType<typeof sahteSunucu>, method: string, yol: string): RequestInit[] {
  return f.mock.calls
    .filter(([url, init]) => url.replace(/^\/api/, "").split("?")[0] === yol && ((init as RequestInit | undefined)?.method ?? "GET") === method)
    .map(([, init]) => (init ?? {}) as RequestInit);
}
