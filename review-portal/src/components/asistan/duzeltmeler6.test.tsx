// Asistan paneli inceleme düzeltmeleri (tur 6): "Bu ne?" kipinde Esc paneli kapatmaz (olay panelin
// onKeyDown'una ulaşmaz); ek öneri "Durdur" cevap bitmişken 409 alırsa sonuç gösterilir; Sohbet'te
// bekleyen soru varken "Başka ne yapabilirim?" pasif (ters yön kilidi); Sohbet kilit ipucu ek öneri
// beklerken de DOM'da ve canlı bölge; "Önerileri yenile" görünen adla, yenileme hatası duyurulur;
// mock: durdurulan cevap kapanırken 409 "kapanıyor" ve bütçe düşükken `derin_onerilir`.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../../App";
import { asistanApi, gonderimHataMetni, oneriApi } from "../../api/asistan";
import { ApiError } from "../../api/http";
import { asistanMockAyarla, asistanMockBaslat, asistanMockBekleyenler, asistanMockIsle } from "../../api/mock/asistan";
import { OturumProvider } from "../../auth";
import { sonHatayiSifirla } from "../../lib/sonHata";
import { oturumAc } from "../../test/yardimci";
import { BildirimProvider } from "../Bildirim";
import { asistanKontrolSifirla } from "./kontrol";
import { ekBekleyenleriGeriYukle, ekOneriSohbetleriniSifirla, sohbetBekleyeniYaz } from "./OneriEkOneriler";
import { OnerilerSekmesi } from "./OnerilerSekmesi";
import { oneriAyar, oneriDeposunuSifirla } from "./OneriVerisi";
import { sohbetAyar } from "./SohbetSekmesi";

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

const panel = () => screen.getByTestId("asistan-paneli");

async function sor(u: ReturnType<typeof userEvent.setup>, metin: string) {
  const alan = within(panel()).getByLabelText("Sorunuz");
  await u.type(alan, metin);
  await u.click(within(panel()).getByRole("button", { name: "Asistana sor" }));
  await waitFor(() => expect(asistanMockBekleyenler().length).toBeGreaterThan(0));
  return asistanMockBekleyenler().at(-1)!;
}

beforeEach(() => {
  asistanKontrolSifirla();
  sonHatayiSifirla();
  oneriDeposunuSifirla();
  ekOneriSohbetleriniSifirla();
  asistanMockAyarla({ otomatikIsle: false });
  Object.assign(sohbetAyar, { yoklamaMs: 30, uzunSurerMs: 25_000 });
  Object.assign(oneriAyar, { olayGecikmeMs: 5000, yoklamaMs: 30 });
});

afterEach(() => {
  vi.restoreAllMocks();
  asistanKontrolSifirla();
  ekOneriSohbetleriniSifirla();
  sessionStorage.clear();
  Object.assign(sohbetAyar, { yoklamaMs: 3000, uzunSurerMs: 25_000 });
  Object.assign(oneriAyar, { olayGecikmeMs: 5000, yoklamaMs: 3000 });
});

describe("ek öneri Durdur yarışı", () => {
  it("cevap sunucuda bitmişken iptal 409 alırsa sonuç okunur ve gösterilir (kaybolmaz)", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    await u.click(await screen.findByTestId("oneri-dugmesi"));
    const s = within(await screen.findByTestId("oneriler-sekmesi"));

    // Olay/okuma iptalden önce cevabı göremesin: o ana dek mesaj "running" okunur.
    const gercekMesaj = asistanApi.mesaj.bind(asistanApi);
    let bitti = false;
    vi.spyOn(asistanApi, "mesaj").mockImplementation(async (id: string) => {
      const m = await gercekMesaj(id);
      return bitti ? m : { ...m, durum: "running", cevap: null };
    });
    await u.click(s.getByRole("button", { name: "Başka ne yapabilirim?" }));
    await s.findByText("Ek öneriler hazırlanıyor…");
    const ekId = asistanMockBekleyenler().at(-1)!;

    const iptal = vi.spyOn(asistanApi, "iptal").mockImplementation(async (id: string) => {
      asistanMockIsle(id);
      bitti = true;
      throw new ApiError(409, "Cevap zaten tamamlandı; iptal edilemez.");
    });
    await u.click(s.getByRole("button", { name: "Durdur" }));
    await waitFor(() => expect(iptal).toHaveBeenCalledWith(ekId));
    expect(await s.findByText("AI önerisi · doğrulanmadı")).toBeInTheDocument();
    expect(s.queryByText("Ek öneriler hazırlanıyor…")).toBeNull();
  });

  it("iptal başarılıysa bekleme kalkar, düğme yeniden etkin", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    await u.click(await screen.findByTestId("oneri-dugmesi"));
    const s = within(await screen.findByTestId("oneriler-sekmesi"));
    await u.click(s.getByRole("button", { name: "Başka ne yapabilirim?" }));
    await u.click(await s.findByRole("button", { name: "Durdur" }));
    expect(await s.findByRole("button", { name: "Başka ne yapabilirim?" })).toBeEnabled();
    expect(asistanMockBekleyenler()).toEqual([]);
  });
});

