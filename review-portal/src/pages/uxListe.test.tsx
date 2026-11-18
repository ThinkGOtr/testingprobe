// UX liste şeridi (dk/ux-liste): adres durumlu süzgeç/sayfa, sayfalama, satır bağlantısı, Bug taslakları
// görünümü (IA-18), Denetim sıra+hash sütunu ve sayfalaması (DZ-02/DZ-20), açılış uyarılarının rolü (ET-16).
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { Sayfalama, TabloSarici } from "../components/tasarim";
import { sayfaAcildi, Uyari } from "../components/ui";
import { useSayfalama, useSorguSuzgeci } from "../lib/sorguDurumu";
import { oturumAc } from "../test/yardimci";
import { siralamaOku } from "./Gereksinimler";

function Konum() {
  const k = useLocation();
  return <div data-testid="konum">{k.pathname + k.search}</div>;
}

function uygulama(yol: string) {
  return render(
    <MemoryRouter initialEntries={[yol]}>
      <OturumProvider>
        <BildirimProvider>
          <Rotalar />
          <Routes>
            <Route path="*" element={<Konum />} />
          </Routes>
        </BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

function SayfaliListe({ n, boyut }: { n: number; boyut: number }) {
  const liste = Array.from({ length: n }, (_, i) => `oge-${i + 1}`);
  const s = useSayfalama(liste, boyut);
  const f = useSorguSuzgeci({ ara: "" });
  return (
    <>
      <input aria-label="Ara" value={f.deger.ara} onChange={(e) => f.ayarla("ara", e.target.value)} />
      <ul>
        {s.gorunen.map((x) => (
          <li key={x}>{x}</li>
        ))}
      </ul>
      <Sayfalama {...s} birim="öğe" />
      <Konum />
    </>
  );
}

describe("adres durumlu süzgeç ve sayfalama", () => {
  it("sayfa adresten okunur, düğmeler adresi günceller; süzgeç değişince sayfa başa döner", async () => {
    const u = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/x?sayfa=2"]}>
        <SayfaliListe n={23} boyut={10} />
      </MemoryRouter>,
    );
    expect(screen.getAllByRole("listitem").map((l) => l.textContent)[0]).toBe("oge-11");
    expect(screen.getByText("11–20 / 23 öğe")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sayfa 2" })).toHaveAttribute("aria-current", "page");
    await u.click(screen.getByRole("button", { name: /Sonraki/ }));
    expect(screen.getByTestId("konum")).toHaveTextContent("/x?sayfa=3");
    expect(screen.getByRole("button", { name: /Sonraki/ })).toBeDisabled();
    await u.type(screen.getByLabelText("Ara"), "a");
    expect(screen.getByTestId("konum")).toHaveTextContent("/x?ara=a");
    expect(screen.getByText("1–10 / 23 öğe")).toBeInTheDocument();
  });

  it("aralık dışı sayfa son sayfaya kırpılır; tek sayfada sayfalama çizilmez", () => {
    const { unmount } = render(
      <MemoryRouter initialEntries={["/x?sayfa=99"]}>
        <SayfaliListe n={23} boyut={10} />
      </MemoryRouter>,
    );
    expect(screen.getByText("21–23 / 23 öğe")).toBeInTheDocument();
    unmount();
    render(
      <MemoryRouter initialEntries={["/x"]}>
        <SayfaliListe n={5} boyut={10} />
      </MemoryRouter>,
    );
    expect(screen.queryByTestId("sayfalama")).toBeNull();
  });

  it("Gereksinimler sıralaması adresten okunur", () => {
    expect(siralamaOku("cekim-azalan")).toEqual({ alan: "cekim", yon: "azalan" });
    expect(siralamaOku("bilinmeyen")).toBeNull();
  });
});

describe("satır bağlantısı (ET-03)", () => {
  it("satirBaglanti tabloya sınıf ekler; satırın bağlantısı tek odak durağı", () => {
    render(
      <TabloSarici etiket="T" satirBaglanti>
        <tbody>
          <tr>
            <td>
              <a href="/a" className="satir-baglanti">
                A
              </a>
            </td>
          </tr>
        </tbody>
      </TabloSarici>,
    );
    expect(screen.getByRole("table")).toHaveClass("tablo-satir-baglantili");
  });
});

describe("liste ekranları", () => {
  it("Test case'leri: süzgeç adreste; 1024'te ikincil sütunlar sınıfla işaretli, Story ve No tek sütun", async () => {
    await oturumAc("testci");
    const guncel = (await api.caseler()).filter((c) => c.durum !== "superseded");
    const durum = guncel[0].durum;
    const u = userEvent.setup();
    uygulama("/caseler");
    const tablo = await screen.findByRole("table");
    expect(tablo).toHaveClass("tablo-satir-baglantili");
    const basliklar = within(tablo).getAllByRole("columnheader").map((h) => h.textContent);
    expect(basliklar[0]).toBe("Case");
    expect(basliklar).not.toContain("No");
    expect(within(tablo).getByRole("columnheader", { name: "Son karar" })).toHaveClass("sutun-ikincil");
    await u.selectOptions(screen.getByLabelText("Durum"), durum);
    expect(screen.getByTestId("konum")).toHaveTextContent(`durum=${durum}`);
  });

  it("Test case'leri: risk verisi olmayan listede Risk sütunu yok (IA-22)", async () => {
    await oturumAc("testci");
    const riskVar = (await api.caseler()).some((c) => c.durum !== "superseded" && c.icerik.risk);
    uygulama("/caseler");
    const tablo = await screen.findByRole("table");
    expect(within(tablo).queryByRole("columnheader", { name: "Risk" }) !== null).toBe(riskVar);
  });

  it("Bug taslakları: varsayılan 'Karar bekleyen', görünüm adreste (IA-18)", async () => {
    await oturumAc("testci");
    const tum = await api.bugTaslaklari();
    const u = userEvent.setup();
    uygulama("/bug-taslaklari");
    const grup = await screen.findByRole("group", { name: "Görünüm" });
    expect(within(grup).getByRole("button", { name: /Karar bekleyen/ })).toHaveAttribute("aria-pressed", "true");
    await u.click(within(grup).getByRole("button", { name: /Tümü/ }));
    expect(screen.getByTestId("konum")).toHaveTextContent("gorunum=tumu");
    const tablo = await screen.findByRole("table");
    expect(within(tablo).getAllByRole("row")).toHaveLength(tum.length + 1);
  });

  it("Denetim: sıra ve hash tek sütunda; arama adreste", async () => {
    await oturumAc("sunucu");
    const u = userEvent.setup();
    uygulama("/denetim");
    const tablo = await screen.findByRole("table");
    const basliklar = within(tablo).getAllByRole("columnheader").map((h) => h.textContent);
    expect(basliklar).not.toContain("Hash");
    expect(basliklar[0]).toContain("hash");
    await u.type(screen.getByLabelText("Ara"), "x");
    expect(screen.getByTestId("konum")).toHaveTextContent("/denetim?ara=x");
  });
});

describe("açılış uyarılarının rolü (ET-16)", () => {
  it("sayfa açılışında var olan hata kutusu note; kullanıcı eyleminden sonra beliren alert", async () => {
    act(() => sayfaAcildi());
    const { unmount } = render(<Uyari ton="hata">Açılışta</Uyari>);
    expect(screen.getByRole("note")).toHaveTextContent("Açılışta");
    unmount();
    // Saat çözünürlüğü: etkileşim açılıştan sonra kaydedilsin.
    await new Promise((r) => setTimeout(r, 5));
    await userEvent.setup().click(document.body);
    render(<Uyari ton="hata">Eylem sonrası</Uyari>);
    expect(screen.getByRole("alert")).toHaveTextContent("Eylem sonrası");
  });
});
