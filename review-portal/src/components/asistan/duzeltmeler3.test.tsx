// Asistan paneli inceleme düzeltmeleri (tur 3): çıkışta / kullanıcı değişince istemci depolarının
// temizlenmesi (§16 madde 1); ek öneri 404'te bekleme kaydının düşmesi; süresi dolmuş "Asistana sor"
// kaydının başka hataya düşmemesi; bekleme sürerken gelen "Neden? Sor"un öneri kuralını koruması;
// 503 `asistan_kapali` sonrası durumun yeniden okunması; kapalı kipte "? Bu ne?"nin gizlenmesi;
// Jira adreslerinin http(s) süzgeci; tek `goreliZaman`; sonuç duyurusu (liste canlı bölge değil);
// "Bu ne?" klavye yolu ve odak dönüşü; dar ekran modalında arka plan `inert`; istemci saatli sayaç.
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { asistanApi, type AsistanMesaji } from "../../api/asistan";
import { ApiError } from "../../api/http";
import { asistanMockAyarla, asistanMockBekleyenler, asistanMockIsle } from "../../api/mock/asistan";
import { OturumProvider, useOturum } from "../../auth";
import { goreliZaman, guvenliDisAdres } from "../../lib/format";
import { hataKaydet, sonHata, sonHatayiSifirla } from "../../lib/sonHata";
import { oturumAc } from "../../test/yardimci";
import { BildirimProvider } from "../Bildirim";
import { AsistanaSorDugmesi } from "../ui";
import { AsistanPaneli } from "./AsistanPaneli";
import { CevapKarti } from "./CevapKarti";
import { acSekme, asistanKontrolSifirla, useAsistanKontrol } from "./kontrol";
import { ekOneriKontrol, ekOneriSohbetleriniSifirla, OneriEkOneriler, useBekleyenEkOneri } from "./OneriEkOneriler";
import { NEDEN_SORUSU, aiOnerisiKarta } from "./OneriKarti";
import { oneriAyar, oneriDeposunuSifirla } from "./OneriVerisi";
import { sohbetAyar } from "./SohbetSekmesi";

const DK = 60_000;

