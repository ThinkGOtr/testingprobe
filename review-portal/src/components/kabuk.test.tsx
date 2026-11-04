// Kabuk adımı (AI-ASISTAN-PLANI §11, Şerit K): paylaşılan KabukDurumu (çekmece genişliğinde panel ile yan
// menü birbirini dışlar), "Asistanı aç" atlama düğmesi, bildirimlerin asistan düğmesinin üstünde durması,
// z-index katmanları ve Olculmedi'nin ui.tsx'te olması.
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { asistanMockAyarla } from "../api/mock/asistan";
import { OturumProvider } from "../auth";
import { oturumAc } from "../test/yardimci";
import { BildirimProvider } from "./Bildirim";
import { Kabuk } from "./Kabuk";
import { KabukDurumuSaglayici, YAN_MENU_CEKMECE_PX } from "./KabukDurumu";
import { acSekme, asistanKontrolSifirla, panelHazirAyarla, paneliKapat, useAsistanKontrol } from "./asistan/kontrol";
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

/** Panelin açık/kapalı durumunu DOM'a yansıtır (kontrol deposu; panel bileşeni çizilmeden). */
function PanelDurumu() {
  return <output data-testid="panel-durumu">{useAsistanKontrol().acik ? "acik" : "kapali"}</output>;
}

describe("KabukDurumu: panel ile yan menü çekmecesi birbirini dışlar", () => {
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

  it("760–860 px'de panel açıkken menü açılırsa panel kapanır; menü açık kalır, panel yeniden açılınca menü kapanır", async () => {
    genislik(800);
    const u = userEvent.setup();
    render(<PanelDurumu />);
    yalnizKabuk(true);
    await screen.findByText("sayfa");
    act(() => acSekme("sohbet"));
    expect(screen.getByTestId("panel-durumu")).toHaveTextContent("acik");
    await u.click(menuDugmesi());
    expect(menuDugmesi()).toHaveAttribute("aria-expanded", "true");
    await waitFor(() => expect(screen.getByTestId("panel-durumu")).toHaveTextContent("kapali"));
    // Kipsel menü: ilk bağlantı odakta, içerik inert (panel kapandı, perdenin üstünde parlak bölge kalmadı).
    expect(screen.getByRole("navigation", { name: "Ana menü" }).contains(document.activeElement)).toBe(true);
    expect(document.getElementById("ana-icerik")).toHaveProperty("inert", true);
    act(() => acSekme("oneriler"));
    await waitFor(() => expect(menuDugmesi()).toHaveAttribute("aria-expanded", "false"));
    expect(screen.getByTestId("panel-durumu")).toHaveTextContent("acik");
  });

  it("geniş ekranda (yan menü sabit) panel ile menü durumu birbirine dokunmaz", async () => {
    genislik(1280);
    const u = userEvent.setup();
    render(<PanelDurumu />);
    yalnizKabuk(true);
    await screen.findByText("sayfa");
    await u.click(menuDugmesi());
    act(() => acSekme("sohbet"));
    expect(menuDugmesi()).toHaveAttribute("aria-expanded", "true");
    await u.click(menuDugmesi());
    await u.click(menuDugmesi());
    expect(screen.getByTestId("panel-durumu")).toHaveTextContent("acik");
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

  /** Seçicinin z-index taşıyan ilk kuralındaki değer (medya sorgusu içindekiler dahil). */
  function katman(css: string, secici: string): number | null {
    const kacis = secici.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    for (const m of css.matchAll(new RegExp(`(?:^|\\n)\\s*${kacis}\\s*\\{([^}]*)\\}`, "g"))) {
      const z = /z-index:\s*(\d+)/.exec(m[1]);
      if (z) return Number(z[1]);
    }
    return null;
  }
  /** Bir medya sorgusu bloğunun gövdesi (ilk eşleşen; iç içe tek düzey süslü parantez). */
  function medyaBlogu(css: string, sorgu: string, icerir: string): string {
    const bas = `@media ${sorgu} {`;
    let i = css.indexOf(bas);
    while (i !== -1) {
      let derinlik = 0;
      let j = i + bas.length - 1;
      for (; j < css.length; j++) {
        if (css[j] === "{") derinlik++;
        else if (css[j] === "}" && --derinlik === 0) break;
      }
      const govde = css.slice(i + bas.length, j);
      if (govde.includes(icerir)) return govde;
      i = css.indexOf(bas, j);
    }
    return "";
  }

  it("üst çubuk 20, menü perdesi 29, yan menü 30, Bu ne? 39, başlatıcı/panel 40, panel içi modal 45, bildirimler 50, .atla 100", () => {
    const sira = [
      katman(stiller, ".ust-cubuk"),
      katman(stiller, ".menu-perde"),
      katman(stiller, ".yan-menu"),
      katman(asistanCss, ".asistan-bune-bindirme"),
      katman(asistanCss, ".asistan-baslatici-kap"),
      katman(asistanCss, ".asistan-panel"),
      katman(asistanCss, ".asistan-modal-arka"),
      katman(stiller, ".bildirimler"),
      katman(stiller, ".atla"),
    ];
    expect(sira).toEqual([20, 29, 30, 39, 40, 40, 45, 50, 100]);
  });

  it("açık mobil menüde (≤860 px) başlatıcı kabı perdenin üstünde görünmez", () => {
    const blok = medyaBlogu(asistanCss, "(max-width: 860px)", ".yan-menu.acik");
    expect(blok).toMatch(/body:has\(\.yan-menu\.acik\)\s+\.asistan-baslatici-kap\s*\{[^}]*visibility:\s*hidden/);
  });

  it("masaüstü paneli açıkken bildirimler panelin solunda (sağ boşluk ≥ panel genişliği + 16 px)", () => {
    const panel = /(?:^|\n)\.asistan-panel\s*\{([^}]*)\}/.exec(asistanCss)![1];
    const genislik = Number(/(?:^|\s)width:\s*(\d+)px/.exec(panel)![1]);
    const m = /body:has\(\.asistan-panel:not\(\.asistan-panel-modal\)\)\s+\.bildirimler\s*\{([^}]*)\}/.exec(stiller);
    expect(m).not.toBeNull();
    expect(Number(/right:\s*(\d+)px/.exec(m![1])?.[1])).toBeGreaterThanOrEqual(genislik + 16);
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
  it("ui.tsx'ten dışa aktarılır", () => {
    render(<ui.Olculmedi />);
    expect(screen.getByText("ölçülmedi")).toHaveClass("olculmedi");
  });
});
