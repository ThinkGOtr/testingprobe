// Faz 2 entegrasyon (tur 2): core'un yeni alanları portalda görünür.
//  - on_inceleme.questions[].kararla_cozuldu → soru "Çözüldü" çipiyle gösterilir, "Cevap bekleniyor" denmez.
//  - case-metrics `uyarilar` (manuel baz yok / REPLAY'de AI süresi ölçülmez) Case review'da görünür.
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { mockVerisi } from "../api/mock/handlers";
import type { CaseMetrikleri, GereksinimDetay as Detay } from "../api/types";
import { onIncelemeUyarla } from "../api/uyum";
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

describe("kararla çözülen ön inceleme sorusu", () => {
  it("uyum katmanı kararla_cozuldu'yu taşır (yoksa alan eklenmez)", () => {
    const on = onIncelemeUyarla({
      verdict: "needs_po",
      questions: [
        { id: "Q1", type: "conflict", text: "t", ac_ref: "AC3", cevap: null, kararla_cozuldu: "doküman düzeltmesiyle cevaplandı: F1 (tur 1)" },
        { id: "Q2", type: "ambiguity", text: "u", ac_ref: null, cevap: null, kararla_cozuldu: null },
        { id: "Q3", type: "ambiguity", text: "v", ac_ref: null, cevap: null },
      ],
      mode: "replay",
      zaman: "z",
    })!;
    expect(on.questions[0].kararla_cozuldu).toMatch(/F1 \(tur 1\)/);
    expect(on.questions[1].kararla_cozuldu).toBeNull();
    expect("kararla_cozuldu" in on.questions[2]).toBe(false);
  });

  it("detayda 'Çözüldü' çipi gösterilir; o soru için 'Cevap bekleniyor' denmez", async () => {
    await oturumAc("analist");
    const g = mockVerisi().gereksinimler.find((x) => x.on_inceleme && x.on_inceleme.questions.length > 1)! as Detay;
    const [ilk, ikinci] = g.on_inceleme!.questions;
    ilk.cevap = null;
    ilk.kararla_cozuldu = "doküman düzeltmesiyle cevaplandı: F1 (tur 1)";
    ikinci.cevap = null;
    ikinci.kararla_cozuldu = null;
    g.po = { ...g.po, durum: "pending" };
    uygulama(`/gereksinimler/${g.id}`);
    const cozuldu = await screen.findByTestId(`soru-cozuldu-${ilk.id}`);
    expect(cozuldu).toHaveTextContent("Çözüldü");
    expect(cozuldu).toHaveTextContent("F1 (tur 1)");
    expect(screen.queryByTestId(`soru-cozuldu-${ikinci.id}`)).not.toBeInTheDocument();
    expect(screen.getAllByText("Cevap bekleniyor").length).toBeGreaterThan(0);
  });
});

describe("case metrik uyarıları", () => {
  it("core'un uyarilar listesi Case review'da gösterilir", async () => {
    await oturumAc("analist");
    const g = mockVerisi().gereksinimler.find((x) => x.durum === "cases_ready") ?? mockVerisi().gereksinimler[0];
    const gercek = api.caseMetrikleri.bind(api);
    vi.spyOn(api, "caseMetrikleri").mockImplementation(async (id: string) => {
      const m = (await gercek(id).catch(() => null)) as CaseMetrikleri | null;
      return {
        ...(m ?? ({} as CaseMetrikleri)),
        uyarilar: ["Manuel baz değer girilmedi (TP_MANUAL_BASELINE_S): Demo-A kazanç gösterilemez."],
      } as CaseMetrikleri;
    });
    uygulama(`/gereksinimler/${g.id}/caseler`);
    const liste = await screen.findByTestId("metrik-uyarilari");
    expect(liste).toHaveTextContent("Manuel baz değer girilmedi");
  });
});
