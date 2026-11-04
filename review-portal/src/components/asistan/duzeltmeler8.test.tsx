// Asistan paneli inceleme düzeltmeleri (tur 8): Sohbet taslağı (girdi, kaldırılan çipler) dar
// ekranda "? Bu ne?" seçiminden ve sekme geçişinden sonra korunur; Geçmiş açıkken "Asistana sor"
// sohbete döner ve girdiyi odaklar; bekleme sayacı ve iptal notu sekme geçişinde sıfırlanmaz;
// hata çipi kaldırılınca "Az önceki hata ne demek?" önerilmez; satır içi hata uyarısında
// "Asistana sor" canlı bölgenin (role="alert") dışındadır.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { asistanApi } from "../../api/asistan";
import { ApiError } from "../../api/http";
import { asistanMockAyarla, asistanMockBekleyenler } from "../../api/mock/asistan";
import { OturumProvider } from "../../auth";
import { hataKaydet, sonHata, sonHatayiSifirla } from "../../lib/sonHata";
import { oturumAc } from "../../test/yardimci";
import { BildirimProvider } from "../Bildirim";
import { AlanHatasi } from "../ui";
import { AsistanPaneli } from "./AsistanPaneli";
import { asistanaSor, asistanKontrolSifirla } from "./kontrol";
import { ekOneriSohbetleriniSifirla } from "./OneriEkOneriler";
import { oneriAyar, oneriDeposunuSifirla } from "./OneriVerisi";
import { sohbetAyar } from "./SohbetSekmesi";

function yalnizPanel(yol: string, ek?: ReactNode) {
  return render(
    <MemoryRouter initialEntries={[yol]}>
      <OturumProvider>
        <BildirimProvider>
          {ek}
          <AsistanPaneli />
        </BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

const panel = () => screen.getByTestId("asistan-paneli");

function darEkran() {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((q: string) => ({ matches: q.includes("max-width"), media: q, addEventListener: () => undefined, removeEventListener: () => undefined })),
  );
}

function hataYaz(yol = "/cases/1/review") {
  const hata = new ApiError(409, "Durum değişti", { kod: "durum_degisti", method: "POST", yol });
  hataKaydet(hata);
  return hata;
}

async function sohbetiAc(u: ReturnType<typeof userEvent.setup>) {
  await u.click(await screen.findByRole("button", { name: "Asistanı aç" }));
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
  vi.unstubAllGlobals();
  asistanKontrolSifirla();
  ekOneriSohbetleriniSifirla();
  sonHatayiSifirla();
  sessionStorage.clear();
  Object.assign(sohbetAyar, { yoklamaMs: 3000, uzunSurerMs: 25_000, duyuruAraMs: 100 });
  Object.assign(oneriAyar, { olayGecikmeMs: 5000, yoklamaMs: 3000 });
});

