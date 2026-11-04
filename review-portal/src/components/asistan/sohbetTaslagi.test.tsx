// Sohbet taslağının ekrana bağlı parçaları: kaldırılan ekran çipi panel kapalıyken / Öneriler
// sekmesindeyken yapılan gezinmede de düşer (A → B → A dönüşünde çip geri gelir); bekletilen
// "Neden? Sor" sorusu başka ekranda gönderilirse öneri kuralı gitmez. HataKutusu'nda yalnız metin
// canlı bölgededir ("Asistana sor" / "Tekrar dene" kardeş öğe).
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { asistanApi } from "../../api/asistan";
import { ApiError } from "../../api/http";
import { asistanMockAyarla, asistanMockBekleyenler, asistanMockIsle } from "../../api/mock/asistan";
import { OturumProvider } from "../../auth";
import { hataKaydet, sonHatayiSifirla } from "../../lib/sonHata";
import { oturumAc } from "../../test/yardimci";
import { BildirimProvider } from "../Bildirim";
import { HataKutusu } from "../ui";
import { AsistanPaneli } from "./AsistanPaneli";
import { acSekme, asistanKontrolSifirla } from "./kontrol";
import { ekOneriSohbetleriniSifirla } from "./OneriEkOneriler";
import { NEDEN_SORUSU } from "./OneriKarti";
import { oneriAyar, oneriDeposunuSifirla } from "./OneriVerisi";
import { sohbetAyar } from "./SohbetSekmesi";

function Gezgin() {
  const git = useNavigate();
  return (
    <>
      <button type="button" onClick={() => git("/gereksinimler")}>
        Gereksinimlere git
      </button>
      <button type="button" onClick={() => git("/kod/s-1")}>
        Koda dön
      </button>
      <button type="button" onClick={() => git("/kosular")}>
        Koşulara git
      </button>
    </>
  );
}

function yalnizPanel(yol: string, ek?: ReactNode) {
  return render(
    <MemoryRouter initialEntries={[yol]}>
      <OturumProvider>
        <BildirimProvider>
          <Gezgin />
          {ek}
          <AsistanPaneli />
        </BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

const panel = () => screen.getByTestId("asistan-paneli");
const ekranCipiKaldir = () => screen.queryByRole("button", { name: "Ekran bağlamını kaldır" });

async function sohbetiAc(u: ReturnType<typeof userEvent.setup>) {
  await u.click(await screen.findByRole("button", { name: "Asistanı aç" }));
  await within(panel()).findByLabelText("Sorunuz");
  return panel();
}

beforeEach(() => {
  asistanKontrolSifirla();
  sonHatayiSifirla();
  oneriDeposunuSifirla();
  ekOneriSohbetleriniSifirla();
  asistanMockAyarla({ otomatikIsle: false });
  Object.assign(sohbetAyar, { yoklamaMs: 30, uzunSurerMs: 25_000, duyuruAraMs: 20 });
  Object.assign(oneriAyar, { olayGecikmeMs: 5000, yoklamaMs: 30 });
});

afterEach(() => {
  vi.restoreAllMocks();
  asistanKontrolSifirla();
  ekOneriSohbetleriniSifirla();
  sonHatayiSifirla();
  sessionStorage.clear();
  Object.assign(sohbetAyar, { yoklamaMs: 3000, uzunSurerMs: 25_000, duyuruAraMs: 100 });
  Object.assign(oneriAyar, { olayGecikmeMs: 5000, yoklamaMs: 3000 });
});

describe("kaldırılan ekran çipi", () => {
  it("panel kapalıyken başka ekrana gidip dönülünce çip geri gelir", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel("/kod/s-1");
    const p = await sohbetiAc(u);
    await u.click(within(p).getByRole("button", { name: "Ekran bağlamını kaldır" }));
    expect(ekranCipiKaldir()).toBeNull();
    await u.click(within(p).getByRole("button", { name: "Asistanı kapat" }));
    await u.click(screen.getByRole("button", { name: "Gereksinimlere git" }));
    await u.click(screen.getByRole("button", { name: "Koda dön" }));
    await sohbetiAc(u);
    expect(ekranCipiKaldir()).not.toBeNull();
  });

  it("Öneriler sekmesindeyken başka ekrana gidip dönülünce çip geri gelir", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel("/kod/s-1");
    const p = await sohbetiAc(u);
    await u.click(within(p).getByRole("button", { name: "Ekran bağlamını kaldır" }));
    await u.click(within(p).getByRole("tab", { name: "Öneriler" }));
    await u.click(screen.getByRole("button", { name: "Gereksinimlere git" }));
    await u.click(screen.getByRole("button", { name: "Koda dön" }));
    await u.click(within(panel()).getByRole("tab", { name: "Sohbet" }));
    await within(panel()).findByLabelText("Sorunuz");
    expect(ekranCipiKaldir()).not.toBeNull();
  });

  it("aynı ekranda panel kapatılıp açılınca kaldırma tercihi korunur", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel("/kod/s-1");
    const p = await sohbetiAc(u);
    await u.click(within(p).getByRole("button", { name: "Ekran bağlamını kaldır" }));
    await u.click(within(p).getByRole("button", { name: "Asistanı kapat" }));
    await sohbetiAc(u);
    expect(ekranCipiKaldir()).toBeNull();
  });
});

