// Asistan paneli içeriğinin kod bölmesi: Sohbet / Öneriler sekmeleri (ve cevap/öneri kartları) panel
// kapalıyken ana pakete girmez, ilk açılışta yüklenir. Diğer testler içeriği önceden yükler
// (test/setup.ts); burada taze modül kaydıyla yükleme anı sınanır: erişilebilir yer tutucu, sonra içerik.
// Oturum temizliği (AI-ASISTAN-PLANI §16 madde 1) içerik hiç yüklenmeden de kayıtlı anahtarları siler.
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
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

  it("parça yüklenemezse uygulama düşmez: panelde hata ve 'Yeniden dene' içeriği yeniden ister; odak panel başlığına", async () => {
    vi.resetModules();
    const http = await import("../../api/http");
    http.yapilandir({ mockZorunlu: true, mockOtomatik: true, yetenekKesfi: false });
    const { oturumAc, sar } = await import("../../test/yardimci");
    const { AsistanPaneli, icerikYukleyici } = await import("./AsistanPaneli");
    // Parça yükleme hatası: dinamik içe aktarım reddedilir (vi.doMock fabrikasından fırlatmak vitest'in
    // "error when mocking a module" yığınını basıyordu — tam koşuda gürültü).
    const asil = icerikYukleyici.yukle;
    icerikYukleyici.yukle = () => Promise.reject(new Error("parça yok"));
    const konsol = vi.spyOn(console, "error").mockImplementation(() => undefined);
    // React sınırın yakaladığı hatayı geliştirme kipinde window "error" olayıyla da bildirir; jsdom işlenmemiş
    // olayı yığınıyla stderr'e basar (konsol casusunu atlar). Beklenen hata: olay işlendi sayılır.
    const yut = (e: ErrorEvent) => e.preventDefault();
    window.addEventListener("error", yut);
    try {
      await oturumAc("analist");
      sar(<AsistanPaneli />, { yol: "/kosular" });
      fireEvent.click(await screen.findByRole("button", { name: "Asistanı aç" }));
      const uyari = await within(screen.getByTestId("asistan-paneli")).findByRole("alert");
      expect(uyari).toHaveTextContent("Asistan yüklenemedi");
      // Başlık ve kapatma düğmesi yerinde: panel (ve uygulama) çizili kalır.
      expect(screen.getByRole("button", { name: "Asistanı kapat" })).toBeInTheDocument();

      icerikYukleyici.yukle = asil;
      const dugme = within(uyari).getByRole("button", { name: "Yeniden dene" });
      dugme.focus();
      fireEvent.click(dugme);
      // Düğme DOM'dan kalkar: odak body'ye düşmez, panel başlığına gelir (WCAG 2.4.3).
      await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Asistan", level: 2 })));
      expect(await within(screen.getByTestId("asistan-paneli")).findByLabelText("Sorunuz")).toBeInTheDocument();
      expect(screen.queryByText("Asistan yüklenemedi")).toBeNull();
    } finally {
      icerikYukleyici.yukle = asil;
      window.removeEventListener("error", yut);
      konsol.mockRestore();
    }
  });

  it("içerik hiç yüklenmeden oturum değişse de kayıtlı sohbet ve bekleyen ek öneri silinir (kayıt ana paketteki AsistanPaneli'nden)", async () => {
    vi.resetModules();
    // İçerik modülleri yüklenirse bu test anlamını yitirir (kendi temizleyicilerini kaydederler): yüklenmediği kanıtlanır.
    const yuklenen: string[] = [];
    for (const m of ["./SohbetSekmesi", "./OnerilerSekmesi", "./OneriEkOneriler", "./oturumAnahtarlari"] as const) {
      vi.doMock(m, async (asil) => {
        yuklenen.push(m);
        return asil();
      });
    }
    try {
      const { oturumVerileriniTemizle } = await import("../../lib/oturumTemizligi");
      await import("./AsistanPaneli");
      // Anahtarlar düz metin (anahtar modülü testte içe aktarılmaz): kayıt yalnız AsistanPaneli'nin yan etkili
      // içe aktarımından gelebilir; o satır silinirse test kırılır.
      sessionStorage.setItem("tp-asistan-sohbet", "sohbet-A");
      sessionStorage.setItem("tp-asistan-ek-bekleyen", JSON.stringify({ "a|": "m-A" }));
      oturumVerileriniTemizle();
      expect(sessionStorage.getItem("tp-asistan-sohbet")).toBeNull();
      expect(sessionStorage.getItem("tp-asistan-ek-bekleyen")).toBeNull();
      expect(yuklenen).toEqual(["./oturumAnahtarlari"]);
    } finally {
      for (const m of ["./SohbetSekmesi", "./OnerilerSekmesi", "./OneriEkOneriler", "./oturumAnahtarlari"]) vi.doUnmock(m);
    }
  });
});
