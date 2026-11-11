// 013 §7 (K12) şeffaflık + yeni hata kodları: kalıcı yapay zekâ bildirimi, cevap kartı kip rozeti
// (CANLI · model / ŞABLON / MODEL KAPALI), 422 `kisisel_veri` ve 429 `donduruldu` metinleri, dondurma
// süresince gönderimin kapalı kalıp süre dolunca açılması (sahte saat).
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { asistanApi, kipRozeti, modelKisaAdi, type AsistanMesaji } from "../../api/asistan";
import { ApiError, mockZorunlu, yapilandir } from "../../api/http";
import { asistanMockAyarla, asistanMockBekleyenler, asistanMockIsle } from "../../api/mock/asistan";
import { OturumProvider } from "../../auth";
import { oturumAc } from "../../test/yardimci";
import { BildirimProvider } from "../Bildirim";
import { AsistanPaneli, YZ_BILDIRIMI } from "./AsistanPaneli";
import { CevapKarti } from "./CevapKarti";
import { asistanKontrolSifirla } from "./kontrol";
import { sohbetAyar } from "./SohbetSekmesi";

const KART = "5105 1051 0510 5100";
const KISISEL = "Soru kart numarası gibi kişisel veri içeriyor; çıkarıp yeniden deneyin.";

