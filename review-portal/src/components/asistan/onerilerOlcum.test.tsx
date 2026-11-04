// Kontrol Kulesi "Öneriler ve asistan" kartı (AI-ASISTAN-PLANI §17.7, §6.4): kural başına sayılar,
// asistan maliyet grubu, boş durum, kaldırılmış kural etiketi; `asistan` bölümü yoksa kart yok;
// kişi bazlı alan çizilmez.
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { kontrolKulesiUyarla } from "../../api/uyumDemoB";
import { OnerilerOlcumKarti, type AsistanKuleOlcumu, type OneriOlcumSatiri } from "./OnerilerOlcumKarti";

function satir(kural_id: string, ek: Partial<OneriOlcumSatiri> = {}): OneriOlcumSatiri {
  return { kural_id, baslik: `Başlık ${kural_id}`, ekran: "/requirements/:id", kural_setinde: true, neden_sor: 0, faydali: 0, gizle: 0, yaptim: 0, ...ek };
}

function olcum(oneriler: OneriOlcumSatiri[]): AsistanKuleOlcumu {
  const toplam = { neden_sor: 0, faydali: 0, gizle: 0, yaptim: 0 };
  for (const s of oneriler) {
    toplam.neden_sor += s.neden_sor;
    toplam.faydali += s.faydali;
    toplam.gizle += s.gizle;
    toplam.yaptim += s.yaptim;
  }
  return {
    maliyet: {
      asistan: { cagri: 3, maliyet_usd: 0.2, maliyet_usd_bugun: 0.1, amaclar: ["assistant", "assistant_deep"] },
      diger: { cagri: 1, maliyet_usd: 0.5, maliyet_usd_bugun: 0.5, amaclar: ["case_generation"] },
    },
    oneriler,
    oneri_toplam: toplam,
    saklama_gun: 90,
  };
}

describe("OnerilerOlcumKarti", () => {
  it("asistan bölümü yoksa çizilmez (eski core; uydurulmaz)", () => {
    const { container } = render(<OnerilerOlcumKarti kule={{ kaynaklar: {} }} />);
    expect(container).toBeEmptyDOMElement();
    const { container: c2 } = render(<OnerilerOlcumKarti kule={{ asistan: null }} />);
    expect(c2).toBeEmptyDOMElement();
  });

  it("kural başına sayılar, toplamlar ve asistan maliyet grubu", () => {
    const veri = olcum([
      satir("gereksinim-ac-eksik", { neden_sor: 2, faydali: 2, gizle: 1 }),
      satir("case-inceleme-bekliyor", { yaptim: 1, gizle: 1 }),
      satir("sessiz-kural"),
      satir("eski-kural", { baslik: null, ekran: null, kural_setinde: false, neden_sor: 1 }),
    ]);
    render(<OnerilerOlcumKarti kule={{ asistan: veri, kaynaklar: { asistan: "ai_call.maliyet …" } }} />);

    expect(screen.getByRole("heading", { name: "Öneriler ve asistan" })).toBeInTheDocument();
    expect(screen.getByTestId("asistan-maliyet").textContent).toMatch(/0[.,]20/);
    expect(screen.getByText(/3 model çağrısı · assistant, assistant_deep/)).toBeInTheDocument();
    expect(screen.getByTestId("oneri-toplam-neden")).toHaveTextContent("3");
    expect(screen.getByTestId("oneri-toplam-geri-bildirim")).toHaveTextContent("2 / 2 / 1");
    expect(screen.getByTestId("oneri-olcum-kaynak")).toHaveAttribute("aria-label", "Kaynak: ai_call.maliyet …");

    const tablo = screen.getByTestId("oneri-olcum-tablosu");
    const basliklar = within(tablo).getAllByRole("columnheader").map((h) => h.textContent);
    expect(basliklar).toEqual(["Kural", "Neden? Sor", "Faydalı", "Gizle", "Yaptım"]);
    const satirlar = within(tablo).getAllByRole("row").slice(1);
    // Etkileşimsiz kural tabloya girmez, altta sayılır.
    expect(satirlar).toHaveLength(3);
    const ilk = within(satirlar[0]).getAllByRole("cell").map((c) => c.textContent);
    expect(ilk[0]).toContain("Başlık gereksinim-ac-eksik");
    expect(ilk.slice(1)).toEqual(["2", "2", "1", "0"]);
    // Kaldırılmış kural: kimlikle gösterilir, etiketli.
    expect(within(satirlar[2]).getByText("kaldırıldı")).toBeInTheDocument();
    expect(within(satirlar[2]).getAllByText("eski-kural").length).toBeGreaterThan(0);
    expect(screen.getByText(/Son 90 gün · kural başına toplam; kişi bazlı rapor/)).toHaveTextContent("1 kuralda henüz etkileşim yok.");
  });

  it("etkileşim yoksa boş durum; tablo yok", () => {
    render(<OnerilerOlcumKarti kule={{ asistan: olcum([satir("a"), satir("b")]) }} />);
    expect(screen.getByText("Henüz öneri etkileşimi yok.")).toBeInTheDocument();
    expect(screen.queryByTestId("oneri-olcum-tablosu")).toBeNull();
    expect(screen.getByTestId("oneri-olcum-kaynak")).toHaveAttribute("aria-label", "Kaynak: core bu ölçünün kaynağını bildirmedi");
  });

  it("kişi bazlı alan çizmez: yalnız kural ve sayı sütunları", () => {
    const veri = olcum([satir("r1", { faydali: 1 })]);
    // Yanıta sızmış olsa bile (olmamalı) kullanıcı alanı çizilmez.
    (veri.oneriler[0] as unknown as Record<string, unknown>).kullanici_adi = "ayse";
    render(<OnerilerOlcumKarti kule={{ asistan: veri }} />);
    expect(screen.queryByText(/ayse/)).toBeNull();
  });

  it("canlı core yanıtı: Kule uyarlayıcısı asistan bölümünü ve kaynağını korur (kart çizilir)", () => {
    const k = kontrolKulesiUyarla({
      kaynaklar: { asistan: "asistan_mesaj + asistan_oneri_geri_bildirim" },
      asistan: {
        maliyet: { asistan: { cagri: 2, maliyet_usd: 0.3, maliyet_usd_bugun: 0.1, amaclar: ["assistant"] }, diger: { cagri: 1, maliyet_usd: 1, maliyet_usd_bugun: 0.5, amaclar: [] } },
        oneriler: [{ kural_id: "r1", baslik: "Kural 1", ekran: "/runs/:id", kural_setinde: true, neden_sor: 1, faydali: 2, gizle: 0, yaptim: 0 }],
        oneri_toplam: { neden_sor: 1, faydali: 2, gizle: 0, yaptim: 0 },
        saklama_gun: 90,
      },
    });
    render(<OnerilerOlcumKarti kule={k} />);
    expect(screen.getByRole("heading", { name: "Öneriler ve asistan" })).toBeInTheDocument();
    expect(screen.getByTestId("oneri-toplam-geri-bildirim")).toHaveTextContent("2 / 0 / 0");
    expect(screen.getByTestId("oneri-olcum-kaynak")).toHaveAttribute("aria-label", "Kaynak: asistan_mesaj + asistan_oneri_geri_bildirim");
    // Eski core (bölüm yok): kart çizilmez.
    expect(kontrolKulesiUyarla({}).asistan).toBeNull();
  });
});
