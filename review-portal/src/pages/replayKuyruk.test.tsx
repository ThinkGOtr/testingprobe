// Ajan koşarken / kuyruktayken REPLAY etiketi görünür; çalışma çipi "Canlı" demez (canlı model sanılmasın).
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { oturumAc } from "../test/yardimci";

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

describe("kod üretimi: koşarken REPLAY etiketi", () => {
  it("verifying + replay: REPLAY bandı 'koşturuluyor' der, çip 'Adımlar geliyor'", async () => {
    const { mockVerisi } = await import("../api/mock/handlers");
    const s = mockVerisi().scriptler.find((x) => x.id === "scr-2")!;
    s.durum = "verifying";
    s.mode = "replay";
    await oturumAc("muhendis");
    uygulama("/kod/scr-2");
    const bant = await screen.findByTestId("replay-bandi");
    expect(within(bant).getByText("REPLAY")).toBeInTheDocument();
    expect(bant).toHaveTextContent("koşturuluyor (canlı model değil)");
    expect(screen.getByText("Adımlar geliyor")).toBeInTheDocument();
    expect(screen.queryByText(/^Canlı$/)).toBeNull();
  });

  it("bitmiş replay koşusu 'koşturuldu' der, çalışma çipi yoktur", async () => {
    const { mockVerisi } = await import("../api/mock/handlers");
    const s = mockVerisi().scriptler.find((x) => x.id === "scr-2")!;
    s.mode = "replay";
    await oturumAc("muhendis");
    uygulama("/kod/scr-2");
    const bant = await screen.findByTestId("replay-bandi");
    expect(bant).toHaveTextContent("koşturuldu.");
    expect(screen.queryByText("Adımlar geliyor")).toBeNull();
  });
});
