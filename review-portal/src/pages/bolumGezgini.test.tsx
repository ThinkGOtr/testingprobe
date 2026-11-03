// Gereksinim detayı bölüm gezgini (tasarım planı §5, F4): yapışkan sağ sütun, düz bağlantılar.
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { oturumAc } from "../test/yardimci";
import { BOLUM_ID } from "./GereksinimDetay";

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

describe("gereksinim detayı: bölüm gezgini", () => {
  it("her bağlantı sayfadaki bir kart bölgesine gider; ad, kartın başlığıyla aynıdır", async () => {
    await oturumAc("analist");
    const { container } = uygulama("/gereksinimler/req-ft-1");
    const gezgin = await screen.findByRole("navigation", { name: "Sayfa bölümleri" });
    const baglantilar = within(gezgin).getAllByRole("link");
    expect(baglantilar.map((a) => a.textContent)).toEqual([
      "Doküman",
      "PO teyidi",
      "Manuel baz değer",
      "Ön inceleme soruları",
      "Tutarlılık bulguları",
    ]);
    for (const a of baglantilar) {
      const hedef = container.querySelector(a.getAttribute("href")!);
      expect(hedef, a.getAttribute("href")!).not.toBeNull();
      // Hedef, aynı adı taşıyan kart bölgesi (aria-labelledby → h2).
      expect(hedef!.tagName).toBe("SECTION");
      expect(within(hedef as HTMLElement).getByRole("heading", { level: 2 }).textContent).toContain(a.textContent!);
    }
    expect(Object.values(BOLUM_ID).map((id) => `#${id}`)).toEqual(baglantilar.map((a) => a.getAttribute("href")));
  });

  it("liste/makale rolü eklemez; kilitli sayımlar ve akış gezgini korunur", async () => {
    await oturumAc("analist");
    uygulama("/gereksinimler/req-ft-1");
    const gezgin = await screen.findByRole("navigation", { name: "Sayfa bölümleri" });
    expect(within(gezgin).queryAllByRole("list")).toHaveLength(0);
    expect(within(gezgin).queryAllByRole("listitem")).toHaveLength(0);
    expect(gezgin.querySelector("[aria-current]")).toBeNull();
    expect(await screen.findAllByRole("article")).toHaveLength(3);
    expect(screen.getByRole("navigation", { name: /14 adımlı akış/ })).toBeInTheDocument();
    // Ad çakışması yok: "Sayfa bölümleri" yalnız bir gezgin, akış adıyla eşleşmez.
    expect(screen.getAllByRole("navigation", { name: /Sayfa bölümleri/ })).toHaveLength(1);
    expect(screen.queryAllByRole("navigation", { name: /akış/ })).toHaveLength(1);
  });
});