function sarmala(yol: string, icerik: ReactNode) {
  return render(
    <MemoryRouter initialEntries={[yol]}>
      <OturumProvider>
        <BildirimProvider>{icerik}</BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

const panel = () => screen.getByTestId("asistan-paneli");

async function paneliAc(u: ReturnType<typeof userEvent.setup>) {
  await u.click(await screen.findByRole("button", { name: "Asistanı aç" }));
  return panel();
}

async function sor(u: ReturnType<typeof userEvent.setup>, metin: string) {
  const alan = within(panel()).getByLabelText("Sorunuz");
  await u.clear(alan);
  await u.type(alan, metin);
  await u.click(within(panel()).getByRole("button", { name: "Asistana sor" }));
  await waitFor(() => expect(asistanMockBekleyenler().length).toBeGreaterThan(0));
  return asistanMockBekleyenler().at(-1)!;
}

function hata(detail: string, yol = "/cases/c-1/review"): ApiError {
  return new ApiError(409, detail, { method: "POST", yol, kod: "durum_degisti" });
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
});

const GEREKSINIM_EKRANI = {
  rota_kalibi: "/gereksinimler/:id",
  ekran: "Gereksinim detayı",
  varlik: { tur: "requirement" as const, id: "req-ft-1" },
};

/** Oturum düğmeleri + depoların anlık görüntüsü. */
function OturumSondasi() {
  const { kullanici, girisYap, cikisYap } = useOturum();
  const ek = useBekleyenEkOneri();
  const kontrol = useAsistanKontrol();
  return (
    <div>
      <span data-testid="kim">{kullanici?.kullanici_adi ?? "yok"}</span>
      <span data-testid="ek-bekleyen">{ek ?? "yok"}</span>
      <span data-testid="panel-acik">{String(kontrol.acik)}</span>
      <button type="button" onClick={() => void cikisYap()}>
        Çıkış
      </button>
      <button type="button" onClick={() => void girisYap("testci", "Demo123!")}>
        B girişi
      </button>
    </div>
  );
}

describe("kişi izolasyonu: çıkış / kullanıcı değişimi", () => {
  it("çıkışta son hata, bekleyen ek öneri, panel durumu ve kayıtlı sohbet silinir; B temiz başlar", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    sarmala(
      "/gereksinimler/req-ft-1",
      <>
        <OturumSondasi />
        <OneriEkOneriler ekran={GEREKSINIM_EKRANI} />
      </>,
    );
    await waitFor(() => expect(screen.getByTestId("kim")).toHaveTextContent("analist"));

    // A: son hata, bekleyen "Başka ne yapabilirim?", açık panel ve kayıtlı sohbet.
    hataKaydet(hata("A'nın hatası"));
    await u.click(screen.getByRole("button", { name: "Başka ne yapabilirim?" }));
    await waitFor(() => expect(screen.getByTestId("ek-bekleyen")).not.toHaveTextContent("yok"));
    act(() => acSekme("sohbet"));
    sessionStorage.setItem("tp-asistan-sohbet", "sohbet-A");
    expect(sonHata()).not.toBeNull();
    expect(screen.getByTestId("panel-acik")).toHaveTextContent("true");

    await u.click(screen.getByRole("button", { name: "Çıkış" }));
    await waitFor(() => expect(screen.getByTestId("kim")).toHaveTextContent("yok"));
    expect(sonHata()).toBeNull();
    expect(screen.getByTestId("ek-bekleyen")).toHaveTextContent("yok");
    expect(screen.getByTestId("panel-acik")).toHaveTextContent("false");
    expect(sessionStorage.getItem("tp-asistan-sohbet")).toBeNull();
    // A'nın ek öneri sonucu/beklemesi B'nin ekranında yok: düğme yeniden başlatılabilir.
    expect(screen.getByRole("button", { name: "Başka ne yapabilirim?" })).toBeEnabled();

    // B aynı sekmede girer: A'dan bir şey kalmamıştır, B'nin Sohbet'i kilitli değildir.
    await u.click(screen.getByRole("button", { name: "B girişi" }));
    await waitFor(() => expect(screen.getByTestId("kim")).toHaveTextContent("testci"));
    expect(sonHata()).toBeNull();
    expect(screen.getByTestId("ek-bekleyen")).toHaveTextContent("yok");
  });

  it("sayfa açılışındaki oturum okuması (me) kayıtlı sohbeti silmez: yenilemeden sonra yeniden bağlanılır", async () => {
    await oturumAc("analist");
    sessionStorage.setItem("tp-asistan-sohbet", "sohbet-A");
    sarmala("/kosular", <OturumSondasi />);
    await waitFor(() => expect(screen.getByTestId("kim")).toHaveTextContent("analist"));
    expect(sessionStorage.getItem("tp-asistan-sohbet")).toBe("sohbet-A");
  });

  it("ek öneri mesajı 404 olunca bekleme kaydı düşer (Sohbet kilitli kalmaz)", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    sarmala("/gereksinimler/req-ft-1", <OturumSondasi />);
    const { unmount } = render(
      <MemoryRouter>
        <OneriEkOneriler ekran={GEREKSINIM_EKRANI} />
      </MemoryRouter>,
    );
    await u.click(screen.getByRole("button", { name: "Başka ne yapabilirim?" }));
    await waitFor(() => expect(screen.getByTestId("ek-bekleyen")).not.toHaveTextContent("yok"));
    const id = screen.getByTestId("ek-bekleyen").textContent!;
    unmount();
    vi.spyOn(asistanApi, "mesaj").mockRejectedValue(new ApiError(404, "Bulunamadı"));
    await act(async () => ekOneriKontrol(id));
    expect(screen.getByTestId("ek-bekleyen")).toHaveTextContent("yok");
  });
});