function yalnizPanel(yol = "/kosular") {
  return render(
    <MemoryRouter initialEntries={[yol]}>
      <OturumProvider>
        <BildirimProvider>
          <AsistanPaneli />
        </BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

const panel = () => screen.getByTestId("asistan-paneli");

async function paneliAc(u: ReturnType<typeof userEvent.setup>) {
  await u.click(await screen.findByRole("button", { name: "Asistanı aç" }));
  return panel();
}

async function yaz(u: ReturnType<typeof userEvent.setup>, metin: string) {
  const alan = within(panel()).getByLabelText("Sorunuz");
  await u.clear(alan);
  await u.type(alan, metin);
  await u.click(within(panel()).getByRole("button", { name: "Asistana sor" }));
}

function mesaj(alan: Partial<AsistanMesaji>): AsistanMesaji {
  return {
    id: "m-1",
    sohbet_id: "s-1",
    sira: 2,
    rol: "assistant",
    ust_mesaj_id: null,
    icerik: "soru",
    cevap: { cevap_bloklari: [{ tur: "paragraf", metin: "Cevap" }], kaynaklar: [], yonlendirmeler: [], eylem_reddi: false },
    durum: "done",
    hata_kodu: null,
    kaynak: "model",
    amac: "assistant",
    kip: "soru",
    tetik: "kullanici",
    maliyet_usd: null,
    sure_ms: null,
    geri_bildirim: null,
    olusturma: "2026-11-11T10:00:00Z",
    tamamlanma: "2026-11-11T10:00:02Z",
    ...alan,
  };
}

function kart(m: AsistanMesaji, modeller?: Parameters<typeof CevapKarti>[0]["modeller"]) {
  return render(
    <MemoryRouter>
      <CevapKarti mesaj={m} modeller={modeller} />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  asistanKontrolSifirla();
  asistanMockAyarla({ otomatikIsle: false });
  Object.assign(sohbetAyar, { yoklamaMs: 30 });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  asistanKontrolSifirla();
  Object.assign(sohbetAyar, { yoklamaMs: 3000 });
});

describe("yapay zekâ bildirimi", () => {
  it("başlığın altında kalıcı, kapatılamaz not; Sohbet ve Öneriler sekmelerinde görünür", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    const not = within(p).getByRole("note");
    expect(not).toHaveTextContent(YZ_BILDIRIMI);
    expect(YZ_BILDIRIMI).toBe("Yapay zekâ asistanı; cevaplar hatalı olabilir, kararı ilgili ekranda siz verirsiniz.");
    // Başlıktan sonra, sekme listesinden önce; kapatma düğmesi yok.
    const baslik = within(p).getByRole("heading", { name: "Asistan", level: 2 });
    expect(baslik.compareDocumentPosition(not) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(not.compareDocumentPosition(within(p).getByRole("tablist")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(not).queryByRole("button")).toBeNull();
    await u.click(within(p).getByRole("tab", { name: "Öneriler" }));
    expect(within(panel()).getByRole("note")).toHaveTextContent(YZ_BILDIRIMI);
    await u.click(within(panel()).getByRole("tab", { name: "Sohbet" }));
    expect(within(panel()).getByRole("note")).toHaveTextContent(YZ_BILDIRIMI);
  });

  it("model kapalı kipte ve pasif asistanda da görünür", async () => {
    asistanMockAyarla({ mod: "off" });
    await oturumAc("analist");
    const u = userEvent.setup();
    const { unmount } = yalnizPanel();
    expect(within(await paneliAc(u)).getByRole("note")).toHaveTextContent(YZ_BILDIRIMI);
    unmount();
    asistanKontrolSifirla();
    asistanMockAyarla({ etkin: false, neden: "worker_yok" });
    yalnizPanel();
    await u.click(await screen.findByRole("button", { name: "Asistan (kapalı)" }));
    // Pasif uyarı da role="note" taşır: bildirim kendi kimliğiyle aranır.
    const not = within(panel()).getByTestId("asistan-yz-bildirimi");
    expect(not).toHaveAttribute("role", "note");
    expect(not).toHaveTextContent(YZ_BILDIRIMI);
  });
});

describe("kip rozeti", () => {
  it("model kısa adı", () => {
    expect(modelKisaAdi("claude-haiku-5-5")).toBe("Haiku 5.5");
    expect(modelKisaAdi("claude-sonnet-5-5")).toBe("Sonnet 5.5");
    expect(modelKisaAdi("claude-sonnet-4-6-20260101")).toBe("Sonnet 4.6");
    expect(modelKisaAdi("claude-sonnet-4-20250514")).toBe("Sonnet 4");
    expect(modelKisaAdi("us.anthropic.claude-opus-5-v1:0")).toBe("Opus 5");
    expect(modelKisaAdi("claude-3-5-haiku-20241022")).toBe("Haiku");
    expect(modelKisaAdi("gpt-x")).toBeNull();
    expect(modelKisaAdi(null)).toBeNull();
    expect(modelKisaAdi("")).toBeNull();
  });

  it("kaynak → rozet: CANLI · model, derin model, ŞABLON, MODEL KAPALI", () => {
    const d = { varsayilan_model: "claude-haiku-5-5", derin_model: "claude-sonnet-5-5" };
    expect(kipRozeti({ kaynak: "model", amac: "assistant" }, d)?.metin).toBe("CANLI · Haiku 5.5");
    expect(kipRozeti({ kaynak: "model", amac: "assistant_deep" }, d)?.metin).toBe("CANLI · Sonnet 5.5");
    // Status derin modeli bildirmiyorsa derin cevapta varsayılan model söylenmez: yalnız CANLI.
    expect(kipRozeti({ kaynak: "model", amac: "assistant_deep" }, { varsayilan_model: "claude-haiku-5-5" })?.metin).toBe("CANLI");
    expect(kipRozeti({ kaynak: "model", amac: "assistant" }, null)?.metin).toBe("CANLI");
    expect(kipRozeti({ kaynak: "model", amac: "assistant" }, { varsayilan_model: "bilinmeyen" })?.metin).toBe("CANLI");
    expect(kipRozeti({ kaynak: "sozluk", amac: null })).toMatchObject({ tur: "sablon", metin: "ŞABLON", aciklama: "Hazır cevap · hata sözlüğü" });
    expect(kipRozeti({ kaynak: "sablon", amac: null })).toMatchObject({ tur: "sablon", metin: "ŞABLON", aciklama: "Hazır cevap · kayıt durumu" });
    expect(kipRozeti({ kaynak: "kapali", amac: null })).toMatchObject({ tur: "kapali", metin: "MODEL KAPALI" });
    expect(kipRozeti({ kaynak: null, amac: null })).toBeNull();
  });

  it("kartta tek rozet: metin + açıklama (title ve ekran okuyucu metni); ayrı 'Hazır cevap' etiketi yok", () => {
    // Gerçek derleme davranışı: örnek veri zorunlu değil (mock derlemesinde CANLI gösterilmez).
    const onceki = mockZorunlu();
    yapilandir({ mockZorunlu: false });
    onTestFinished(() => yapilandir({ mockZorunlu: onceki }));
    const { unmount } = kart(mesaj({ kaynak: "model" }), { varsayilan_model: "claude-haiku-5-5" });
    const r = screen.getByTestId("kip-rozeti");
    expect(r).toHaveTextContent(/^CANLI · Haiku 5\.5$/);
    expect(r).toHaveClass("rozet", "rozet-kip", "rozet-kip-canli");
    expect(r).toHaveAttribute("title", "Canlı model cevabı");
    unmount();

    const k2 = kart(mesaj({ kaynak: "sablon", amac: null }));
    const s = screen.getByTestId("kip-rozeti");
    expect(s).toHaveTextContent(/^ŞABLON$/);
    expect(s).toHaveClass("rozet-kip-sablon");
    expect(s).toHaveAttribute("title", "Hazır cevap · kayıt durumu");
    // Açıklama yalnız görünmez metin: görünür ikinci etiket yok.
    expect(screen.getByText("Hazır cevap · kayıt durumu")).toHaveClass("gorunmez");
    expect(screen.getAllByTestId("kip-rozeti")).toHaveLength(1);
    k2.unmount();

    kart(mesaj({ kaynak: "kapali", amac: null }));
    expect(screen.getByTestId("kip-rozeti")).toHaveTextContent(/^MODEL KAPALI$/);
    expect(screen.getByTestId("kip-rozeti")).toHaveClass("rozet-kip-kapali");
  });

  it("panelde (örnek veri): model cevabında CANLI yok, ÖRNEK VERİ var; şablon cevabı 'ŞABLON'", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    await yaz(u, "Kırarak doğrula neden gri?");
    await waitFor(() => expect(asistanMockBekleyenler()).toHaveLength(1));
    act(() => asistanMockIsle(asistanMockBekleyenler()[0]));
    const k1 = await within(p).findByRole("article", { name: "Asistan cevabı" }, { timeout: 5000 });
    // Örnek veri derlemesi: hazırlanmış "model" cevabı CANLI gösterilmez, yalnız ÖRNEK VERİ.
    expect(within(k1).queryByTestId("kip-rozeti")).toBeNull();
    expect(within(k1).getByText("ÖRNEK VERİ")).toBeInTheDocument();
    await yaz(u, "Bugün ne yapmalıyım?");
    await waitFor(() => expect(asistanMockBekleyenler()).toHaveLength(1));
    act(() => asistanMockIsle(asistanMockBekleyenler()[0]));
    await waitFor(() => expect(within(p).getAllByRole("article")).toHaveLength(2));
    expect(within(within(p).getAllByRole("article")[1]).getByTestId("kip-rozeti")).toHaveTextContent(/^ŞABLON$/);
  });

  it("model kapalı kipte genel soru 'MODEL KAPALI'", async () => {
    asistanMockAyarla({ mod: "off" });
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    await yaz(u, "Bu ekran ne işe yarar?");
    await waitFor(() => expect(asistanMockBekleyenler()).toHaveLength(1));
    act(() => asistanMockIsle(asistanMockBekleyenler()[0]));
    const k = await within(p).findByRole("article", {}, { timeout: 5000 });
    expect(within(k).getByTestId("kip-rozeti")).toHaveTextContent(/^MODEL KAPALI$/);
  });
});

describe("yeni hata kodları", () => {
  it("422 kisisel_veri: metin gösterilir, taslak girdide kalır", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    const soru = `Müşterinin kartı ${KART} neden reddedildi?`;
    await yaz(u, soru);
    expect(await within(p).findByRole("alert")).toHaveTextContent(KISISEL);
    expect(within(p).getByLabelText("Sorunuz")).toHaveValue(soru);
    expect(asistanMockBekleyenler()).toHaveLength(0);
    // Gönderim açık kalır (dondurma değil).
    expect(within(p).getByRole("button", { name: "Asistana sor" })).toBeEnabled();
  });

  it("429 donduruldu: ~N dk metni, gönderim kalan_s boyunca kapalı, süre dolunca açılır; taslak korunur", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const ilerlet = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));
    await oturumAc("analist");
    const u = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const gonder = vi
      .spyOn(asistanApi, "soruGonder")
      .mockRejectedValueOnce(new ApiError(429, "Dondu.", { kod: "donduruldu", ek: { kalan_s: 61 } }));
    yalnizPanel();
    const p = await paneliAc(u);
    await yaz(u, "Bu ekran ne işe yarar?");
    const uyari = await within(p).findByRole("alert");
    // ⌈61/60⌉ = 2
    expect(uyari).toHaveTextContent("Asistan, art arda engellenen istekler nedeniyle ~2 dk kullanılamıyor.");
    const alan = within(p).getByLabelText("Sorunuz");
    expect(alan).toHaveValue("Bu ekran ne işe yarar?");
    const dugme = within(p).getByRole("button", { name: "Asistana sor" });
    expect(dugme).toBeDisabled();
    expect(dugme.getAttribute("aria-describedby")).toContain("asistan-gonderim-hatasi");
    // Enter da göndermez; hazır soru çipleri de kapalı.
    fireEvent.keyDown(alan, { key: "Enter" });
    expect(gonder).toHaveBeenCalledTimes(1);

    await ilerlet(60_000);
    expect(within(p).getByRole("button", { name: "Asistana sor" })).toBeDisabled();
    await ilerlet(1_100);
    await waitFor(() => expect(within(p).getByRole("button", { name: "Asistana sor" })).toBeEnabled());
    expect(within(p).queryByText(/art arda engellenen/)).toBeNull();
    expect(within(p).getByLabelText("Sorunuz")).toHaveValue("Bu ekran ne işe yarar?");
  });

  it("dondurma sekme geçişinde korunur; kalan_s yoksa 10 dk varsayılır", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const ilerlet = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));
    await oturumAc("analist");
    const u = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    vi.spyOn(asistanApi, "soruGonder").mockRejectedValueOnce(new ApiError(429, "Dondu.", { kod: "donduruldu" }));
    yalnizPanel();
    const p = await paneliAc(u);
    await yaz(u, "Bu ekran ne işe yarar?");
    expect(await within(p).findByRole("alert")).toHaveTextContent("~10 dk");
    await u.click(within(p).getByRole("tab", { name: "Öneriler" }));
    await u.click(within(panel()).getByRole("tab", { name: "Sohbet" }));
    expect(within(panel()).getByRole("alert")).toHaveTextContent("art arda engellenen");
    expect(within(panel()).getByRole("button", { name: "Asistana sor" })).toBeDisabled();
    await ilerlet(600_000 + 100);
    await waitFor(() => expect(within(panel()).getByRole("button", { name: "Asistana sor" })).toBeEnabled());
  });

  it("mock: art arda üç sır reddinden sonra 429 donduruldu (~10 dk)", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    const sahte = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4";
    for (let i = 0; i < 3; i++) {
      await yaz(u, `token ${sahte}`);
      expect(await within(p).findByRole("alert")).toHaveTextContent(/parola\/token/);
    }
    await yaz(u, "Bu ekran ne işe yarar?");
    await waitFor(() => expect(within(p).getByRole("alert")).toHaveTextContent("Asistan, art arda engellenen istekler nedeniyle ~10 dk kullanılamıyor."));
    expect(within(p).getByRole("button", { name: "Asistana sor" })).toBeDisabled();
    expect(within(p).getByLabelText("Sorunuz")).toHaveValue("Bu ekran ne işe yarar?");
  });
});
