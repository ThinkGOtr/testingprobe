// 009: kanıt dosyası okuyucu — yalnızca core artefakt ucu / data:, boyut sınırı, hata metinleri.
import { afterEach, describe, expect, it, vi } from "vitest";
import { artefaktMetniOku, okunabilirArtefakt } from "./artefakt";

afterEach(() => {
  vi.unstubAllGlobals();
});

function akisYaniti(parcalar: string[], status = 200): Response {
  const enc = new TextEncoder();
  const govde = new ReadableStream<Uint8Array>({
    start(c) {
      for (const p of parcalar) c.enqueue(enc.encode(p));
      c.close();
    },
  });
  return new Response(govde, { status });
}

describe("artefaktMetniOku", () => {
  it("yalnızca core artefakt ucu ve data: okunur; başka adres ağa çıkmaz", async () => {
    expect(okunabilirArtefakt("/api/artifacts/runs/r1/target/kanit/A.b/sayfa-kaynagi.xml")).toBe(true);
    expect(okunabilirArtefakt("data:application/xml;base64,PGEvPg==")).toBe(true);
    expect(okunabilirArtefakt("https://ornek.test/x.xml")).toBe(false);
    expect(okunabilirArtefakt("/api/artifacts/runs/../../etc")).toBe(false);
    expect(okunabilirArtefakt("/api/artifacts/%2E%2e/requirements")).toBe(false);
    expect(okunabilirArtefakt("/api/requirements")).toBe(false);
    expect(okunabilirArtefakt(null)).toBe(false);
    const f = vi.fn();
    vi.stubGlobal("fetch", f);
    await expect(artefaktMetniOku("https://ornek.test/x.xml")).rejects.toThrow(/okunamaz/);
    expect(f).not.toHaveBeenCalled();
  });

  it("data: (base64 ve yüzde kodlu) yerelde çözülür; Türkçe karakter korunur", async () => {
    const b64 = btoa(String.fromCharCode(...new TextEncoder().encode("<a>Giriş</a>")));
    expect((await artefaktMetniOku(`data:application/xml;base64,${b64}`)).metin).toBe("<a>Giriş</a>");
    expect((await artefaktMetniOku(`data:text/plain,${encodeURIComponent("<b>ş</b>")}`)).metin).toBe("<b>ş</b>");
    await expect(artefaktMetniOku("data:text/plain,%E0%A4%A")).rejects.toThrow("Kanıt adresi çözülemedi.");
  });

  it("boyut sınırında kesilir ve işaretlenir", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => akisYaniti(["0123456789", "abcdefghij", "KLMNOPQRST"])));
    const r = await artefaktMetniOku("/api/artifacts/runs/r1/kaynak.xml", { sinir: 15 });
    expect(r).toEqual({ metin: "0123456789abcde", kesildi: true, bayt: 15 });
    vi.stubGlobal("fetch", vi.fn(async () => akisYaniti(["<x/>"])));
    expect(await artefaktMetniOku("/api/artifacts/runs/r1/kaynak.xml", { sinir: 15 })).toEqual({ metin: "<x/>", kesildi: false, bayt: 4 });
  });

  it("aynı köken + çerez ile istenir; 404 ve ağ hatası Türkçe", async () => {
    const f = vi.fn(async () => new Response("yok", { status: 404 }));
    vi.stubGlobal("fetch", f);
    await expect(artefaktMetniOku("/api/artifacts/runs/r1/k.xml")).rejects.toThrow(/bulunamadı/);
    expect(f).toHaveBeenCalledWith("/api/artifacts/runs/r1/k.xml", expect.objectContaining({ credentials: "same-origin" }));
    vi.stubGlobal("fetch", vi.fn(async () => new Response("x", { status: 500 })));
    await expect(artefaktMetniOku("/api/artifacts/runs/r1/k.xml")).rejects.toThrow(/HTTP 500/);
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("ağ"))));
    await expect(artefaktMetniOku("/api/artifacts/runs/r1/k.xml")).rejects.toThrow(/ulaşılamadı/);
  });
});
