// `api.hata`: geçersiz kimlik (core 422 pydantic metni) → "bulunamadı"; core triage yanıtı onarım
// kaydını zaten katıyorsa (`oneri_durumu`) ayrı `GET /failures/{id}/fix` çağrılmaz (404 konsol hatası yok).
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, HATA_BULUNAMADI } from "./client";
import { yapilandir } from "./http";

function yanit(status: number, govde: unknown): Response {
  return new Response(JSON.stringify(govde), { status, headers: { "Content-Type": "application/json" } });
}

const TRIAGE = {
  id: "11111111-1111-1111-1111-111111111111",
  run_id: "r1",
  test_adi: "t",
  sinif: "test_maintenance",
  oneri_durumu: "none",
  oneri: { tur: "locator_fix", eski_test_id: "add-to-cart", yeni_test_id: "cart-add", pr: null, dogrulama: [] },
  kanit_linkleri: [],
};

describe("api.hata", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("core oneri_durumu gönderiyorsa GET /fix çağrılmaz", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false });
    const f = vi.fn().mockImplementation(() => Promise.resolve(yanit(200, TRIAGE)));
    vi.stubGlobal("fetch", f);
    const h = await api.hata(TRIAGE.id);
    expect(h.oneri).toMatchObject({ tur: "locator_fix", eski_test_id: "add-to-cart" });
    expect(f.mock.calls.map((c) => c[0])).toEqual([`/api/failures/${TRIAGE.id}`]);
  });

  it("geçersiz kimlik (422) ve yok (404) → Türkçe 'bulunamadı'", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => Promise.resolve(yanit(422, { detail: [{ loc: ["path", "failure_id"], msg: "Input should be a valid UUID" }] }))),
    );
    await expect(api.hata("abc")).rejects.toMatchObject({ status: 404, detail: HATA_BULUNAMADI });
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(yanit(404, { detail: "Başarısızlık bulunamadı" }))));
    await expect(api.hata(TRIAGE.id)).rejects.toMatchObject({ status: 404, detail: HATA_BULUNAMADI });
  });
});
