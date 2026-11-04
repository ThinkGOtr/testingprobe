// Öneri düğmesi ve Öneriler sekmesi (AI-ASISTAN-PLANI §13 "Portal (öneri)", §17.4–17.6): sayı rozeti,
// gizleme kuralları ve yetenek kapısı, rozet yenileme (rota/varlık, açık varlığın olayları 5 sn
// içinde tek yenileme, 429'da son değer), öncelik sırası, "Git", Jira taslağı kopyala + "Jira'yı aç"
// yalnız sunucu verdiyse, "Neden? Sor" (`oneri_kural_id`) / "Açıklamayı göster", "Başka ne
// yapabilirim?" (model kapalıyken gizli), "Gizle"/"Yaptım" geri bildirimi ve 5 rol.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../../App";
import { asistanApi, oneriApi, type OneriListesi } from "../../api/asistan";
import { ApiError, yapilandir } from "../../api/http";
import { asistanMockAyarla, asistanMockBekleyenler, asistanMockIsle } from "../../api/mock/asistan";
import { mockOlayYayinla } from "../../api/mock/olaylar";
import { oneriMockAyarla, oneriMockGeriBildirimleri } from "../../api/mock/oneri";
import { OturumProvider } from "../../auth";
import { oturumAc } from "../../test/yardimci";
import { BildirimProvider } from "../Bildirim";
import { acSekme, asistanKontrolSifirla } from "./kontrol";
import { aiMetniTemizle, aiOnerisiKarta, goreliZaman, taslakMetni } from "./OneriKarti";
import { OneriDugmesi } from "./OneriDugmesi";
import { OnerilerSekmesi } from "./OnerilerSekmesi";
import { ekOneriSohbetleriniSifirla } from "./OneriEkOneriler";
import { oneriAyar, oneriDeposunuSifirla } from "./OneriVerisi";
import { sohbetAyar } from "./SohbetSekmesi";

function Konum() {
  const l = useLocation();
  return <span data-testid="konum">{l.pathname + l.hash}</span>;
}

