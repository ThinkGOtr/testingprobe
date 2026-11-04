// Asistan paneli inceleme düzeltmeleri (tur 5): bekleyen soru varken "Yeni sohbet"/"Geçmiş" pasif;
// yeni sohbette ilk soruda mesaj listesi bir kez çekilir; tamamlanmış cevabın iptali 409 (core gibi)
// panelde gösterilir; `derin_onerilir` kartta vurgulanır; asistan ucu yokken içerik adlı bölge
// (adsız sekme paneli değil); çapalı "Git" masaüstünde de paneli kapatır.
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { asistanApi, type AsistanMesaji } from "../../api/asistan";
import { asistanMockAyarla, asistanMockBekleyenler, asistanMockIsle } from "../../api/mock/asistan";
import { OturumProvider } from "../../auth";
import { sonHatayiSifirla } from "../../lib/sonHata";
import { oturumAc } from "../../test/yardimci";
import { BildirimProvider } from "../Bildirim";
import { AsistanPaneli } from "./AsistanPaneli";
import { CevapKarti } from "./CevapKarti";
import { acSekme, asistanKontrolSifirla, paneliAc as kontrolPaneliAc, useAsistanKontrol } from "./kontrol";
import { ekOneriSohbetleriniSifirla } from "./OneriEkOneriler";
import { OneriEylemAlani } from "./OneriKarti";
import { oneriDeposunuSifirla } from "./OneriVerisi";
import { sohbetAyar } from "./SohbetSekmesi";

function yalnizPanel(yol = "/kosular", ek?: ReactNode) {
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

beforeEach(() => {
  asistanKontrolSifirla();
  sonHatayiSifirla();
  oneriDeposunuSifirla();
  ekOneriSohbetleriniSifirla();
  asistanMockAyarla({ otomatikIsle: false });
  Object.assign(sohbetAyar, { yoklamaMs: 30, uzunSurerMs: 25_000 });
});

afterEach(() => {
  vi.restoreAllMocks();
  asistanKontrolSifirla();
  ekOneriSohbetleriniSifirla();
  Object.assign(sohbetAyar, { yoklamaMs: 3000, uzunSurerMs: 25_000 });
});

describe("bekleyen soru varken sohbet değiştirilemez", () => {
  it("'Yeni sohbet' ve 'Geçmiş' pasif, ipucu görünür; cevap gelince yeniden etkin", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    const id = await sor(u, "Bugün ne yapmalıyım?");
    expect(await within(p).findByTestId("asistan-bekleme")).toBeInTheDocument();
    const yeni = within(p).getByRole("button", { name: "Yeni sohbet" });
    const gecmis = within(p).getByRole("button", { name: "Geçmiş" });
    expect(yeni).toBeDisabled();
    expect(gecmis).toBeDisabled();
    expect(yeni).toHaveAccessibleDescription(/yeni sohbet açabilirsiniz/);
    // Pasif düğmeye tıklamak bekleme göstergesini ve "Beklemeyi bırak"ı kaybettirmez.
    await u.click(yeni);
    expect(within(p).getByTestId("asistan-bekleme")).toBeInTheDocument();
    expect(within(p).getByRole("button", { name: "Beklemeyi bırak" })).toBeInTheDocument();
    act(() => asistanMockIsle(id));
    expect(await within(p).findByRole("article", {}, { timeout: 3000 })).toBeInTheDocument();
    await waitFor(() => expect(within(p).getByRole("button", { name: "Yeni sohbet" })).toBeEnabled());
    expect(within(p).getByRole("button", { name: "Geçmiş" })).toBeEnabled();
  });
});

describe("yeni sohbette ilk soru", () => {
  it("mesaj listesi bir kez çekilir; 'Sohbet yükleniyor…' gösterilmez", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    const liste = vi.spyOn(asistanApi, "mesajlar");
    await sor(u, "Bugün ne yapmalıyım?");
    expect(await within(p).findByTestId("asistan-bekleme")).toBeInTheDocument();
    expect(within(p).queryByText("Sohbet yükleniyor…")).toBeNull();
    expect(liste).toHaveBeenCalledTimes(1);
  });

  it("geçmişten başka sohbet seçilince yine yüklenir (atlama bayrağı yalnız gönderim için)", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    const id = await sor(u, "Bugün ne yapmalıyım?");
    act(() => asistanMockIsle(id));
    expect(await within(p).findByRole("article", {}, { timeout: 3000 })).toBeInTheDocument();
    await waitFor(() => expect(within(p).getByRole("button", { name: "Yeni sohbet" })).toBeEnabled());
    await u.click(within(p).getByRole("button", { name: "Yeni sohbet" }));
    expect(within(p).queryByRole("article")).toBeNull();
    await u.click(within(p).getByRole("button", { name: "Geçmiş" }));
    const liste = vi.spyOn(asistanApi, "mesajlar");
    await u.click(await within(p).findByRole("button", { name: /^Bugün ne yapmalıyım\?(?! sohbetini sil)/ }));
    expect(await within(p).findByRole("article")).toBeInTheDocument();
    expect(liste).toHaveBeenCalledTimes(1);
  });
});

