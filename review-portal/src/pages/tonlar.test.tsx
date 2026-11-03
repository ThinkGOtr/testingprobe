// Tasarım yenileme §4.6: mor (`vurgu`) yalnız AI'a ayrılır; AI olmayan kategorik çipler `notr`,
// insan incelemesi bekleyen durumlar `bilgi` (indigo).
import { render, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { Kosu, Tetik } from "../api/types";
import { GEREKSINIM_DURUMU, SCRIPT_DURUMU } from "../lib/etiketler";
import { KosuTablosu } from "./Kosular";

function kosu(id: string, tetik: Tetik, kaynak: Kosu["kaynak"], ek: Partial<Kosu> = {}): Kosu {
  return {
    id,
    tetik,
    kaynak,
    commit: "abc1234",
    pr_no: null,
    durum: "passed",
    baslangic: "2026-11-03T10:00:00Z",
    sure_ms: 1000,
    toplam: 1,
    gecen: 1,
    basarisiz: 0,
    flaky: 0,
    atlanan: 0,
    allure_url: null,
    rapor_url: null,
    sauce_url: null,
    ci_url: null,
    break_campaign: false,
    script_id: null,
    ...ek,
  } as Kosu;
}

describe("ton disiplini (§4.6)", () => {
  it("Case review ve PR açık `bilgi`; diğer script durumları değişmez", () => {
    expect(GEREKSINIM_DURUMU.cases_ready.ton).toBe("bilgi");
    expect(SCRIPT_DURUMU.pr_open.ton).toBe("bilgi");
    expect(SCRIPT_DURUMU.blocked.ton).toBe("uyari");
    expect(SCRIPT_DURUMU.merged.ton).toBe("basari");
  });

  it("koşu tetiği (gece/deploy) ve kaynak çipleri nötr; kırarak doğrula ve kırma çipi amber kalır", () => {
    const kosular = [
      kosu("run-g", "nightly", "sauce"),
      kosu("run-d", "deploy", "github"),
      kosu("run-k", "break_verify", "local", { break_campaign: true }),
    ];
    const { getByRole } = render(
      <MemoryRouter>
        <KosuTablosu kosular={kosular} />
      </MemoryRouter>,
    );
    const tablo = getByRole("region", { name: "Koşular tablosu" });
    for (const metin of ["Gece", "Deploy", "Sauce Labs", "GitHub Actions", "Yerel Chromium"]) {
      expect(within(tablo).getByText(metin)).toHaveClass("cip", "cip-notr");
    }
    expect(within(tablo).getByText("Kırarak doğrula")).toHaveClass("cip-uyari");
    expect(within(tablo).getByText("kırma")).toHaveClass("cip-uyari");
    expect(tablo.querySelector(".cip-vurgu")).toBeNull();
  });
});