function uygulama(yol: string) {
  return render(
    <MemoryRouter initialEntries={[yol]}>
      <OturumProvider>
        <BildirimProvider>
          <Rotalar />
          <Konum />
        </BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

/** Düğme tek başına (olay akışı yok). */
function yalnizDugme(yol: string) {
  return render(
    <MemoryRouter initialEntries={[yol]}>
      <OturumProvider>
        <BildirimProvider>
          <OneriDugmesi />
        </BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

function panoAyarla(pano: unknown) {
  Object.defineProperty(navigator, "clipboard", { value: pano, configurable: true, writable: true });
}

const dugme = () => screen.findByTestId("oneri-dugmesi");
const sekme = () => screen.getByTestId("oneriler-sekmesi");

async function oneriPaneliniAc(u: ReturnType<typeof userEvent.setup>) {
  await u.click(await dugme());
  return within(await screen.findByTestId("oneriler-sekmesi"));
}

function liste(d: Partial<OneriListesi>): OneriListesi {
  return { oneriler: [], ekranda_kural_var: true, bastirilan: [], diger_ekranlar: null, hesaplandi: new Date().toISOString(), ...d };
}

beforeEach(() => {
  asistanKontrolSifirla();
  oneriDeposunuSifirla();
  ekOneriSohbetleriniSifirla();
  asistanMockAyarla({ otomatikIsle: false });
  Object.assign(oneriAyar, { olayGecikmeMs: 5000, yoklamaMs: 30 });
  Object.assign(sohbetAyar, { yoklamaMs: 30 });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  asistanKontrolSifirla();
  oneriDeposunuSifirla();
  Object.assign(oneriAyar, { olayGecikmeMs: 5000, yoklamaMs: 3000 });
  Object.assign(sohbetAyar, { yoklamaMs: 3000 });
});

describe("Öneri düğmesi", () => {
  it("üst çubukta tek örnek; sayı rozeti ve aria-label", async () => {
    await oturumAc("analist");
    uygulama("/gereksinimler/req-ft-1");
    const d = await dugme();
    expect(d).toHaveAccessibleName("Öneriler (1)");
    expect(within(d).getByText("1")).toBeInTheDocument();
    expect(screen.getAllByTestId("oneri-dugmesi")).toHaveLength(1);
    expect(d.closest(".ust-sag")).not.toBeNull();
    // Rozet aria-live ile duyurulmaz.
    expect(d.closest("[aria-live]")).toBeNull();
  });

  it("kural var ama iş yoksa rozetsiz görünür; kuralsız (rota × rol) için gizli", async () => {
    await oturumAc("analist");
    const { unmount } = yalnizDugme("/gereksinimler/req-tpd-1");
    const d = await dugme();
    expect(d).toHaveAccessibleName("Öneriler (0)");
    expect(d.querySelector(".oneri-rozet")).toBeNull();
    unmount();
    const spy = vi.spyOn(oneriApi, "liste");
    yalnizDugme("/gereksinimler");
    await waitFor(() => expect(spy).toHaveBeenCalled());
    await act(async () => undefined);
    expect(screen.queryByTestId("oneri-dugmesi")).toBeNull();
  });

  it("öneri ucu kapalı (404) ya da uç yok (501) → gizli", async () => {
    await oturumAc("analist");
    oneriMockAyarla({ etkin: false });
    const spy = vi.spyOn(oneriApi, "liste");
    const { unmount } = yalnizDugme("/gereksinimler/req-ft-1");
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    await act(async () => undefined);
    expect(screen.queryByTestId("oneri-dugmesi")).toBeNull();
    unmount();
    oneriDeposunuSifirla();
    oneriMockAyarla({ etkin: true, ucYok: true });
    yalnizDugme("/gereksinimler/req-ft-1");
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    await act(async () => undefined);
    expect(screen.queryByTestId("oneri-dugmesi")).toBeNull();
  });

  it("yetenek kapısı: uç listesi okunurken gizli; listede uç yoksa gizli ve istek atılmaz", async () => {
    await oturumAc("analist");
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    let coz: (r: Response) => void = () => undefined;
    const f = vi.fn().mockImplementation((url: string) => {
      if (url === "/api/openapi.json") return new Promise<Response>((r) => (coz = r));
      if (url === "/api/auth/me") return Promise.resolve(new Response(JSON.stringify({ id: "u-analist", kullanici_adi: "analist", rol: "analyst" }), { status: 200 }));
      return Promise.resolve(new Response("{}", { status: 404 }));
    });
    vi.stubGlobal("fetch", f);
    yalnizDugme("/gereksinimler/req-ft-1");
    await act(async () => undefined);
    expect(screen.queryByTestId("oneri-dugmesi")).toBeNull();
    await act(async () => coz(new Response(JSON.stringify({ paths: { "/runs": { get: {} } } }), { status: 200 })));
    await act(async () => undefined);
    expect(screen.queryByTestId("oneri-dugmesi")).toBeNull();
    expect(f.mock.calls.map((c) => String(c[0])).some((u) => u.includes("/assistant/suggestions"))).toBe(false);
  });

  it("rota/varlık değişince bir istek (sekme paylaşır); 429'da son değer sessizce korunur", async () => {
    await oturumAc("analist");
    Object.assign(oneriAyar, { olayGecikmeMs: 20 });
    const spy = vi.spyOn(oneriApi, "liste");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    expect(await dugme()).toHaveAccessibleName("Öneriler (1)");
    const s = await oneriPaneliniAc(u);
    const rotalar = () => spy.mock.calls.map((c) => c[0].rota);
    expect(rotalar().filter((r) => r === "/gereksinimler/req-ft-1")).toHaveLength(1);

    // Başka ekrana geçiş ("Diğer ekranlarda … → Git"): yeni ekran için tek istek.
    await u.click(within(s.getByText(/Diğer ekranlarda sizi bekleyen/)).getByRole("link", { name: "Git" }));
    const yeni = screen.getByTestId("konum").textContent!;
    expect(yeni).not.toBe("/gereksinimler/req-ft-1");
    await waitFor(() => expect(rotalar().filter((r) => r === yeni)).toHaveLength(1));
    await act(async () => undefined);
    expect(rotalar().filter((r) => r === yeni)).toHaveLength(1);
    const yeniDeger = (await dugme()).getAttribute("aria-label");

    // 429: olayla yenileme reddedilir, rozet son değerde kalır.
    oneriMockAyarla({ hizSiniri: true });
    const once = spy.mock.calls.length;
    const id = decodeURIComponent(yeni.split("/").pop()!);
    act(() => {
      mockOlayYayinla({ type: "requirement.updated", id, data: { requirement_id: id } });
    });
    await waitFor(() => expect(spy.mock.calls.length).toBe(once + 1));
    await act(async () => undefined);
    expect(await dugme()).toHaveAttribute("aria-label", yeniDeger!);
  });

  it("açık varlığın olayları 5 sn penceresinde tek yenileme; başka varlığın olayı yok sayılır", async () => {
    // Sahte saat: pencere kesin ilerletilir, negatif doğrulama gerçek beklemeye dayanmaz.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      await oturumAc("analist");
      const pencere = oneriAyar.olayGecikmeMs;
      const ilerlet = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));
      const spy = vi.spyOn(oneriApi, "liste");
      uygulama("/gereksinimler/req-ft-1");
      await dugme();
      await waitFor(() => expect(spy).toHaveBeenCalled());
      await ilerlet(10);
      const once = spy.mock.calls.length;
      act(() => {
        mockOlayYayinla({ type: "requirement.updated", id: "req-tpd-3", data: { requirement_id: "req-tpd-3" } });
        mockOlayYayinla({ type: "assistant.answered", id: "m-1", data: { mesaj_id: "m-1" } });
      });
      await ilerlet(pencere + 100);
      expect(spy.mock.calls.length).toBe(once);
      act(() => {
        mockOlayYayinla({ type: "requirement.updated", id: "req-ft-1", data: { requirement_id: "req-ft-1" } });
        mockOlayYayinla({ type: "finding.updated", id: "fnd-1", data: { requirement_id: "req-ft-1" } });
        mockOlayYayinla({ type: "requirement.updated", id: "req-ft-1", data: { requirement_id: "req-ft-1" } });
      });
      await ilerlet(pencere - 100);
      expect(spy.mock.calls.length).toBe(once);
      await ilerlet(200);
      await waitFor(() => expect(spy.mock.calls.length).toBe(once + 1));
      await ilerlet(pencere * 2);
      expect(spy.mock.calls.length).toBe(once + 1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("core biçimli olaylar (gereksinim kimliği taşımayan bulgu/case olayları) rozeti yeniler", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      await oturumAc("analist");
      const pencere = oneriAyar.olayGecikmeMs;
      const ilerlet = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));
      const spy = vi.spyOn(oneriApi, "liste");
      uygulama("/gereksinimler/req-ft-1");
      await dugme();
      await waitFor(() => expect(spy).toHaveBeenCalled());
      await ilerlet(10);
      const once = spy.mock.calls.length;
      // Başka gereksinimin kendi core olayı yok sayılır.
      act(() => mockOlayYayinla({ type: "requirement.state", id: "req-tpd-3", data: { id: "req-tpd-3", durum: "approved" } }));
      await ilerlet(pencere + 100);
      expect(spy.mock.calls.length).toBe(once);
      // core: consistency_finding.state {id, from, durum, aktor} — requirement_id yok.
      act(() => mockOlayYayinla({ type: "consistency_finding.state", id: "fnd-9", data: { id: "fnd-9", from: "open", durum: "resolved", aktor: "u1" } }));
      await ilerlet(pencere + 100);
      await waitFor(() => expect(spy.mock.calls.length).toBe(once + 1));
      // core: review.recorded {id, nesne_turu, nesne_id} ve test_case.state.
      act(() => mockOlayYayinla({ type: "review.recorded", id: "tc-9", data: { id: "rv-1", nesne_turu: "test_case", nesne_id: "tc-9" } }));
      await ilerlet(pencere + 100);
      await waitFor(() => expect(spy.mock.calls.length).toBe(once + 2));
      act(() => mockOlayYayinla({ type: "test_case.state", id: "tc-9", data: { id: "tc-9", from: "draft", durum: "approved" } }));
      await ilerlet(pencere + 100);
      await waitFor(() => expect(spy.mock.calls.length).toBe(once + 3));
    } finally {
      vi.useRealTimers();
    }
  });

  it("sonuç varken Öneriler sekmesinde 'Yenile' zorla yeniden okur", async () => {
    await oturumAc("analist");
    const spy = vi.spyOn(oneriApi, "liste");
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
    expect(spy).toHaveBeenCalledTimes(1);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Önerileri yenile" }));
    });
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
  });

  it("429: önceki değer yokken sekmede kısa not, değer varken sessiz", async () => {
    await oturumAc("analist");
    const spy = vi.spyOn(oneriApi, "liste").mockRejectedValueOnce(new ApiError(429, "Çok sık", { kod: "hiz_siniri" }));
    render(
      <MemoryRouter>
        <OturumProvider>
          <BildirimProvider>
            <OnerilerSekmesi ekran={{ rota_kalibi: "/gereksinimler/:id", ekran: "Gereksinim detayı", varlik: { tur: "requirement", id: "req-ft-1" } }} asistan={null} />
          </BildirimProvider>
        </OturumProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText(/Çok sık istek gönderildi/)).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Yeniden dene" }));
    });
    expect(await screen.findByText(/tutarlılık bulgusu kararınızı bekliyor/)).toBeInTheDocument();
    expect(spy).toHaveBeenCalledTimes(2);
  });
});

