// Asistan paneli inceleme düzeltmeleri (tur 2): "Neden? Sor" StrictMode'da tek gönderim ve takip
// sorularında `oneri_kural_id` yok; ek öneri beklemesi sekme değişince kaybolmaz; Geçmiş hataları;
// pasif asistanın yeniden okunması; "Son hata" çipinin 5 dk sonunda kalkması; "Bu ne?" seçiminin rota
// değişince temizlenmesi; alıntı modalının odak tuzağı; "Asistanı aç" atlamasının hedefi; AI öneri
// kartında "Bunu sor"; güven tablosunun dört değeri.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode, type ReactNode } from "react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../../App";
import { asistanApi, type AsistanMesaji, type GuvenGosterimi } from "../../api/asistan";
import { ApiError } from "../../api/http";
import { asistanMockAyarla, asistanMockBekleyenler, asistanMockIsle } from "../../api/mock/asistan";
import { OturumProvider } from "../../auth";
import { hataKaydet, SON_HATA_GECERLILIK_MS, sonHatayiSifirla } from "../../lib/sonHata";
import { oturumAc } from "../../test/yardimci";
import { BildirimProvider } from "../Bildirim";
import { AsistanPaneli, panelAyar } from "./AsistanPaneli";
import { CevapKarti, GUVEN_TONU } from "./CevapKarti";
import { acSekme, asistanKontrolSifirla } from "./kontrol";
import { ekOneriSohbetleriniSifirla } from "./OneriEkOneriler";
import { NEDEN_SORUSU } from "./OneriKarti";
import { oneriAyar, oneriDeposunuSifirla } from "./OneriVerisi";
import { sohbetAyar } from "./SohbetSekmesi";

function Gezgin() {
  const git = useNavigate();
  return (
    <button type="button" onClick={() => git("/kosular")}>
      Koşulara geç
    </button>
  );
}

function yalnizPanel(yol: string, ek?: ReactNode, strict = false) {
  const agac = (
    <MemoryRouter initialEntries={[yol]}>
      <OturumProvider>
        <BildirimProvider>
          {ek}
          <AsistanPaneli />
        </BildirimProvider>
      </OturumProvider>
    </MemoryRouter>
  );
  return render(strict ? <StrictMode>{agac}</StrictMode> : agac);
}

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

async function paneliAc(u: ReturnType<typeof userEvent.setup>) {
  await u.click(await screen.findByRole("button", { name: "Asistanı aç" }));
  return panel();
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
  vi.unstubAllGlobals();
  asistanKontrolSifirla();
  ekOneriSohbetleriniSifirla();
  Object.assign(sohbetAyar, { yoklamaMs: 3000, uzunSurerMs: 25_000 });
  Object.assign(oneriAyar, { olayGecikmeMs: 5000, yoklamaMs: 3000 });
  Object.assign(panelAyar, { pasifYoklamaMs: 30_000 });
});

