// Tasarım yenileme Şerit D (docs/TASARIM-YENILEME-PLANI.md §4.10, §5, §6.1 #4–#6): yol haritasında tür
// DOM'da (data-tur), bulgu kartında durum DOM'da (data-durum), Kontrol Kulesi'nde REPLAY'de maliyet
// "REPLAY — ölçülmedi"; akış/yol haritası stil kuralları (tür = biçim + renk, eski durum renkleri yok).
import { render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ayar } from "../api/mock/handlers";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { AKIS_ADIMLARI, BULGU_DURUMU } from "../lib/etiketler";
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

beforeEach(() => {
  ayar.isAdimiMs = 0;
});
afterEach(() => {
  vi.restoreAllMocks();
});

const css = () => readFileSync(resolve(__dirname, "../styles.css"), "utf8");

describe("Yol haritası: daire = tür (data-tur)", () => {
  it("14 adımın her satırı akıştaki türünü data-tur ile taşır; data-hal aynen kalır", async () => {
    await oturumAc("sunucu");
    uygulama("/yol-haritasi");
    const liste = await screen.findByRole("list", { name: "14 adımlı demo akışı" });
    const ogeler = within(liste).getAllByRole("listitem").filter((li) => li.classList.contains("yh-adim"));
    expect(ogeler).toHaveLength(14);
    expect(ogeler.map((li) => li.getAttribute("data-tur"))).toEqual(AKIS_ADIMLARI.map((a) => a.tur));
    for (const li of ogeler) expect(li.getAttribute("data-hal")).toMatch(/^(tamam|suruyor|bekliyor|engel|yedek)$/);
    // Locator yolu satırları da türünü taşır.
    const loc = screen.getByRole("list", { name: "Test bakımı yolu" });
    for (const li of within(loc).getAllByRole("listitem").filter((x) => x.classList.contains("yh-adim"))) {
      expect(li.getAttribute("data-tur")).toMatch(/^(sistem|ai|insan|ai_insan)$/);
    }
  });

  it("stil: eski durum renkli daire kuralları yok; daire [data-tur] ile çizilir", () => {
    const s = css();
    expect(s).not.toMatch(/\.yh-adim\.yh-(suruyor|engel|yedek) \.yh-no/);
    expect(s).not.toMatch(/\.yh-adim\.yh-tamam \.yh-no \{[^}]*--ok-bg/);
    for (const tur of ["ai", "insan", "ai_insan"]) expect(s).toContain(`.yh-adim[data-tur="${tur}"] .yh-no`);
  });
});

describe("Akış göstergesi: tür = biçim + renk (§4.10)", () => {
  it("stil: tamam adımı AI'nin kesik kenarını ezmez (dolu indigo/solid kural yok); tür renkleri tanımlı", () => {
    const s = css();
    const tamam = s.match(/\.akis-tamam \.akis-no \{([^}]*)\}/)?.[1] ?? "";
    expect(tamam).not.toMatch(/border-style|border-color|var\(--accent\)/);
    expect(s).toMatch(/\.akis-tur-ai \.akis-no \{[^}]*dashed var\(--vurgu\)/);
    expect(s).toMatch(/\.akis-tur-insan \.akis-no \{[^}]*solid var\(--ok\)/);
    expect(s).toMatch(/\.akis-tur-ai_insan \.akis-no \{[^}]*dashed var\(--vurgu\)[^}]*inset 0 0 0 2px var\(--ok\)/);
    expect(s).toMatch(/\.akis-simdi \.akis-no \{[^}]*0 0 0 5px var\(--accent\)/);
  });
  it("stil: tamam dolgusu kesik kenarın altına boyanmaz (background-clip: padding-box; akış ve yol haritası)", () => {
    const s = css();
    expect(s).toMatch(/(^|\n)\.akis-no \{[^}]*background-clip: padding-box/);
    expect(s).toMatch(/(^|\n)\.yh-no \{[^}]*background-clip: padding-box/);
  });
});

