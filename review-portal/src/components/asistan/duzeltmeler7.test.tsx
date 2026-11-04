// Asistan paneli inceleme düzeltmeleri (tur 7): ek öneri cevabı panel kapalıyken gelirse Sohbet
// yeniden açılınca kilitli kalmaz; ardışık cevapların her biri ekran okuyucuya duyurulur; 402
// `butce_asildi` kapsamı sunucu metniyle söylenir (soru başı bütçe "yarın" demez); mock sözlük
// hata durumuna göre açıklar; kaynaksız kayıt dışı HataKutusu son hataya yazılmaz; hazır kapı
// geçici durum hatasında pasife düşmez.
import { act, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../../App";
import { asistanApi, gonderimHataMetni, mesajHataMetni } from "../../api/asistan";
import { ApiError } from "../../api/http";
import { asistanMockAyarla, asistanMockBekleyenler, asistanMockIsle } from "../../api/mock/asistan";
import { OturumProvider } from "../../auth";
import { sonHata, sonHatayiSifirla } from "../../lib/sonHata";
import { oturumAc } from "../../test/yardimci";
import { BildirimProvider } from "../Bildirim";
import { HataKutusu } from "../ui";
import { asistanKontrolSifirla } from "./kontrol";
import { ekOneriSohbetleriniSifirla } from "./OneriEkOneriler";
import { oneriAyar, oneriDeposunuSifirla } from "./OneriVerisi";
import { sohbetAyar } from "./SohbetSekmesi";
import { useAsistanKapisi } from "./yetenek";

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
  await u.clear(alan);
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

describe("ek öneri cevabı panel kapalıyken gelir", () => {
  it("panel Sohbet'te yeniden açılınca bekleyen okunur, kilit kalkar", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    await u.click(await screen.findByTestId("oneri-dugmesi"));
    const s = within(await screen.findByTestId("oneriler-sekmesi"));
    await u.click(s.getByRole("button", { name: "Başka ne yapabilirim?" }));
    await waitFor(() => expect(asistanMockBekleyenler().length).toBe(1));
    const id = asistanMockBekleyenler()[0];

    // Sohbet sekmesinde bekleme görünür; panel kapanır, cevap o sırada gelir (dinleyen yok).
    await u.click(within(panel()).getByRole("tab", { name: "Sohbet" }));
    expect(await within(panel()).findByTestId("ek-oneri-bekliyor")).toBeInTheDocument();
    await u.click(within(panel()).getByRole("button", { name: "Asistanı kapat" }));
    expect(screen.queryByTestId("asistan-paneli")).toBeNull();
    act(() => asistanMockIsle(id));
    expect((await asistanApi.mesaj(id)).durum).toBe("done");

    await u.click(screen.getByRole("button", { name: "Asistanı aç" }));
    const p = await screen.findByTestId("asistan-paneli");
    await waitFor(() => expect(within(p).queryByTestId("ek-oneri-bekliyor")).toBeNull());
    await u.type(within(p).getByLabelText("Sorunuz"), "Bugün ne yapmalıyım?");
    expect(within(p).getByRole("button", { name: "Asistana sor" })).toBeEnabled();
  });
});

describe("cevap duyurusu", () => {
  it("ardışık iki cevabın ikisi de canlı bölgede yeniden yazılır", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    await u.click(await screen.findByRole("button", { name: "Asistanı aç" }));
    const bolge = within(panel()).getByTestId("asistan-duyuru");
    const yazilanlar: string[] = [];
    const g = new MutationObserver(() => {
      if (bolge.textContent) yazilanlar.push(bolge.textContent);
    });
    g.observe(bolge, { childList: true, characterData: true, subtree: true });

    const ilk = await sor(u, "Bugün ne yapmalıyım?");
    act(() => asistanMockIsle(ilk));
    await waitFor(() => expect(yazilanlar).toEqual(["Asistanın cevabı geldi."]));

    const ikinci = await sor(u, "TPD-3 neden bekliyor?");
    act(() => asistanMockIsle(ikinci));
    await waitFor(() => expect(yazilanlar).toEqual(["Asistanın cevabı geldi.", "Asistanın cevabı geldi."]));
    g.disconnect();
  });
});