describe("bekletilen öneri sorusu ekrana bağlıdır", () => {
  it("başka ekranda gönderilirse oneri_kural_id gitmez, soru o anki ekran bağlamıyla gider (aynı ekran: duzeltmeler3)", async () => {
    await oturumAc("analist");
    const gonder = vi.spyOn(asistanApi, "soruGonder");
    const u = userEvent.setup();
    yalnizPanel("/gereksinimler/req-ft-1");
    const p = await sohbetiAc(u);
    const alan = within(p).getByLabelText("Sorunuz");
    await u.type(alan, "Bugün ne yapmalıyım?");
    await u.click(within(p).getByRole("button", { name: "Asistana sor" }));
    await waitFor(() => expect(asistanMockBekleyenler().length).toBeGreaterThan(0));
    const ilk = asistanMockBekleyenler().at(-1)!;
    act(() => acSekme("sohbet", { oneriKuralId: "gereksinim-bulgu-karari", soru: NEDEN_SORUSU }));
    expect(await within(panel()).findByText(/Yanıt bekleyen bir sorunuz var/)).toBeInTheDocument();
    expect(within(panel()).getByLabelText("Sorunuz")).toHaveValue(NEDEN_SORUSU);

    await u.click(screen.getByRole("button", { name: "Koşulara git" }));
    act(() => asistanMockIsle(ilk));
    await waitFor(() => expect(within(panel()).getByRole("button", { name: "Asistana sor" })).toBeEnabled(), { timeout: 3000 });
    expect(within(panel()).getByLabelText("Sorunuz")).toHaveValue(NEDEN_SORUSU);
    await u.click(within(panel()).getByRole("button", { name: "Asistana sor" }));
    await waitFor(() => expect(gonder).toHaveBeenCalledTimes(2));
    expect(gonder.mock.calls[1][1]).toMatchObject({ soru: NEDEN_SORUSU });
    expect(gonder.mock.calls[1][1].oneri_kural_id ?? null).toBeNull();
    expect(gonder.mock.calls[1][1].baglam).toMatchObject({ rota_kalibi: "/kosular" });
  });
});

describe("HataKutusu canlı bölgesi", () => {
  it("yalnız metin role=alert içindedir; 'Asistana sor' ve 'Tekrar dene' kardeş öğedir", async () => {
    await oturumAc("analist");
    const hata = new ApiError(409, "İçerik değişti", { kod: "onay_hash_uyusmuyor", method: "POST", yol: "/cases/:id/review" });
    hataKaydet(hata);
    yalnizPanel("/gereksinimler", <HataKutusu hata="İçerik değişti, yeniden inceleyin." kaynak={hata} yenile={() => undefined} />);
    const sor = await screen.findByRole("button", { name: "Asistana sor" });
    const tekrar = screen.getByRole("button", { name: "Tekrar dene" });
    const uyari = screen.getByRole("alert");
    expect(uyari).toHaveTextContent("İçerik değişti, yeniden inceleyin.");
    expect(uyari).not.toContainElement(sor);
    expect(uyari).not.toContainElement(tekrar);
    expect(uyari.textContent).not.toMatch(/Asistana sor|Tekrar dene/);
    expect(uyari.parentElement).toHaveClass("uyari-kutusu", "uyari-hata");
  });
});