describe('"Neden? Sor" sohbeti', () => {
  it("StrictMode'da dış istek bir kez işlenir: tek sohbet, tek soru, uyarı yok", async () => {
    await oturumAc("analist");
    const olustur = vi.spyOn(asistanApi, "sohbetOlustur");
    const gonder = vi.spyOn(asistanApi, "soruGonder");
    yalnizPanel("/gereksinimler/req-ft-1", null, true);
    await screen.findByRole("button", { name: "Asistanı aç" });
    act(() => acSekme("sohbet", { oneriKuralId: "gereksinim-bulgu-karari", soru: NEDEN_SORUSU }));
    await waitFor(() => expect(gonder).toHaveBeenCalledTimes(1));
    await act(async () => undefined);
    expect(olustur).toHaveBeenCalledTimes(1);
    expect(gonder).toHaveBeenCalledTimes(1);
    expect(within(panel()).queryByText(/Yanıt bekleyen bir sorunuz var/)).toBeNull();
  });

  it("takip sorusu oneri_kural_id göndermez; ekran çipi kaldırılsa da 409 almaz", async () => {
    await oturumAc("analist");
    const gonder = vi.spyOn(asistanApi, "soruGonder");
    const u = userEvent.setup();
    yalnizPanel("/gereksinimler/req-ft-1");
    const p = await paneliAc(u);
    // İlk soruda ekran çipi kaldırılmış olsa da kural sorusu ekranı taşır (kural ekrana bağlı).
    await u.click(within(p).getByRole("button", { name: "Ekran bağlamını kaldır" }));
    act(() => acSekme("sohbet", { oneriKuralId: "gereksinim-bulgu-karari", soru: NEDEN_SORUSU }));
    await waitFor(() => expect(gonder).toHaveBeenCalledTimes(1));
    expect(gonder.mock.calls[0][1]).toMatchObject({ oneri_kural_id: "gereksinim-bulgu-karari", baglam: { rota_kalibi: "/gereksinimler/:id" } });
    act(() => asistanMockIsle(asistanMockBekleyenler().at(-1)!));
    await waitFor(() => expect(within(p).queryByTestId("asistan-bekleme")).toBeNull());
    // Takip: ekran çipi yine kaldırılır (rota aynı); kural kimliği gitmez, sunucu sohbetten taşır.
    const cip = within(p).queryByRole("button", { name: "Ekran bağlamını kaldır" });
    if (cip) await u.click(cip);
    await u.type(within(p).getByLabelText("Sorunuz"), "Peki sonra?");
    await u.click(within(p).getByRole("button", { name: "Asistana sor" }));
    await waitFor(() => expect(gonder).toHaveBeenCalledTimes(2));
    const takip = gonder.mock.calls[1];
    expect(takip[0]).toBe(gonder.mock.calls[0][0]);
    expect(takip[1]).not.toHaveProperty("oneri_kural_id");
    await waitFor(() => expect(within(p).getByLabelText("Sorunuz")).toHaveValue(""));
    expect(within(p).queryByText(/artık geçerli değil/)).toBeNull();
  });

  it("mock sunucu: kural ekranı bağlamda yoksa ya da farklıysa 409 oneri_gecersiz", async () => {
    await oturumAc("analist");
    const s = await asistanApi.sohbetOlustur(null);
    await expect(asistanApi.soruGonder(s.id, { soru: "x", baglam: {}, oneri_kural_id: "gereksinim-bulgu-karari" })).rejects.toMatchObject({
      status: 409,
      kod: "oneri_gecersiz",
    });
    await expect(
      asistanApi.soruGonder(s.id, { soru: "x", baglam: { rota_kalibi: "/kosular" }, oneri_kural_id: "gereksinim-bulgu-karari" }),
    ).rejects.toBeInstanceOf(ApiError);
    await expect(
      asistanApi.soruGonder(s.id, { soru: "x", baglam: { rota_kalibi: "/gereksinimler/:id" }, oneri_kural_id: "gereksinim-bulgu-karari" }),
    ).resolves.toHaveProperty("mesaj_id");
  });
});

