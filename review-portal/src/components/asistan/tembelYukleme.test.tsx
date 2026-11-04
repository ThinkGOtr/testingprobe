// Asistan paneli içeriğinin kod bölmesi: Sohbet / Öneriler sekmeleri (ve cevap/öneri kartları) panel
// kapalıyken ana pakete girmez, ilk açılışta yüklenir. Diğer testler içeriği önceden yükler
// (test/setup.ts); burada taze modül kaydıyla yükleme anı sınanır: erişilebilir yer tutucu, sonra içerik.
// Oturum temizliği (AI-ASISTAN-PLANI §16 madde 1) içerik hiç yüklenmeden de kayıtlı anahtarları siler.
import { act, fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import kaynak from "./AsistanPaneli.tsx?raw";

describe("asistan paneli içeriği ayrı parçada (kod bölme)", () => {
  it("AsistanPaneli içerik modüllerini statik içe aktarmaz (yalnız tip)", () => {
    const statik = /^import\s+(?!type\b)[^;]*?from\s+"\.\/(SohbetSekmesi|OnerilerSekmesi|CevapKarti|OneriKarti|OneriEkOneriler)"/m;
    expect(kaynak).not.toMatch(statik);
  });

  it("ilk açılışta erişilebilir yer tutucu, içerik yüklenince Sohbet çizilir; sonraki açılış askıya almaz", async () => {
    vi.resetModules();
    const http = await import("../../api/http");
    http.yapilandir({ mockZorunlu: true, mockOtomatik: true, yetenekKesfi: false });
    const { oturumAc, sar } = await import("../../test/yardimci");
    const { AsistanPaneli } = await import("./AsistanPaneli");
    const { paneliKapat } = await import("./kontrol");
    await oturumAc("analist");
    sar(<AsistanPaneli />, { yol: "/kosular" });

    fireEvent.click(await screen.findByRole("button", { name: "Asistanı aç" }));
    const panel = screen.getByTestId("asistan-paneli");
    expect(within(panel).getByRole("status")).toHaveTextContent("Asistan yükleniyor…");
    expect(await within(panel).findByLabelText("Sorunuz")).toBeInTheDocument();
    expect(within(panel).queryByText("Asistan yükleniyor…")).toBeNull();

    act(() => paneliKapat());
    fireEvent.click(await screen.findByRole("button", { name: "Asistanı aç" }));
    expect(within(screen.getByTestId("asistan-paneli")).getByLabelText("Sorunuz")).toBeInTheDocument();
  });

  it("parça yüklenemezse uygulama düşmez: panelde hata ve 'Yeniden dene' içeriği yeniden ister", async () => {
    vi.resetModules();
    vi.doMock("./SohbetSekmesi", () => {
      throw new Error("parça yok");
    });
    const konsol = vi.spyOn(console, "error").mockImplementation(() => undefined);
    try {
      const http = await import("../../api/http");
      http.yapilandir({ mockZorunlu: true, mockOtomatik: true, yetenekKesfi: false });
      const { oturumAc, sar } = await import("../../test/yardimci");
      const { AsistanPaneli } = await import("./AsistanPaneli");
      await oturumAc("analist");
      sar(<AsistanPaneli />, { yol: "/kosular" });
      fireEvent.click(await screen.findByRole("button", { name: "Asistanı aç" }));
      const uyari = await within(screen.getByTestId("asistan-paneli")).findByRole("alert");
      expect(uyari).toHaveTextContent("Asistan yüklenemedi");
      // Başlık ve kapatma düğmesi yerinde: panel (ve uygulama) çizili kalır.
      expect(screen.getByRole("button", { name: "Asistanı kapat" })).toBeInTheDocument();

      vi.doUnmock("./SohbetSekmesi");
      fireEvent.click(within(uyari).getByRole("button", { name: "Yeniden dene" }));
      expect(await within(screen.getByTestId("asistan-paneli")).findByLabelText("Sorunuz")).toBeInTheDocument();
      expect(screen.queryByText("Asistan yüklenemedi")).toBeNull();
    } finally {
      vi.doUnmock("./SohbetSekmesi");
      konsol.mockRestore();
    }
  });

  it("içerik hiç yüklenmeden oturum değişse de kayıtlı sohbet ve bekleyen ek öneri silinir", async () => {
    vi.resetModules();
    const { oturumVerileriniTemizle } = await import("../../lib/oturumTemizligi");
    const { SOHBET_ANAHTARI, EK_BEKLEYEN_ANAHTARI } = await import("./oturumAnahtarlari");
    sessionStorage.setItem(SOHBET_ANAHTARI, "sohbet-A");
    sessionStorage.setItem(EK_BEKLEYEN_ANAHTARI, JSON.stringify({ "a|": "m-A" }));
    oturumVerileriniTemizle();
    expect(sessionStorage.getItem(SOHBET_ANAHTARI)).toBeNull();
    expect(sessionStorage.getItem(EK_BEKLEYEN_ANAHTARI)).toBeNull();
  });
});
