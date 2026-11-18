// Script detay (DetaySayfasi iskeleti): PR açılınca kullanıcının bulunduğu sekme korunur; ajan adımları paneli
// yeniden mount edilmez (AjanAdimlari'nda seçilen adım korunur, DOM öğesi aynı kalır); PR sekmesi PR'ı gösterir.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { mockVerisi } from "../api/mock/handlers";
import { mockOlayYayinla } from "../api/mock/olaylar";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { oturumAc } from "../test/yardimci";

describe("Script detay sekmeleri", () => {
  it("PR açılınca seçili sekme ve seçili ajan adımı korunur; PR sekmesi PR kartını gösterir", async () => {
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
    fireEvent.click(await screen.findByRole("tab", { name: /^Ajan adımları/ }));
    const liste = await screen.findByRole("list", { name: "Ajan adımları" });
    const ilk = liste.querySelector("button")!;
    fireEvent.click(ilk);
    expect(ilk).toHaveAttribute("aria-pressed", "true");
    expect(ilk).toHaveAttribute("aria-current", "step");
    expect(await screen.findByText("Olaylar: örnek veri")).toBeInTheDocument();

    s.pr = pr;
    await act(async () => {
      mockOlayYayinla({ type: "pr.opened", id: "scr-2", data: {} });
    });
    await waitFor(() => expect(screen.getByTestId("ozet-karti")).toHaveTextContent(`PR #${pr!.number}`));
    expect(screen.getByRole("tab", { name: /^Ajan adımları/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("list", { name: "Ajan adımları" })).toBe(liste);
    expect(ilk).toBeInTheDocument();
    expect(ilk).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("tab", { name: /^Pull request/ }));
    expect(screen.getByRole("heading", { name: "Pull request", level: 2 })).toBeInTheDocument();
  });
});