describe('"Asistana sor": süresi dolan kayıt', () => {
  it("seçilen kaydın süresi dolduysa başka bir hataya düşülmez, girdi doldurulmaz, not gösterilir", async () => {
    await oturumAc("analist");
    const gonder = vi.spyOn(asistanApi, "soruGonder");
    const u = userEvent.setup();
    const a = hata("A hatası");
    hataKaydet(a, Date.now() - 6 * DK);
    hataKaydet(hata("B hatası", "/cases/c-2/review"), Date.now() - 4 * DK);
    expect(sonHata()?.detail).toBe("B hatası");
    sarmala("/kosular", <AsistanPaneli />);
    await screen.findByRole("button", { name: "Asistanı aç" });
    act(() => acSekme("sohbet", { kayitId: a.kayitId }));
    const p = panel();
    expect(await within(p).findByText(/Bu hatanın kaydı artık yok/)).toBeInTheDocument();
    expect(within(p).queryByText(/Son hata:/)).toBeNull();
    expect(within(p).getByLabelText("Sorunuz")).toHaveValue("");
    await u.type(within(p).getByLabelText("Sorunuz"), "Bu ne demek?");
    await u.click(within(p).getByRole("button", { name: "Asistana sor" }));
    await waitFor(() => expect(gonder).toHaveBeenCalled());
    expect(gonder.mock.calls[0][1].baglam).not.toHaveProperty("son_hata");
  });

  it("düğme 5 dk'dan uzun ekranda kaldıysa tıklama kaydı tazeler: o hatanın bağlamıyla açılır", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    const a = hata("Eski ama ekrandaki hata");
    hataKaydet(a, Date.now() - 6 * DK);
    hataKaydet(hata("Başka hata", "/cases/c-2/review"), Date.now() - 4 * DK);
    sarmala("/kosular", <AsistanPaneli />);
    await screen.findByRole("button", { name: "Asistanı aç" });
    render(<AsistanaSorDugmesi hata="Eski ama ekrandaki hata" kaynak={a} />);
    await u.click(await screen.findByRole("button", { name: "Asistana sor" }));
    const p = panel();
    expect(await within(p).findByText(/Son hata: Eski ama ekrandaki hata/)).toBeInTheDocument();
    expect(within(p).getByLabelText("Sorunuz")).toHaveValue("Bu hata ne demek, ne yapmalıyım?");
  });
});

describe("bekleme sürerken gelen dış soru", () => {
  it('"Neden? Sor" bekletilir; girdiden gönderilince öneri kuralıyla yeni sohbette gider', async () => {
    await oturumAc("analist");
    const olustur = vi.spyOn(asistanApi, "sohbetOlustur");
    const gonder = vi.spyOn(asistanApi, "soruGonder");
    const u = userEvent.setup();
    sarmala("/gereksinimler/req-ft-1", <AsistanPaneli />);
    const p = await paneliAc(u);
    const ilk = await sor(u, "Bugün ne yapmalıyım?");
    act(() => acSekme("sohbet", { oneriKuralId: "gereksinim-bulgu-karari", soru: NEDEN_SORUSU }));
    expect(await within(p).findByText(/Yanıt bekleyen bir sorunuz var/)).toBeInTheDocument();
    expect(within(p).getByLabelText("Sorunuz")).toHaveValue(NEDEN_SORUSU);
    act(() => asistanMockIsle(ilk));
    await waitFor(() => expect(within(p).getByRole("button", { name: "Asistana sor" })).toBeEnabled(), { timeout: 3000 });
    await u.click(within(p).getByRole("button", { name: "Asistana sor" }));
    await waitFor(() => expect(gonder).toHaveBeenCalledTimes(2));
    expect(gonder.mock.calls[1][1]).toMatchObject({ soru: NEDEN_SORUSU, oneri_kural_id: "gereksinim-bulgu-karari" });
    expect(olustur).toHaveBeenCalledTimes(2);
    expect(gonder.mock.calls[1][0]).not.toBe(gonder.mock.calls[0][0]);
  });

  it("bekletilen soru elle değiştirilirse öneri kuralı gitmez", async () => {
    await oturumAc("analist");
    const gonder = vi.spyOn(asistanApi, "soruGonder");
    const u = userEvent.setup();
    sarmala("/gereksinimler/req-ft-1", <AsistanPaneli />);
    const p = await paneliAc(u);
    const ilk = await sor(u, "Bugün ne yapmalıyım?");
    act(() => acSekme("sohbet", { oneriKuralId: "gereksinim-bulgu-karari", soru: NEDEN_SORUSU }));
    await within(p).findByText(/Yanıt bekleyen bir sorunuz var/);
    act(() => asistanMockIsle(ilk));
    await waitFor(() => expect(within(p).getByRole("button", { name: "Asistana sor" })).toBeEnabled(), { timeout: 3000 });
    await u.type(within(p).getByLabelText("Sorunuz"), " Kısaca.");
    await u.click(within(p).getByRole("button", { name: "Asistana sor" }));
    await waitFor(() => expect(gonder).toHaveBeenCalledTimes(2));
    expect(gonder.mock.calls[1][1]).not.toHaveProperty("oneri_kural_id");
    expect(gonder.mock.calls[1][0]).toBe(gonder.mock.calls[0][0]);
  });

  it("gönderim sürerken gelen dış soru sessizce düşmez: girdiye yazılır, not gösterilir", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    vi.spyOn(asistanApi, "soruGonder").mockImplementation(() => new Promise(() => undefined));
    sarmala("/gereksinimler/req-ft-1", <AsistanPaneli />);
    const p = await paneliAc(u);
    await u.type(within(p).getByLabelText("Sorunuz"), "bir");
    await u.click(within(p).getByRole("button", { name: "Asistana sor" }));
    act(() => acSekme("sohbet", { soru: "Bunu sor" }));
    expect(await within(p).findByText(/Önceki soru gönderiliyor/)).toBeInTheDocument();
    expect(within(p).getByLabelText("Sorunuz")).toHaveValue("Bunu sor");
  });
});

