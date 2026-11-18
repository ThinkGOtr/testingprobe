// TP UX şerit A: İşlerim (IA-01/02), Hatalar kuyruğu ve sınıflandırma kartı (IA-16), başka projedeki
// kayıt (IA-05). Örnek veri arka ucu (api/mock/islerim.ts) üzerinden.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { ApiError } from "../api/http";
import { islerimApi, isKuyruguUyarla, kayitYeriUyarla } from "../api/islerim";
import { isKuyruguHesapla } from "../api/mock/islerim";
import { mockVerisi } from "../api/mock/handlers";
import type { HataAnalizi } from "../api/types";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { BaskaProjedeKayit } from "../components/BaskaProjedeKayit";
import { oturumAc, sar } from "../test/yardimci";
import { hataSuz } from "./Hatalar";

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

function belirsizHata(id = "fail-belirsiz"): HataAnalizi {
  const ornek = mockVerisi().hatalar[0];
  const h: HataAnalizi = {
    ...ornek,
    id,
    test_adi: "Giriş yap butonu tıklanamadı",
    sinif: "unknown",
    alt_tur: null,
    karar_kaynagi: "rule",
    oneri: null,
    eslesen_sinyaller: [],
    llm_yorumu: null,
    mode: "replay_miss",
  };
  mockVerisi().hatalar.unshift(h);
  return h;
}

describe("İşlerim uyarlayıcı ve örnek veri hesabı", () => {
  it("boş grupları atar, menü sayılarını okur", () => {
    const k = isKuyruguUyarla({
      rol: "tester",
      toplam: 3,
      benim: [
        { anahtar: "a", tur: "case", rol: "tester", baslik: "Case kararı", sonraki_adim: "x", sayi: 3, ogeler: [{ id: "r1", tur: "case", etiket: "TPD-1", neden: "3 case", rota: "/gereksinimler/r1/caseler", sayi: 3 }] },
        { anahtar: "b", tur: "case", rol: "tester", baslik: "Boş", sonraki_adim: "x", sayi: 0, ogeler: [] },
      ],
      ekip: [],
      menu: { "/caseler": 3, "/islerim": 3 },
    });
    expect(k.benim.map((g) => g.anahtar)).toEqual(["a"]);
    expect(k.menu["/caseler"]).toBe(3);
    expect(kayitYeriUyarla({ bulundu: true, ayni_proje: false, proje: { pid: "p2", name: "Bayi" } })).toEqual({
      bulundu: true,
      ayni_proje: false,
      proje: { pid: "p2", ad: "Bayi" },
    });
    expect(kayitYeriUyarla({ bulundu: false })).toEqual({ bulundu: false, ayni_proje: false, proje: null });
  });

  it("önceki sürüme ait case karar bekliyor sayılmaz", () => {
    const v = mockVerisi();
    const once = isKuyruguHesapla(v, "tester").menu["/caseler"];
    for (const c of v.caseler) if (c.durum === "draft") c.onceki_icerik = true;
    const sonra = isKuyruguHesapla(v, "tester");
    expect(sonra.benim.find((g) => g.anahtar === "case_karari")).toBeUndefined();
    expect(sonra.menu["/caseler"]).toBeLessThanOrEqual(once);
  });

  it("görüntüleyici yalnız ekip sayısını görür, öğe ayrıntısını görmez", () => {
    const v = mockVerisi();
    const k = isKuyruguHesapla(v, "viewer");
    expect(k.benim).toEqual([]);
    expect(k.ekip.length).toBeGreaterThan(0);
    for (const g of k.ekip.filter((x) => x.tur === "case")) expect(g.ogeler).toEqual([]);
  });
});

describe("İşlerim sayfası ve menü", () => {
  it("Test Uzmanı açılışta İşlerim'e düşer; sıradaki adım, bağlantı ve ekipte bekleyenler görünür", async () => {
    belirsizHata();
    await oturumAc("testci");
    uygulama("/");
    expect(await screen.findByRole("heading", { name: "İşlerim", level: 1 })).toBeInTheDocument();
    const grup = (await screen.findByText("Sınıflandırma bekleyen hata")).closest("section") as HTMLElement;
    expect(within(grup).getByText(/Sıradaki adım:/)).toBeInTheDocument();
    expect(within(grup).getByRole("link", { name: "Giriş yap butonu tıklanamadı" })).toHaveAttribute("href", "/hatalar/fail-belirsiz");
    expect(screen.getByRole("heading", { name: "Ekipte bekleyenler" })).toBeInTheDocument();
    // Menü: İşlerim ilk öğe; rozet yalnız gerçek bekleyen iş sayısı, erişilebilir metinle.
    const menu = screen.getByRole("navigation", { name: "Ana menü" });
    const ilk = within(menu).getAllByRole("link")[0];
    expect(ilk).toHaveTextContent(/^İşlerim/);
    await waitFor(() => expect(within(menu).getByTestId("menu-sayac-hatalar")).toHaveTextContent("1"));
    expect(within(menu).getByText("(1 iş bekliyor)", { exact: false })).toBeInTheDocument();
    // Eski "rolünüzün çalışma alanı" noktası yok.
    expect(within(menu).queryByText(/rolünüzün çalışma alanı/)).toBeNull();
  });

  it("sayı 0 olan menü öğesinde rozet yok", async () => {
    await oturumAc("izleyici");
    uygulama("/kontrol-kulesi");
    const menu = await screen.findByRole("navigation", { name: "Ana menü" });
    await waitFor(() => expect(within(menu).getByText("İşlerim")).toBeInTheDocument());
    expect(within(menu).queryByTestId(/^menu-sayac-/)).toBeNull();
  });
});

