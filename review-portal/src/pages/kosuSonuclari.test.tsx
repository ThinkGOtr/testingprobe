// Koşu detayı: test sonucu süzgeci (saf fonksiyonlar), satır ayrıntısı (adımlar, stack, ekler),
// CI adımları özeti ve GitHub koşusunda yerel rapor kopyası / GitHub yedeği (canlı core şekli).
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { yapilandir } from "../api/http";
import type { TestSonucu } from "../api/types";
import { kosuDetayUyarla } from "../api/uyumDemoB";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { adimHatali, CiAdimlari, ekTuru, githubYedekNotu, sonucFiltresiOku, sonuclariSuz, sonucSayaclari, TestAyrintisi } from "./KosuSonuclari";

const RID = "9106b437-0770-4afb-9f58-c9d437cf659d";
const OPENAPI = {
  paths: Object.fromEntries(["/auth/me", "/auth/login", "/runs", "/runs/{run_id}", "/events"].map((p) => [p, { get: {}, post: {} }])),
};

function sahteCore(ek: Record<string, unknown>, rol = "analyst") {
  return vi.fn().mockImplementation((url: string) => {
    const j = (status: number, govde: unknown) =>
      Promise.resolve(new Response(JSON.stringify(govde), { status, headers: { "Content-Type": "application/json" } }));
    if (url === "/api/openapi.json") return j(200, OPENAPI);
    if (url === "/api/auth/me") return j(200, { id: "u1", kullanici_adi: rol, rol });
    const yol = url.replace(/^\/api/, "").split("?")[0];
    if (yol in ek) return j(200, ek[yol]);
    return j(404, { detail: "Not Found" });
  });
}

