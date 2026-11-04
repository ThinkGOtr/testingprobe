// SSE kısa kopukluğu (inceleme tur 5): kopukluk yoklama aralığından kısa sürerse arada yayınlanan
// `assistant.answered` kaçar (Last-Event-ID ile tekrar oynatma yok). Bağlantı geri gelince bekleyen
// mesaj bir kez okunmalı; yoksa bekleme takılı kalır. Olay yolu taklit edilir: bağlantı durumu
// testten sürülür, olaylar hiç teslim edilmez (kaçan olay).
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useSyncExternalStore, type ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BaglantiDurumu } from "../../api/events";
import { asistanMockAyarla, asistanMockBekleyenler, asistanMockIsle } from "../../api/mock/asistan";
import { OturumProvider } from "../../auth";
import { sonHatayiSifirla } from "../../lib/sonHata";
import { oturumAc } from "../../test/yardimci";
import { BildirimProvider } from "../Bildirim";
import { AsistanPaneli } from "./AsistanPaneli";
import { asistanKontrolSifirla } from "./kontrol";
import { ekOneriSohbetleriniSifirla, OneriEkOneriler } from "./OneriEkOneriler";
import { oneriAyar, oneriDeposunuSifirla } from "./OneriVerisi";
import { sohbetAyar } from "./SohbetSekmesi";

const baglanti = vi.hoisted(() => {
  let durum: BaglantiDurumu = "bagli";
  const dinleyiciler = new Set<() => void>();
  return {
    al: () => durum,
    ayarla: (d: BaglantiDurumu) => {
      durum = d;
      dinleyiciler.forEach((f) => f());
    },
    abone: (f: () => void) => {
      dinleyiciler.add(f);
      return () => void dinleyiciler.delete(f);
    },
  };
});

vi.mock("../../api/events", async (gercek) => ({
  ...(await gercek<typeof import("../../api/events")>()),
  useBaglantiDurumu: () => useSyncExternalStore(baglanti.abone, baglanti.al),
  // Olaylar teslim edilmez: kopukluk sırasında yayınlanan cevap olayı kaçmış sayılır.
  useOlay: () => undefined,
}));

function sarmala(icerik: ReactNode) {
  return render(
    <MemoryRouter initialEntries={["/kosular"]}>
      <OturumProvider>
        <BildirimProvider>{icerik}</BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

function kisaKopukluk() {
  act(() => baglanti.ayarla("yeniden"));
  act(() => baglanti.ayarla("bagli"));
}

beforeEach(() => {
  baglanti.ayarla("bagli");
  asistanKontrolSifirla();
  sonHatayiSifirla();
  oneriDeposunuSifirla();
  ekOneriSohbetleriniSifirla();
  asistanMockAyarla({ otomatikIsle: false });
  // Yoklama bu testlerde hiç dolmaz: cevabı yalnız yeniden bağlanma okuması getirebilir.
  Object.assign(sohbetAyar, { yoklamaMs: 60_000 });
  Object.assign(oneriAyar, { yoklamaMs: 60_000 });
});

afterEach(() => {
  asistanKontrolSifirla();
  ekOneriSohbetleriniSifirla();
  Object.assign(sohbetAyar, { yoklamaMs: 3000 });
  Object.assign(oneriAyar, { yoklamaMs: 3000 });
});

describe("SSE yeniden bağlanınca bekleyenler bir kez okunur", () => {
  it("Sohbet: kopukken biten cevap bağlantı gelince görünür, bekleme kalkar", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    sarmala(<AsistanPaneli />);
    await u.click(await screen.findByRole("button", { name: "Asistanı aç" }));
    const p = screen.getByTestId("asistan-paneli");
    await u.type(within(p).getByLabelText("Sorunuz"), "Bugün ne yapmalıyım?");
    await u.click(within(p).getByRole("button", { name: "Asistana sor" }));
    await waitFor(() => expect(asistanMockBekleyenler().length).toBeGreaterThan(0));
    expect(await within(p).findByTestId("asistan-bekleme")).toBeInTheDocument();

    act(() => baglanti.ayarla("yeniden"));
    act(() => asistanMockIsle(asistanMockBekleyenler().at(-1)!));
    act(() => baglanti.ayarla("bagli"));

    expect(await within(p).findByRole("article")).toBeInTheDocument();
    expect(within(p).queryByTestId("asistan-bekleme")).toBeNull();
  });

  it("bağlantı değişmedikçe bekleme sürer (ek okuma yok); kısa kopukluktan sonra cevap okunur", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    sarmala(<AsistanPaneli />);
    await u.click(await screen.findByRole("button", { name: "Asistanı aç" }));
    const p = screen.getByTestId("asistan-paneli");
    await u.type(within(p).getByLabelText("Sorunuz"), "Bugün ne yapmalıyım?");
    await u.click(within(p).getByRole("button", { name: "Asistana sor" }));
    await waitFor(() => expect(asistanMockBekleyenler().length).toBeGreaterThan(0));
    act(() => asistanMockIsle(asistanMockBekleyenler().at(-1)!));
    await act(async () => undefined);
    // Olay taklitte teslim edilmedi, bağlantı da değişmedi: bekleme sürer (yoklama 60 sn).
    expect(within(p).getByTestId("asistan-bekleme")).toBeInTheDocument();
    kisaKopukluk();
    expect(await within(p).findByRole("article")).toBeInTheDocument();
  });

  it("Ek öneri: kopukken biten 'Başka ne yapabilirim?' bağlantı gelince hazırlanıyor durumundan çıkar", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    sarmala(<OneriEkOneriler ekran={{ rota_kalibi: "/gereksinimler/:id", ekran: "Gereksinim detayı", varlik: { tur: "requirement", id: "req-ft-1" } }} />);
    await u.click(await screen.findByRole("button", { name: "Başka ne yapabilirim?" }));
    expect(await screen.findByText("Ek öneriler hazırlanıyor…")).toBeInTheDocument();
    await waitFor(() => expect(asistanMockBekleyenler().length).toBeGreaterThan(0));
    act(() => asistanMockIsle(asistanMockBekleyenler().at(-1)!));
    await act(async () => undefined);
    expect(screen.getByText("Ek öneriler hazırlanıyor…")).toBeInTheDocument();
    kisaKopukluk();
    await waitFor(() => expect(screen.queryByText("Ek öneriler hazırlanıyor…")).toBeNull());
  });
});
