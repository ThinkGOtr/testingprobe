// Detay sayfa iskeleti (DS-1): sekme erişilebilirliği, klavye, derin bağlantı (?sekme= ve eski çapalar),
// tembel çizim ve durum korunması; gereksinim detayının sekmelere taşınması.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import { mockVerisi } from "../api/mock/handlers";
import { OturumProvider } from "../auth";
import { GEREKSINIM_SEKMESI, gereksinimSiradakiAdim } from "../lib/gereksinimSekmeleri";
import { BOLUM_ID } from "../pages/GereksinimDetay";
import { oturumAc, sekmeAc } from "../test/yardimci";
import { BildirimProvider } from "./Bildirim";
import { DetaySayfasi, OzetKarti, type DetaySekmesi } from "./DetaySayfasi";

function Sayac() {
  const [n, setN] = useState(0);
  return (
    <button type="button" onClick={() => setN(n + 1)}>
      sayaç {n}
    </button>
  );
}

let cizim = 0;
function Pahali() {
  cizim++;
  return <p>pahalı içerik</p>;
}

const SEKMELER: DetaySekmesi[] = [
  { id: "bir", ad: "Bir", icerik: <Sayac /> },
  { id: "iki", ad: "İki", sayi: 3, capalar: ["eski-iki"], icerik: () => <Pahali /> },
  { id: "uc", ad: "Üç", sayi: 0, dikkat: true, icerik: <p id="eski-uc">üç</p> },
];

function Adres() {
  const k = useLocation();
  return <output data-testid="adres">{`${k.pathname}${k.search}${k.hash}`}</output>;
}