describe("ek öneri beklemesi sekme değişince", () => {
  it("Sohbet'e geçince bekleme görünür ve durdurulabilir; Öneriler'e dönünce bekleme, cevap gelince sonuç", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    await u.click(await screen.findByTestId("oneri-dugmesi"));
    const s = within(await screen.findByTestId("oneriler-sekmesi"));
    await u.click(s.getByRole("button", { name: "Başka ne yapabilirim?" }));
    expect(await s.findByText("Ek öneriler hazırlanıyor…")).toBeInTheDocument();
    const ekId = asistanMockBekleyenler().at(-1)!;

    await u.click(screen.getByRole("tab", { name: "Sohbet" }));
    const p = panel();
    expect(await within(p).findByTestId("ek-oneri-bekliyor")).toHaveTextContent("Ek öneriler hazırlanıyor");
    expect(within(p).getByRole("button", { name: "Asistana sor" })).toBeDisabled();

    await u.click(screen.getByRole("tab", { name: "Öneriler" }));
    const s2 = within(await screen.findByTestId("oneriler-sekmesi"));
    expect(s2.getByText("Ek öneriler hazırlanıyor…")).toBeInTheDocument();

    // Cevap Sohbet açıkken gelir; Öneriler'e dönünce sonuç görünür.
    await u.click(screen.getByRole("tab", { name: "Sohbet" }));
    act(() => asistanMockIsle(ekId));
    await waitFor(() => expect(within(panel()).queryByTestId("ek-oneri-bekliyor")).toBeNull());
    await u.click(screen.getByRole("tab", { name: "Öneriler" }));
    expect(await within(screen.getByTestId("oneriler-sekmesi")).findByText("AI önerisi · doğrulanmadı")).toBeInTheDocument();
  });

  it("Sohbet'teki Durdur bekleyen ek öneriyi iptal eder", async () => {
    await oturumAc("analist");
    const iptal = vi.spyOn(asistanApi, "iptal");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    await u.click(await screen.findByTestId("oneri-dugmesi"));
    const s = within(await screen.findByTestId("oneriler-sekmesi"));
    await u.click(s.getByRole("button", { name: "Başka ne yapabilirim?" }));
    await s.findByText("Ek öneriler hazırlanıyor…");
    await u.click(screen.getByRole("tab", { name: "Sohbet" }));
    const bekleme = await within(panel()).findByTestId("ek-oneri-bekliyor");
    await u.click(within(bekleme).getByRole("button", { name: "Durdur" }));
    await waitFor(() => expect(iptal).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(within(panel()).queryByTestId("ek-oneri-bekliyor")).toBeNull());
    await u.click(screen.getByRole("tab", { name: "Öneriler" }));
    expect(await within(screen.getByTestId("oneriler-sekmesi")).findByRole("button", { name: "Başka ne yapabilirim?" })).toBeEnabled();
  });

  it('AI öneri kartı "Bunu sor": başlık ve gerekçe ek öneri sohbetinde kip=soru ile sorulur', async () => {
    await oturumAc("analist");
    const gonder = vi.spyOn(asistanApi, "soruGonder");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    await u.click(await screen.findByTestId("oneri-dugmesi"));
    const s = within(await screen.findByTestId("oneriler-sekmesi"));
    await u.click(s.getByRole("button", { name: "Başka ne yapabilirim?" }));
    await waitFor(() => expect(gonder).toHaveBeenCalledTimes(1));
    act(() => asistanMockIsle(asistanMockBekleyenler().at(-1)!));
    const kart = (await s.findAllByText("AI önerisi · doğrulanmadı"))[0].closest("article")!;
    const baslik = within(kart).getByRole("heading").textContent!;
    expect(within(kart).getByRole("list", { name: "Hazır sorular" })).toBeInTheDocument();
    await u.click(within(kart).getByRole("button", { name: "Bunu sor" }));
    await waitFor(() => expect(gonder).toHaveBeenCalledTimes(2));
    const [sohbetId, govde] = gonder.mock.calls[1];
    expect(sohbetId).toBe(gonder.mock.calls[0][0]);
    expect(govde.kip).toBe("soru");
    expect(govde.soru).toContain(baslik);
    expect(govde).not.toHaveProperty("oneri_kural_id");
    expect(screen.getByRole("tab", { name: "Sohbet" })).toHaveAttribute("aria-selected", "true");
  });
});