describe("Sohbet taslağı korunur", () => {
  it("dar ekranda '? Bu ne?' seçiminden sonra girdi ve kaldırılan çipler geri gelmez; bağlama gitmez", async () => {
    darEkran();
    await oturumAc("analist");
    const u = userEvent.setup();
    const casus = vi.spyOn(asistanApi, "soruGonder");
    yalnizPanel(
      "/kod/s-1",
      <button type="button" disabled>
        Kırarak doğrula
      </button>,
    );
    hataYaz();
    const p = await sohbetiAc(u);
    await u.click(within(p).getByRole("button", { name: "Ekran bağlamını kaldır" }));
    await u.click(within(p).getByRole("button", { name: "Son hata bağlamını kaldır" }));
    await u.type(within(p).getByLabelText("Sorunuz"), "Bu düğme neden gri?");

    const hedef = screen.getByRole("button", { name: "Kırarak doğrula" });
    Object.defineProperty(document, "elementsFromPoint", {
      configurable: true,
      value: () => [screen.getByTestId("asistan-bune-bindirme"), hedef, document.body],
    });
    await u.click(within(p).getByRole("button", { name: "? Bu ne?" }));
    // Dar ekranda kip açıkken panel DOM'dan kalkar.
    expect(screen.queryByTestId("asistan-paneli")).toBeNull();
    fireEvent.click(screen.getByTestId("asistan-bune-bindirme"), { clientX: 5, clientY: 5 });

    const yeni = await screen.findByTestId("asistan-paneli");
    expect(within(yeni).getByLabelText("Sorunuz")).toHaveValue("Bu düğme neden gri?");
    expect(within(yeni).queryByText(/Son hata:/)).toBeNull();
    expect(within(yeni).queryByText(/Bu ekran:/)).toBeNull();
    expect(within(yeni).getByText(/Seçili: Kırarak doğrula/)).toBeInTheDocument();

    await u.click(within(yeni).getByRole("button", { name: "Asistana sor" }));
    await waitFor(() => expect(casus).toHaveBeenCalled());
    const baglam = casus.mock.calls[0][1].baglam as Record<string, unknown>;
    expect(baglam).not.toHaveProperty("son_hata");
    expect(baglam).not.toHaveProperty("rota_kalibi");
    expect(baglam).toHaveProperty("secili_eleman");
  });

  it("masaüstünde Sohbet → Öneriler → Sohbet geçişinde girdi ve kaldırılan hata çipi korunur", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel("/kod/s-1");
    hataYaz();
    const p = await sohbetiAc(u);
    await u.click(within(p).getByRole("button", { name: "Son hata bağlamını kaldır" }));
    await u.type(within(p).getByLabelText("Sorunuz"), "Yarım kalan soru");
    await u.click(within(p).getByRole("tab", { name: "Öneriler" }));
    await u.click(within(panel()).getByRole("tab", { name: "Sohbet" }));
    expect(within(panel()).getByLabelText("Sorunuz")).toHaveValue("Yarım kalan soru");
    expect(within(panel()).queryByText(/Son hata:/)).toBeNull();
    expect(within(panel()).getByText(/Bu ekran:/)).toBeInTheDocument();
  });

  it("yeni hata kaydı gelince kaldırılmış hata çipi yeniden eklenir", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel("/kod/s-1");
    hataYaz();
    const p = await sohbetiAc(u);
    await u.click(within(p).getByRole("button", { name: "Son hata bağlamını kaldır" }));
    expect(within(p).queryByText(/Son hata:/)).toBeNull();
    act(() => void hataYaz("/findings/2/decision"));
    expect(await within(p).findByText(/Son hata:/)).toBeInTheDocument();
  });

  it("oturum değişince (asistanKontrolSifirla) taslak temizlenir", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    const { unmount } = yalnizPanel("/kod/s-1");
    const p = await sohbetiAc(u);
    await u.type(within(p).getByLabelText("Sorunuz"), "Gizli taslak");
    unmount();
    asistanKontrolSifirla();
    yalnizPanel("/kod/s-1");
    const p2 = await sohbetiAc(u);
    expect(within(p2).getByLabelText("Sorunuz")).toHaveValue("");
  });
});

describe("Geçmiş açıkken 'Asistana sor'", () => {
  it("sohbete döner, hata çipi ve soru görünür, odak girdide", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel("/kod/s-1");
    const p = await sohbetiAc(u);
    await u.click(within(p).getByRole("button", { name: "Geçmiş" }));
    expect(await within(p).findByText("Sohbet geçmişi")).toBeInTheDocument();

    act(() => {
      hataYaz();
      asistanaSor(sonHata()!.kayitId);
    });
    const alan = await within(panel()).findByLabelText("Sorunuz");
    expect(within(panel()).queryByText("Sohbet geçmişi")).toBeNull();
    expect(alan).toHaveValue("Bu hata ne demek, ne yapmalıyım?");
    expect(within(panel()).getByText(/Son hata:/)).toBeInTheDocument();
    await waitFor(() => expect(document.activeElement).toBe(alan));
  });
});

