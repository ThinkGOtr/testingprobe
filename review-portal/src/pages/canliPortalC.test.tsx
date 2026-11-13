// Canlı UI testi düzeltmeleri (fix/canli-portal-c): Kontrol Kulesi'nde boş veri ile rol kısıtının
// ayrılması.
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { yapilandir } from "../api/http";
import { mockIstek } from "../api/mock/handlers";
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

/** Mock core; `ozel` tanımsız dışında bir değer dönerse o yanıt kullanılır. */
function izle(ozel?: (c: { method: string; path: string }) => unknown) {
  yapilandir({
    mock: async (method, path, q, govde) => {
      const o = ozel?.({ method, path });
      if (o !== undefined) return o;
      return mockIstek(method, path, q, govde);
    },
  });
}

function bosKule() {
  izle((c) => {
    if (c.path === "/control-tower") {
      return (async () => ({ ...((await mockIstek("GET", "/control-tower", new URLSearchParams(), undefined)) as object), karne: [] }))();
    }
    return undefined;
  });
}

describe("Kontrol Kulesi: boş veri ≠ yetkisizlik", () => {
  it("Görüntüleyici: rol notu ('gereksinim ayrıntılarını göremez') + boş karne veri yokluğu olarak açıklanır", async () => {
    bosKule();
    await oturumAc("izleyici");
    uygulama("/kontrol-kulesi");
    expect(await screen.findByTestId("karne-rol-notu")).toHaveTextContent("Bu rol gereksinim ayrıntılarını göremez");
    const bos = screen.getByTestId("karne-bos-neden");
    expect(bos).toHaveTextContent("Henüz case üretilmiş story yok");
    expect(bos).toHaveTextContent("yetki kısıtı değildir");
  });

  it("Denetçi de rol notunu görür; karne doluysa satırlar yine çizilir", async () => {
    izle();
    await oturumAc("denetci");
    uygulama("/kontrol-kulesi");
    expect(await screen.findByTestId("karne-rol-notu")).toBeInTheDocument();
    expect(screen.queryByTestId("karne-bos-neden")).toBeNull();
    expect(within(screen.getByRole("region", { name: "Karne tablosu" })).getAllByRole("row").length).toBeGreaterThan(1);
  });

  it("Analist (requirement.read var): rol notu yok; boş karnede yalnız veri yokluğu", async () => {
    bosKule();
    await oturumAc("analist");
    uygulama("/kontrol-kulesi");
    expect(await screen.findByTestId("karne-bos-neden")).toBeInTheDocument();
    expect(screen.queryByTestId("karne-rol-notu")).toBeNull();
  });
});
