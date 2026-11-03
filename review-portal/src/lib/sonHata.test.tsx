// Son hata deposu (AI-ASISTAN-PLANI §5.5): GET dışı hatalar hemen, GET hataları yalnız
// HataKutusu gösterince yazılır; /assistant/*, /auth/* ve 501 hiç yazılmaz; mock-zorunlu dalda da
// çalışır; 5 dk geçerli; gösterilen metin eklenir; ApiError kod/method/yol/kayitId taşır.
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { ApiError, BU_FAZDA_YOK, cakismaMesaji, detayOku, ICERIK_DEGISTI, istek, yapilandir } from "../api/http";
import { HataKutusu } from "../components/ui";
import { oturumAc } from "../test/yardimci";
import { OturumProvider } from "../auth";
import {
  hataAdayi,
  hataGosterildi,
  hataKaydet,
  hataKaydi,
  SON_HATA_GECERLILIK_MS,
  sonHata,
  sonHataBaglami,
  sonHatayiSifirla,
} from "./sonHata";

function yanit(status: number, govde: unknown): Response {
  return new Response(JSON.stringify(govde), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => sonHatayiSifirla());
afterEach(() => vi.unstubAllGlobals());

describe("ApiError ek alanları", () => {
  it("eski iki argümanlı çağrı derlenir; kayitId her hatada üretilir ve tekildir", () => {
    const a = new ApiError(409, "x");
    const b = new ApiError(409, "x");
    expect(a.kayitId).toMatch(/^h-/);
    expect(a.kayitId).not.toBe(b.kayitId);
    expect(a.kod).toBeUndefined();
    const c = new ApiError(409, "y", { kod: "bekleyen_var", method: "POST", yol: "/x/:id", kayitId: "sabit" });
    expect(c).toMatchObject({ kod: "bekleyen_var", method: "POST", yol: "/x/:id", kayitId: "sabit" });
  });

  it("detayOku yanıttaki kod'u okur (detail dizisi ve kodsuz gövde dahil)", async () => {
    expect(await detayOku(yanit(409, { detail: "Bekleyen var", kod: "bekleyen_var" }))).toEqual({ detail: "Bekleyen var", json: true, kod: "bekleyen_var" });
    expect(await detayOku(yanit(422, { detail: [{ msg: "çok uzun" }], kod: "gecersiz_istek" }))).toMatchObject({ detail: "çok uzun", kod: "gecersiz_istek" });
    expect((await detayOku(yanit(400, { detail: "x" }))).kod).toBeUndefined();
  });

  it("gerçek modda hata kod, method ve normalleştirilmiş yolu taşır", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false });
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(yanit(409, { detail: "Onay hash'i uyuşmuyor", kod: "onay_hash_uyusmuyor" }))));
    const e = await istek("POST", "/cases/3f2a9c10/review", { govde: {} }).catch((x: unknown) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect(e).toMatchObject({ status: 409, kod: "onay_hash_uyusmuyor", method: "POST", yol: "/cases/:id/review" });
  });
});

