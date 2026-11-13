// 013 §7 (K12) şeffaflık + yeni hata kodları: kalıcı yapay zekâ bildirimi, cevap kartı kip rozeti
// (CANLI · model / ŞABLON / MODEL KAPALI, görünür açıklama), 422 `kisisel_veri` ve 429 `donduruldu`
// ortak metinleri, dondurma süresince gönderimin kapalı kalıp kalan dk'nın güncellenmesi, süre
// dolunca "Asistan yeniden kullanılabilir." ve sayfa yenilemede (sessionStorage) korunması (sahte
// saat), sızıntı cevabında güven rozetinin gizlenmesi, rolüne kapalı rotaya "Git" çizilmemesi.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { asistanApi, KIP_ACIKLAMALARI, kipRozeti, modelKisaAdi, SIZINTI_METNI, type AsistanMesaji } from "../../api/asistan";
import { ApiError, mockZorunlu, yapilandir } from "../../api/http";
import { asistanMockAyarla, asistanMockBekleyenler, asistanMockIsle } from "../../api/mock/asistan";
import { OturumProvider } from "../../auth";
import { oturumAc } from "../../test/yardimci";
import { BildirimProvider } from "../Bildirim";
import { AsistanPaneli, YZ_BILDIRIMI } from "./AsistanPaneli";
import { CevapKarti } from "./CevapKarti";
import { asistanKontrolSifirla } from "./kontrol";
import { DONDURMA_ANAHTARI } from "./oturumAnahtarlari";
import { kayitliDondurma, sohbetAyar } from "./SohbetSekmesi";

const KART = "5105 1051 0510 5100";
// Ortak metinler (backend ile birebir; 013 inceleme turu 1).
const KISISEL =
  "Soru ya da eklenen ekran bilgisi bir kart numarası içeriyor. Numarayı silin ya da maskeleyin (ör. 5105 **** **** 5100) ve yeniden gönderin.";
const dondu = (n: number) =>
  `Art arda engellenen istekler nedeniyle asistan geçici olarak durduruldu. Yaklaşık ${n} dk sonra yeniden sorabilirsiniz; sorunuz kutuda duruyor.`;
const hataKutusu = () => within(panel()).getByTestId("asistan-gonderim-hatasi");

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

function kart(m: AsistanMesaji, modeller?: Parameters<typeof CevapKarti>[0]["modeller"], rol?: Parameters<typeof CevapKarti>[0]["rol"]) {
  return render(
    <MemoryRouter>
      <CevapKarti mesaj={m} modeller={modeller} rol={rol} />
    </MemoryRouter>,
  );
}

