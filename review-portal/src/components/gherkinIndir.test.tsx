// "Gherkin indir" (specs/011 F8): uygunluk kuralı (onaylı + hazır + güncel), kapalı düğme ve nedeni,
// dahil olan case sayısı, indirme ve örnek veri katmanındaki uç (sabit örnek; 404 uygun case yoksa).
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import { V3_GEREKSINIM_ID } from "../api/mock/caseV3";
import { mockVerisi } from "../api/mock/handlers";
import type { TestCase } from "../api/types";
import { OturumProvider } from "../auth";
import { oturumAc, sar } from "../test/yardimci";
import { BildirimProvider } from "./Bildirim";
import { GHERKIN_YOK_NEDENI, GherkinIndir, gherkinDosyaAdi, gherkinUygun } from "./GherkinIndir";

async function caseler(): Promise<TestCase[]> {
  return api.caseler(V3_GEREKSINIM_ID);
}

/** Örnek veride gereksinimin bütün case'lerini taslağa alır (fikstürde onaylı case'ler var). */
function tumunuTaslakYap(): void {
  for (const c of mockVerisi().caseler) if (c.requirement_id === V3_GEREKSINIM_ID) c.durum = "draft";
}

/** Bütün case'ler taslakken ilk hazır v3 case'i onaylı yapar. */
function birHazirOnayla(): string {
  tumunuTaslakYap();
  const c = mockVerisi().caseler.find((x) => x.requirement_id === V3_GEREKSINIM_ID && (x.icerik.readiness ?? "ready") === "ready")!;
  c.durum = "approved";
  return c.id;
}

afterEach(() => vi.restoreAllMocks());

describe("gherkinUygun", () => {
  it("onaylı/yayınlanmış + hazır + güncel case dahil; taslak, hazır olmayan ve önceki içerik dahil değil", async () => {
    await oturumAc("analist");
    const [ornek] = await caseler();
    const hazir = { ...ornek, readiness: "ready" as const, onceki_icerik: false };
    expect(gherkinUygun({ ...hazir, durum: "approved" })).toBe(true);
    expect(gherkinUygun({ ...hazir, durum: "published" })).toBe(true);
    expect(gherkinUygun({ ...hazir, durum: "draft" })).toBe(false);
    expect(gherkinUygun({ ...hazir, durum: "approved", readiness: "assumption_dependent" })).toBe(false);
    expect(gherkinUygun({ ...hazir, durum: "approved", readiness: "blocked" })).toBe(false);
    expect(gherkinUygun({ ...hazir, durum: "approved", onceki_icerik: true })).toBe(false);
    // Eski (v2) case: readiness yok → hazır sayılır (K9).
    const { readiness: _r, ...eski } = { ...hazir, durum: "approved" as const, icerik: { ...hazir.icerik, readiness: undefined } };
    expect(gherkinUygun(eski)).toBe(true);
  });

  it("dosya adı anahtardan güvenli türetilir", () => {
    expect(gherkinDosyaAdi("TPD-1")).toBe("TPD-1.feature");
    expect(gherkinDosyaAdi('a"b/c')).toBe("a_b_c.feature");
  });
});

describe("GherkinIndir düğmesi", () => {
  it("uygun case yoksa kapalı ve nedeni görünür", async () => {
    await oturumAc("analist");
    const liste = (await caseler()).map((c) => ({ ...c, durum: "draft" as const }));
    sar(<GherkinIndir requirementId={V3_GEREKSINIM_ID} anahtar="TPD-9" caseler={liste} />);
    const dugme = await screen.findByRole("button", { name: "Gherkin indir" });
    expect(dugme).toBeDisabled();
    expect(screen.getByText(GHERKIN_YOK_NEDENI)).toBeInTheDocument();
    expect(screen.queryByTestId("gherkin-sayisi")).toBeNull();
  });

  it("dahil olan case sayısını gösterir ve dosyayı indirir", async () => {
    await oturumAc("analist");
    birHazirOnayla();
    const liste = await caseler();
    const uygun = liste.filter(gherkinUygun).length;
    expect(uygun).toBe(1);
    const olustur = vi.fn(() => "blob:gherkin");
    const birak = vi.fn();
    Object.assign(URL, { createObjectURL: olustur, revokeObjectURL: birak });
    const tik = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const cagri = vi.spyOn(api, "gherkin");
    sar(<GherkinIndir requirementId={V3_GEREKSINIM_ID} anahtar="TPD-9" caseler={liste} />);
    expect(screen.getByTestId("gherkin-sayisi").textContent).toMatch(/1 case dahil · \d+ case onay\/hazırlık bekliyor/);
    await userEvent.click(screen.getByRole("button", { name: "Gherkin indir" }));
    await waitFor(() => expect(tik).toHaveBeenCalledTimes(1));
    expect(cagri).toHaveBeenCalledWith(V3_GEREKSINIM_ID);
    expect(olustur).toHaveBeenCalledTimes(1);
    expect(birak).toHaveBeenCalledWith("blob:gherkin");
    const a = tik.mock.instances[0] as unknown as HTMLAnchorElement;
    expect(a.download).toBe("TPD-9.feature");
  });

  it("case review sayfasında yer alır", async () => {
    await oturumAc("analist");
    render(
      <MemoryRouter initialEntries={[`/gereksinimler/${V3_GEREKSINIM_ID}/caseler`]}>
        <OturumProvider>
          <BildirimProvider>
            <Rotalar />
          </BildirimProvider>
        </OturumProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("gherkin-indir")).toBeInTheDocument();
  });
});

describe("örnek veri katmanı: cases.feature", () => {
  it("uygun case yoksa 404, varsa sabit Türkçe Gherkin örneği", async () => {
    await oturumAc("analist");
    tumunuTaslakYap();
    await expect(api.gherkin(V3_GEREKSINIM_ID)).rejects.toSatisfy((e: unknown) => e instanceof ApiError && e.status === 404);
    birHazirOnayla();
    const metin = await api.gherkin(V3_GEREKSINIM_ID);
    expect(metin.startsWith("# language: tr\n")).toBe(true);
    expect(metin).toContain("Özellik:");
    expect(metin).toContain("# 1 case");
    // Yalnız yayınlanan istenirse onaylı (yayınlanmamış) case sayılmaz.
    await expect(api.gherkin(V3_GEREKSINIM_ID, true)).rejects.toSatisfy((e: unknown) => e instanceof ApiError && e.status === 404);
  });
});