function Konum() {
  const l = useLocation();
  return <span data-testid="konum">{l.search}</span>;
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

const T = (id: string, test_adi: string, durum: TestSonucu["durum"], ek: Partial<TestSonucu> = {}): TestSonucu => ({
  id,
  test_adi,
  durum,
  sure_ms: 100,
  retry: 0,
  hata_mesaji: null,
  failure_id: null,
  case_id: null,
  ...ek,
});

const SONUCLAR: TestSonucu[] = [
  T("1", "Sepet › ürün ekler", "passed", { dosya: "cart.spec.ts", sure_ms: 300 }),
  T("2", "Sepet › sayaç artar", "failed", { dosya: "cart.spec.ts", sure_ms: 900, hata_mesaji: "expect(locator).toBeVisible() failed" }),
  T("3", "Katalog › İndirim görünür", "flaky", { dosya: "katalog.spec.ts", sure_ms: 1200 }),
  T("4", "Katalog › eski", "skipped", { dosya: "katalog.spec.ts", sure_ms: 0 }),
  T("5", "Ödeme › kart", "failed", {
    dosya: "odeme.spec.ts",
    sure_ms: 50,
    denemeler: [{ deneme: 0, sonuc: "failed", sure_ms: 50, hata: { mesaj: "Timeout 5000ms ödeme butonu", stack: "Error\n at odeme.spec.ts:3" } }],
  }),
];

const BOS = { durum: "", ara: "", dosya: "", sirala: "durum", yalnizBasarisiz: false } as const;

describe("sonuclariSuz / sonucSayaclari / sonucFiltresiOku", () => {
  it("durum, dosya ve yalnız başarısız süzer; sayaçlar duruma göre", () => {
    expect(sonucSayaclari(SONUCLAR)).toEqual({ tumu: 5, passed: 1, failed: 2, flaky: 1, skipped: 1 });
    expect(sonuclariSuz(SONUCLAR, { ...BOS, durum: "flaky" }).map((s) => s.id)).toEqual(["3"]);
    expect(sonuclariSuz(SONUCLAR, { ...BOS, dosya: "katalog.spec.ts" }).map((s) => s.id)).toEqual(["3", "4"]);
    expect(sonuclariSuz(SONUCLAR, { ...BOS, yalnizBasarisiz: true }).map((s) => s.id)).toEqual(["5", "2"]);
  });

  it("arama ad, dosya, hata mesajı ve deneme hatasında; Türkçe büyük/küçük harf duyarsız", () => {
    expect(sonuclariSuz(SONUCLAR, { ...BOS, ara: "İNDİRİM" }).map((s) => s.id)).toEqual(["3"]);
    expect(sonuclariSuz(SONUCLAR, { ...BOS, ara: "tobevisible" }).map((s) => s.id)).toEqual(["2"]);
    expect(sonuclariSuz(SONUCLAR, { ...BOS, ara: "ödeme butonu" }).map((s) => s.id)).toEqual(["5"]);
    expect(sonuclariSuz(SONUCLAR, { ...BOS, ara: "odeme.spec" }).map((s) => s.id)).toEqual(["5"]);
  });

  it("sıralama: durum (başarısız önce), süre (uzun önce), ad", () => {
    expect(sonuclariSuz(SONUCLAR, BOS).map((s) => s.durum)).toEqual(["failed", "failed", "flaky", "passed", "skipped"]);
    expect(sonuclariSuz(SONUCLAR, { ...BOS, sirala: "sure" }).map((s) => s.id)).toEqual(["3", "2", "1", "5", "4"]);
    expect(sonuclariSuz(SONUCLAR, { ...BOS, sirala: "ad" }).map((s) => s.test_adi)[0]).toBe("Katalog › eski");
  });

  it("adres çubuğundan okur; bilinmeyen değerler varsayılana düşer", () => {
    expect(sonucFiltresiOku(new URLSearchParams("t_durum=failed&t_ara=x&t_sirala=sure&t_basarisiz=1&t_dosya=a.spec.ts"))).toEqual({
      durum: "failed",
      ara: "x",
      dosya: "a.spec.ts",
      sirala: "sure",
      yalnizBasarisiz: true,
    });
    expect(sonucFiltresiOku(new URLSearchParams("t_durum=bozuk&t_sirala=xx"))).toEqual(BOS);
  });

  it("githubYedekNotu: yerel kopya varsa not yok; hata/budandıysa GitHub'a düştüğü söylenir", () => {
    expect(githubYedekNotu({ kaynak: "github", github_artefakt: { durum: "indirildi", hata: null } })).toBeNull();
    expect(githubYedekNotu({ kaynak: "local", github_artefakt: null })).toBeNull();
    expect(githubYedekNotu({ kaynak: "github", github_artefakt: { durum: "hata", hata: "artefakt çok büyük" } })).toMatch(/alınamadı \(artefakt çok büyük\).*GitHub/);
    expect(githubYedekNotu({ kaynak: "github", github_artefakt: { durum: "budandi", hata: null } })).toMatch(/silindi/);
  });

  it("ekTuru ve adimHatali", () => {
    expect(ekTuru({ ad: "screenshot", tur: "image/png", url: "/a.png" })).toBe("resim");
    expect(ekTuru({ ad: "video", tur: "video/webm", url: "/v.webm" })).toBe("video");
    expect(ekTuru({ ad: "trace", tur: "application/zip", url: "/t/trace.zip" })).toBe("iz");
    expect(ekTuru({ ad: "log", tur: "text/plain", url: "/x.txt" })).toBe("diger");
    expect(adimHatali({ baslik: "a", sure_ms: 1, adimlar: [{ baslik: "b", sure_ms: 1, hata: "x" }] })).toBe(true);
    expect(adimHatali({ baslik: "a", sure_ms: 1 })).toBe(false);
  });
});

/** core `run_detail` şekli (GitHub koşusu, yerel kopya indirildi). */
const KOSU = {
  id: RID,
  tetik: "deploy",
  kaynak: "github",
  commit: "a".repeat(40),
  pr_no: null,
  durum: "failed",
  baslangic: "2026-11-02T10:00:00+00:00",
  sure_ms: 90000,
  toplam: 2,
  gecen: 1,
  basarisiz: 1,
  flaky: 0,
  atlanan: 0,
  allure_url: `/api/artifacts/runs/${RID}/src/e2e/results/allure-results`,
  allure_rapor: false,
  allure_sonuclari_url: `/api/artifacts/runs/${RID}/src/e2e/results/allure-results`,
  rapor_url: `/api/artifacts/k/1.x/runs/${RID}/src/e2e/results/playwright-report/index.html`,
  junit_url: `/api/artifacts/runs/${RID}/src/e2e/results/junit.xml`,
  sauce_url: null,
  ci_url: "https://github.com/acme/demo-app/actions/runs/700",
  log_url: `/api/artifacts/runs/${RID}/src/e2e/results/run-checks.log`,
  break_campaign: false,
  script_id: null,
  saglik_hatasi: null,
  github_run_id: "700",
  github_artefakt: { durum: "indirildi", hata: null },
  hata: null,
  uyarilar: [],
  adimlar: null,
  github: {
    conclusion: "failure",
    isler: [
      { ad: "ast-guard", sonuc: "success", url: "https://github.com/j/1" },
      { ad: "test-local", sonuc: "failure", url: "https://github.com/j/2" },
    ],
    meta: { durum: "failed", exit_code: "1", playwright: "1.64.1", event: "repository_dispatch", sha: "a".repeat(40) },
  },
  sonuclar: [
    {
      id: "r1",
      test_adi: "Sepet › sepete ekler",
      dosya: "cart.spec.ts",
      durum: "failed",
      ham_durum: "failed",
      sure_ms: 1500,
      retry: 1,
      hata_mesaji: "expect(locator).toBeVisible() failed",
      failure_id: null,
      case_id: null,
      ekler: [
        { ad: "screenshot", tur: "image/png", deneme: 1, url: `/api/artifacts/runs/${RID}/src/e2e/results/artifacts/cart/test-failed-1.png` },
        { ad: "trace", tur: "application/zip", deneme: 1, url: `/api/artifacts/runs/${RID}/src/e2e/results/artifacts/cart/trace.zip` },
        { ad: "video", tur: "video/webm", deneme: 1, url: `/api/artifacts/runs/${RID}/src/e2e/results/artifacts/cart/video.webm` },
      ],
      denemeler: [
        { deneme: 0, sonuc: "failed", sure_ms: 700, hata: { mesaj: "ilk deneme hatası" } },
        {
          deneme: 1,
          sonuc: "failed",
          sure_ms: 800,
          hata: { mesaj: "expect(locator).toBeVisible() failed", stack: "Error: expect\n    at cart.spec.ts:9:5", konum: "cart.spec.ts:9" },
          adimlar: [
            { baslik: "Sepeti aç", sure_ms: 300 },
            { baslik: "Ürün ekle", sure_ms: 500, hata: "görünmüyor", adimlar: [{ baslik: "Tıkla", sure_ms: 10 }] },
          ],
          stdout: "merhaba\n",
        },
      ],
    },
    { id: "r2", test_adi: "Katalog › listeler", dosya: "katalog.spec.ts", durum: "passed", sure_ms: 400, retry: 0, hata_mesaji: null, failure_id: null, case_id: null },
  ],
};

describe("koşu detayı (canlı core şekli)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("GitHub koşusu: raporlar core'dan, CI işi GitHub'a; not yok", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    vi.stubGlobal("fetch", sahteCore({ [`/runs/${RID}`]: KOSU }));
    uygulama(`/kosular/${RID}`);
    const kart = await screen.findByRole("region", { name: "Raporlar ve bağlantılar" });
    expect(within(kart).getByRole("link", { name: /Playwright HTML raporu/ })).toHaveAttribute("href", KOSU.rapor_url);
    expect(within(kart).getByRole("link", { name: /JUnit XML/ })).toHaveAttribute("href", KOSU.junit_url);
    expect(within(kart).getByRole("link", { name: /Koşu günlüğü/ })).toHaveAttribute("href", KOSU.log_url);
    expect(within(kart).getByRole("link", { name: /CI işi/ })).toHaveAttribute("href", KOSU.ci_url);
    expect(within(kart).queryByText(/GitHub'daki artefakta gider/)).not.toBeInTheDocument();
    // CI adımları: GitHub işleri ve ci-meta.json okunur halde.
    const ci = screen.getByRole("region", { name: "CI adımları" });
    expect(within(ci).getByRole("link", { name: /test-local/ })).toHaveAttribute("href", "https://github.com/j/2");
    expect(within(ci).getByText("1.64.1")).toBeInTheDocument();
  });

  it("yerel kopya alınamadıysa bağlantılar GitHub'a düşer ve kısa not görünür", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    const kosu = {
      ...KOSU,
      rapor_url: "https://github.com/acme/demo-app/actions/runs/700#artifacts",
      junit_url: null,
      log_url: null,
      github_artefakt: { durum: "hata", hata: "artefakt açılamadı" },
    };
    vi.stubGlobal("fetch", sahteCore({ [`/runs/${RID}`]: kosu }));
    uygulama(`/kosular/${RID}`);
    const kart = await screen.findByRole("region", { name: "Raporlar ve bağlantılar" });
    expect(within(kart).getByRole("link", { name: /Playwright HTML raporu \(GitHub\)/ })).toHaveAttribute("href", kosu.rapor_url);
    expect(kart).toHaveTextContent("JUnit XML (GitHub artefaktında)");
    expect(kart).toHaveTextContent("Raporlar portala alınamadı (artefakt açılamadı); bağlantılar GitHub'daki artefakta gider.");
  });

  it("süzgeç adres çubuğuna yazılır; satır açılınca adımlar, stack, ekler ve çıktı görünür", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    vi.stubGlobal("fetch", sahteCore({ [`/runs/${RID}`]: KOSU }));
    const u = userEvent.setup();
    uygulama(`/kosular/${RID}`);
    const tablo = await screen.findByRole("region", { name: "Test sonuçları tablosu" });
    expect(within(tablo).getAllByRole("row")).toHaveLength(3);
    await u.click(screen.getByRole("button", { name: "Başarısız (1)" }));
    expect(screen.getByTestId("konum")).toHaveTextContent("t_durum=failed");
    expect(within(screen.getByRole("region", { name: "Test sonuçları tablosu" })).getAllByRole("row")).toHaveLength(2);
    await u.click(screen.getByRole("button", { name: /Sepet › sepete ekler/ }));
    const ayrinti = screen.getByRole("region", { name: "Test ayrıntısı: Sepet › sepete ekler" });
    expect(within(ayrinti).getByText("Deneme 2")).toBeInTheDocument();
    expect(within(ayrinti).getByText(/at cart\.spec\.ts:9:5/)).toBeInTheDocument();
    const adimlar = within(ayrinti).getByRole("region", { name: "Adımlar (deneme 2)" });
    const hatali = adimlar.querySelectorAll("[data-hatali='1']");
    expect([...hatali].map((x) => x.querySelector("span span:nth-child(2)")?.textContent)).toEqual(["Ürün ekle"]);
    expect(within(ayrinti).getByRole("img", { name: "Ekran görüntüsü: screenshot" })).toHaveAttribute("src", KOSU.sonuclar[0].ekler![0].url);
    expect(within(ayrinti).getByLabelText("Video: video")).toHaveAttribute("src", KOSU.sonuclar[0].ekler![2].url);
    expect(within(ayrinti).getByRole("link", { name: /Playwright trace'i indir/ })).toHaveAttribute("href", KOSU.sonuclar[0].ekler![1].url);
    expect(within(ayrinti).getByText("merhaba")).toBeInTheDocument();
    await u.type(screen.getByRole("searchbox", { name: "Ara" }), "yok-boyle");
    expect(screen.getByText("Süzgece uyan test yok.")).toBeInTheDocument();
  });

  it("GitHub iş sonuçları Türkçe; Sauce durumu koşu başlığında; satır kapalıyken aria-controls yok", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    vi.stubGlobal("fetch", sahteCore({ [`/runs/${RID}`]: { ...KOSU, sauce_durum: "error", sauce_neden: "oturum sınırı dolu" } }));
    const u = userEvent.setup();
    uygulama(`/kosular/${RID}`);
    const ci = await screen.findByRole("region", { name: "CI adımları" });
    expect(within(ci).getByText("geçti")).toBeInTheDocument();
    expect(within(ci).getByText("kaldı")).toBeInTheDocument();
    expect(within(ci).queryByText("success")).not.toBeInTheDocument();
    expect(screen.getByText("Sauce koşmadı: oturum sınırı dolu")).toBeInTheDocument();
    const dugme = screen.getByRole("button", { name: /Sepet › sepete ekler/ });
    expect(dugme).not.toHaveAttribute("aria-controls");
    await u.click(dugme);
    expect(dugme).toHaveAttribute("aria-controls", "test-ayrinti-r1");
  });

  it("Sauce çipi: sonuçlar Türkçe; sıradaki GitHub koşusunda sırada; Sauce'suz yerel koşuda yok", async () => {
    const { SauceCipi } = await import("./Kosular");
    const temel = { kaynak: "github" as const, durum: "passed" as const, sauce_neden: "SAUCE_TETIKLER" };
    const metin = (k: Parameters<typeof SauceCipi>[0]["k"]) => render(<>{SauceCipi({ k })}</>).container.textContent;
    expect(metin({ ...temel, sauce_durum: "passed" })).toBe("Sauce: geçti");
    expect(metin({ ...temel, sauce_durum: "failed" })).toBe("Sauce: kırmızı");
    expect(metin({ ...temel, sauce_durum: "atlandi" })).toBe("Sauce atlandı: SAUCE_TETIKLER");
    expect(metin({ ...temel, durum: "queued", sauce_durum: null })).toBe("Sauce: sırada/sürüyor");
    expect(metin({ ...temel, sauce_durum: null })).toBe("");
    expect(metin({ ...temel, kaynak: "local", durum: "running", sauce_durum: null })).toBe("");
  });

  it("Koşular: iki tetik düğmesinin açıklaması görünür ve düğmeye aria-describedby ile bağlı", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    // Koşular listesi yalnız mühendis / sunucuya açıktır (OTOMASYON_ROLLERI).
    vi.stubGlobal("fetch", sahteCore({ "/runs": [] }, "engineer"));
    uygulama("/kosular");
    const gece = await screen.findByRole("button", { name: "Gece koşusunu şimdi başlat" });
    expect(gece).toHaveAccessibleDescription(/zamanlanmış koşuyu şimdi başlatır: aynı onaylı test paketi/);
    expect(screen.getByRole("button", { name: "Deploy sonrası testleri koş" })).toHaveAccessibleDescription(/uygulamayı hiçbir yere yüklemez/);
    expect(screen.queryByText(/tam regresyon/)).not.toBeInTheDocument();
  });

  it("GitHub yedeğinde Allure GitHub artefaktı diye etiketlenir; eksik dosyalar CI koşusuna bağlanır", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    const kosu = {
      ...KOSU,
      allure_url: "https://github.com/acme/demo-app/actions/runs/700#artifacts",
      allure_sonuclari_url: null,
      junit_url: null,
      log_url: null,
      github_artefakt: { durum: "budandi", hata: null },
    };
    vi.stubGlobal("fetch", sahteCore({ [`/runs/${RID}`]: kosu }));
    uygulama(`/kosular/${RID}`);
    const kart = await screen.findByRole("region", { name: "Raporlar ve bağlantılar" });
    expect(within(kart).getByRole("link", { name: /Allure raporu \(GitHub artefaktı\)/ })).toHaveAttribute("href", kosu.allure_url);
    expect(within(kart).getByRole("link", { name: /JUnit XML \(GitHub artefaktında\)/ })).toHaveAttribute("href", KOSU.ci_url);
    expect(within(kart).getByRole("link", { name: /Koşu günlüğü \(GitHub artefaktında\)/ })).toHaveAttribute("href", KOSU.ci_url);
  });

  it("Extent raporu: Java koşusunda Allure'un yanında bağlantı; rapor yoksa (web, eski koşu) satır yok", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    const extent = `/api/artifacts/runs/${RID}/src/e2e-app/target/extent-report/index.html`;
    const allure = `/api/artifacts/runs/${RID}/src/e2e-app/target/allure-report/index.html`;
    const java = { ...KOSU, kaynak: "local", ci_url: null, platform: "android", allure_url: allure, allure_rapor: true, extent_url: extent };
    vi.stubGlobal("fetch", sahteCore({ [`/runs/${RID}`]: java }));
    const { unmount } = uygulama(`/kosular/${RID}`);
    let kart = await screen.findByRole("region", { name: "Raporlar ve bağlantılar" });
    expect(within(kart).getByRole("link", { name: /Extent raporu/ })).toHaveAttribute("href", extent);
    expect(within(kart).getByRole("link", { name: /Allure raporu/ })).toHaveAttribute("href", allure);
    unmount();

    // Web koşusu / eski core yanıtı: alan null ya da hiç yok → ne bağlantı ne "yok" metni.
    for (const kosu of [{ ...KOSU, extent_url: null }, KOSU]) {
      vi.stubGlobal("fetch", sahteCore({ [`/runs/${RID}`]: kosu }));
      const r = uygulama(`/kosular/${RID}`);
      kart = await screen.findByRole("region", { name: "Raporlar ve bağlantılar" });
      expect(within(kart).getByRole("link", { name: /Allure ham sonuçları/ })).toBeInTheDocument();
      expect(within(kart).queryByText(/Extent/)).not.toBeInTheDocument();
      r.unmount();
    }
    expect(kosuDetayUyarla({ ...KOSU, extent_url: "/artifacts/runs/x/src/e2e-app/target/extent-report/index.html" }).extent_url).toBe(
      "/api/artifacts/runs/x/src/e2e-app/target/extent-report/index.html",
    );
    expect(kosuDetayUyarla({ ...KOSU, extent_url: "javascript:alert(1)" }).extent_url).toBeNull();
    expect(kosuDetayUyarla(KOSU).extent_url).toBeNull();
  });

  it("CI adımları: atlanan adımın gerekçesi soluk, kalan adımın hatası kırmızı", () => {
    const k = kosuDetayUyarla({
      ...KOSU,
      github: null,
      adimlar: {
        tsc: { ok: false, atlandi: false, error: "2 tip hatası" },
        eslint: { ok: false, atlandi: true, reason: "deps kurulamadı" },
      },
    });
    render(<CiAdimlari k={k} />);
    const liste = screen.getByRole("list", { name: "Yerel CI adımları" });
    expect(within(liste).getByText("2 tip hatası")).toHaveClass("hata-metin");
    const gerekce = within(liste).getByText("deps kurulamadı");
    expect(gerekce).toHaveClass("soluk");
    expect(gerekce).not.toHaveClass("hata-metin");
  });

  it("ayrıntı: denemesi olmayan (JUnit) test hata mesajını gösterir", () => {
    const s = kosuDetayUyarla({ ...KOSU, sonuclar: [{ id: "x", test_adi: "a", durum: "failed", hata_mesaji: "junit hatası" }] }).sonuclar[0];
    render(<TestAyrintisi s={s} />);
    expect(screen.getByText("junit hatası")).toBeInTheDocument();
  });
});