describe("Bulgu kartı: durum DOM'da (data-durum)", () => {
  it("her bulgu article'ı core durumunu data-durum ile taşır; sayım (3) aynen", async () => {
    await oturumAc("analist");
    uygulama("/gereksinimler/req-ft-1");
    await waitFor(() => expect(screen.getAllByRole("article")).toHaveLength(3));
    for (const a of screen.getAllByRole("article")) {
      expect(a).toHaveClass("bulgu");
      expect(Object.keys(BULGU_DURUMU)).toContain(a.getAttribute("data-durum"));
    }
  });

  it("stil: kapanmış bulgu nötr şerit alır", () => {
    expect(css()).toMatch(
      /article\.bulgu:is\(\[data-durum="decided"\], \[data-durum="resolved"\], \[data-durum="stale"\], \[data-durum="discarded"\]\) \{\s*border-left-color: var\(--border-strong\)/,
    );
  });
});

describe("Kontrol Kulesi: REPLAY'de maliyet ölçülmedi (§4.12)", () => {
  async function kule(ai: Record<string, unknown>) {
    await oturumAc("sunucu");
    const orj = await api.kontrolKulesi();
    vi.spyOn(api, "kontrolKulesi").mockResolvedValue({ ...orj, ai_katkisi: { ...orj.ai_katkisi, ...ai } });
    uygulama("/kontrol-kulesi");
    const etiket = await screen.findByText("Maliyet (toplam)");
    const maliyet = etiket.closest(".metrik") as HTMLElement;
    const bugun = screen.getByText("Bugün").closest(".metrik") as HTMLElement;
    return { maliyet, bugun };
  }

  it("tüm çağrılar REPLAY → 'Maliyet (toplam)' ve 'Bugün' değeri 'REPLAY — ölçülmedi'; alt satırlar aynen", async () => {
    const { maliyet, bugun } = await kule({ cagri_sayisi: 12, replay_cagri: 12, maliyet_usd_toplam: 0, maliyet_usd_bugun: 0, gunluk_butce_usd: 5 });
    expect(within(maliyet).getByText("REPLAY — ölçülmedi")).toBeInTheDocument();
    expect(within(bugun).getByText("REPLAY — ölçülmedi")).toBeInTheDocument();
    expect(maliyet).not.toHaveTextContent(/\$0/);
    expect(bugun).not.toHaveTextContent(/\$0/);
    expect(maliyet).toHaveTextContent("12 model çağrısı");
    expect(bugun).toHaveTextContent(/Günlük tavan/);
  });

  it("karışık kipte (canlı çağrı var) ölçülen maliyet gösterilir", async () => {
    const { maliyet } = await kule({ cagri_sayisi: 12, replay_cagri: 4, maliyet_usd_toplam: 0.42, maliyet_usd_bugun: 0.1 });
    expect(within(maliyet).queryByText("REPLAY — ölçülmedi")).toBeNull();
    expect(maliyet).toHaveTextContent(/0,42/);
  });

  it("null koruması: çağrı sayısı bilinmiyorsa REPLAY sayılmaz ('REPLAY — ölçülmedi' demez)", async () => {
    const { maliyet, bugun } = await kule({ cagri_sayisi: null, replay_cagri: null, maliyet_usd_toplam: 0, maliyet_usd_bugun: null });
    expect(within(maliyet).queryByText("REPLAY — ölçülmedi")).toBeNull();
    expect(within(bugun).queryByText("REPLAY — ölçülmedi")).toBeNull();
    expect(within(bugun).getByText("ölçülmedi")).toBeInTheDocument();
  });

  it("çağrı sayısı 0 iken (0 === 0) REPLAY sayılmaz", async () => {
    const { maliyet } = await kule({ cagri_sayisi: 0, replay_cagri: 0, maliyet_usd_toplam: 0 });
    expect(within(maliyet).queryByText("REPLAY — ölçülmedi")).toBeNull();
  });
});