describe("bekleme durumu sekme geçişinde korunur", () => {
  it("'Uzun sürüyor' ve sayaç sıfırlanmaz; 'Beklemeyi bırak' ücret notu kalır", async () => {
    Object.assign(sohbetAyar, { uzunSurerMs: 150, saatMs: 20 });
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel("/kod/s-1");
    const p = await sohbetiAc(u);
    await u.type(within(p).getByLabelText("Sorunuz"), "Bugün ne yapmalıyım?");
    await u.click(within(p).getByRole("button", { name: "Asistana sor" }));
    await waitFor(() => expect(asistanMockBekleyenler().length).toBe(1));
    expect(await within(p).findByText("Uzun sürüyor", {}, { timeout: 2000 })).toBeInTheDocument();

    await u.click(within(p).getByRole("tab", { name: "Öneriler" }));
    await u.click(within(panel()).getByRole("tab", { name: "Sohbet" }));
    // Yeniden çizimde başlangıç korunur: "Uzun sürüyor" hemen görünür.
    expect(within(panel()).getByText("Uzun sürüyor")).toBeInTheDocument();

    await u.click(within(panel()).getByRole("button", { name: "Beklemeyi bırak" }));
    expect(await within(panel()).findByText(/Bekleme bırakıldı\./)).toBeInTheDocument();
    await u.click(within(panel()).getByRole("tab", { name: "Öneriler" }));
    await u.click(within(panel()).getByRole("tab", { name: "Sohbet" }));
    expect(await within(panel()).findByText(/Bekleme bırakıldı\./)).toBeInTheDocument();
    expect(within(panel()).queryByText("Soru iptal edildi.")).toBeNull();
    Object.assign(sohbetAyar, { saatMs: 1000 });
  });
});

describe("hata çipi kaldırılınca öneri", () => {
  it("'Az önceki hata ne demek?' önerilmez; çip yerindeyken önerilir", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel("/kod/s-1");
    hataYaz();
    const p = await sohbetiAc(u);
    const oneriler = () => within(within(p).getByRole("list", { name: "Soru önerileri" }));
    expect(oneriler().getByRole("button", { name: "Az önceki hata ne demek?" })).toBeInTheDocument();
    await u.click(within(p).getByRole("button", { name: "Son hata bağlamını kaldır" }));
    expect(oneriler().queryByRole("button", { name: "Az önceki hata ne demek?" })).toBeNull();
  });
});

describe("AlanHatasi", () => {
  it("'Asistana sor' role=alert paragrafının dışında, kardeş öğedir", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    const hata = hataYaz("/findings/:id/decision");
    yalnizPanel("/gereksinimler", <AlanHatasi asistan={{ hata: "İçerik değişti.", kaynak: hata }}>İçerik değişti.</AlanHatasi>);
    const dugme = await screen.findByRole("button", { name: "Asistana sor" });
    const uyari = screen.getByRole("alert");
    expect(uyari).toHaveTextContent("İçerik değişti.");
    expect(uyari).not.toContainElement(dugme);
    expect(uyari.textContent).not.toMatch(/Asistana sor/);
    await u.click(dugme);
    expect(within(panel()).getByText(/Son hata: İçerik değişti\./)).toBeInTheDocument();
  });

  it("asistan verilmezse (doğrulama uyarısı) düğme yok", async () => {
    await oturumAc("analist");
    yalnizPanel("/gereksinimler", <AlanHatasi asistan={null}>Alan zorunlu.</AlanHatasi>);
    await screen.findByRole("button", { name: "Asistanı aç" });
    expect(screen.getByRole("alert")).toHaveTextContent("Alan zorunlu.");
    expect(screen.queryByRole("button", { name: "Asistana sor" })).toBeNull();
  });
});