describe("ters yön kilidi: Sohbet'te bekleyen soru", () => {
  it("'Başka ne yapabilirim?' pasif ve nedeni yazılı; cevap gelince (Öneriler açıkken) etkin", async () => {
    await oturumAc("analist");
    const gonder = vi.spyOn(asistanApi, "soruGonder");
    const olustur = vi.spyOn(asistanApi, "sohbetOlustur");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    await u.click(await screen.findByRole("button", { name: "Asistanı aç" }));
    const id = await sor(u, "Bugün ne yapmalıyım?");
    const olusturmaSayisi = olustur.mock.calls.length;

    await u.click(screen.getByRole("tab", { name: "Öneriler" }));
    const s = within(await screen.findByTestId("oneriler-sekmesi"));
    const dugme = s.getByRole("button", { name: "Başka ne yapabilirim?" });
    expect(dugme).toBeDisabled();
    const ipucu = document.getElementById(dugme.getAttribute("aria-describedby")!);
    expect(ipucu).toHaveTextContent("cevap gelince kullanılabilir");
    expect(ipucu).toHaveAttribute("role", "status");
    expect(gonder).toHaveBeenCalledTimes(1);
    expect(olustur).toHaveBeenCalledTimes(olusturmaSayisi);

    act(() => asistanMockIsle(id));
    await waitFor(() => expect(s.getByRole("button", { name: "Başka ne yapabilirim?" })).toBeEnabled());
    expect(s.getByRole("button", { name: "Başka ne yapabilirim?" })).not.toHaveAttribute("aria-describedby");
  });

  it("sekme değişirken kaçan cevap Öneriler açılınca okunur: kilit kalkar", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    await u.click(await screen.findByRole("button", { name: "Asistanı aç" }));
    await sor(u, "Bugün ne yapmalıyım?");
    // Kayıt Sohbet'te kalmış ama sunucuda bu kimlik artık yok (silinmiş sohbet): 404 → kilit düşer.
    act(() => sohbetBekleyeniYaz("msg-yok"));
    vi.spyOn(asistanApi, "mesaj").mockRejectedValue(new ApiError(404, "Bulunamadı"));
    await u.click(screen.getByRole("tab", { name: "Öneriler" }));
    const s = within(await screen.findByTestId("oneriler-sekmesi"));
    await waitFor(() => expect(s.getByRole("button", { name: "Başka ne yapabilirim?" })).toBeEnabled());
  });
});

describe("Sohbet kilit ipucu", () => {
  it("ek öneri de beklerken aria-describedby DOM'daki canlı bölgeye işaret eder", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    await u.click(await screen.findByRole("button", { name: "Asistanı aç" }));
    const id = await sor(u, "Bugün ne yapmalıyım?");
    const p = panel();
    const yeni = within(p).getByRole("button", { name: "Yeni sohbet" });
    expect(yeni).toBeDisabled();
    const kilit = () => document.getElementById(yeni.getAttribute("aria-describedby")!);
    expect(kilit()).toHaveAttribute("role", "status");

    // SSE gecikmesi: ek öneri bekleyeni de görünür (sunucuda nadiren iki bekleyen).
    sessionStorage.setItem("tp-asistan-ek-bekleyen", JSON.stringify({ "/gereksinimler/:id|req-ft-1": id }));
    act(() => {
      ekBekleyenleriGeriYukle();
      sohbetBekleyeniYaz(null);
    });
    expect(await within(p).findByTestId("ek-oneri-bekliyor")).toBeInTheDocument();
    expect(within(p).getByRole("button", { name: "Geçmiş" })).toBeDisabled();
    expect(kilit()).not.toBeNull();
    expect(kilit()).toHaveTextContent("Cevap gelince yeni soru sorabilir");
  });
});