function iskelet(yol = "/x", varsayilan?: string) {
  return render(
    <MemoryRouter initialEntries={[yol]}>
      <Routes>
        <Route
          path="/x"
          element={
            <>
              <DetaySayfasi
                sekmeEtiketi="Örnek bölümler"
                varsayilanSekme={varsayilan}
                ozet={<OzetKarti kimlik="TPD-9" baslik="Örnek" siradaki="bir şey yapın." eylemler={<button type="button">Eylem</button>} />}
                serit={<p>şerit</p>}
                sekmeler={SEKMELER}
              />
              <Adres />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("DetaySayfasi iskeleti", () => {
  it("tablist/tab/tabpanel bağları, sayı rozeti ve gezici tabindex", () => {
    iskelet();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("TPD-9 Örnek");
    expect(screen.getByTestId("siradaki-adim")).toHaveTextContent("Sıradaki adım: bir şey yapın.");
    const liste = screen.getByRole("tablist", { name: "Örnek bölümler" });
    const sekmeler = within(liste).getAllByRole("tab");
    expect(sekmeler.map((s) => s.textContent)).toEqual(["Bir", "İki (3)", "Üç (0)"]);
    expect(sekmeler[0]).toHaveAttribute("aria-selected", "true");
    expect(sekmeler[0]).toHaveAttribute("tabindex", "0");
    expect(sekmeler[1]).toHaveAttribute("tabindex", "-1");
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveAttribute("id", sekmeler[0].getAttribute("aria-controls"));
    expect(panel).toHaveAttribute("aria-labelledby", sekmeler[0].id);
    expect(sekmeler[2].querySelector(".ds-sayi-dikkat")).not.toBeNull();
  });

  it("←/→ sarmalı, Home/End; seçim ?sekme='ye yazılır", () => {
    iskelet();
    const tab = (ad: RegExp) => screen.getByRole("tab", { name: ad });
    fireEvent.keyDown(tab(/^Bir/), { key: "ArrowRight" });
    expect(tab(/^İki/)).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("adres")).toHaveTextContent("/x?sekme=iki");
    fireEvent.keyDown(tab(/^İki/), { key: "End" });
    expect(tab(/^Üç/)).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(tab(/^Üç/), { key: "ArrowRight" });
    expect(tab(/^Bir/)).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(tab(/^Bir/), { key: "ArrowLeft" });
    expect(tab(/^Üç/)).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(tab(/^Üç/), { key: "Home" });
    expect(tab(/^Bir/)).toHaveAttribute("aria-selected", "true");
  });

  it("derin bağlantı: ?sekme=, eski çapa (capalar) ve varsayılan; bilinmeyen değer varsayılana düşer", () => {
    const { unmount } = iskelet("/x?sekme=uc");
    expect(screen.getByRole("tab", { name: /^Üç/ })).toHaveAttribute("aria-selected", "true");
    unmount();
    const ikinci = iskelet("/x#eski-iki");
    expect(screen.getByRole("tab", { name: /^İki/ })).toHaveAttribute("aria-selected", "true");
    // Çapadan açılan sekme parametreye de yazılır; hash korunur (Kabuk kaydırır).
    expect(screen.getByTestId("adres")).toHaveTextContent("/x?sekme=iki#eski-iki");
    ikinci.unmount();
    const ucuncu = iskelet("/x?sekme=yok", "uc");
    expect(screen.getByRole("tab", { name: /^Üç/ })).toHaveAttribute("aria-selected", "true");
    ucuncu.unmount();
  });

  it("adreste seçim yokken varsayılanı izler; sekme alanında dokununca o anki sekme sabitlenir", () => {
    const ciz = (v: string) => (
      <MemoryRouter initialEntries={["/x"]}>
        <Routes>
          <Route path="/x" element={<DetaySayfasi sekmeEtiketi="Örnek bölümler" varsayilanSekme={v} ozet={<OzetKarti baslik="Örnek" />} sekmeler={SEKMELER} />} />
        </Routes>
      </MemoryRouter>
    );
    const { rerender } = render(ciz("bir"));
    rerender(ciz("iki"));
    expect(screen.getByRole("tab", { name: /^İki/ })).toHaveAttribute("aria-selected", "true");
    fireEvent.pointerDown(screen.getByText("pahalı içerik"));
    rerender(ciz("uc"));
    expect(screen.getByRole("tab", { name: /^İki/ })).toHaveAttribute("aria-selected", "true");
  });

  it("tembel çizim: panel ilk açılışta bağlanır, sonra gizli tutulur (durum korunur)", () => {
    cizim = 0;
    iskelet();
    expect(screen.queryByText("pahalı içerik")).toBeNull();
    expect(cizim).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "sayaç 0" }));
    fireEvent.click(screen.getByRole("tab", { name: /^İki/ }));
    expect(screen.getByText("pahalı içerik")).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: /^Bir/ }));
    expect(screen.getByText("pahalı içerik")).not.toBeVisible();
    expect(screen.getByRole("button", { name: "sayaç 1" })).toBeVisible();
  });
});

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

