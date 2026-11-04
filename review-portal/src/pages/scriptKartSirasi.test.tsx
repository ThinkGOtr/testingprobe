// Script detay: PR açılınca karar kartları üste gelir; üretim kartları yeniden mount edilmeden taşınır
// (AjanAdimlari'nda sunucunun seçtiği adım korunur, DOM öğesi aynı kalır).
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { mockVerisi } from "../api/mock/handlers";
import { mockOlayYayinla } from "../api/mock/olaylar";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { oturumAc } from "../test/yardimci";

describe("Script detay kart sırası", () => {
  it("PR açılınca karar kartları üste geçer; seçili ajan adımı ve öğe kimliği korunur", async () => {
    const s = mockVerisi().scriptler.find((x) => x.id === "scr-2")!;
    const pr = s.pr;
    expect(pr).not.toBeNull();
    s.pr = null;
    await oturumAc("muhendis");
    render(
      <MemoryRouter initialEntries={["/kod/scr-2"]}>
        <OturumProvider>
          <BildirimProvider>
            <Rotalar />
          </BildirimProvider>
        </OturumProvider>
      </MemoryRouter>,
    );
    const liste = await screen.findByRole("list", { name: "Ajan adımları" });
    const ilk = liste.querySelector("button")!;
    fireEvent.click(ilk);
    expect(ilk).toHaveAttribute("aria-pressed", "true");
    const basliklar = () => screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(basliklar().indexOf("Ajan adımları (Playwright MCP)")).toBeLessThan(basliklar().indexOf("Pull request"));
    expect(await screen.findByText("Olaylar: örnek veri")).toBeInTheDocument();

    s.pr = pr;
    await act(async () => {
      mockOlayYayinla({ type: "pr.opened", id: "scr-2", data: {} });
    });
    await waitFor(() => expect(basliklar().indexOf("Pull request")).toBeLessThan(basliklar().indexOf("Ajan adımları (Playwright MCP)")));
    expect(screen.getByRole("list", { name: "Ajan adımları" })).toBe(liste);
    expect(ilk).toBeInTheDocument();
    expect(ilk).toHaveAttribute("aria-pressed", "true");
  });
});
