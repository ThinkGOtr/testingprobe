// Kabuk adımı (AI-ASISTAN-PLANI §11, Şerit K): paylaşılan KabukDurumu (çekmece genişliğinde panel
// açılınca yan menü kapanır), "Asistanı aç" atlama düğmesi, bildirimlerin asistan düğmesinin üstünde
// durması, z-index katmanları ve Olculmedi'nin ui.tsx'e taşınması.
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { asistanMockAyarla } from "../api/mock/asistan";
import { OturumProvider } from "../auth";
import * as kule from "../pages/KontrolKulesi";
import { oturumAc } from "../test/yardimci";
import { BildirimProvider } from "./Bildirim";
import { Kabuk } from "./Kabuk";
import { KabukDurumuSaglayici, YAN_MENU_CEKMECE_PX } from "./KabukDurumu";
import { acSekme, asistanKontrolSifirla, panelHazirAyarla, paneliKapat } from "./asistan/kontrol";
import * as ui from "./ui";

/** `max-width: <px>` sorgusunu verilen genişliğe göre yanıtlayan matchMedia sahtesi. */
function genislik(px: number) {
  vi.stubGlobal(
    "matchMedia",
    (q: string) => {
      const m = /max-width:\s*(\d+)px/.exec(q);
      return {
        matches: m ? px <= Number(m[1]) : false,
        media: q,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
      };
    },
  );
}

function yalnizKabuk(saglayiciIle = false) {
  const kabuk = saglayiciIle ? (
    <KabukDurumuSaglayici>
      <Kabuk />
    </KabukDurumuSaglayici>
  ) : (
    <Kabuk />
  );
  return render(
    <MemoryRouter initialEntries={["/kosular"]}>
      <OturumProvider>
        <BildirimProvider>
          <Routes>
            <Route element={kabuk}>
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

const menuDugmesi = () => screen.getByRole("button", { name: "Menü" });
const atlamaDugmesi = () => screen.queryByRole("button", { name: "Asistanı aç (panele atla)" });

beforeEach(async () => {
  asistanKontrolSifirla();
  asistanMockAyarla({ otomatikIsle: false });
  await oturumAc("analist");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("KabukDurumu: panel açılınca yan menü", () => {
  it(`${YAN_MENU_CEKMECE_PX} px ve altında (760–860) panel açılınca yan menü çekmecesi kapanır`, async () => {
    genislik(800);
    const u = userEvent.setup();
    yalnizKabuk();
    await screen.findByText("sayfa");
    await u.click(menuDugmesi());
    expect(menuDugmesi()).toHaveAttribute("aria-expanded", "true");
    act(() => acSekme("sohbet"));
    await waitFor(() => expect(menuDugmesi()).toHaveAttribute("aria-expanded", "false"));
    expect(screen.getByRole("navigation", { name: "Ana menü" })).not.toHaveClass("acik");
  });

  it("panel açıkken menü yeniden açılabilir (yalnız açılma geçişi kapatır)", async () => {
    genislik(800);
    const u = userEvent.setup();
    yalnizKabuk(true);
    await screen.findByText("sayfa");
    act(() => acSekme("sohbet"));
    await u.click(menuDugmesi());
    expect(menuDugmesi()).toHaveAttribute("aria-expanded", "true");
    // Kapat-aç yeniden kapatır.
    act(() => paneliKapat());
    expect(menuDugmesi()).toHaveAttribute("aria-expanded", "true");
    act(() => acSekme("oneriler"));
    await waitFor(() => expect(menuDugmesi()).toHaveAttribute("aria-expanded", "false"));
  });

  it("geniş ekranda (yan menü sabit) panel açılması menü durumuna dokunmaz", async () => {
    genislik(1280);
    const u = userEvent.setup();
    yalnizKabuk(true);
    await screen.findByText("sayfa");
    await u.click(menuDugmesi());
    act(() => acSekme("sohbet"));
    expect(menuDugmesi()).toHaveAttribute("aria-expanded", "true");
  });
});

describe('"Asistanı aç" atlama düğmesi', () => {
  it("asistan kullanılamazken yok; kullanılabilir olunca .atla yanında çıkar", async () => {
    yalnizKabuk();
    await screen.findByText("sayfa");
    expect(atlamaDugmesi()).toBeNull();
    act(() => panelHazirAyarla(true));
    const d = atlamaDugmesi();
    expect(d).not.toBeNull();
    expect(d).toHaveClass("atla");
    // Belge sırasında "İçeriğe atla"nın hemen ardından gelir.
    const icerigeAtla = screen.getByRole("link", { name: "İçeriğe atla" });
    expect(icerigeAtla.nextElementSibling).toBe(d);
  });

  it("tıklanınca paneli Sohbet sekmesinde açar ve odağı panele taşır", async () => {
    genislik(1280);
    const u = userEvent.setup();
    uygulama("/kosular");
    const d = await screen.findByRole("button", { name: "Asistanı aç (panele atla)" });
    act(() => acSekme("oneriler"));
    act(() => paneliKapat());
    await u.click(d);
    const panel = await screen.findByTestId("asistan-paneli");
    expect(within(panel).getByRole("tab", { name: "Sohbet" })).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(panel.contains(document.activeElement)).toBe(true));
  });
});

describe("Katmanlar ve bildirim konumu", () => {
  const kok = resolve(__dirname, "..");
  const stiller = readFileSync(resolve(kok, "styles.css"), "utf8");
  const asistanCss = readFileSync(resolve(kok, "components/asistan/asistan.css"), "utf8");

  /** Seçicinin ilk kuralındaki z-index. */
  function katman(css: string, secici: string): number | null {
    const kacis = secici.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const m = new RegExp(`(?:^|\\n)\\s*${kacis}\\s*\\{([^}]*)\\}`).exec(css);
    const z = m && /z-index:\s*(\d+)/.exec(m[1]);
    return z ? Number(z[1]) : null;
  }

  it("üst çubuk 20, yan menü 30, panel 40, bildirimler 50, .atla 100", () => {
    expect(katman(stiller, ".ust-cubuk")).toBe(20);
    expect(katman(stiller, ".yan-menu")).toBe(30);
    expect(katman(asistanCss, ".asistan-panel")).toBe(40);
    expect(katman(stiller, ".bildirimler")).toBe(50);
    expect(katman(stiller, ".atla")).toBe(100);
  });

  it("asistan düğmesi görünürken bildirimler düğmenin üstüne çıkar", () => {
    const m = /body:has\(\.asistan-baslatici\)\s+\.bildirimler\s*\{([^}]*)\}/.exec(stiller);
    expect(m).not.toBeNull();
    const alt = Number(/bottom:\s*(\d+)px/.exec(m![1])?.[1]);
    // Düğme: bottom 16 px + ~44 px yükseklik; bildirimler bunun üstünde.
    expect(alt).toBeGreaterThanOrEqual(16 + 44);
  });
});

describe("Olculmedi taşıma", () => {
  it("ui.tsx'ten dışa aktarılır; KontrolKulesi aynı bileşeni yeniden dışa aktarır", () => {
    expect(kule.Olculmedi).toBe(ui.Olculmedi);
    render(<ui.Olculmedi />);
    expect(screen.getByText("ölçülmedi")).toHaveClass("olculmedi");
  });
});
