// Canlı UI testi düzeltmeleri (fix/canli-portal-b): Jira çekim onayı, gereksinim sıralaması,
// rol adı tutarlılığı, yetkisiz çağrıların koşullanması, 422 → bulunamadı, takılmış koşu uyarısı vb.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { yapilandir } from "../api/http";
import { mockIstek } from "../api/mock/handlers";
import type { Gereksinim } from "../api/types";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { izinRolleriMetni } from "../lib/yetki";
import { oturumAc } from "../test/yardimci";
import { gereksinimSirala, jiraCekimMetni, jiraProjeleri } from "./Gereksinimler";

export function uygulama(yol: string) {
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

type Cagri = { method: string; path: string; govde: unknown };
export function izle(ozel?: (c: Cagri) => unknown) {
  const cagrilar: Cagri[] = [];
  yapilandir({
    mock: async (method, path, q, govde) => {
      const c = { method, path, govde };
      cagrilar.push(c);
      const o = ozel?.(c);
      if (o !== undefined) return o;
      return mockIstek(method, path, q, govde);
    },
  });
  return cagrilar;
}

describe("Jira'dan çek: onay penceresi", () => {
  it("düğme hemen POST göndermez; proje adıyla onay sorar, İptal çekmez, Çek çeker", async () => {
    const cagrilar = izle();
    await oturumAc("analist");
    uygulama("/gereksinimler");
    const dugme = await screen.findByRole("button", { name: "Jira'dan çek" });
    await userEvent.click(dugme);
    const onay = await screen.findByTestId("jira-cek-onay");
    expect(cagrilar.some((c) => c.path === "/requirements/sync")).toBe(false);
    expect(within(onay).getByText(/Jira'ya bir şey yazılmaz/)).toBeInTheDocument();
    expect(within(onay).getByText(/\(TPD\)/)).toBeInTheDocument();
    await userEvent.click(within(onay).getByRole("button", { name: "İptal" }));
    expect(screen.queryByTestId("jira-cek-onay")).toBeNull();
    expect(cagrilar.some((c) => c.path === "/requirements/sync")).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Jira'dan çek" }));
    await userEvent.click(within(await screen.findByTestId("jira-cek-onay")).getByRole("button", { name: "Çek" }));
    await waitFor(() => expect(cagrilar.some((c) => c.method === "POST" && c.path === "/requirements/sync")).toBe(true));
  });

  it("proje anahtarı listeden türetilir; yoksa genel metin", () => {
    expect(jiraProjeleri([{ jira_key: "TPD-1" }, { jira_key: null }, { jira_key: "TPD-12" }, { jira_key: "ABC-3" }])).toEqual(["ABC", "TPD"]);
    expect(jiraCekimMetni([])).toMatch(/^Yapılandırılmış Jira projesindeki/);
    expect(jiraCekimMetni(["TPD"])).toMatch(/\(TPD\)/);
  });
});

describe("gereksinim tablosu sıralaması", () => {
  const g = (jira_key: string | null, baslik: string, bulgu = 0): Gereksinim =>
    ({
      id: baslik,
      jira_key,
      baslik,
      durum: "new",
      ac_missing: false,
      po: { durum: "not_requested" },
      sayaclar: { bulgu_acik: bulgu, case_toplam: 0, case_onayli: 0 },
      cekim_zamani: "2026-11-01T00:00:00Z",
    }) as unknown as Gereksinim;

  it("anahtar sayı farkında, başlık tr-TR, yön değişir", () => {
    const l = [g("TPD-10", "Ç"), g("TPD-2", "A"), g(null, "B")];
    expect(gereksinimSirala(l, { alan: "anahtar", yon: "artan" }).map((x) => x.jira_key)).toEqual([null, "TPD-2", "TPD-10"]);
    expect(gereksinimSirala(l, { alan: "baslik", yon: "azalan" }).map((x) => x.baslik)).toEqual(["Ç", "B", "A"]);
  });

  it("başlıklar düğmedir ve aria-sort taşır", async () => {
    await oturumAc("analist");
    uygulama("/gereksinimler");
    const anahtar = await screen.findByRole("button", { name: /^Anahtar/ });
    const th = anahtar.closest("th")!;
    expect(th).toHaveAttribute("aria-sort", "none");
    await userEvent.click(anahtar);
    expect(th).toHaveAttribute("aria-sort", "ascending");
    await userEvent.click(anahtar);
    expect(th).toHaveAttribute("aria-sort", "descending");
  });
});

describe("rol adı tutarlılığı", () => {
  it("izin rolleri metni rol etiketlerinden gelir (Automation Engineer)", () => {
    expect(izinRolleriMetni("automation.manage")).toBe("Analist ve Automation Engineer");
    expect(izinRolleriMetni("testdata.manage")).toBe("Analist, Testçi ve Automation Engineer");
    expect(izinRolleriMetni("automation.jira_status")).toBe("Automation Engineer");
  });
});