/** Gerçek derleme davranışı: örnek veri zorunlu değil (mock derlemesinde CANLI gösterilmez). */
function canliDerlemeGibi() {
  const onceki = mockZorunlu();
  yapilandir({ mockZorunlu: false });
  onTestFinished(() => yapilandir({ mockZorunlu: onceki }));
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
    // Metin sabite karşı değil, ekrandaki DOM'a karşı birebir denetlenir.
    expect(not.textContent).toBe("Yapay zekâ asistanı; cevaplar hatalı olabilir, kararı ilgili ekranda siz verirsiniz.");
    expect(not).toHaveTextContent(YZ_BILDIRIMI);
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

  it("kaynak → rozet: CANLI · model (önce cevap.model, yoksa status), ŞABLON, MODEL KAPALI; ortak açıklamalar", () => {
    const d = { varsayilan_model: "claude-haiku-5-5", derin_model: "claude-sonnet-5-5" };
    expect(kipRozeti({ kaynak: "model", amac: "assistant" }, d)?.metin).toBe("CANLI · Haiku 5.5");
    expect(kipRozeti({ kaynak: "model", amac: "assistant_deep" }, d)?.metin).toBe("CANLI · Sonnet 5.5");
    // Cevabın kendi modeli status'tan önce gelir (yedek modele düşen cevap doğru adı taşır).
    const cevap = { cevap_bloklari: [], kaynaklar: [], yonlendirmeler: [], eylem_reddi: false, model: "claude-opus-5-5" };
    expect(kipRozeti({ kaynak: "model", amac: "assistant", cevap }, d)?.metin).toBe("CANLI · Opus 5.5");
    expect(kipRozeti({ kaynak: "model", amac: "assistant", cevap: { ...cevap, model: "bilinmeyen" } }, d)?.metin).toBe("CANLI · Haiku 5.5");
    // Status derin modeli bildirmiyorsa derin cevapta varsayılan model söylenmez: yalnız CANLI.
    expect(kipRozeti({ kaynak: "model", amac: "assistant_deep" }, { varsayilan_model: "claude-haiku-5-5" })?.metin).toBe("CANLI");
    expect(kipRozeti({ kaynak: "model", amac: "assistant" }, null)?.metin).toBe("CANLI");
    expect(kipRozeti({ kaynak: "model", amac: "assistant" }, { varsayilan_model: "bilinmeyen" })?.metin).toBe("CANLI");
    expect(kipRozeti({ kaynak: "model", amac: "assistant" }, d)?.aciklama).toBe("Bu cevabı yapay zekâ modeli üretti; hatalı olabilir.");
    expect(kipRozeti({ kaynak: "sozluk", amac: null })).toMatchObject({ tur: "sablon", metin: "ŞABLON", aciklama: "Yapay zekâ kullanılmadı; hazır açıklama." });
    expect(kipRozeti({ kaynak: "sablon", amac: null })).toMatchObject({ tur: "sablon", metin: "ŞABLON", aciklama: "Yapay zekâ kullanılmadı; hazır açıklama." });
    expect(kipRozeti({ kaynak: "kapali", amac: null })).toMatchObject({
      tur: "kapali",
      metin: "MODEL KAPALI",
      aciklama: "Model kapalı; yapay zekâ kullanılmadı, hazır açıklama.",
    });
    expect(kipRozeti({ kaynak: null, amac: null })).toBeNull();
  });

  it("kartta tek rozet + görünür açıklama (title değil, aria-describedby); ayrı 'Hazır cevap' etiketi yok", () => {
    canliDerlemeGibi();
    const { unmount } = kart(mesaj({ kaynak: "model" }), { varsayilan_model: "claude-haiku-5-5" });
    const r = screen.getByTestId("kip-rozeti");
    expect(r).toHaveTextContent(/^CANLI · Haiku 5\.5$/);
    expect(r).toHaveClass("rozet", "rozet-kip", "rozet-kip-canli");
    expect(r).not.toHaveAttribute("title");
    expect(r).toHaveAccessibleDescription(KIP_ACIKLAMALARI.canli);
    expect(screen.getByTestId("kip-aciklamasi")).toBeVisible();
    expect(screen.getByTestId("kip-aciklamasi")).not.toHaveClass("gorunmez");
    unmount();

    const k2 = kart(mesaj({ kaynak: "sablon", amac: null }));
    const s = screen.getByTestId("kip-rozeti");
    expect(s).toHaveTextContent(/^ŞABLON$/);
    expect(s).toHaveClass("rozet-kip-sablon");
    expect(s).toHaveAccessibleDescription("Yapay zekâ kullanılmadı; hazır açıklama.");
    expect(screen.queryByText(/Hazır cevap/)).toBeNull();
    expect(screen.getAllByTestId("kip-rozeti")).toHaveLength(1);
    k2.unmount();

    kart(mesaj({ kaynak: "kapali", amac: null }));
    expect(screen.getByTestId("kip-rozeti")).toHaveTextContent(/^MODEL KAPALI$/);
    expect(screen.getByTestId("kip-rozeti")).toHaveClass("rozet-kip-kapali");
    expect(screen.getByTestId("kip-aciklamasi")).toHaveTextContent("Model kapalı; yapay zekâ kullanılmadı, hazır açıklama.");
  });

  it("cevap.model rozette status'tan önce gelir", () => {
    canliDerlemeGibi();
    const m = mesaj({ kaynak: "model" });
    kart({ ...m, cevap: { ...m.cevap!, model: "claude-sonnet-5-5" } }, { varsayilan_model: "claude-haiku-5-5" });
    expect(screen.getByTestId("kip-rozeti")).toHaveTextContent(/^CANLI · Sonnet 5\.5$/);
  });

  it("kip rozeti büyük harf dönüşümü kapalı (Türkçe yerelde 'HAİKU' olmasın), imleç 'help' değil", () => {
    // jsdom CSS dosyalarını uygulamaz: kural dosyadan denetlenir.
    const css = readFileSync("src/components/asistan/asistan.css", "utf8");
    expect(css).toMatch(/\.rozet\.rozet-kip\s*\{[^}]*text-transform:\s*none/);
    expect(css).not.toMatch(/\.rozet-kip[^{]*\{[^}]*cursor:\s*help/);
  });

  it("sızıntı cevabında güven rozeti gösterilmez; metin ortak metin", () => {
    canliDerlemeGibi();
    const m = mesaj({
      kaynak: "model",
      cevap: {
        cevap_bloklari: [{ tur: "paragraf", metin: SIZINTI_METNI }],
        kaynaklar: [],
        yonlendirmeler: [],
        eylem_reddi: false,
        guven_gosterimi: "Emin değil",
        sizinti: true,
      },
    });
    const { unmount } = kart(m, { varsayilan_model: "claude-haiku-5-5" });
    expect(screen.getByText(SIZINTI_METNI)).toBeInTheDocument();
    expect(screen.queryByText("Emin değil")).toBeNull();
    // Kip rozeti de yok (BE2-3): gösterilen metin modelin cevabı değil; status'ta model olsa da.
    expect(screen.queryByTestId("kip-rozeti")).toBeNull();
    expect(kipRozeti({ kaynak: "model", amac: "assistant", cevap: { ...m.cevap!, model: "claude-haiku-5-5" } })).toBeNull();
    unmount();
    // Karşı örnek: sızıntı olmayan cevapta aynı güven rozeti ve CANLI rozeti çizilir.
    kart({ ...m, cevap: { ...m.cevap!, sizinti: false } }, { varsayilan_model: "claude-haiku-5-5" });
    expect(screen.getByText("Emin değil")).toBeInTheDocument();
    expect(screen.getByTestId("kip-rozeti")).toHaveTextContent(/^CANLI · Haiku 5\.5$/);
  });

  it("rolüne kapalı rotaya 'Git' düğmesi çizilmez; açık rotalar (Kontrol Kulesi) herkese", () => {
    const m = mesaj({
      kaynak: "sablon",
      amac: null,
      cevap: {
        cevap_bloklari: [{ tur: "paragraf", metin: "Cevap" }],
        kaynaklar: [],
        yonlendirmeler: [
          { rota: "/demo", etiket: "Demo kontrolleri" },
          { rota: "/claude-code", etiket: "Claude Code kanalı" },
          { rota: "/kontrol-kulesi", etiket: "Kontrol Kulesi" },
        ],
        eylem_reddi: false,
      },
    });
    // 012: /demo `demo.manage` (Sistem Yöneticisi, Automation Engineer); /claude-code `claude_code.read`.
    const { unmount } = kart(m, null, "tester");
    expect(screen.getByRole("link", { name: "Git: Kontrol Kulesi" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Git: Demo kontrolleri" })).toBeNull();
    expect(screen.getByRole("link", { name: "Git: Claude Code kanalı" })).toBeInTheDocument();
    unmount();
    const k2 = kart(m, null, "admin");
    expect(screen.getByRole("link", { name: "Git: Demo kontrolleri" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Git: Claude Code kanalı" })).toBeInTheDocument();
    k2.unmount();
    const k3 = kart(m, null, "viewer");
    expect(screen.getByRole("link", { name: "Git: Kontrol Kulesi" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Git: (Demo|Claude)/ })).toBeNull();
    k3.unmount();
    kart(m, null, null);
    expect(screen.queryByRole("link", { name: /Git: (Demo|Claude)/ })).toBeNull();
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
  it("422 kisisel_veri: ortak metin gösterilir, taslak girdide kalır", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    const soru = `Müşterinin kartı ${KART} neden reddedildi?`;
    await yaz(u, soru);
    expect((await within(p).findByRole("alert")).textContent).toBe(KISISEL);
    expect(within(p).getByLabelText("Sorunuz")).toHaveValue(soru);
    expect(asistanMockBekleyenler()).toHaveLength(0);
    // Gönderim açık kalır (dondurma değil).
    expect(within(p).getByRole("button", { name: "Asistana sor" })).toBeEnabled();
  });

  // Sahte saat panel açılışından önce kurulur (zamanlayıcılar sahte saatte kurulsun). Gerçek geçen
  // süre de akar (`shouldAdvanceTime`): kalan_s 120 ve 60 sn'lik sınırlardan uzak noktalar
  // seçildiği için birkaç yüz ms'lik gerçek gecikme sonucu değiştirmez.
  function sahteSaat() {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    return (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));
  }

  it("429 donduruldu: ortak metin, gönderim kalan_s boyunca kapalı, kalan dk 30 sn'de bir güncellenir, bitince 'yeniden kullanılabilir'", async () => {
    const ilerlet = sahteSaat();
    await oturumAc("analist");
    const u = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const gonder = vi
      .spyOn(asistanApi, "soruGonder")
      .mockRejectedValueOnce(new ApiError(429, "Dondu.", { kod: "donduruldu", ek: { kalan_s: 120 } }));
    yalnizPanel();
    const p = await paneliAc(u);
    await yaz(u, "Bu ekran ne işe yarar?");
    await waitFor(() => expect(hataKutusu()).toHaveTextContent(dondu(2)));
    // Değişen metin canlı bölge değil (her dakika okunmasın); başlangıç bir kez duyurulur.
    expect(hataKutusu()).not.toHaveAttribute("role");
    await ilerlet(200);
    expect(within(p).getByTestId("asistan-duyuru")).toHaveTextContent(dondu(2));
    expect(Number(sessionStorage.getItem(DONDURMA_ANAHTARI))).toBeGreaterThan(Date.now());
    const alan = within(p).getByLabelText("Sorunuz");
    expect(alan).toHaveValue("Bu ekran ne işe yarar?");
    const dugme = within(p).getByRole("button", { name: "Asistana sor" });
    expect(dugme).toBeDisabled();
    expect(dugme.getAttribute("aria-describedby")).toContain("asistan-gonderim-hatasi");
    // Enter da göndermez.
    fireEvent.keyDown(alan, { key: "Enter" });
    expect(gonder).toHaveBeenCalledTimes(1);

    // 61 sn sonra kalan 59 sn → "1 dk" (30 sn'lik saat yeniden çizer).
    await ilerlet(61_000);
    expect(hataKutusu()).toHaveTextContent(dondu(1));
    expect(within(p).getByRole("button", { name: "Asistana sor" })).toBeDisabled();
    expect(within(p).queryByTestId("dondurma-bitti")).toBeNull();
    await ilerlet(60_000);
    expect(within(p).getByRole("button", { name: "Asistana sor" })).toBeEnabled();
    expect(within(p).queryByTestId("asistan-gonderim-hatasi")).toBeNull();
    const bitti = within(p).getByTestId("dondurma-bitti");
    expect(bitti).toHaveAttribute("role", "status");
    expect(bitti.textContent).toBe("Asistan yeniden kullanılabilir.");
    expect(sessionStorage.getItem(DONDURMA_ANAHTARI)).toBeNull();
    expect(within(p).getByLabelText("Sorunuz")).toHaveValue("Bu ekran ne işe yarar?");
  });

  it("dondurma sekme geçişinde korunur; kalan_s yoksa 10 dk varsayılır", async () => {
    const ilerlet = sahteSaat();
    await oturumAc("analist");
    const u = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    vi.spyOn(asistanApi, "soruGonder").mockRejectedValueOnce(new ApiError(429, "Dondu.", { kod: "donduruldu" }));
    yalnizPanel();
    const p = await paneliAc(u);
    await yaz(u, "Bu ekran ne işe yarar?");
    await waitFor(() => expect(within(p).getByTestId("asistan-gonderim-hatasi")).toHaveTextContent(dondu(10)));
    await u.click(within(p).getByRole("tab", { name: "Öneriler" }));
    await u.click(within(panel()).getByRole("tab", { name: "Sohbet" }));
    expect(hataKutusu()).toHaveTextContent(dondu(10));
    expect(within(panel()).getByRole("button", { name: "Asistana sor" })).toBeDisabled();
    await ilerlet(600_000 + 100);
    expect(within(panel()).getByRole("button", { name: "Asistana sor" })).toBeEnabled();
    expect(within(panel()).getByTestId("dondurma-bitti")).toHaveTextContent("Asistan yeniden kullanılabilir.");
  });

  it("sayfa yenilense de dondurma sürer (sessionStorage); geçmiş ya da bozuk kayıt yok sayılır", async () => {
    sessionStorage.setItem(DONDURMA_ANAHTARI, String(Date.now() + 180_000));
    expect(kayitliDondurma()).not.toBeNull();
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    await waitFor(() => expect(within(p).getByTestId("asistan-gonderim-hatasi")).toHaveTextContent(dondu(3)));
    await u.type(within(p).getByLabelText("Sorunuz"), "Bu ekran ne?");
    expect(within(p).getByRole("button", { name: "Asistana sor" })).toBeDisabled();

    sessionStorage.setItem(DONDURMA_ANAHTARI, String(Date.now() - 1000));
    expect(kayitliDondurma()).toBeNull();
    sessionStorage.setItem(DONDURMA_ANAHTARI, "bozuk");
    expect(kayitliDondurma()).toBeNull();
    sessionStorage.removeItem(DONDURMA_ANAHTARI);
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
    await waitFor(() => expect(hataKutusu()).toHaveTextContent(dondu(10)));
    expect(within(p).getByRole("button", { name: "Asistana sor" })).toBeDisabled();
    expect(within(p).getByLabelText("Sorunuz")).toHaveValue("Bu ekran ne işe yarar?");
  });
});
