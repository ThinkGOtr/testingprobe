// API istemcisi. Tüm çağrılar aynı origin'de /api önekiyle yapılır (nginx / vite proxy).
// Oturum HttpOnly çerezdedir; tarayıcı otomatik gönderir.

export interface User {
  kullanici_adi: string;
  ad: string;
}

export interface Product {
  kod: string;
  ad: string;
  fiyat: string;
  kampanya: string | null;
}

export interface CartLine {
  urun_kod: string;
  urun_ad: string;
  birim_fiyat: string;
  adet: number;
  kampanya: string | null;
  bedava_adet: number;
  ucretli_adet: number;
  ara_tutar: string;
  indirim: string;
  satir_tutari: string;
}

export interface Warning {
  kod: string;
  mesaj: string;
}

export interface Cart {
  satirlar: CartLine[];
  adet_toplam: number;
  ara_toplam: string;
  indirim: string;
  toplam: string;
  min_siparis_tutari: string;
  min_siparis_saglandi: boolean;
  onaylanabilir: boolean;
  uyarilar: Warning[];
}

export interface OrderSummary {
  numara: string;
  olusturma: string;
  adet_toplam: number;
  ara_toplam: string;
  indirim: string;
  toplam: string;
}

export interface OrderLine {
  urun_kod: string;
  urun_ad: string;
  birim_fiyat: string;
  adet: number;
  bedava_adet: number;
  satir_tutari: string;
}

export interface Order extends OrderSummary {
  satirlar: OrderLine[];
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type UnauthorizedHandler = () => void;
let onUnauthorized: UnauthorizedHandler = () => {};

/** 401 alındığında çağrılır (oturum düştü → giriş ekranı). */
export function setUnauthorizedHandler(handler: UnauthorizedHandler): void {
  onUnauthorized = handler;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`/api${path}`, {
      method,
      credentials: "same-origin",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Sunucuya ulaşılamadı. Lütfen tekrar deneyin.");
  }
  if (resp.status === 204) return undefined as T;
  const data: unknown = await resp.json().catch(() => null);
  if (!resp.ok) {
    if (resp.status === 401 && path !== "/auth/login") onUnauthorized();
    throw new ApiError(resp.status, errorMessage(data, resp.status));
  }
  return data as T;
}

function errorMessage(data: unknown, status: number): string {
  if (data && typeof data === "object" && "detail" in data) {
    const detail = (data as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return "Girilen değer geçersiz.";
  }
  return status >= 500 ? "Beklenmeyen bir hata oluştu." : `İstek başarısız (${status}).`;
}

export const api = {
  login: (kullanici_adi: string, parola: string) =>
    request<User>("POST", "/auth/login", { kullanici_adi, parola }),
  logout: () => request<void>("POST", "/auth/logout"),
  me: () => request<User>("GET", "/auth/me"),
  /** Oturum yoklaması: oturum yoksa 200 + null döner (401 → tarayıcı konsol hatası üretmez). */
  session: () =>
    request<{ oturum: User | null }>("GET", "/auth/session").then((r) => r.oturum),
  products: () => request<Product[]>("GET", "/products"),
  cart: () => request<Cart>("GET", "/cart"),
  addToCart: (urun_kod: string, adet: number) =>
    request<Cart>("POST", "/cart/lines", { urun_kod, adet }),
  removeLine: (urun_kod: string) =>
    request<Cart>("DELETE", `/cart/lines/${encodeURIComponent(urun_kod)}`),
  checkout: () => request<Order>("POST", "/orders"),
  orders: () => request<OrderSummary[]>("GET", "/orders"),
  order: (numara: string) => request<Order>("GET", `/orders/${encodeURIComponent(numara)}`),
};