describe("gereksinim detayı sekmeleri", () => {
  it("özet kartı + akış şeridi + beş ana sekme; boş sekme gizlenmez, boş durum söyler", async () => {
    await oturumAc("analist");
    uygulama("/gereksinimler/req-ft-1?sekme=tasarim-modeli");
    const liste = await screen.findByRole("tablist", { name: "Gereksinim bölümleri" });
    expect(within(liste).getAllByRole("tab").map((s) => s.textContent?.replace(/ \(\d+\)$/, ""))).toEqual([
      "Doküman",
      "Tasarım modeli",
      "Case'ler",
      "PO teyidi",
      "Tutarlılık",
    ]);
    expect(screen.getByTestId("ozet-karti")).toContainElement(screen.getByRole("heading", { level: 1 }));
    expect(screen.getByRole("navigation", { name: /14 adımlı akış/ })).toBeInTheDocument();
    expect(await screen.findByText("Bu gereksinimde tasarım modeli yok.")).toBeInTheDocument();
    // Eski bölüm gezgini yok.
    expect(screen.queryByRole("navigation", { name: "Sayfa bölümleri" })).toBeNull();
  });

  it("varsayılan sekme sıradaki adımın sekmesi: bulgu kararı bekleyen gereksinimde Tutarlılık", async () => {
    await oturumAc("analist");
    uygulama("/gereksinimler/req-ft-1");
    expect(await screen.findByTestId("siradaki-adim")).toHaveTextContent(/bulgularına karar verin/);
    expect(screen.getByRole("tab", { name: /^Tutarlılık/ })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findAllByRole("article")).toHaveLength(3);
    // Panel dışındaki sekmeler henüz çizilmedi (tembel).
    expect(document.getElementById(BOLUM_ID.po)).toBeNull();
    await sekmeAc("PO teyidi");
    expect(screen.getByRole("region", { name: "PO teyidi" })).toBeVisible();
    expect(screen.getByRole("region", { name: "Ön inceleme soruları" })).toBeVisible();
  });

  it.each([
    [BOLUM_ID.dokuman, "Doküman"],
    [BOLUM_ID.po, "PO teyidi"],
    [BOLUM_ID.sorular, "PO teyidi"],
    [BOLUM_ID.bulgular, "Tutarlılık"],
    [BOLUM_ID.baz, "Case'ler"],
    [BOLUM_ID.ajan, "Case'ler"],
  ])("eski çapa #%s ilgili sekmeyi (%s) açar ve hedef DOM'da", async (capa, sekme) => {
    await oturumAc("analist");
    uygulama(`/gereksinimler/req-ft-1#${capa}`);
    const tab = await screen.findByRole("tab", { name: new RegExp(`^${sekme}`) });
    expect(tab).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("tabpanel")).toBeInTheDocument();
    await vi.waitFor(() => expect(document.getElementById(capa)).not.toBeNull());
  });

  it("#tasarim-modeli: model aşamasında model sekmesi açılır ve panel çizilir", async () => {
    await oturumAc("analist");
    const g = mockVerisi().gereksinimler.find((x) => x.id === "req-tpd-1")!;
    g.durum = "modeling";
    const casus = vi.spyOn(api, "ajanTesti").mockRejectedValue(new ApiError(404, "Not Found"));
    uygulama("/gereksinimler/req-tpd-1#tasarim-modeli");
    expect(await screen.findByRole("tab", { name: /^Tasarım modeli/ })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("region", { name: /Tasarım modeli \(iki tur\)/ })).toHaveAttribute("id", BOLUM_ID.model);
    casus.mockRestore();
  });

  it("asistan çapa sözleşmesi korunur", () => {
    expect(BOLUM_ID.bulgular).toBe("bulgular");
    expect(BOLUM_ID.po).toBe("po-onay");
    expect(BOLUM_ID.model).toBe("tasarim-modeli");
  });
});

describe("gereksinimSiradakiAdim", () => {
  const g = (durum: string, ek: object = {}) => ({ durum, kaynak: "jira" as const, ac_missing: false, ...ek }) as Parameters<typeof gereksinimSiradakiAdim>[0];
  const d = { uretimHatasi: false, ajanBagli: false };
  it.each([
    ["new", GEREKSINIM_SEKMESI.dokuman],
    ["in_review", GEREKSINIM_SEKMESI.tutarlilik],
    ["findings_open", GEREKSINIM_SEKMESI.tutarlilik],
    ["doc_final", GEREKSINIM_SEKMESI.po],
    ["pending_po", GEREKSINIM_SEKMESI.po],
    ["po_approved", GEREKSINIM_SEKMESI.caseler],
    ["modeling", GEREKSINIM_SEKMESI.model],
    ["model_ready", GEREKSINIM_SEKMESI.model],
    ["generating", GEREKSINIM_SEKMESI.caseler],
    ["cases_ready", GEREKSINIM_SEKMESI.caseler],
    ["done", GEREKSINIM_SEKMESI.caseler],
    ["failed", GEREKSINIM_SEKMESI.tutarlilik],
  ])("%s → %s", (durum, sekme) => {
    expect(gereksinimSiradakiAdim(g(durum), d).sekme).toBe(sekme);
  });
  it("üretim hatası Case'ler sekmesine, serbest metin PO teyidi portala yönlendirir", () => {
    expect(gereksinimSiradakiAdim(g("failed"), { ...d, uretimHatasi: true })).toEqual({ metin: "case üretimini yeniden deneyin.", sekme: "caseler" });
    expect(gereksinimSiradakiAdim(g("pending_po", { kaynak: "free_text" }), d).metin).toMatch(/portalda/);
  });
});
