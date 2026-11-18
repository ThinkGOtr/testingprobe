// IA-11: her sayfa sekme başlığını "<Sayfa> · <Proje> · Testing Probe" yapar.
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { OturumProvider } from "../auth";
import { oturumAc } from "../test/yardimci";
import { BildirimProvider } from "./Bildirim";
import { dugumMetni, sekmeBasligi } from "./ui";

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

describe("sekme başlığı (IA-11)", () => {
  it("metin: sayfa · proje · ürün; proje yoksa atlanır", () => {
    expect(sekmeBasligi("Koşular", "Bayi Portalı")).toBe("Koşular · Bayi Portalı · Testing Probe");
    expect(sekmeBasligi("  Case  review ", null)).toBe("Case review · Testing Probe");
    expect(dugumMetni(<span>TPD-1 <strong>Case</strong> review</span>)).toBe("TPD-1 Case review");
  });

  it("sayfa açılınca document.title sayfanın adını taşır; ayrıldıkça değişir", async () => {
    await oturumAc("muhendis");
    const { unmount } = uygulama("/kosular");
    await screen.findByRole("heading", { name: "Koşular", level: 1 });
    await waitFor(() => expect(document.title).toMatch(/^Koşular · (.+ · )?Testing Probe$/));
    unmount();
    expect(document.title).toBe("Testing Probe");
    uygulama("/gereksinimler");
    await screen.findByRole("heading", { name: "Gereksinimler", level: 1 });
    await waitFor(() => expect(document.title).toMatch(/^Gereksinimler · (.+ · )?Testing Probe$/));
  });
});