describe("kapalı / kapanan asistan", () => {
  it("gönderim 503 asistan_kapali alınca durum yeniden okunur: panel pasif uyarıya geçer", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    sarmala("/kosular", <AsistanPaneli />);
    const p = await paneliAc(u);
    asistanMockAyarla({ etkin: false, neden: "worker_yok" });
    await u.type(within(p).getByLabelText("Sorunuz"), "Merhaba");
    await u.click(within(p).getByRole("button", { name: "Asistana sor" }));
    expect(await within(panel()).findByText("Asistan kullanılamıyor")).toBeInTheDocument();
    asistanMockAyarla({ etkin: true, neden: null });
  });

  it('model kapalıyken "? Bu ne?" gösterilmez (seçili öğe sorusu modelsiz cevaplanamaz)', async () => {
    asistanMockAyarla({ mod: "off" });
    await oturumAc("analist");
    const u = userEvent.setup();
    sarmala("/kosular", <AsistanPaneli />);
    const p = await paneliAc(u);
    expect(within(p).getByLabelText("Sorunuz")).toBeInTheDocument();
    expect(within(p).queryByRole("button", { name: "? Bu ne?" })).toBeNull();
    asistanMockAyarla({ mod: "live" });
  });
});

function mesaj(ek: Partial<AsistanMesaji> = {}): AsistanMesaji {
  return {
    id: "m1",
    sohbet_id: "s1",
    sira: 2,
    rol: "assistant",
    ust_mesaj_id: null,
    icerik: "soru",
    cevap: {
      cevap_bloklari: [{ tur: "paragraf", metin: "Cevap" }],
      kaynaklar: [
        { tur: "jira", ref: "TPD-1", alinti: "yorum", dogrulandi: true, jira: { anahtar: "TPD-1", url: "javascript:alert(1)", tarih: "gecersiz" } },
      ],
      jira_baglantilari: [
        { anahtar: "TPD-2", url: "javascript:alert(2)" },
        { anahtar: "TPD-3", url: "https://jira.example.test/browse/TPD-3" },
      ],
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

describe("dış adres süzgeci ve göreli zaman", () => {
  it("cevap kartında javascript: Jira adresi bağlantı olmaz; https olan olur", () => {
    render(
      <MemoryRouter>
        <BildirimProvider>
          <CevapKarti mesaj={mesaj()} />
        </BildirimProvider>
      </MemoryRouter>,
    );
    const baglantilar = screen.queryAllByRole("link");
    expect(baglantilar.map((a) => a.getAttribute("href"))).toEqual(["https://jira.example.test/browse/TPD-3"]);
    // Geçersiz tarih "NaN" üretmez.
    expect(screen.queryByText(/NaN/)).toBeNull();
  });

  it("AI öneri kartı ve ortak yardımcı aynı süzgeci kullanır", () => {
    expect(guvenliDisAdres("javascript:alert(1)")).toBeNull();
    expect(guvenliDisAdres(" data:text/html,x")).toBeNull();
    expect(guvenliDisAdres("HTTPS://jira.example.test/x")).toBe("HTTPS://jira.example.test/x");
    const k = aiOnerisiKarta({ baslik: "b", neden: "n", eylem: { tur: "jira_taslak", baglanti: "javascript:x" } } as never);
    expect(k.eylem.baglanti ?? null).toBeNull();
  });

  it("goreliZaman tek yerde: geçersiz tarihte null, dakika/saat/gün", () => {
    const simdi = Date.parse("2026-11-03T12:00:00Z");
    expect(goreliZaman("gecersiz", simdi)).toBeNull();
    expect(goreliZaman(null, simdi)).toBeNull();
    expect(goreliZaman("2026-11-03T11:59:40Z", simdi)).toBe("az önce");
    expect(goreliZaman("2026-11-03T11:15:00Z", simdi)).toBe("45 dk önce");
    expect(goreliZaman("2026-11-03T10:00:00Z", simdi)).toBe("2 sa önce");
    expect(goreliZaman("2026-11-01T10:00:00Z", simdi)).toBe("2 gün önce");
  });
});

describe("erişilebilirlik ve sayaç", () => {
  it("mesaj listesi canlı bölge değil; cevap gelince yalnız sonuç duyurulur", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    sarmala("/kosular", <AsistanPaneli />);
    const p = await paneliAc(u);
    expect(p.querySelector(".asistan-mesajlar")).not.toHaveAttribute("aria-live");
    const id = await sor(u, "Kırarak doğrula neden gri?");
    act(() => asistanMockIsle(id));
    await waitFor(() => expect(within(p).getByTestId("asistan-duyuru")).toHaveTextContent("Asistanın cevabı geldi."), { timeout: 3000 });
  });

  it("bekleme sayacı istemci saatiyle başlar: sunucu zamanı 1 sa geride olsa da 'Uzun sürüyor' hemen çıkmaz", async () => {
    await oturumAc("analist");
    const asil = asistanApi.mesajlar.bind(asistanApi);
    vi.spyOn(asistanApi, "mesajlar").mockImplementation(async (id: string) =>
      (await asil(id)).map((m) => ({ ...m, olusturma: new Date(Date.now() - 60 * DK).toISOString() })),
    );
    const u = userEvent.setup();
    sarmala("/kosular", <AsistanPaneli />);
    const p = await paneliAc(u);
    await sor(u, "Kırarak doğrula neden gri?");
    const b = await within(p).findByTestId("asistan-bekleme");
    expect(within(b).getByText(/· \d sn/)).toBeInTheDocument();
    expect(within(p).queryByText("Uzun sürüyor")).toBeNull();
  });

  it('"Bu ne?" klavyeyle: odaktaki öğe Enter ile seçilir, odak soru alanına döner', async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    sarmala(
      "/kosular",
      <>
        <section className="kart">
          <h2>Doğrulama</h2>
          <button type="button">Kaydet</button>
        </section>
        <AsistanPaneli />
      </>,
    );
    const p = await paneliAc(u);
    await u.click(within(p).getByRole("button", { name: "? Bu ne?" }));
    expect(screen.getByTestId("asistan-bune-bindirme")).toHaveTextContent(/Tab ile öğeye gidip Enter/);
    const kaydet = screen.getByRole("button", { name: "Kaydet" });
    kaydet.focus();
    fireEvent.keyDown(kaydet, { key: "Enter" });
    expect(screen.queryByTestId("asistan-bune-bindirme")).toBeNull();
    expect(within(panel()).getByText(/Seçili: Kaydet/)).toBeInTheDocument();
    expect(document.activeElement).toBe(within(panel()).getByLabelText("Sorunuz"));
  });

  it("dar ekran: Esc ile 'Bu ne?'den çıkınca odak '? Bu ne?' düğmesine döner; modal açıkken arka plan inert ve kaydırma kilitli", async () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn((q: string) => ({ matches: q.includes("max-width"), media: q, addEventListener: () => undefined, removeEventListener: () => undefined })),
    );
    await oturumAc("analist");
    const u = userEvent.setup();
    sarmala(
      "/kosular",
      <>
        <main data-testid="arka-plan">
          <button type="button">Arka düğme</button>
        </main>
        <AsistanPaneli />
      </>,
    );
    await u.click(await screen.findByRole("button", { name: "Asistanı aç" }));
    const arka = screen.getByTestId("arka-plan");
    expect(arka).toHaveAttribute("inert");
    expect(document.body.style.overflow).toBe("hidden");

    await u.click(within(panel()).getByRole("button", { name: "? Bu ne?" }));
    // Kip açıkken panel kalkar (modal değil): arka plan seçilebilir olmalı.
    expect(screen.queryByTestId("asistan-paneli")).toBeNull();
    expect(arka).not.toHaveAttribute("inert");
    await u.keyboard("{Escape}");
    expect(document.activeElement).toBe(within(panel()).getByRole("button", { name: "? Bu ne?" }));
    expect(arka).toHaveAttribute("inert");

    await u.click(within(panel()).getByRole("button", { name: "Asistanı kapat" }));
    expect(arka).not.toHaveAttribute("inert");
    expect(document.body.style.overflow).toBe("");
  });
});
