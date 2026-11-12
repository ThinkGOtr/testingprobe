// Gereksinim detayı bölüm gezgini (tasarım planı §5, F4): yapışkan sağ sütun, düz bağlantılar.
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { oturumAc } from "../test/yardimci";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import { mockVerisi } from "../api/mock/handlers";
import { BOLUM_ID, BOLUMLER } from "./GereksinimDetay";

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
    // Tasarım modeli paneli bu gereksinimde yok → gezginde de yok; Ürün AI ajanı (bağlı değil, daraltılmış) var.
    expect(baglantilar.map((a) => a.textContent)).toEqual([
      "Doküman",
      "PO teyidi",
      "Ürün AI ajanı",
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
    expect(BOLUMLER.map((b) => b.id)).toEqual(Object.values(BOLUM_ID));
    expect(Object.values(BOLUM_ID).filter((id) => id !== BOLUM_ID.model).map((id) => `#${id}`)).toEqual(baglantilar.map((a) => a.getAttribute("href")));
    // Gezgin ile asistan öneri çapaları (rules/assistant/oneriler.yaml) aynı kimlikleri kullanır.
    expect(BOLUM_ID.bulgular).toBe("bulgular");
    expect(BOLUM_ID.po).toBe("po-onay");
  });

  it("tasarım modeli paneli görünürse gezginin ilk bölümüdür; ajan ucu yoksa 'Ürün AI ajanı' gezginde de yok", async () => {
    await oturumAc("analist");
    const g = mockVerisi().gereksinimler.find((x) => x.id === "req-tpd-1")!;
    g.durum = "modeling"; // model aşaması: panel her zaman çizilir
    const casus = vi.spyOn(api, "ajanTesti").mockRejectedValue(new ApiError(404, "Not Found"));
    const { container } = uygulama("/gereksinimler/req-tpd-1");
    const gezgin = await screen.findByRole("navigation", { name: "Sayfa bölümleri" });
    await within(gezgin).findByRole("link", { name: "Tasarım modeli" });
    const adlar = within(gezgin).getAllByRole("link").map((a) => a.textContent);
    expect(adlar[0]).toBe("Tasarım modeli");
    expect(adlar).not.toContain("Ürün AI ajanı");
    const hedef = container.querySelector(`#${BOLUM_ID.model}`)!;
    expect(within(hedef as HTMLElement).getByRole("heading", { level: 2 }).textContent).toContain("Tasarım modeli");
    casus.mockRestore();
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
