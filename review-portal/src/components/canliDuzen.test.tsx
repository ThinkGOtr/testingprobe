// Canlı UI testi düzeltmeleri (düzen/mobil): çekmecede rol seçici, kart kalıbındaki tablolar, uzun Sauce çipi,
// "Canlı olaylar" erişilebilir adı, yetkisiz ekranın h1'i, değiştirici ve asistan düğmesi yerleşimi.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { OturumProvider } from "../auth";
import { SauceCipi } from "../pages/Kosular";
import { oturumAc } from "../test/yardimci";
import { BildirimProvider } from "./Bildirim";
import { Kabuk } from "./Kabuk";
import { KabukDurumuSaglayici } from "./KabukDurumu";

const kok = resolve(__dirname, "..");
const oku = (yol: string) => readFileSync(resolve(kok, yol), "utf8");

function genislik(px: number) {
  vi.stubGlobal("matchMedia", (q: string) => {
    const m = /max-width:\s*(\d+)px/.exec(q);
    const n = /min-width:\s*(\d+)px/.exec(q);
    return {
      matches: m ? px <= Number(m[1]) : n ? px >= Number(n[1]) : false,
      media: q,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    };
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function kabuk() {
  return render(
    <MemoryRouter initialEntries={["/kosular"]}>
      <OturumProvider>
        <BildirimProvider>
          <Routes>
            <Route
              element={
                <KabukDurumuSaglayici>
                  <Kabuk />
                </KabukDurumuSaglayici>
              }
            >
              <Route path="/kosular" element={<p>sayfa</p>} />
            </Route>
          </Routes>
        </BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

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

describe("mobil çekmecede rol", () => {
  it("çekmece açıkken başında ad ve 'Rol: X' görünür; kapalıyken (ve geniş ekranda) ikinci seçici çizilmez", async () => {
    genislik(390);
    await oturumAc("analist");
    const u = userEvent.setup();
    kabuk();
    await screen.findByText("sayfa");
    expect(screen.queryByTestId("menu-kullanici")).toBeNull();
    await u.click(screen.getByRole("button", { name: "Menü" }));
    const blok = screen.getByTestId("menu-kullanici");
    expect(screen.getByRole("navigation", { name: "Ana menü" })).toContainElement(blok);
    expect(blok).toHaveTextContent(/Rol:\s*\S+/);
    // Kipsel menünün ilk odağı yine ilk bağlantı.
    expect(document.activeElement?.tagName).toBe("A");
  });

  it("CSS: blok yalnız ≤860 px'te görünür, rol listesi çekmecede akışta açılır", () => {
    const css = oku("styles.css");
    const blok = css.slice(css.indexOf("/* canlı UI düzeltmeleri — düzen/mobil */"));
    expect(blok).toMatch(/\.menu-kullanici \{\s*display: none;/);
    expect(blok).toMatch(/\.menu-kullanici \.rol-secici-menu \{\s*position: static;/);
  });
});

describe("kart kalıbı (.tablo-yigin) tabloları", () => {
  it("Koşular tablosu dar ekranda karta döner; Durum ve Geçen hücreleri etiketli", async () => {
    await oturumAc("muhendis");
    uygulama("/kosular");
    const tablo = await screen.findByRole("table");
    expect(tablo).toHaveClass("tablo-yigin");
    const ilk = within(tablo).getAllByRole("row")[1];
    const etiketler = [...ilk.querySelectorAll("td")].map((td) => td.getAttribute("data-etiket"));
    expect(etiketler).toEqual(expect.arrayContaining(["Koşu", "Tetik", "Durum", "Geçen / toplam", "Başlangıç"]));
    expect(etiketler).not.toContain(null);
  });

  it.each(["pages/Denetim.tsx", "pages/BugTaslaklari.tsx", "pages/TestVerisi.tsx", "pages/KontrolKulesi.tsx"])(
    "%s: her tablo .tablo-yigin, her hücre data-etiket'li",
    (dosya) => {
      const kaynak = oku(dosya);
      const tablolar = kaynak.match(/<table className="[^"]*"/g) ?? [];
      expect(tablolar.length).toBeGreaterThan(0);
      for (const t of tablolar) expect(t).toContain("tablo-yigin");
      const hucreler = kaynak.match(/<td\b[^>]*>/g) ?? [];
      expect(hucreler.length).toBeGreaterThan(0);
      for (const h of hucreler) expect(h).toContain("data-etiket=");
    },
  );

  it("CSS: kartlarda uzun değer sarar (yatay taşma yok)", () => {
    const blok = oku("styles.css").split("/* canlı UI düzeltmeleri — düzen/mobil */")[1];
    expect(blok).toMatch(/\.tablo-yigin td \{\s*overflow-wrap: anywhere;/);
  });
});

describe("uzun Sauce çipi", () => {
  it("hata/atlandı nedeni sarabilen çipte (cip-uzun); kısa çipler değişmez", () => {
    const temel = { kaynak: "github" as const, durum: "passed" as const };
    const { container: hata } = render(<>{SauceCipi({ k: { ...temel, sauce_durum: "error", sauce_neden: "saucectl 1 koduyla çıktı ve Sauce job'u oluşmadı" } })}</>);
    expect(hata.querySelector(".cip")).toHaveClass("cip-uzun", "cip-uyari");
    const { container: gecti } = render(<>{SauceCipi({ k: { ...temel, sauce_durum: "passed", sauce_neden: null } })}</>);
    expect(gecti.querySelector(".cip")).not.toHaveClass("cip-uzun");
    expect(oku("styles.css")).toMatch(/\.cip\.cip-uzun \{\s*max-width: 100%;\s*white-space: normal;\s*overflow-wrap: anywhere;/);
  });
});

describe("Canlı olaylar göstergesi", () => {
  it("dar ekranda metin display:none değil, görsel gizli (erişilebilir ad korunur); title var", () => {
    const blok = oku("styles.css").split("/* canlı UI düzeltmeleri — düzen/mobil */")[1];
    expect(blok).toMatch(/\.ust-sag \.baglanti-metin \{[^}]*position: absolute;[^}]*clip: rect\(0 0 0 0\);/);
    expect(oku("components/Kabuk.tsx")).toMatch(/className=\{`baglanti baglanti-\$\{b\.sinif\}`\} role="status" title=\{b\.etiket\}/);
  });
});

describe("yetkisiz ekran", () => {
  it("sayfa başlığı (h1) var", async () => {
    await oturumAc("gelistirici");
    uygulama("/claude-code");
    expect(await screen.findByText("Bu ekran için yetkiniz yok.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Erişim yok" })).toBeInTheDocument();
  });
});

describe("yerleşim: değiştirici paneli ve asistan düğmesi", () => {
  const blok = () => oku("styles.css").split("/* canlı UI düzeltmeleri — düzen/mobil */")[1];
  it("dar ekranda değiştirici host'u konumlandırılmaz; panel üst çubuğun sağ grubuna yaslanır", () => {
    expect(blok()).toMatch(/\.ust-sag \{\s*position: relative;/);
    expect(blok()).toMatch(/\.ust-sag aiprobe-switcher \{\s*position: static;/);
  });
  it("içerik sonunda düğme kadar boşluk; geniş ekranda düğme varken sağ oluk", () => {
    expect(blok()).toMatch(/\.icerik \{\s*padding-bottom: 96px;/);
    expect(blok()).toMatch(/body:has\(\.asistan-baslatici-kap\) \.icerik \{\s*padding-right: 76px;/);
  });
});