describe("Geçmiş hataları", () => {
  it("liste okunamazsa 'Henüz sohbet yok' denmez; hata ve Yeniden dene", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel("/kosular");
    const p = await paneliAc(u);
    const liste = vi.spyOn(asistanApi, "sohbetler").mockRejectedValueOnce(new ApiError(500, "Sunucu hatası"));
    await u.click(within(p).getByRole("button", { name: "Geçmiş" }));
    expect(await within(p).findByRole("alert")).toHaveTextContent("Sunucu hatası");
    expect(within(p).queryByText("Henüz sohbet yok.")).toBeNull();
    await u.click(within(p).getByRole("button", { name: "Yeniden dene" }));
    expect(await within(p).findByText("Henüz sohbet yok.")).toBeInTheDocument();
    expect(liste).toHaveBeenCalledTimes(2);
    expect(within(p).queryByRole("alert")).toBeNull();
  });

  it("silme başarısızsa Geçmiş'te hata görünür, sohbet listede kalır", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel("/kosular");
    const p = await paneliAc(u);
    await u.type(within(p).getByLabelText("Sorunuz"), "Bugün ne yapmalıyım?");
    await u.click(within(p).getByRole("button", { name: "Asistana sor" }));
    await waitFor(() => expect(asistanMockBekleyenler().length).toBeGreaterThan(0));
    act(() => asistanMockIsle(asistanMockBekleyenler().at(-1)!));
    vi.spyOn(asistanApi, "sohbetSil").mockRejectedValueOnce(new ApiError(503, "Geçici hata"));
    // Bekleyen soru varken Geçmiş pasiftir: cevap gelince açılır.
    await waitFor(() => expect(within(p).getByRole("button", { name: "Geçmiş" })).toBeEnabled());
    await u.click(within(p).getByRole("button", { name: "Geçmiş" }));
    await u.click(await within(p).findByRole("button", { name: /sohbetini sil/ }));
    await u.click(within(within(p).getByRole("group", { name: "Silme onayı" })).getByRole("button", { name: "Sil" }));
    expect(await within(p).findByRole("alert")).toHaveTextContent(/Sohbet silinemedi: Geçici hata/);
    expect(within(p).getByRole("button", { name: /sohbetini sil/ })).toBeInTheDocument();
  });
});

describe("pasif asistan", () => {
  it("panel açıkken durum yeniden okunur; worker gelince sohbet açılır; Yeniden dene", async () => {
    asistanMockAyarla({ etkin: false, neden: "worker_yok" });
    panelAyar.pasifYoklamaMs = 40;
    await oturumAc("analist");
    const durum = vi.spyOn(asistanApi, "durum");
    const u = userEvent.setup();
    yalnizPanel("/kosular");
    await u.click(await screen.findByRole("button", { name: /Asistan \(kapalı/ }));
    const p = panel();
    expect(within(p).getByText("Asistan kullanılamıyor")).toBeInTheDocument();
    const once = durum.mock.calls.length;
    await u.click(within(p).getByRole("button", { name: "Yeniden dene" }));
    await waitFor(() => expect(durum.mock.calls.length).toBeGreaterThan(once));
    asistanMockAyarla({ etkin: true, neden: null });
    expect(await within(panel()).findByLabelText("Sorunuz")).toBeInTheDocument();
  });
});

describe("bağlam çipleri", () => {
  it("'Son hata' çipi 5 dk dolunca panel açıkken kalkar ve bağlama girmez", async () => {
    await oturumAc("analist");
    const gonder = vi.spyOn(asistanApi, "soruGonder");
    const hata = new ApiError(409, "İçerik değişti", { kod: "onay_hash_uyusmuyor", method: "POST", yol: "/cases/:id/review" });
    hataKaydet(hata, Date.now() - SON_HATA_GECERLILIK_MS + 150);
    const u = userEvent.setup();
    yalnizPanel("/kosular");
    const p = await paneliAc(u);
    expect(within(p).getByText(/Son hata: İçerik değişti/)).toBeInTheDocument();
    await waitFor(() => expect(within(p).queryByText(/Son hata:/)).toBeNull(), { timeout: 2000 });
    await u.type(within(p).getByLabelText("Sorunuz"), "ne oldu?");
    await u.click(within(p).getByRole("button", { name: "Asistana sor" }));
    await waitFor(() => expect(gonder).toHaveBeenCalled());
    expect(gonder.mock.calls[0][1].baglam).not.toHaveProperty("son_hata");
  });

  it("'Bu ne?' seçimi rota değişince temizlenir", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    const sayfa = (
      <>
        <Gezgin />
        <button type="button" data-testid="hedef">
          Kırarak doğrula
        </button>
      </>
    );
    yalnizPanel("/gereksinimler/req-ft-1", sayfa);
    const p = await paneliAc(u);
    const hedef = screen.getByTestId("hedef");
    Object.defineProperty(document, "elementsFromPoint", {
      configurable: true,
      value: () => [screen.getByTestId("asistan-bune-bindirme"), hedef, document.body],
    });
    await u.click(within(p).getByRole("button", { name: "? Bu ne?" }));
    fireEvent.click(screen.getByTestId("asistan-bune-bindirme"), { clientX: 5, clientY: 5 });
    expect(within(panel()).getByText(/Seçili: Kırarak doğrula/)).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Koşulara geç" }));
    await waitFor(() => expect(within(panel()).queryByText(/Seçili:/)).toBeNull());
    delete (document as { elementsFromPoint?: unknown }).elementsFromPoint;
  });
});

