// 009 mobil-masaüstü portal ekranları: Kod üretiminde platform seçimi, platform rozeti, Kontrol Kulesi
// platform süzgeci, uygulama ajanı adımları (app_*), platform check'leri ve sayfa kaynağı kanıtı.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ayar, mockVerisi } from "../api/mock/handlers";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { PlatformRozeti, PlatformSecici, PlatformSuzgeci } from "../components/Platform";
import { SayfaKaynagiGoruntuleyici } from "../components/SayfaKaynagi";
import { hataAnaliziUyarla } from "../api/uyumTriage";
import { kosuDetayUyarla, kosuUyarla, scriptUyarla } from "../api/uyumDemoB";
import { oturumAc } from "../test/yardimci";
import { kanitTuru, onarimAsamalari, uygulamaKanitlari } from "./HataDetay";
import { platformDagilimi } from "./KontrolKulesi";
import { kosulariSuz } from "./Kosular";

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

beforeEach(() => {
  ayar.isAdimiMs = 0;
});

describe("platform bileşenleri", () => {
  it("rozet: görünür ad + ekran okuyucuya 'Platform:'; platform yoksa çizilmez", () => {
    const { container, rerender } = render(<PlatformRozeti platform="ios" />);
    expect(screen.getByTestId("platform-rozeti")).toHaveTextContent("Platform: iOS");
    expect(screen.getByTestId("platform-rozeti")).toHaveClass("cip-notr");
    rerender(<PlatformRozeti platform={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("seçici: legend adlı radyo grubu, varsayılan değer seçili, değişiklik bildirilir", async () => {
    const u = userEvent.setup();
    const degistir = vi.fn();
    render(<PlatformSecici etiket="Hedef platform" deger="web" degistir={degistir} aciklamali />);
    const grup = screen.getByRole("group", { name: "Hedef platform" });
    const radyolar = within(grup).getAllByRole("radio");
    expect(radyolar.map((r) => r.getAttribute("value"))).toEqual(["web", "android", "ios", "windows"]);
    expect(within(grup).getByRole("radio", { name: /^Web/ })).toBeChecked();
    // Ad yalnız platform adı (✓ işareti ada girmez); kısa açıklama tanım olarak okunur.
    const android = within(grup).getByRole("radio", { name: "Android" });
    expect(android).not.toBeChecked();
    expect(android).toHaveAccessibleDescription("Emülatör · Appium + Java");
    await u.click(within(grup).getByRole("radio", { name: /^iOS/ }));
    expect(degistir).toHaveBeenCalledWith("ios");
  });

  it("süzgeç: Tümü + dört platform", () => {
    render(<PlatformSuzgeci etiket="Platform" deger="tumu" degistir={() => undefined} />);
    expect(screen.getAllByRole("radio").map((r) => r.getAttribute("value"))).toEqual(["tumu", "web", "android", "ios", "windows"]);
    expect(screen.getByRole("radio", { name: "Tümü" })).toBeChecked();
  });
});

describe("uyarlayıcılar (core şekli)", () => {
  it("script platformu: core değeri; alan yoksa (009 öncesi core) web; tanınmayan null", () => {
    expect(scriptUyarla({ id: "s", platform: "android" }).platform).toBe("android");
    expect(scriptUyarla({ id: "s" }).platform).toBe("web");
    expect(scriptUyarla({ id: "s", platform: "tv" }).platform).toBeNull();
  });

  it("koşu platformu: platform → ortam.platform → tek local-ci-<platform>; yoksa null (web varsayılmaz)", () => {
    expect(kosuUyarla({ id: "r", ortam: { platform: "ios" } }).platform).toBe("ios");
    expect(kosuUyarla({ id: "r" }).platform).toBeNull();
    const d = kosuDetayUyarla({
      id: "r",
      checks: { yol: "checks/x.json", var: true, durum: "completed", conclusion: "success", platformlar: { "local-ci-android": { durum: "completed", conclusion: "failure" } } },
    });
    expect(d.platform_kontrolleri).toEqual([{ ad: "local-ci-android", platform: "android", durum: "failed" }]);
    // Check'ler commit'indir: web koşusunun commit'inde de local-ci-android olabilir → platform türetilmez.
    expect(d.platform).toBeNull();
  });

  it("triage: öneri kaynağı/platformu okunur; failure platformu öneriden düşer", () => {
    const h = hataAnaliziUyarla({
      id: "f",
      run_id: "r",
      sinif: "test_maintenance",
      oneri: { tur: "locator_fix", eski_test_id: "a", yeni_test_id: "b", rol: "", ad: "", kaynak: "sayfa_kaynagi", platform: "android" },
      kanit_linkleri: [{ etiket: "Hata anı sayfa kaynağı (Appium)", url: "/api/artifacts/runs/r/k.xml", tur: "page_source" }],
    });
    expect(h.platform).toBe("android");
    expect(h.oneri).toMatchObject({ kaynak: "sayfa_kaynagi", platform: "android" });
    expect(kanitTuru(h.kanit_linkleri[0])).toBe("page_source");
    // "Hata anı" etiketi error_context ile karışmaz.
    expect(kanitTuru({ etiket: "Hata anı sayfa snapshot'ı (error-context)", url: null })).toBe("error_context");
    expect(uygulamaKanitlari(h.kanit_linkleri, h.platform).sayfaKaynagi?.url).toBe("/api/artifacts/runs/r/k.xml");
    // Web testinde ekran görüntüsü satır içi gösterilmez (bağlantı olarak kalır).
    expect(uygulamaKanitlari([{ etiket: "Ekran görüntüsü", url: "/api/artifacts/runs/r/a.png", tur: "screenshot" }], "web").ekran).toBeNull();
  });
});

describe("Kod üretimi: platform seçimi", () => {
  it("varsayılan Web; Android seçilince aday listesi platforma göre ve POST gövdesinde platform", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    const casus = vi.spyOn(api, "kodUret");
    uygulama("/kod");
    const grup = await screen.findByRole("group", { name: "Hedef platform" });
    expect(within(grup).getByRole("radio", { name: /^Web/ })).toBeChecked();
    // C2'nin web script'i var: web adayı değil. Android'de de script'i var (scr-and); iOS listesinde de yok.
    expect(screen.queryByRole("checkbox", { name: /7 adet kampanyalı/ })).toBeNull();
    await u.click(within(grup).getByRole("radio", { name: /^Android/ }));
    const aday = await screen.findByRole("checkbox", { name: /minimum tutarın altında uyarı/ });
    await u.click(aday);
    await u.click(screen.getByRole("button", { name: "Seçilenler için kod üret (1) · Android" }));
    await waitFor(() => expect(casus).toHaveBeenCalledWith(["case-1-4"], "android"));
    await waitFor(() => expect(mockVerisi().scriptler.find((s) => s.case_ids.includes("case-1-4") && s.platform === "android")).toBeTruthy());
    const s = mockVerisi().scriptler.find((x) => x.case_ids.includes("case-1-4") && x.platform === "android")!;
    expect(s.branch).toMatch(/^tp\/case-android-/);
    expect(s.dosya_yolu).toMatch(/e2e-app\/.*\.java$/);
    casus.mockRestore();
  });

  it("platform değişince seçim temizlenir (Web'de seçilen case Android'e taşınmaz)", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    uygulama("/kod");
    await u.click(await screen.findByRole("checkbox", { name: /minimum tutarın altında uyarı/ }));
    expect(screen.getByRole("button", { name: "Seçilenler için kod üret (1)" })).toBeEnabled();
    await u.click(screen.getByRole("radio", { name: /^Android/ }));
    expect(screen.getByRole("checkbox", { name: /minimum tutarın altında uyarı/ })).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Seçilenler için kod üret (0) · Android" })).toBeDisabled();
  });

  it("liste satırında platform rozeti (web + uygulamalar)", async () => {
    await oturumAc("muhendis");
    uygulama("/kod");
    const tablo = await screen.findByRole("region", { name: "Üretilen testler tablosu" });
    const rozetler = within(tablo).getAllByTestId("platform-rozeti").map((r) => r.textContent);
    expect(rozetler).toEqual(expect.arrayContaining(["Platform: Web", "Platform: Android", "Platform: iOS", "Platform: Windows"]));
  });
});

describe("Script detayı (uygulama)", () => {
  it("app_* adımları Türkçe adla, dikey ekran çerçevesi; PR check'i 'Yerel CI · Android'", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    uygulama("/kod/scr-and");
    const adimlar = await screen.findByRole("list", { name: "Ajan adımları" });
    expect(within(adimlar).getAllByRole("button")[0]).toHaveTextContent("Uygulamayı başlat");
    expect(adimlar).toHaveTextContent("Ekranı oku");
    expect(adimlar).toHaveTextContent("Locator üret");
    await u.click(within(adimlar).getAllByRole("button")[0]);
    const sekil = document.querySelector("figure.ajan-ekran")!;
    expect(sekil).toHaveClass("ajan-ekran-dikey");
    expect(sekil).toHaveTextContent("Uygulamayı başlat (app_launch)");
    expect(screen.getByRole("heading", { name: "Ajan adımları (Appium · app-mcp)" })).toBeInTheDocument();
    const checks = screen.getAllByRole("list", { name: "PR check'leri" })[0];
    expect(checks).toHaveTextContent("Yerel CI · Android (local-ci-android)");
    expect(screen.getAllByTestId("platform-rozeti")[0]).toHaveTextContent("Android");
  });

  it("web script'i değişmez: Playwright MCP başlığı, local-ci 'Yerel CI · Web'", async () => {
    await oturumAc("muhendis");
    uygulama("/kod/scr-2");
    expect(await screen.findByRole("heading", { name: "Ajan adımları (Playwright MCP)" })).toBeInTheDocument();
    expect(document.querySelector("figure.ajan-ekran")).not.toHaveClass("ajan-ekran-dikey");
    expect(screen.getAllByRole("list", { name: "PR check'leri" })[0]).toHaveTextContent("Yerel CI · Web (local-ci)");
  });
});

describe("Triage (uygulama): sayfa kaynağı ve kimlik onarımı", () => {
  it("sayfa kaynağı açılınca kaçışlı metin olarak görünür; onarım kartında boş rol/ad satırı yok", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    uygulama("/hatalar/fail-5");
    expect(await screen.findByTestId("triage-sinif")).toHaveTextContent("Platform: Android");
    const sk = screen.getByTestId("sayfa-kaynagi");
    await u.click(within(sk).getByText("Sayfa kaynağını göster (XML)"));
    const pre = await within(sk).findByLabelText(/Hata anı sayfa kaynağı \(Appium\) \(XML/);
    expect(pre).toHaveTextContent('resource-id="login-button"');
    // XML yorumlanmaz: <hierarchy> eleman olarak DOM'a girmez.
    expect(document.querySelector("hierarchy")).toBeNull();
    expect(screen.getByTestId("kanit-ekran").querySelector("img")).toHaveAttribute("alt", "Hata anı ekran görüntüsü (Android)");
    expect(screen.getByTestId("onarim-sayfa-kaynagi")).toHaveTextContent("Kimlikler.java");
    expect(screen.queryByTestId("onarim-niyet")).toBeNull();
    expect(screen.getByRole("heading", { name: /Locator onarım önerisi/ })).toHaveTextContent("Android");
    expect(screen.getByLabelText("Locator değişikliği")).toHaveTextContent('Giris.GIRIS_YAP (kimlik)"login-submit"→yeni değer"login-button"');
  });

  it("onarım hattı sayfa kaynağı adlarını kullanır", () => {
    const o = mockVerisi().hatalar.find((h) => h.id === "fail-5")!.oneri;
    if (o?.tur !== "locator_fix") throw new Error("öneri yok");
    const adlar = onarimAsamalari(o).map((a) => a.ad);
    expect(adlar[0]).toMatch(/sayfa kaynağından/);
    expect(adlar[1]).toMatch(/Sayfa kaynağında tek aday kimlik/);
    expect(adlar[3]).toMatch(/Android cihazında/);
  });

  it("görüntüleyici: büyük dosya kesilir ve not düşülür", async () => {
    const u = userEvent.setup();
    const buyuk = `data:text/plain,${encodeURIComponent("x".repeat(300 * 1024))}`;
    render(<SayfaKaynagiGoruntuleyici url={buyuk} />);
    await u.click(screen.getByText("Sayfa kaynağını göster (XML)"));
    expect(await screen.findByTestId("sayfa-kaynagi-kesildi")).toHaveTextContent("ilk 256 KB");
  });

  it("görüntüleyici: core artefakt ucu dışındaki adres okunmaz", () => {
    render(<SayfaKaynagiGoruntuleyici url="https://ornek.test/k.xml" />);
    expect(screen.queryByText("Sayfa kaynağını göster (XML)")).toBeNull();
    expect(screen.getByTestId("sayfa-kaynagi")).toHaveTextContent("core artefakt ucu değil");
  });
});

describe("Koşular ve Kontrol Kulesi", () => {
  it("koşu detayı: platform rozeti, platform kontrolleri, triage satırında rozet", async () => {
    await oturumAc("muhendis");
    uygulama("/kosular/run-110");
    const liste = await screen.findByRole("list", { name: "Platform kontrolleri" });
    expect(liste).toHaveTextContent("Yerel CI · Android");
    expect(liste).toHaveTextContent("kırmızı");
    expect(within(screen.getByRole("list", { name: "Triage kayıtları" })).getByTestId("platform-rozeti")).toHaveTextContent("Android");
  });

  it("koşu süzgeci: platform seçimi platformsuz koşuyu dışarıda bırakır", () => {
    const k = mockVerisi().kosular;
    const and = kosulariSuz(k, { tetik: "", kaynak: "", durum: "", kirma: true, platform: "android" });
    expect(and.map((x) => x.id)).toEqual(["run-110"]);
    expect(kosulariSuz([{ ...k[0], platform: null }], { tetik: "", kaynak: "", durum: "", kirma: true, platform: "web" })).toEqual([]);
  });

  it("Kule: platform süzgeci son koşuları ve platform dağılımını daraltır; adres çubuğuna yazılır", async () => {
    await oturumAc("sunucu");
    const u = userEvent.setup();
    uygulama("/kontrol-kulesi");
    const grup = await screen.findByRole("group", { name: "Platform" });
    expect(within(grup).getByRole("radio", { name: "Tümü" })).toBeChecked();
    const dagilim = await screen.findByRole("region", { name: "Platform dağılımı tablosu" });
    expect(within(dagilim).getAllByRole("row")).toHaveLength(5);
    await u.click(within(grup).getByRole("radio", { name: "Android" }));
    await waitFor(() => expect(within(screen.getByRole("region", { name: "Platform dağılımı tablosu" })).getAllByRole("row")).toHaveLength(2));
    expect(screen.getByTestId("platform-dagilimi-android")).toHaveTextContent("Android1100");
    const kosular = screen.getByRole("region", { name: "Koşular tablosu" });
    expect(within(kosular).getAllByRole("row")).toHaveLength(2);
    expect(kosular).toHaveTextContent("run-110");
    expect(grup.parentElement).toHaveTextContent(/çekirdekte platform ayrımı taşımaz/);
    await u.click(within(grup).getByRole("radio", { name: "iOS" }));
    expect(await screen.findByText("iOS için koşu yok.")).toBeInTheDocument();
  });

  it("platform dağılımı: kapatılanlar sayılmaz; PR açık/birleşti/defect adayı", () => {
    const d = platformDagilimi(mockVerisi().scriptler);
    // 011: web'de ayrıca C9 Java PR'ı (açık) ve C8 doğrulanmamış Python script'i.
    expect(d.find((x) => x.platform === "web")).toMatchObject({ toplam: 5, pr_acik: 3, defect: 1 });
    expect(d.find((x) => x.platform === "windows")).toMatchObject({ toplam: 1, pr_acik: 1 });
  });
});