describe("bütçe metinleri", () => {
  it("402 butce_asildi: sunucunun kapsam metni gösterilir (soru başı 'yarın' demez)", () => {
    const soru = new ApiError(402, "Bu soru için ayrılan bütçe doldu.", { kod: "butce_asildi" });
    expect(gonderimHataMetni(soru)).toBe("Bu soru için ayrılan bütçe doldu.");
    const gunluk = new ApiError(402, "Günlük AI bütçesi doldu; yarın yeniden deneyin.", { kod: "butce_asildi" });
    expect(gonderimHataMetni(gunluk)).toMatch(/yarın/);
    expect(gonderimHataMetni(new ApiError(402, "", { kod: "butce_asildi" }))).toMatch(/yeni soru/);
  });

  it("mesaj hata kodu: kapsamsız butce_asildi kesin 'yarın' demez; soru_butcesi ayrı metin", () => {
    expect(mesajHataMetni("butce_asildi")).toMatch(/yeni soru sorabilirsiniz/);
    expect(mesajHataMetni("soru_butcesi")).toBe("Bu soru için ayrılan bütçe doldu; soruyu daraltıp yeni soru sorabilirsiniz.");
  });
});

describe("mock sözlük cevabı hata durumuna göre", () => {
  async function sozlukCevabi(sonHataBaglami: Record<string, unknown>) {
    await oturumAc("analist");
    const s = await asistanApi.sohbetOlustur(null);
    const { mesaj_id } = await asistanApi.soruGonder(s.id, { soru: "Bu hata ne demek?", baglam: { son_hata: sonHataBaglami } });
    asistanMockIsle(mesaj_id);
    const m = await asistanApi.mesaj(mesaj_id);
    expect(m.kaynak).toBe("sozluk");
    return m.cevap!;
  }

  it("404 'içerik değişti' denmez; 409 açıklaması korunur; bilinmeyende doğrulandı çipi yok", async () => {
    const c404 = await sozlukCevabi({ status: 404, detail: "Gereksinim bulunamadı: req-yok" });
    const metin404 = JSON.stringify(c404.cevap_bloklari);
    expect(metin404).toMatch(/bulunamadığını/);
    expect(metin404).not.toMatch(/değiştiğini/);

    const c409 = await sozlukCevabi({ status: 409, detail: "İçerik değişti" });
    expect(JSON.stringify(c409.cevap_bloklari)).toMatch(/değiştiğini/);
    expect(c409.guven_gosterimi).toBe("Kaynakla doğrulandı");

    const cBilinmeyen = await sozlukCevabi({ status: null, detail: "Bir şey oldu" });
    expect(cBilinmeyen.guven_gosterimi).toBe("Kısmen");
    expect(cBilinmeyen.kaynaklar).toEqual([]);
  });
});

describe("kayıt dışı HataKutusu", () => {
  it("kayitDisi verilen kutu son hata deposuna yazılmaz", () => {
    render(<HataKutusu hata="Script üretimi başarısız" kayitDisi />);
    expect(screen.getByRole("alert")).toHaveTextContent("Script üretimi başarısız");
    expect(sonHata()).toBeNull();
  });
});

describe("asistan kapısı geçici hata", () => {
  it("hazırken 5xx / ağ hatası kapıyı pasife düşürmez; 503 asistan_kapali düşürür", async () => {
    await oturumAc("analist");
    const { result } = renderHook(() => useAsistanKapisi());
    await waitFor(() => expect(result.current.kapi.tur).toBe("hazir"));

    const durum = vi.spyOn(asistanApi, "durum");
    durum.mockRejectedValueOnce(new ApiError(500, "Sunucu hatası"));
    await act(() => result.current.yenile());
    expect(result.current.kapi.tur).toBe("hazir");
    durum.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await act(() => result.current.yenile());
    expect(result.current.kapi.tur).toBe("hazir");

    durum.mockRejectedValueOnce(new ApiError(503, "Asistan kapalı", { kod: "asistan_kapali" }));
    await act(() => result.current.yenile());
    expect(result.current.kapi.tur).toBe("pasif");
  });

  it("ilk okumada hata pasif gösterir (önceki hazır durum yok)", async () => {
    await oturumAc("analist");
    vi.spyOn(asistanApi, "durum").mockRejectedValue(new ApiError(500, "Sunucu hatası"));
    const { result } = renderHook(() => useAsistanKapisi());
    await waitFor(() => expect(result.current.kapi.tur).toBe("pasif"));
  });
});