function mesaj(guven: GuvenGosterimi | null, ek: Partial<AsistanMesaji> = {}): AsistanMesaji {
  return {
    id: "m1",
    sohbet_id: "s1",
    sira: 2,
    rol: "assistant",
    ust_mesaj_id: null,
    icerik: "soru",
    cevap: {
      cevap_bloklari: [{ tur: "paragraf", metin: "Cevap" }],
      kaynaklar: [{ tur: "probe_verisi", ref: "kayit:1", alinti: "alıntı metni", dogrulandi: true }],
      ...(guven ? { guven_gosterimi: guven } : {}),
    },
    durum: "done",
    hata_kodu: null,
    kaynak: "model",
    amac: "assistant",
    kip: "soru",
    tetik: "kullanici",
    maliyet_usd: null,
    sure_ms: null,
    geri_bildirim: null,
    olusturma: new Date().toISOString(),
    tamamlanma: null,
    ...ek,
  } as AsistanMesaji;
}

function kartCiz(m: AsistanMesaji) {
  return render(
    <MemoryRouter>
      <BildirimProvider>
        <CevapKarti mesaj={m} />
      </BildirimProvider>
    </MemoryRouter>,
  );
}

describe("cevap kartı", () => {
  const TABLO: [GuvenGosterimi, string, RegExp][] = [
    ["Kaynakla doğrulandı", "basari", /deterministik olarak doğrulandı/],
    ["Kısmen", "uyari", /model emin değil/],
    ["Emin değil", "hata", /doğrulanmış kaynak yok/],
    ["Genel bilgi", "bilgi", /genel QA bilgisi/],
  ];

  it.each(TABLO)("güven tablosu: %s → %s tonu ve açıklama", (guven, ton, aciklama) => {
    expect(GUVEN_TONU[guven]).toBe(ton);
    kartCiz(mesaj(guven));
    const cip = screen.getByText(guven);
    expect(cip.closest(`.cip-${ton}`) ?? cip).toHaveClass(`cip-${ton}`);
    expect(cip.closest("[title]")!.getAttribute("title")).toMatch(aciklama);
  });

  it("alıntı modalı: odak Kapat'ta, Tab modal içinde döner, kapanınca açan düğmeye döner", async () => {
    const u = userEvent.setup();
    kartCiz(mesaj("Kaynakla doğrulandı"));
    const ac = screen.getByRole("button", { name: "Alıntıyı göster" });
    await u.click(ac);
    const modal = screen.getByRole("dialog");
    const kapat = within(modal).getByRole("button", { name: "Kapat" });
    expect(kapat).toHaveFocus();
    await u.tab();
    expect(modal.contains(document.activeElement)).toBe(true);
    await u.tab({ shift: true });
    expect(modal.contains(document.activeElement)).toBe(true);
    await u.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(ac).toHaveFocus();
  });
});

describe('"Asistanı aç" atlaması', () => {
  it("odağı soru alanına verir (kapat düğmesine değil)", async () => {
    await oturumAc("analist");
    uygulama("/kosular");
    const atla = await screen.findByRole("button", { name: "Asistanı aç (panele atla)" });
    fireEvent.click(atla);
    await waitFor(() => expect(screen.getByLabelText("Sorunuz")).toHaveFocus());
  });
});