describe("tamamlanmış cevabın iptali", () => {
  it("cevap sunucuda bitmişken 'Beklemeyi bırak' 409 metnini gösterir ve cevabı yükler", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    // Olay akışı yok ve yoklama seyrek: cevap sunucuda bitti, ekran hâlâ bekliyor.
    Object.assign(sohbetAyar, { yoklamaMs: 60_000 });
    yalnizPanel();
    const p = await paneliAc(u);
    const id = await sor(u, "Bugün ne yapmalıyım?");
    expect(await within(p).findByTestId("asistan-bekleme")).toBeInTheDocument();
    act(() => asistanMockIsle(id));
    await u.click(within(p).getByRole("button", { name: "Beklemeyi bırak" }));
    expect(await within(p).findByRole("alert")).toHaveTextContent("Cevap zaten tamamlandı; iptal edilemez.");
    expect(await within(p).findByRole("article")).toBeInTheDocument();
    expect(within(p).queryByTestId("asistan-bekleme")).toBeNull();
  });
});

function mesaj(ek: Partial<AsistanMesaji["cevap"] & object> = {}): AsistanMesaji {
  return {
    id: "m1",
    sohbet_id: "s1",
    sira: 2,
    rol: "assistant",
    ust_mesaj_id: null,
    icerik: "soru",
    cevap: { cevap_bloklari: [{ tur: "paragraf", metin: "Cevap" }], kaynaklar: [], yonlendirmeler: [], eylem_reddi: false, ...ek },
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
  };
}

function kart(m: AsistanMesaji, derinIncelenebilir = true) {
  return render(
    <MemoryRouter>
      <BildirimProvider>
        <CevapKarti mesaj={m} derinIncelenebilir={derinIncelenebilir} derinIncele={() => undefined} />
      </BildirimProvider>
    </MemoryRouter>,
  );
}

describe("derin_onerilir (§6.2: otomatik yerine kartta önerilir)", () => {
  it("bayrak varken düğme birincil tonda ve notla", () => {
    kart(mesaj({ derin_onerilir: true }));
    const d = screen.getByRole("button", { name: "Daha ayrıntılı incele" });
    expect(d).toHaveClass("dugme-birincil");
    expect(screen.getByTestId("derin-onerilir")).toHaveTextContent("Bu cevap kaynakla doğrulanamadı; ayrıntılı inceleme önerilir.");
    expect(d).toHaveAccessibleDescription(/ayrıntılı inceleme önerilir/);
  });

  it("bayrak yoksa ikincil ton, not yok; incelenemiyorsa bayrak olsa da not yok", () => {
    const { unmount } = kart(mesaj());
    expect(screen.getByRole("button", { name: "Daha ayrıntılı incele" })).toHaveClass("dugme-ikincil");
    expect(screen.queryByTestId("derin-onerilir")).toBeNull();
    unmount();
    kart(mesaj({ derin_onerilir: true }), false);
    expect(screen.queryByRole("button", { name: "Daha ayrıntılı incele" })).toBeNull();
    expect(screen.queryByTestId("derin-onerilir")).toBeNull();
  });
});

describe("asistan ucu yokken (yalnız Öneriler)", () => {
  it("içerik adsız sekme paneli değil, 'Öneriler' adlı bölge", async () => {
    await oturumAc("analist");
    asistanMockAyarla({ statusYok: true });
    yalnizPanel();
    act(() => acSekme("oneriler"));
    const p = await screen.findByTestId("asistan-paneli");
    expect(within(p).queryByRole("tablist")).toBeNull();
    expect(within(p).queryByRole("tabpanel")).toBeNull();
    expect(within(p).getByRole("region", { name: "Öneriler" })).toBeInTheDocument();
  });
});

describe("çapalı Git", () => {
  function KontrolDurumu() {
    const k = useAsistanKontrol();
    return <span data-testid="acik">{String(k.acik)}</span>;
  }

  function eylemAlani(capa: string | null) {
    return render(
      <MemoryRouter initialEntries={["/"]}>
        <BildirimProvider>
          <KontrolDurumu />
          <OneriEylemAlani eylem={{ tur: "rota", rota: "/scripts/s-1", capa }} />
        </BildirimProvider>
      </MemoryRouter>,
    );
  }

  it("çapa varsa panel (masaüstünde de, onGit verilmese de) kapanır", async () => {
    const u = userEvent.setup();
    act(() => kontrolPaneliAc());
    eylemAlani("kirarak-dogrula");
    expect(screen.getByTestId("acik")).toHaveTextContent("true");
    await u.click(screen.getByRole("button", { name: "Git" }));
    expect(screen.getByTestId("acik")).toHaveTextContent("false");
  });

  it("çapasız rota masaüstünde paneli açık bırakır", async () => {
    const u = userEvent.setup();
    act(() => kontrolPaneliAc());
    eylemAlani(null);
    await u.click(screen.getByRole("button", { name: "Git" }));
    expect(screen.getByTestId("acik")).toHaveTextContent("true");
  });
});