describe("Öneriler sekmesi", () => {
  it("panelde öncelik sırası (azalan)", async () => {
    await oturumAc("analist");
    vi.spyOn(oneriApi, "liste").mockResolvedValue(
      liste({
        oneriler: [
          { kural_id: "b", baslik: "Düşük öncelik", neden: "n", oncelik: 40, eylem: { tur: "bilgi" } },
          { kural_id: "a", baslik: "Yüksek öncelik", neden: "n", oncelik: 95, eylem: { tur: "bilgi" } },
          { kural_id: "c", baslik: "Orta öncelik", neden: "n", oncelik: 70, eylem: { tur: "bilgi" } },
        ],
      }),
    );
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    const s = await oneriPaneliniAc(u);
    const basliklar = s.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(basliklar).toEqual(["Yüksek öncelik", "Orta öncelik", "Düşük öncelik"]);
    expect(await dugme()).toHaveAccessibleName("Öneriler (3)");
  });

  it('"Git" iç rotaya (çapa ile) gider', async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    const s = await oneriPaneliniAc(u);
    await u.click(s.getByRole("button", { name: "Git" }));
    expect(screen.getByTestId("konum")).toHaveTextContent("/gereksinimler/req-ft-1#bulgular");
  });

  it("Jira taslağı: Taslağı göster, panoya düz metin; 'Jira'yı aç' yalnız sunucu verdiyse", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    // userEvent.setup kendi pano sahtesini kurar; ondan sonra değiştirilir.
    const yaz = vi.fn().mockResolvedValue(undefined);
    panoAyarla({ writeText: yaz });
    uygulama("/kosular/run-109");
    const s = await oneriPaneliniAc(u);
    expect(s.getByRole("heading", { name: "Testler koşmadı: CI ortam hatası" })).toBeInTheDocument();
    // Simülatörde kayıt oluşturma sayfası yok: bağlantı yok, neden yazılı.
    expect(s.queryByRole("link", { name: /Jira'yı aç/ })).toBeNull();
    expect(s.getByText(/Demo Jira'sında kayıt oluşturma sayfası yok/)).toBeInTheDocument();
    expect(s.getByText("Bu bir öneridir; kaydı siz açarsınız.")).toBeInTheDocument();
    await u.click(s.getByRole("button", { name: "Taslağı göster" }));
    expect(s.getByText("Proje: TPD, Tür: Task seçin; metni yapıştırın.")).toBeInTheDocument();
    await u.click(s.getByRole("button", { name: "Kopyala" }));
    expect(yaz).toHaveBeenCalledTimes(1);
    const metin = yaz.mock.calls[0][0] as string;
    expect(metin).toContain("Proje: TPD");
    expect(metin).toContain("Tür: Task");
    expect(metin).toContain("Etiketler: ci, ortam");
    expect(metin).toContain("Özet: CI ortam hatası testlerin koşmasını engelliyor");
    expect(metin).not.toMatch(/https?:\/\//);
    expect(await screen.findByText("Taslak panoya kopyalandı.")).toBeInTheDocument();
  });

  it("Jira yorumu: sunucu kurduğu bağlantı yeni sekmede, rel=noopener noreferrer", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-tpd-2");
    const s = await oneriPaneliniAc(u);
    const a = s.getByRole("link", { name: /Jira'yı aç/ });
    expect(a).toHaveAttribute("href", "http://127.0.0.1:8090/browse/TPD-2");
    expect(a).toHaveAttribute("target", "_blank");
    expect(a.getAttribute("rel")).toBe("noopener noreferrer");
    await u.click(s.getByRole("button", { name: "Taslağı göster" }));
    expect(s.getByText(/TPD-2 kaydında kabul kriterleri eksik/)).toBeInTheDocument();
  });

  it("pano yoksa (HTTPS değil) hata bildirimi + seçilebilir textarea yedeği", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    panoAyarla(undefined);
    uygulama("/kosular/run-109");
    const s = await oneriPaneliniAc(u);
    await u.click(s.getByRole("button", { name: "Taslağı göster" }));
    await u.click(s.getByRole("button", { name: "Kopyala" }));
    const alan = s.getByLabelText("Kopyalanacak taslak metni") as HTMLTextAreaElement;
    expect(alan.readOnly).toBe(true);
    expect(alan.value).toContain("Proje: TPD");
    expect(await screen.findByText(/Pano bu bağlantıda kullanılamıyor/)).toBeInTheDocument();
  });

  it('"Neden? Sor" sohbet sekmesine geçer ve oneri_kural_id ile soru gönderir; hazır soru çipleri', async () => {
    await oturumAc("analist");
    const gonder = vi.spyOn(asistanApi, "soruGonder");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    const s = await oneriPaneliniAc(u);
    expect(s.getByRole("button", { name: "Kim onaylıyor?" })).toBeInTheDocument();
    // Jira çipi yalnız Jira eylemli kartta.
    expect(s.queryByRole("button", { name: "Jira'da nasıl açarım?" })).toBeNull();
    await u.click(s.getByRole("button", { name: "Neden? Sor" }));
    await waitFor(() => expect(gonder).toHaveBeenCalled());
    const [, govde] = gonder.mock.calls[0];
    expect(govde.oneri_kural_id).toBe("gereksinim-bulgu-karari");
    expect(govde.soru).toBe("Bu öneriyi neden yapmalıyım, yapmazsam ne olur?");
    expect(govde.kip).toBe("soru");
    expect(screen.getByRole("tab", { name: "Sohbet" })).toHaveAttribute("aria-selected", "true");
  });

  it('"Neden? Sor" sonrası aynı kartın hazır soru çipi yeni sohbet açmaz, o sohbete takip sorusu olur', async () => {
    await oturumAc("analist");
    const olustur = vi.spyOn(asistanApi, "sohbetOlustur");
    const gonder = vi.spyOn(asistanApi, "soruGonder");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    const s = await oneriPaneliniAc(u);
    await u.click(s.getByRole("button", { name: "Neden? Sor" }));
    await waitFor(() => expect(gonder).toHaveBeenCalledTimes(1));
    act(() => asistanMockIsle(asistanMockBekleyenler().at(-1)!));
    await waitFor(() => expect(asistanMockBekleyenler()).toHaveLength(0));
    await u.click(screen.getByRole("tab", { name: "Öneriler" }));
    await u.click(within(await screen.findByTestId("oneriler-sekmesi")).getByRole("button", { name: "Kim onaylıyor?" }));
    await waitFor(() => expect(gonder).toHaveBeenCalledTimes(2));
    expect(olustur).toHaveBeenCalledTimes(1);
    expect(gonder.mock.calls[1][0]).toBe(gonder.mock.calls[0][0]);
    expect(gonder.mock.calls[1][1].oneri_kural_id).toBeUndefined();
    expect(gonder.mock.calls[1][1].soru).toBe("Kim onaylıyor?");
  });

  it('model kapalıyken "Açıklamayı göster" kural açıklamasını gösterir (model çağrısı yok); "Başka ne yapabilirim?" gizli', async () => {
    await oturumAc("analist");
    asistanMockAyarla({ mod: "off" });
    const gonder = vi.spyOn(asistanApi, "soruGonder");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    const s = await oneriPaneliniAc(u);
    expect(s.queryByRole("button", { name: "Neden? Sor" })).toBeNull();
    expect(s.queryByRole("button", { name: "Başka ne yapabilirim?" })).toBeNull();
    expect(s.queryByRole("list", { name: "Hazır sorular" })).toBeNull();
    await u.click(s.getByRole("button", { name: "Açıklamayı göster" }));
    expect(s.getByText(/Tutarlılık denetimi dokümanı kodla ve veriyle karşılaştırdı/)).toBeInTheDocument();
    expect(gonder).not.toHaveBeenCalled();
  });

  it('"Başka ne yapabilirim?" kip=oneri gönderir; AI önerisi etiketli kart', async () => {
    await oturumAc("analist");
    const gonder = vi.spyOn(asistanApi, "soruGonder");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    const s = await oneriPaneliniAc(u);
    await u.click(s.getByRole("button", { name: "Başka ne yapabilirim?" }));
    await waitFor(() => expect(gonder).toHaveBeenCalled());
    expect(gonder.mock.calls[0][1].kip).toBe("oneri");
    expect(gonder.mock.calls[0][1].soru).toBe("");
    expect(s.getByText("Ek öneriler hazırlanıyor…")).toBeInTheDocument();
    const id = asistanMockBekleyenler().at(-1)!;
    act(() => asistanMockIsle(id));
    expect(await s.findByText("AI önerisi · doğrulanmadı")).toBeInTheDocument();
    expect(s.getByRole("heading", { name: "Kapsam bulgularını gözden geçirin" })).toBeInTheDocument();
  });

  it('"Başka ne yapabilirim?" ekran/varlık başına tek "Ek öneri" sohbeti açar (tekrar tıklamada yeniden kullanır)', async () => {
    await oturumAc("analist");
    const olustur = vi.spyOn(asistanApi, "sohbetOlustur");
    const gonder = vi.spyOn(asistanApi, "soruGonder");
    const u = userEvent.setup();
    for (let tur = 0; tur < 2; tur++) {
      // Her turda bileşen yeniden bağlanır (panel kapatılıp açılmış gibi); sohbet eşlemi modülde kalır.
      const r = uygulama("/gereksinimler/req-ft-1");
      const s = await oneriPaneliniAc(u);
      await u.click(s.getByRole("button", { name: "Başka ne yapabilirim?" }));
      await waitFor(() => expect(gonder).toHaveBeenCalledTimes(tur + 1));
      act(() => asistanMockIsle(asistanMockBekleyenler().at(-1)!));
      await s.findByText("AI önerisi · doğrulanmadı");
      r.unmount();
      asistanKontrolSifirla();
    }
    expect(olustur).toHaveBeenCalledTimes(1);
    expect(olustur).toHaveBeenCalledWith("Ek öneri");
    expect(gonder.mock.calls[1][0]).toBe(gonder.mock.calls[0][0]);
  });

  it('"Faydalı" 1 geri bildirimi yazar; kart kalır ve düğme basılı olur', async () => {
    await oturumAc("analist");
    const gb = vi.spyOn(oneriApi, "geriBildirim");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    const s = await oneriPaneliniAc(u);
    await u.click(s.getByRole("button", { name: "Faydalı" }));
    await waitFor(() => expect(gb).toHaveBeenCalledWith("gereksinim-bulgu-karari", { deger: 1, varlik_id: "req-ft-1" }));
    expect(oneriMockGeriBildirimleri()[0]).toMatchObject({ deger: 1, varlik_id: "req-ft-1" });
    expect(await s.findByRole("button", { name: "Faydalı" })).toHaveAttribute("aria-pressed", "true");
    expect(s.getByRole("heading", { name: /bulgu/i })).toBeInTheDocument();
  });

  it('"Gizle" -1 geri bildirimi yazar ve kartı kaldırır (yalnız o kullanıcı)', async () => {
    await oturumAc("analist");
    const gb = vi.spyOn(oneriApi, "geriBildirim");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    const s = await oneriPaneliniAc(u);
    await u.click(s.getByRole("button", { name: "Gizle" }));
    await waitFor(() => expect(gb).toHaveBeenCalledWith("gereksinim-bulgu-karari", { deger: -1, varlik_id: "req-ft-1" }));
    expect(await s.findByText("Bu ekranda sizin için bekleyen bir iş yok.")).toBeInTheDocument();
    await waitFor(async () => expect(await dugme()).toHaveAccessibleName("Öneriler (0)"));
  });

  it('"Yaptım" isteğe bağlı Jira anahtarıyla: geçersiz anahtar reddedilir; kartın yerinde "yaptım dedi"', async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    const s = await oneriPaneliniAc(u);
    await u.click(s.getByRole("button", { name: "Yaptım" }));
    const alan = s.getByLabelText("Jira anahtarı (isteğe bağlı)");
    await u.type(alan, "tpd 12");
    await u.click(s.getByRole("button", { name: "Kaydet" }));
    expect(s.getByRole("alert")).toHaveTextContent("Jira anahtarı biçimi geçersiz");
    expect(oneriMockGeriBildirimleri()).toHaveLength(0);
    await u.clear(alan);
    await u.type(alan, "tpd-12");
    await u.click(s.getByRole("button", { name: "Kaydet" }));
    expect(await s.findByText(/analist yaptım dedi · TPD-12 · az önce/)).toBeInTheDocument();
    expect(oneriMockGeriBildirimleri()[0]).toMatchObject({ deger: 2, jira_anahtari: "TPD-12", varlik_id: "req-ft-1" });
  });

  it('"Yaptım" tüm rollerde bastırır; "Diğer ekranlarda N iş → Git" rozete sayılmaz', async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    uygulama("/kod/scr-1");
    const s = await oneriPaneliniAc(u);
    expect(await dugme()).toHaveAccessibleName("Öneriler (1)");
    const diger = s.getByText(/Diğer ekranlarda sizi bekleyen \d+ iş/);
    expect(within(diger).getByRole("link", { name: "Git" })).toBeInTheDocument();
  });

  it("boş durum: metin + kuyruk bağlantısı", async () => {
    await oturumAc("analist");
    vi.spyOn(oneriApi, "liste").mockResolvedValue(liste({}));
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-tpd-1");
    const s = await oneriPaneliniAc(u);
    expect(s.getByText("Bu ekranda sizin için bekleyen bir iş yok.")).toBeInTheDocument();
    expect(s.getByRole("link", { name: "İş kuyruğunuza gidin" })).toHaveAttribute("href", "/");
  });
});

describe("vurgu ve mock sözleşmesi", () => {
  it("panel bir kuralla açılınca o kart vurgulanır", async () => {
    await oturumAc("analist");
    uygulama("/gereksinimler/req-ft-1");
    await dugme();
    act(() => acSekme("oneriler", { oneriKuralId: "gereksinim-bulgu-karari" }));
    const s = within(await screen.findByTestId("oneriler-sekmesi"));
    const kart = (await s.findByRole("heading", { name: /tutarlılık bulgusu/ })).closest("article")!;
    expect(kart).toHaveClass("oneri-karti-vurgulu");
  });

  it("geri bildirim: bilinmeyen kural 422, geçersiz anahtar 422, başka rolün kuralı 404", async () => {
    await oturumAc("analist");
    await expect(oneriApi.geriBildirim("yok-boyle", { deger: -1 })).rejects.toMatchObject({ status: 422 });
    await expect(oneriApi.geriBildirim("gereksinim-bulgu-karari", { deger: 2, varlik_id: "req-ft-1", jira_anahtari: "tpd" })).rejects.toMatchObject({ status: 422 });
    await expect(oneriApi.geriBildirim("bug-taslagi-karari", { deger: -1, varlik_id: "bug-1" })).rejects.toMatchObject({ status: 404 });
    await expect(oneriApi.liste({ rota: "/claude-code" })).resolves.toMatchObject({ ekranda_kural_var: false });
    await oturumAc("testci");
    await expect(oneriApi.liste({ rota: "/claude-code" })).rejects.toMatchObject({ status: 404 });
  });
});

describe("yardımcılar", () => {
  it("AI taslağında URL, wiki bağlantısı ve mention temizlenir; dış rota Git olmaz", () => {
    expect(aiMetniTemizle("Bkz. https://evil.example/x?a=1 ve www.x.com")).toBe("Bkz. [bağlantı kaldırıldı] ve [bağlantı kaldırıldı]");
    expect(aiMetniTemizle("[tıkla|https://evil.example] [~accountid:123] @ahmet")).toBe("tıkla  ahmet");
    const k = aiOnerisiKarta({
      baslik: "Bak https://x.y",
      neden: "n",
      eylem: { tur: "rota", rota: "https://evil.example", anahtar: null, taslak: null },
    });
    expect(k.eylem.tur).toBe("bilgi");
    expect(k.baslik).toBe("Bak [bağlantı kaldırıldı]");
    const t = aiOnerisiKarta({
      baslik: "b",
      neden: "n",
      eylem: { tur: "jira_taslak", rota: null, anahtar: "kötü", taslak: { tur: "Task", ozet: "ö", aciklama: "a [x|http://e.x]" }, baglanti: "javascript:alert(1)" },
    });
    expect(t.eylem.baglanti).toBeNull();
    expect(t.eylem.anahtar).toBeNull();
    expect(t.eylem.taslak?.aciklama).toBe("a x");
  });

  it("göreli zaman ve taslak metni", () => {
    const simdi = Date.parse("2026-11-03T12:00:00Z");
    expect(goreliZaman("2026-11-03T11:59:40Z", simdi)).toBe("az önce");
    expect(goreliZaman("2026-11-03T11:15:00Z", simdi)).toBe("45 dk önce");
    expect(goreliZaman("2026-11-03T10:00:00Z", simdi)).toBe("2 sa önce");
    expect(goreliZaman("2026-11-01T10:00:00Z", simdi)).toBe("2 gün önce");
    expect(taslakMetni({ anahtar: "TPD-3", taslak: { proje: "TPD", tur: "yorum", ozet: "", aciklama: "Merhaba" } })).toBe(
      "Proje: TPD\nKayıt: TPD-3\nTür: yorum\n\nAçıklama:\nMerhaba",
    );
  });
});

describe.each([
  { kullanici: "analist", yol: "/gereksinimler/req-ft-1", baslik: /tutarlılık bulgusu kararınızı bekliyor/, eylem: "Git" },
  { kullanici: "po", yol: "/gereksinimler/req-tpd-3", baslik: /Onayınız bekleniyor/, eylem: "Jira'yı aç" },
  { kullanici: "muhendis", yol: "/kod/scr-1", baslik: /Merge öncesi kırarak doğrulayın/, eylem: "Git" },
  { kullanici: "testci", yol: "/hatalar/fail-1", baslik: /Bug taslağı kararınızı bekliyor/, eylem: "Git" },
  { kullanici: "sunucu", yol: "/kosular", baslik: /Güncel koşu yok/, eylem: "Git" },
])("5 rol: $kullanici", ({ kullanici, yol, baslik, eylem }) => {
  it("kendi rolünün önerisini görür; başka rolün kuralı görünmez", async () => {
    await oturumAc(kullanici);
    const u = userEvent.setup();
    uygulama(yol);
    const d = await dugme();
    await waitFor(() => expect(d.getAttribute("aria-label")).toMatch(/^Öneriler \([1-9]\d*\)$/));
    const s = await oneriPaneliniAc(u);
    expect(s.getByRole("heading", { name: baslik })).toBeInTheDocument();
    const eylemOgesi = eylem === "Git" ? s.getAllByRole("button", { name: "Git" })[0] : s.getByRole("link", { name: /Jira'yı aç/ });
    expect(eylemOgesi).toBeInTheDocument();
    // Diğer rollerin kural başlıkları bu rolde yok.
    const yabanci = {
      analist: /Onayınız bekleniyor/,
      po: /tutarlılık bulgusu/,
      muhendis: /Bug taslağı kararınızı/,
      testci: /kırarak doğrulayın/,
      sunucu: /Bakım hatası/,
    }[kullanici]!;
    expect(sekme().textContent).not.toMatch(yabanci);
  });
});
