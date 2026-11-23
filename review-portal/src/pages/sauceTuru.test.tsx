// Elle Sauce Labs turu: Koşular'daki tek düğme (tetik `sauce`), core `sauce.platformlar[]` uyarlaması
// ve koşu detayındaki platform tablosu (etiket · durum · geçen/toplam · Sauce video bağlantıları).
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { kosuDetayUyarla, saucePlatformlari } from "../api/uyumDemoB";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { teknikMetniCevir } from "../lib/kullaniciMetni";
import { TETIK } from "../lib/etiketler";
import { oturumAc, sar } from "../test/yardimci";
import { SauceTuru } from "./Kosular";

const IS = (n: number) => `https://app.eu-central-1.saucelabs.com/tests/${String(n).padStart(32, "0")}`;

function uygulama(yol: string) {
  return render(
    <MemoryRouter initialEntries={[yol]}>
      <OturumProvider>
        <BildirimProvider>
          <Rotalar />
        </BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

describe("saucePlatformlari (core sauce.json platformlar[])", () => {
  it("bilinmeyen platform ve Sauce dışı bağlantı atlanır; durum bilinmiyorsa 'error'", () => {
    const p = saucePlatformlari([
      { platform: "web", etiket: "Windows 11 · Edge", durum: "passed", toplam: 1, gecen: 1, isler: [{ ad: "Windows-11-Edge", url: IS(1), durum: "passed" }, { url: "javascript:alert(1)" }, { url: "https://evil.example/tests/1" }] },
      { platform: "ios", durum: "garip", isler: [] },
      { platform: "windows-wpf", etiket: "x", durum: "passed" },
    ]);
    expect(p).toEqual([
      { platform: "web", etiket: "Windows 11 · Edge", durum: "passed", neden: null, toplam: 1, gecen: 1, basarisiz: 0, isler: [{ ad: "Windows-11-Edge", url: IS(1), durum: "passed" }] },
      { platform: "ios", etiket: "ios", durum: "error", neden: null, toplam: 0, gecen: 0, basarisiz: 0, isler: [] },
    ]);
    expect(saucePlatformlari(undefined)).toBeNull();
    expect(saucePlatformlari([])).toBeNull();
  });

  it("koşu detayı uyarlaması `sauce.platformlar`'ı taşır; tetik etiketi Sauce Labs", () => {
    const k = kosuDetayUyarla({ id: "r1", tetik: "sauce", kaynak: "github", durum: "passed", sauce: { platformlar: [{ platform: "android", etiket: "Android · emülatör", durum: "failed", isler: [] }] } });
    expect(k.tetik).toBe("sauce");
    expect(TETIK[k.tetik]).toBe("Sauce Labs");
    expect(k.sauce_platformlari?.[0]?.etiket).toBe("Android · emülatör");
  });

  it("SAUCE_TETIKLER=sauce kullanıcı cümlesine çevrilir", () => {
    expect(teknikMetniCevir("Sauce bu tetikte koşmaz (deploy); SAUCE_TETIKLER=sauce")).toBe(
      "bu koşu türünde Sauce çalıştırılmıyor (proje ayarı: yalnız Sauce Labs turu koşularında)",
    );
  });
});

describe("SauceTuru tablosu", () => {
  it("platform satırları, durum çipi, geçen/toplam ve video bağlantıları", async () => {
    await oturumAc("muhendis");
    sar(
      <SauceTuru
        k={{
          tetik: "sauce",
          durum: "failed",
          sauce_platformlari: [
            { platform: "web", etiket: "Windows 11 · Chromium", durum: "passed", neden: null, toplam: 3, gecen: 3, basarisiz: 0, isler: [{ ad: "Windows-11-Chromium", url: IS(1), durum: "passed" }] },
            { platform: "web", etiket: "Windows 11 · Edge", durum: "error", neden: "Sauce işi oluşmadı", toplam: 0, gecen: 0, basarisiz: 0, isler: [] },
            { platform: "ios", etiket: "iOS · simülatör", durum: "failed", neden: null, toplam: 2, gecen: 1, basarisiz: 1, isler: [{ ad: "GirisTesti.dogruBilgilerleGiris", url: IS(2), durum: "passed" }, { ad: "SiparisTesti.siparisOnayVeGecmis", url: IS(3), durum: "failed" }] },
          ],
        }}
      />,
    );
    const tablo = screen.getByTestId("sauce-turu");
    const satirlar = within(tablo).getAllByRole("row").slice(1);
    expect(satirlar.map((r) => r.querySelector("td")?.textContent)).toEqual(["Windows 11 · Chromium", "Windows 11 · Edge", "iOS · simülatör"]);
    expect(within(satirlar[1]!).getByText("Koşmadı")).toBeInTheDocument();
    expect(within(satirlar[1]!).getByText("Sauce işi oluşmadı")).toBeInTheDocument();
    expect(within(satirlar[2]!).getByText("1/2")).toBeInTheDocument();
    const video = within(satirlar[2]!).getByRole("link", { name: /Video 2 · SiparisTesti\.siparisOnayVeGecmis/ });
    expect(video).toHaveAttribute("href", IS(3));
  });

  it("satır yokken: sürüyorsa bekleme notu; Sauce dışı koşuda hiçbir şey", async () => {
    await oturumAc("muhendis");
    const { unmount } = sar(<SauceTuru k={{ tetik: "sauce", durum: "running", sauce_platformlari: null }} />);
    expect(screen.getByTestId("sauce-turu-bos")).toHaveTextContent("Tur sürüyor");
    unmount();
    sar(<SauceTuru k={{ tetik: "deploy", durum: "passed", sauce_platformlari: null }} />);
    expect(screen.queryByText("Sauce Labs turu")).toBeNull();
  });
});

describe("Koşular › Sauce Labs turunu başlat", () => {
  it("Otomasyon Mühendisi düğmeyi görür ve tetikler; geliştirici görmez", async () => {
    await oturumAc("muhendis");
    const { unmount } = uygulama("/kosular");
    const d = await screen.findByRole("button", { name: "Sauce Labs turunu başlat" });
    expect(d).toHaveAttribute("aria-describedby", "kosular-sauce-aciklama");
    expect(screen.getByText(/Windows 11 · Chromium ve Edge/)).toBeInTheDocument();
    fireEvent.click(d);
    await waitFor(() => expect(screen.getAllByText(/Sauce Labs koşusu sıraya alındı/).length).toBeGreaterThan(0));
    unmount();
    await oturumAc("gelistirici");
    uygulama("/kosular");
    await screen.findByRole("button", { name: "Manuel koşu başlat" });
    expect(screen.queryByRole("button", { name: "Sauce Labs turunu başlat" })).toBeNull();
  });
});