describe("Öneriler sekmesi erişilebilirliği", () => {
  it("'Önerileri yenile' görünen metinle adlanır, yüklemede aria-busy; sonuç varken yenileme hatası duyurulur", async () => {
    await oturumAc("analist");
    render(
      <MemoryRouter>
        <OturumProvider>
          <BildirimProvider>
            <OnerilerSekmesi ekran={{ rota_kalibi: "/gereksinimler/:id", ekran: "Gereksinim detayı", varlik: { tur: "requirement", id: "req-ft-1" } }} asistan={null} />
          </BildirimProvider>
        </OturumProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText(/tutarlılık bulgusu kararınızı bekliyor/)).toBeInTheDocument();
    const dugme = screen.getByRole("button", { name: "Önerileri yenile" });
    expect(dugme).toHaveTextContent("Önerileri yenile");
    expect(dugme).not.toHaveAttribute("aria-label");

    let bitir: (e: unknown) => void = () => undefined;
    vi.spyOn(oneriApi, "liste").mockImplementation(() => new Promise((_, ret) => (bitir = ret)));
    await act(async () => {
      fireEvent.click(dugme);
    });
    expect(screen.getByRole("button", { name: "Önerileri yenile" })).toHaveAttribute("aria-busy", "true");
    await act(async () => bitir(new ApiError(500, "Sunucu hatası")));
    const hata = await screen.findByText(/Öneriler okunamadı/);
    expect(hata).toHaveAttribute("role", "status");
    expect(screen.getByText(/tutarlılık bulgusu kararınızı bekliyor/)).toBeInTheDocument();
  });
});

describe("mock: core'un tur 5 davranışları", () => {
  it("çalışırken durdurulan cevap kapanırken yeni soru 409 'kapanıyor' alır; pencere bitince kabul edilir", async () => {
    await oturumAc("analist");
    asistanMockAyarla({ kapanmaMs: 60_000 });
    const s = await asistanApi.sohbetOlustur("x");
    const { mesaj_id } = await asistanApi.soruGonder(s.id, { soru: "ilk soru" });
    asistanMockBaslat(mesaj_id);
    await asistanApi.iptal(mesaj_id);
    const hata = await asistanApi.soruGonder(s.id, { soru: "ikinci soru" }).catch((e: unknown) => e);
    expect(hata).toBeInstanceOf(ApiError);
    expect((hata as ApiError).status).toBe(409);
    expect((hata as ApiError).kod).toBe("bekleyen_var");
    expect(gonderimHataMetni(hata)).toMatch(/Durdurulan cevap kapanıyor/);

    vi.spyOn(Date, "now").mockReturnValue(Date.now() + 61_000);
    await expect(asistanApi.soruGonder(s.id, { soru: "üçüncü soru" })).resolves.toHaveProperty("mesaj_id");
  });

  it("sırada (başlamamış) durdurulan cevap hemen düşer: 409 yok", async () => {
    await oturumAc("analist");
    asistanMockAyarla({ kapanmaMs: 60_000 });
    const s = await asistanApi.sohbetOlustur("x");
    const { mesaj_id } = await asistanApi.soruGonder(s.id, { soru: "ilk soru" });
    await asistanApi.iptal(mesaj_id);
    await expect(asistanApi.soruGonder(s.id, { soru: "ikinci soru" })).resolves.toHaveProperty("mesaj_id");
  });

  it("bütçe düşükken 'Emin değil' cevap otomatik yükseltilmez, derin_onerilir taşır", async () => {
    await oturumAc("analist");
    asistanMockAyarla({ butceDusuk: true });
    const s = await asistanApi.sohbetOlustur("x");
    const { mesaj_id } = await asistanApi.soruGonder(s.id, { soru: "Emin misin, kısmen mi?" });
    asistanMockIsle(mesaj_id);
    const m = await asistanApi.mesaj(mesaj_id);
    expect(m.cevap?.guven_gosterimi).toBe("Emin değil");
    expect(m.cevap?.derin_onerilir).toBe(true);
    expect(asistanMockBekleyenler()).toEqual([]);
  });

  it("bütçe yeterliyken davranış değişmez: çocuk mesaj açılır, derin_onerilir yok", async () => {
    await oturumAc("analist");
    const s = await asistanApi.sohbetOlustur("x");
    const { mesaj_id } = await asistanApi.soruGonder(s.id, { soru: "Emin misin, kısmen mi?" });
    asistanMockIsle(mesaj_id);
    const m = await asistanApi.mesaj(mesaj_id);
    expect(m.cevap?.derin_onerilir).toBeUndefined();
    expect(asistanMockBekleyenler()).toHaveLength(1);
  });
});
