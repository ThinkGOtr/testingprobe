// UX denetimi IA-03 / IA-04 / IA-06 / IA-07: tek tutarlı durum modeli.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import type { Gereksinim, TestCase } from "../api/types";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { onayaHazirDegil } from "../lib/caseV3";
import {
  bolumSirasi,
  oncekiTurMetni,
  siradakiAdim,
  siradakiMetni,
  surumDurumCumlesi,
  surumKumeleri,
  tasarimModeliBayat,
  tumCaseSayisi,
  varsayilanSekme,
  varsayilanSurum,
} from "../lib/durumModeli";
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

afterEach(() => vi.restoreAllMocks());

const g = (durum: Gereksinim["durum"], ek: Partial<Gereksinim> = {}) => ({ durum, ac_missing: false, ...ek });

describe("lib/durumModeli", () => {
  it("sıradaki adım: core alanı öncelikli, yoksa durumdan türetilir (kimi bekliyor)", () => {
    expect(siradakiMetni(siradakiAdim(g("new")))).toBe("Ön inceleme · Analist");
    expect(siradakiMetni(siradakiAdim(g("pending_po")))).toMatch(/^PO teyidi · /);
    expect(siradakiAdim(g("new", { ac_missing: true })).ad).toBe("Kabul kriteri eksik · PO'ya sor");
    expect(siradakiMetni(siradakiAdim(g("generating")))).toBe("Case üretimi sürüyor");
    const core = { adim_no: 3, ad: "PO teyidi", rol: "po" as const, rol_etiketi: "Ürün Sahibi (PO)" };
    expect(siradakiAdim(g("new", { siradaki: core }))).toBe(core);
  });

  it("önceki tur metni ve toplam case sayısı", () => {
    expect(oncekiTurMetni(null)).toBeNull();
    expect(oncekiTurMetni({ case_toplam: 15, case_onayli: 15, case_yayinda: 15, pr_birlesen: 8 })).toBe("Önceki tur: 15 case yayında, 8 PR birleşti");
    expect(oncekiTurMetni({ case_toplam: 3, case_onayli: 0, case_yayinda: 0, pr_birlesen: 0 })).toBe("Önceki tur: 3 case");
    expect(tumCaseSayisi({ sayaclar: { bulgu_acik: 0, case_toplam: 0, case_onayli: 0 }, onceki_tur: { case_toplam: 15, case_onayli: 15, case_yayinda: 15, pr_birlesen: 8 } })).toBe(15);
  });

  it("sürüm kümeleri: önceki sürüm ayrı; güncel yoksa varsayılan önceki; durum cümlesi sıradaki adımı söyler", () => {
    const c = (id: string, onceki: boolean, durum: TestCase["durum"] = "published") => ({ id, onceki_icerik: onceki, durum });
    const k = surumKumeleri([c("a", true), c("b", true), c("x", false, "superseded")]);
    expect([k.guncel.length, k.onceki.length]).toEqual([0, 2]);
    expect(varsayilanSurum(k)).toBe("onceki");
    expect(surumDurumCumlesi(g("new"), k)).toMatch(/Bu 2 case gereksinimin önceki sürümüne ait.*Sıradaki adım: Ön inceleme · Analist\./);
    const k2 = surumKumeleri([c("a", true), c("b", false, "draft")]);
    expect(varsayilanSurum(k2)).toBe("guncel");
    expect(surumDurumCumlesi(g("cases_ready"), k2)).toMatch(/^1 case gereksinimin önceki sürümüne ait/);
    expect(surumDurumCumlesi(g("cases_ready"), surumKumeleri([c("b", false)]))).toBeNull();
  });

  it("hazır değil: yalnız karar bekleyen güncel case (yayınlanmış ve önceki sürüm sayılmaz)", () => {
    const tc = (ek: Partial<TestCase>) => ({ readiness: "ready", icerik: {}, onay_engeli: "Karar yalnızca taslak…", ...ek }) as unknown as TestCase;
    expect(onayaHazirDegil(tc({ durum: "published" }))).toBe(false);
    expect(onayaHazirDegil(tc({ durum: "approved" }))).toBe(false);
    expect(onayaHazirDegil(tc({ durum: "draft", onceki_icerik: true }))).toBe(false);
    expect(onayaHazirDegil(tc({ durum: "draft" }))).toBe(true);
  });

  it("tasarım modeli bayatlığı ve varsayılan sekme / bölüm sırası (bayat model asla varsayılan değil)", () => {
    const m = (guncel: boolean, durum: "draft" | "approved" | "superseded" = "approved") => ({ guncel, durum, surum: 1 });
    expect(tasarimModeliBayat(g("new"), m(false))).toEqual({ bayat: true, ozet: "Tasarım modeli v1 · eski içeriğe ait · PO teyidinden sonra yeniden üretilecek" });
    expect(tasarimModeliBayat(g("cases_ready"), m(true)).bayat).toBe(false);
    expect(tasarimModeliBayat(g("done"), m(true, "superseded")).bayat).toBe(true);
    expect(tasarimModeliBayat(g("new"), null).bayat).toBe(false);

    expect(varsayilanSekme(g("findings_open"), "analyst", false)).toBe("tutarlilik");
    expect(varsayilanSekme(g("findings_open"), "viewer", false)).toBe("dokuman");
    expect(varsayilanSekme(g("pending_po"), "po", false)).toBe("po-teyidi");
    expect(varsayilanSekme(g("cases_ready"), "tester", false)).toBe("caseler");
    expect(varsayilanSekme(g("model_ready"), "tester", false)).toBe("tasarim-modeli");
    expect(varsayilanSekme(g("model_ready"), "tester", true)).toBe("dokuman");
    expect(bolumSirasi(g("findings_open"), true)).toEqual(["tutarlilik", "po-teyidi", "dokuman", "caseler", "tasarim-modeli"]);
    expect(bolumSirasi(g("pending_po"), false)[0]).toBe("po-teyidi");
  });
});