describe("istek → son hata deposu", () => {
  it("GET dışı hata hemen yazılır (uç, durum, kod)", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false });
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(yanit(409, { detail: "İçerik değişti", kod: "cakisma" }))));
    const e = (await istek("POST", "/cases/c1/review", { govde: {} }).catch((x: unknown) => x)) as ApiError;
    const k = sonHata();
    expect(k).toMatchObject({ kayitId: e.kayitId, uc: "POST /cases/:id/review", status: 409, kod: "cakisma", detail: "İçerik değişti" });
  });

  it("GET hatası gösterilmeden yazılmaz; HataKutusu gösterince yazılır ve görünen metni eklenir", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false });
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(yanit(403, { detail: "Yetkiniz yok" }))));
    const e = await istek("GET", "/runs").catch((x: unknown) => x);
    expect(sonHata()).toBeNull();
    render(<HataKutusu hata="Yetkiniz yok" kaynak={e} />);
    expect(sonHata()).toMatchObject({ uc: "GET /runs", status: 403, gorunen_metin: "Yetkiniz yok" });
  });

  it("kaynaksız HataKutusu aynı metinli GET adayını bulur; yoksa yalnız metinden kayıt açar", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false });
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(yanit(500, { detail: "Sunucu hatası" }))));
    await istek("GET", "/control-tower").catch(() => undefined);
    const { unmount } = render(<HataKutusu hata="Sunucu hatası" />);
    expect(sonHata()).toMatchObject({ uc: "GET /control-tower", status: 500 });
    unmount();
    render(<HataKutusu hata="Bilinmeyen bir sorun" />);
    expect(sonHata()).toMatchObject({ uc: null, status: null, detail: "Bilinmeyen bir sorun" });
  });

  it("/assistant/* uçları, /auth/* ve 501 'bu fazda yok' hiç yazılmaz", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false });
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(yanit(409, { detail: "Bekleyen var", kod: "bekleyen_var" }))));
    await istek("POST", "/assistant/conversations/s1/messages", { govde: {} }).catch(() => undefined);
    await istek("POST", "/auth/login", { govde: {} }).catch(() => undefined);
    expect(sonHata()).toBeNull();
    const bfy = new ApiError(501, BU_FAZDA_YOK, { method: "GET", yol: "/control-tower" });
    hataAdayi(bfy);
    render(<HataKutusu hata={BU_FAZDA_YOK} kaynak={bfy} />);
    expect(sonHata()).toBeNull();
    hataKaydet(new ApiError(501, "x", { method: "POST", yol: "/demo/break-locator" }));
    expect(sonHata()).toBeNull();
  });

  it("mock-zorunlu dalda da GET dışı hata yazılır", async () => {
    yapilandir({ mockZorunlu: true });
    await oturumAc("testci");
    // Testçi PO onayı veremez: mock rol hatası atar.
    const e = (await istek("POST", "/requirements/req-1/po-approve", { govde: {} }).catch((x: unknown) => x)) as ApiError;
    expect(e).toBeInstanceOf(ApiError);
    expect(sonHata()).toMatchObject({ kayitId: e.kayitId, uc: "POST /requirements/:id/po-approve", status: e.status });
  });

  it("kayıt 5 dakika geçerlidir", () => {
    const t0 = 1_000_000;
    hataKaydet(new ApiError(409, "x", { method: "POST", yol: "/a" }), t0);
    expect(sonHata(t0 + SON_HATA_GECERLILIK_MS)).not.toBeNull();
    expect(sonHata(t0 + SON_HATA_GECERLILIK_MS + 1)).toBeNull();
    const id = sonHata(t0)!.kayitId;
    expect(hataKaydi(id, t0 + SON_HATA_GECERLILIK_MS + 1)).toBeNull();
    expect(sonHataBaglami(sonHata(t0)!, t0 + 42_000)).toMatchObject({ uc: "POST /a", status: 409, yas_s: 42 });
  });

  it("cakismaMesaji gösterilen metni kayitId üzerinden ekler", () => {
    const e = new ApiError(409, "İçerik siz görüntüledikten sonra değişmiş", { method: "POST", yol: "/cases/:id/review" });
    hataKaydet(e);
    expect(cakismaMesaji(e)).toBe(ICERIK_DEGISTI);
    expect(sonHata()).toMatchObject({ kayitId: e.kayitId, gorunen_metin: ICERIK_DEGISTI });
  });

  it("hataGosterildi aynı kaydı ikinci kez yazmaz, kimliği döndürür", () => {
    const e = new ApiError(400, "x", { method: "POST", yol: "/a" });
    hataKaydet(e);
    expect(hataGosterildi(e, "x")).toBe(e.kayitId);
    expect(hataGosterildi(e, "x")).toBe(e.kayitId);
    expect(hataGosterildi(undefined, null)).toBeNull();
  });
});

describe("client.ts 404 dönüşümü", () => {
  it("api.hata 422 → 404 'bulunamadı' dönüşümü kayitId'yi korur", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false });
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(yanit(422, { detail: [{ msg: "Input should be a valid UUID" }], kod: "gecersiz_istek" }))));
    const e = (await api.hata("abc").catch((x: unknown) => x)) as ApiError;
    expect(e.status).toBe(404);
    expect(e.kod).toBe("gecersiz_istek");
    expect(e.yol).toBe("/failures/abc");
    // Gösterilince depodaki GET adayı (aynı kimlik) kayda döner.
    render(
      <MemoryRouter>
        <OturumProvider>
          <HataKutusu hata={e.detail} kaynak={e} />
        </OturumProvider>
      </MemoryRouter>,
    );
    expect(sonHata()).toMatchObject({ kayitId: e.kayitId, uc: "GET /failures/abc", gorunen_metin: e.detail });
  });
});