describe("Hatalar kuyruğu ve sınıflandırma (IA-16)", () => {
  it("sekme süzgeci: kasıtlı kırma kuyruğa girmez", () => {
    const h = belirsizHata("x1");
    const kirma = { ...h, id: "x2", kirma: true };
    expect(hataSuz([h, kirma], "unknown").map((x) => x.id)).toEqual(["x1"]);
    expect(hataSuz([h, kirma], "hepsi")).toHaveLength(2);
  });

  it("Hatalar sayfası varsayılan sekmede sınıflandırılmamış hatayı listeler", async () => {
    belirsizHata();
    await oturumAc("testci");
    uygulama("/hatalar");
    expect(await screen.findByRole("heading", { name: "Hatalar", level: 1 })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Giriş yap butonu tıklanamadı" })).toHaveAttribute("href", "/hatalar/fail-belirsiz");
    expect(screen.getByRole("button", { name: /Sınıflandırılmamış \(1\)/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("Test Uzmanı belirsiz hatayı ürün hatası olarak sınıflandırır; bug taslağı açılır", async () => {
    belirsizHata();
    await oturumAc("testci");
    const u = userEvent.setup();
    uygulama("/hatalar/fail-belirsiz");
    const kart = await screen.findByTestId("siniflandirma-karti");
    expect(within(kart).getByText(/REPLAY-MISS/)).toBeInTheDocument();
    const kaydet = within(kart).getByRole("button", { name: "Sınıfı kaydet" });
    await u.click(within(kart).getByRole("radio", { name: /Ürün hatası/ }));
    await u.type(within(kart).getByLabelText(/Gerekçe/), "Buton gerçekten pasif kalıyor");
    await u.click(kaydet);
    expect(await screen.findByRole("link", { name: "Bug taslağına git" })).toBeInTheDocument();
    const h = mockVerisi().hatalar.find((x) => x.id === "fail-belirsiz")!;
    expect(h.sinif).toBe("product_defect");
    expect(h.karar_kaynagi).toBe("human");
    expect(mockVerisi().denetim.some((d) => d.eylem === "failure.classified")).toBe(true);
  });

  it("yetkisiz rol tek satırda kimi beklediğimizi görür", async () => {
    belirsizHata();
    await oturumAc("analist");
    uygulama("/hatalar/fail-belirsiz");
    expect(await screen.findByTestId("siniflandirma-bekleniyor")).toHaveTextContent("Bu adım Test Uzmanı'nda: sınıflandırma bekleniyor");
    expect(screen.queryByRole("button", { name: "Sınıfı kaydet" })).toBeNull();
  });

  it("iç terimler: 'LLM yorumu' yok, sinyal kodları Teknik ayrıntı'da", async () => {
    await oturumAc("muhendis");
    uygulama("/hatalar/fail-2?sekme=teknik");
    expect(await screen.findByText("Sinyal kodları")).toBeInTheDocument();
    expect(screen.queryByText("LLM yorumu")).toBeNull();
    expect(screen.queryByText(/^imza:/)).toBeNull();
  });
});

describe("başka projedeki kayıt (IA-05)", () => {
  it("404'te kayıt başka projedeyse 'X projesine geç ve aç' gösterir", async () => {
    await oturumAc("analist");
    const casus = vi.spyOn(islerimApi, "kayitYeri").mockResolvedValue({ bulundu: true, ayni_proje: false, proje: { pid: "p2", ad: "Bayi Portalı" } });
    sar(
      <BaskaProjedeKayit
        tur="script"
        id="s-9"
        hata={new ApiError(404, "Script bulunamadı")}
        ad="Test kodu"
        liste={["/kod", "Kod üretimi"]}
        yedek={<p>yedek</p>}
      />,
    );
    expect(await screen.findByText("Bu kayıt Bayi Portalı projesinde.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Bayi Portalı projesine geç ve aç" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Test kodu başka projede");
    // Ham "Script bulunamadı" tekrarı yok.
    expect(screen.queryByText("Script bulunamadı")).toBeNull();
    expect(casus).toHaveBeenCalledWith("script", "s-9");
    casus.mockRestore();
  });

  it("404 dışı hatada sayfanın kendi hata görünümü (yedek) çizilir", async () => {
    await oturumAc("analist");
    sar(<BaskaProjedeKayit tur="run" id="r" hata={new ApiError(500, "x")} ad="Koşu" liste={["/kosular", "Koşular"]} yedek={<p>yedek görünüm</p>} />);
    expect(screen.getByText("yedek görünüm")).toBeInTheDocument();
  });
});