describe("Gereksinimler listesi (IA-03)", () => {
  it("Sıradaki sütunu kimi beklediğini, tur ve önceki tur ürünlerini gösterir; case sütunu güncel sürümü sayar", async () => {
    await oturumAc("analist");
    const liste = await api.gereksinimler();
    const ilk = liste.find((x) => x.durum !== "done") ?? liste[0];
    vi.spyOn(api, "gereksinimler").mockResolvedValue([
      {
        ...ilk,
        durum: "new",
        ac_missing: false,
        tur: 2,
        sayaclar: { bulgu_acik: 0, case_toplam: 0, case_onayli: 0 },
        siradaki: { adim_no: 2, ad: "Ön inceleme", rol: "analyst", rol_etiketi: "Analist" },
        onceki_tur: { case_toplam: 15, case_onayli: 15, case_yayinda: 15, pr_birlesen: 8 },
      },
    ]);
    uygulama("/gereksinimler");
    const tablo = await screen.findByRole("table");
    expect(within(tablo).getByRole("button", { name: /Sıradaki/ })).toBeInTheDocument();
    expect(within(tablo).getByTestId("gereksinim-siradaki")).toHaveTextContent("Ön inceleme · Analist");
    expect(within(tablo).getByTestId("gereksinim-tur")).toHaveTextContent("Tur 2");
    expect(within(tablo).getByTestId("gereksinim-onceki-tur")).toHaveTextContent("Önceki tur: 15 case yayında, 8 PR birleşti");
  });

  it("veri gelmeden boş durum göstermez (yükleniyor)", async () => {
    await oturumAc("analist");
    vi.spyOn(api, "gereksinimler").mockReturnValue(new Promise(() => {}));
    uygulama("/gereksinimler");
    await screen.findByRole("heading", { name: "Gereksinimler", level: 1 });
    expect(screen.queryByText("Henüz gereksinim yok.")).not.toBeInTheDocument();
  });
});

describe("Case review sürüm ayrımı (IA-04)", () => {
  it("tüm case'ler önceki sürümdeyse tepede tek durum cümlesi, Önceki sürüm sekmesi, kartta 'Önceki sürüm' rozeti", async () => {
    await oturumAc("testci");
    const gercek = await api.caseler("req-tpd-1");
    const eski = gercek.filter((c) => c.durum !== "superseded").map((c) => ({ ...c, onceki_icerik: true }));
    vi.spyOn(api, "caseler").mockResolvedValue(eski);
    uygulama("/gereksinimler/req-tpd-1/caseler");
    const durum = await screen.findByTestId("case-surum-durumu");
    expect(durum).toHaveTextContent(`Bu ${eski.length} case gereksinimin önceki sürümüne ait`);
    const secici = await screen.findByTestId("case-surum-secici");
    expect(within(secici).getByRole("button", { name: `Önceki sürüm (${eski.length})` })).toHaveAttribute("aria-pressed", "true");
    expect(within(secici).getByRole("button", { name: "Güncel (0)" })).toBeInTheDocument();
    expect((await screen.findAllByTestId("case-onceki-surum")).length).toBe(eski.length);
    expect(within(document.querySelector(".case-liste") as HTMLElement).queryAllByTestId("case-hazirlik")).toHaveLength(0);
    // Önceki sürüm case'leri "Hazır değil" sayılmaz.
    expect(screen.getByRole("button", { name: "Hazır değil (0)" })).toBeInTheDocument();
    await userEvent.click(within(secici).getByRole("button", { name: "Güncel (0)" }));
    expect(await screen.findByText("Güncel sürüm için henüz case yok.")).toBeInTheDocument();
  });
});
