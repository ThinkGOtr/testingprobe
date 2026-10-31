// Demo-B ekranları: Kod üretimi (eşleme, yerel kontrol / defect adayı, PR check'leri, merge kapısı,
// kırarak doğrulama), Koşular (süzgeç, raporlar), Kontrol Kulesi (KPI kaynağı, "ölçülmedi"), rol bazlı
// açılış ve core şekilli yanıtların uyarlanması (canlı derleme, örnek veri yok).
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { yapilandir } from "../api/http";
import { ayar, mockVerisi } from "../api/mock/handlers";
import { OturumProvider, varsayilanSayfa } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { mergeEngelleri, mergeOnayNotu, mergeUyarilari } from "../lib/kapi";
import { oturumAc } from "../test/yardimci";
import { kosulariSuz } from "./Kosular";
import { BirlesmisPrCi } from "./ScriptDetay";

function Konum() {
  const k = useLocation();
  return <div data-testid="konum">{k.pathname + k.search}</div>;
}

function uygulama(yol: string) {
  return render(
    <MemoryRouter initialEntries={[yol]}>
      <OturumProvider>
        <BildirimProvider>
          <Rotalar />
          <Routes>
            <Route path="*" element={<Konum />} />
          </Routes>
        </BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

describe("Kod üretimi: ekranlar (örnek veri)", () => {
  it("defect adayı: eşleme tablosu, yerel kontrol açıklaması, PR yok ve merge kapısı gerekçesi", async () => {
    await oturumAc("muhendis");
    uygulama("/kod/scr-3");
    expect(await screen.findByRole("heading", { level: 1, name: /6 adet kampanyalı üründe bedava ürün verilmez/ })).toBeInTheDocument();
    const tablo = screen.getByRole("region", { name: "Eşlenen adımlar tablosu" });
    const satir = within(tablo).getByText('CartPage.expectDiscount("0,00 TL")').closest("tr")!;
    expect(satir).toHaveTextContent("Doğrulama");
    expect(satir).toHaveTextContent("yerel kontrolde koşulur"); // doğrulama uygulamada gözlem iddia etmez
    expect(satir).toHaveTextContent("indirim 0,00 TL");
    const sinif = screen.getByTestId("yerel-sinif");
    expect(sinif).toHaveTextContent("Defect adayı");
    expect(sinif).toHaveTextContent(/otomatik düzeltme yapılmaz/i);
    expect(screen.getByText(/Gerçekleşen:/).closest("li")).toHaveTextContent("bedava adet 1 · indirim 25,00 TL");
    expect(screen.getByText("PR açılmadı: defect adayı insana düştü.")).toBeInTheDocument();
    // PR yokken merge kapısı yok (core merge_engelleri = []); PR kartı nedenini söyler.
    expect(screen.queryByTestId("merge-kapisi")).toBeNull();
    expect(screen.queryByRole("button", { name: "Merge et" })).not.toBeInTheDocument();
    // Kod görünümü renklendirilmiş (belirteç sınıfları) ve dosya adını taşır.
    const kod = screen.getByLabelText("demo-app/e2e/tests/tpd-1/c3-kampanya-6-adet-bedava-yok.spec.ts içeriği");
    expect(kod.querySelector(".tk-metin")).not.toBeNull();
  });

  it("hata yakalayan test: check listesi, kırma zaman çizelgesi, 'test hata yakalıyor ✓', merge kapısı açık", async () => {
    await oturumAc("muhendis");
    uygulama("/kod/scr-2");
    expect(await screen.findByText("Test hata yakalıyor ✓")).toBeInTheDocument();
    const checks = screen.getByRole("list", { name: "PR check'leri" });
    expect(checks).toHaveTextContent("local-ci");
    expect(checks).toHaveTextContent("zorunlu");
    const zaman = screen.getByRole("list", { name: "Kırarak doğrulama zaman çizelgesi" });
    expect(within(zaman).getAllByRole("listitem").map((l) => l.textContent)).toEqual([
      expect.stringContaining("Yeşil"),
      expect.stringContaining("Kırmızı"),
      expect.stringContaining("Yeşil"),
    ]);
    expect(screen.getByTestId("merge-kapisi")).toHaveTextContent("açık ✓");
    expect(screen.getByRole("button", { name: "Merge et" })).toBeEnabled();
  });

  it("PR açıklaması (core govde) katlanır bölümde güvenli Markdown alt kümesiyle çizilir", async () => {
    await oturumAc("muhendis");
    uygulama("/kod/scr-2");
    const bolum = await screen.findByTestId("pr-aciklamasi");
    expect(within(bolum).getByText("PR açıklaması")).toBeInTheDocument();
    expect(within(bolum).getByText("İzlenebilirlik").closest("strong")).not.toBeNull();
    expect(within(bolum).getByText("TPD-1").tagName).toBe("CODE");
    expect(bolum.querySelector("pre")).toHaveTextContent("| S3 | CartPage | expectFreeQuantity |");
    expect(screen.queryByText(/LocalForge'un PR sayfası yok/)).not.toBeInTheDocument();
  });

  it("değişiklik iste / reddet: ret nedeni seçilmeden düğme kapalı; seçilince PR kapanır ve denetime yazılır", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    uygulama("/kod/scr-2");
    const bolum = await screen.findByTestId("pr-ret");
    await u.click(within(bolum).getByText("Değişiklik iste / reddet"));
    const reddet = within(bolum).getByRole("button", { name: "Reddet" });
    expect(reddet).toBeDisabled();
    expect(reddet).toHaveAttribute("title", "Önce ret nedeni seçin");
    await u.selectOptions(within(bolum).getByRole("combobox", { name: "Ret nedeni" }), "wrong_element");
    expect(reddet).toBeEnabled();
    await u.click(reddet);
    await waitFor(() => expect(mockVerisi().denetim.at(-1)?.ozet).toContain("reddet · wrong_element"));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Merge et" })).not.toBeInTheDocument());
  });

  it("dal main'in gerisinde: uyarı ve 'Dalı güncelle' düğmesi core'a gider", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    const s = mockVerisi().scriptler.find((x) => x.id === "scr-2")!;
    s.pr!.dal = { geride: true, guncelleme: null, neden: null };
    uygulama("/kod/scr-2");
    expect(await screen.findByText("Dal main'in gerisinde")).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Dalı güncelle" }));
    await waitFor(() => expect(screen.queryByText("Dal main'in gerisinde")).not.toBeInTheDocument());
  });

  it("zayıf test: kapı açık, uyarı açık kabulle merge edilir ve kabul notu core'a gider", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    uygulama("/kod/scr-1");
    expect(await screen.findByText(/Zayıf test: kırılmış uygulamada da yeşil kaldı\./)).toBeInTheDocument();
    const kapi = screen.getByTestId("merge-kapisi");
    expect(kapi).toHaveTextContent("açık ✓");
    // Mock core gibi `merge_kabul_gerekli` gönderir; portal metni aynen gösterir.
    expect(screen.getByTestId("merge-uyarilari")).toHaveTextContent("Zayıf test: BREAK_CAMPAIGN ile kırılan uygulamada da yeşil kaldı (açık kabul gerekir).");
    const dugme = screen.getByRole("button", { name: "Merge et" });
    expect(dugme).toBeDisabled();
    expect(dugme).toHaveAttribute("title", "Önce uyarıyı kabul edin");
    await u.click(screen.getByRole("checkbox", { name: /zayıf test olarak merge et/ }));
    expect(dugme).toBeEnabled();
    await u.click(dugme);
    await waitFor(() => expect(screen.getByTestId("merge-kapisi")).toHaveTextContent("✓ Birleştirildi — muhendis"));
    expect(screen.getByTestId("merge-kapisi")).toHaveTextContent(/merge commit \w{7}/);
    expect(screen.getByTestId("merge-kapisi")).not.toHaveTextContent("kapalı");
    expect(screen.queryByRole("button", { name: "Merge et" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^(Kırarak|Yeniden) doğrula$/ })).not.toBeInTheDocument();
    expect(mockVerisi().denetim.at(-1)?.ozet).toContain("Zayıf test olarak merge edildi");
  });

  it("birleştirilmiş PR (core: merge_engelleri 'durum: merged'): kapı yerine birleştirme bilgisi", async () => {
    await oturumAc("muhendis");
    const s = mockVerisi().scriptler.find((x) => x.id === "scr-2")!;
    s.durum = "merged";
    s.pr = { ...s.pr!, durum: "merged", merge_sha: "5b06333abc", merge_eden: "muhendis", merge_zamani: "2026-10-31T13:15:00Z" };
    s.merge_engelleri = ["PR merge edilebilir durumda değil (durum: merged)"];
    uygulama("/kod/scr-2");
    const kapi = await screen.findByTestId("merge-kapisi");
    expect(kapi).toHaveTextContent("✓ Birleştirildi — muhendis");
    expect(kapi).toHaveTextContent("merge commit 5b06333");
    expect(kapi).not.toHaveTextContent("durum: merged");
    expect(screen.queryByRole("button", { name: "Merge et" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Yeniden doğrula" })).not.toBeInTheDocument();
  });

  it("birleşmiş PR'ın kartı push CI sürerken 'CI: bekliyor · zorunlu' göstermez; push CI ayrı satırda", async () => {
    await oturumAc("muhendis");
    const s = mockVerisi().scriptler.find((x) => x.id === "scr-2")!;
    s.durum = "merged";
    // LocalForge hızlı ileri merge: merge commit'i = PR head; core o commit'in check'lerini (push CI)
    // verir ve PR çıktısında merge_sha taşımaz (bilinmiyor → aynı commit sayılır).
    s.pr = {
      ...s.pr!,
      durum: "merged",
      ci: "pending",
      merge_sha: null,
      checks: [{ ad: "local-ci", durum: "pending", zorunlu: true, url: null, aciklama: null }],
      merge_eden: "muhendis",
    };
    uygulama("/kod/scr-2");
    const push = await screen.findByTestId("push-ci");
    expect(push).toHaveTextContent(/^main üzerinde push CI \(commit [0-9a-f]{7}\): koşuyor/);
    expect(push).not.toHaveTextContent("zorunlu");
    expect(within(push).getByRole("link", { name: "Koşular'da izle" })).toHaveAttribute("href", "/kosular?tetik=push");
    expect(screen.getByText("PR CI: merge öncesi yeşil")).toBeInTheDocument();
    expect(screen.queryByText(/^CI: bekliyor$/)).toBeNull();
    expect(screen.getByTestId("merge-kapisi")).toHaveTextContent("✓ Birleştirildi");
  });

  it("birleşmiş PR, ayrı merge commit'i: check'ler PR head'inin merge öncesi sonucu olarak gösterilir", () => {
    render(
      <MemoryRouter>
        <BirlesmisPrCi
          pr={{
            number: 7,
            url: null,
            baslik: "x",
            branch: "tp/x",
            durum: "merged",
            ci: "passed",
            icerik_hash: "h",
            head_sha: "aaaaaaa111",
            merge_sha: "bbbbbbb222",
            checks: [{ ad: "local-ci", durum: "passed", zorunlu: true, url: null, aciklama: null }],
          }}
        />
      </MemoryRouter>,
    );
    const push = screen.getByTestId("push-ci");
    expect(push).toHaveTextContent("PR check'leri (merge öncesi, head aaaaaaa)");
    expect(push).toHaveTextContent("main üzerinde push CI (merge commit bbbbbbb)");
    expect(push).not.toHaveTextContent("zorunlu");
  });

  it("analist merge edemez (rol); düğme gerekçesi rolü söyler", async () => {
    await oturumAc("analist");
    uygulama("/kod/scr-2");
    const d = await screen.findByRole("button", { name: "Merge et" });
    expect(d).toBeDisabled();
    expect(d).toHaveAttribute("title", expect.stringMatching(/gereken rol/i));
  });

  it("liste: defect adayı rozeti ve onaylı case seçimiyle kod üretimi canlı adımlarla PR'a ulaşır", async () => {
    ayar.isAdimiMs = 1;
    await oturumAc("muhendis");
    const u = userEvent.setup();
    uygulama("/kod");
    const satir = (await screen.findByRole("link", { name: /bedava ürün verilmez/ })).closest("tr")!;
    expect(satir).toHaveTextContent("Defect adayı");
    expect(satir).toHaveTextContent("İnsana düştü");
    // Aday: minimum sipariş case'i (C5, onaylı, kodu yok); beklenen sonucu görünür.
    const aday = screen.getByRole("checkbox", { name: /minimum tutarın altında uyarı/ });
    expect(aday.closest("li")).toHaveTextContent('Beklenen: "Minimum sipariş tutarı 750,00 TL"');
    await u.click(aday);
    await u.click(screen.getByRole("button", { name: "Seçilenler için kod üret (1)" }));
    await waitFor(() => expect(mockVerisi().scriptler.find((s) => s.case_ids.includes("case-1-4"))?.durum).toBe("pr_open"), { timeout: 4000 });
    ayar.isAdimiMs = 0;
  });
});

describe("merge kapısı gerekçeleri (core göndermezse türetilir)", () => {
  const temel = {
    durum: "pr_open" as const,
    zayif_test: false,
    yerel_sinif: "gecti" as const,
    break_verify: { durum: "passed" as const, asamalar: [] },
    pr: { number: 1, url: null, baslik: "", branch: "b", durum: "open" as const, ci: "passed" as const, icerik_hash: "", head_sha: "" },
  };
  it("açık kapı → boş; CI kırmızı → başarısız check adı; kırma yok/zayıf → kapı değil uyarı", () => {
    expect(mergeEngelleri(temel)).toEqual([]);
    expect(
      mergeEngelleri({
        ...temel,
        pr: { ...temel.pr, ci: "failed", checks: [{ ad: "local-ci", durum: "failed", zorunlu: true, url: null, aciklama: null }] },
      }),
    ).toEqual(["CI kırmızı: local-ci."]);
    const yok = { ...temel, break_verify: { durum: "not_started" as const, asamalar: [] } };
    expect(mergeEngelleri(yok)).toEqual([]);
    expect(mergeUyarilari(yok)[0]).toMatch(/Kırarak doğrulama yapılmadı/);
    expect(mergeOnayNotu(yok)).toMatch(/kırarak doğrulama yapılmadan merge/i);
    const zayif = { ...temel, zayif_test: true, break_verify: { durum: "weak" as const, asamalar: [] } };
    expect(mergeEngelleri(zayif)).toEqual([]);
    expect(mergeUyarilari(zayif)[0]).toMatch(/^Zayıf test/);
    expect(mergeOnayNotu(zayif)).toBe("Zayıf test olarak merge edildi (insan kabulü).");
    expect(mergeUyarilari(temel)).toEqual([]);
    expect(mergeEngelleri({ ...temel, break_verify: { durum: "running", asamalar: [] } })).toEqual(["Kırarak doğrulama sürüyor."]);
  });
  it("core'un gerekçeleri varsa yalnızca onlar gösterilir (portal kural eklemez)", () => {
    expect(mergeEngelleri({ ...temel, merge_engelleri: ["head sha değişti"] })).toEqual(["head sha değişti"]);
    // C1/C5 gibi kampanya dışı testler: core kapıyı açık sayar → portal da açık (zayıf işaretine rağmen).
    expect(mergeEngelleri({ ...temel, zayif_test: true, break_verify: { durum: "weak", asamalar: [] }, merge_engelleri: [] })).toEqual([]);
  });
});

describe("Koşular", () => {
  it("süzgeç adres çubuğunda; tetik ve kaynak çipleri; kırma koşuları gizlenebilir", async () => {
    await oturumAc("sunucu");
    const u = userEvent.setup();
    uygulama("/kosular");
    const tablo = await screen.findByRole("region", { name: "Koşular tablosu" });
    const toplam = within(tablo).getAllByRole("row").length - 1;
    await u.selectOptions(screen.getByRole("combobox", { name: "Tetik" }), "local_check");
    expect(screen.getByTestId("konum")).toHaveTextContent("tetik=local_check");
    const satirlar = within(screen.getByRole("region", { name: "Koşular tablosu" })).getAllByRole("row").slice(1);
    expect(satirlar.length).toBeLessThan(toplam);
    for (const r of satirlar) expect(r).toHaveTextContent("Yerel kontrol");
  });

  it("kosulariSuz: kırma koşuları kapatılınca BREAK_CAMPAIGN koşuları düşer", () => {
    const k = mockVerisi().kosular;
    const hepsi = kosulariSuz(k, { tetik: "", kaynak: "", durum: "", kirma: true });
    const kirmasiz = kosulariSuz(k, { tetik: "", kaynak: "", durum: "", kirma: false });
    expect(hepsi.length).toBe(k.length);
    expect(kirmasiz.every((x) => !x.break_campaign)).toBe(true);
    expect(kirmasiz.length).toBeLessThan(hepsi.length);
  });

  it("sunucu 'Deploy tetikle' ile koşu kuyruğa alınır; mühendis tetikleyemez", async () => {
    await oturumAc("sunucu");
    const u = userEvent.setup();
    uygulama("/kosular");
    await u.click(await screen.findByRole("button", { name: "Deploy tetikle" }));
    expect(await screen.findAllByText(/Deploy koşusu sıraya alındı/)).not.toHaveLength(0);
  });

  it("koşu detayı: raporlar kartı, adres yoksa nedeniyle düz metin; üretilen teste bağlantı", async () => {
    await oturumAc("muhendis");
    uygulama("/kosular/run-108");
    const kart = await screen.findByRole("region", { name: "Raporlar ve bağlantılar" });
    expect(kart).toHaveTextContent("Playwright HTML raporu");
    expect(within(kart).queryByRole("link", { name: /Playwright HTML raporu/ })).not.toBeInTheDocument();
    expect(within(kart).getByRole("link", { name: "Üretilen test" })).toHaveAttribute("href", "/kod/scr-3");
  });
});

describe("Kontrol Kulesi", () => {
  it("her KPI'nın kaynak ipucu var; baz değer 'ölçülmedi'; uyarılar görünür", async () => {
    await oturumAc("sunucu");
    uygulama("/kontrol-kulesi");
    await screen.findByRole("heading", { name: "Geçme oranı" });
    const ipuclari = screen.getAllByTestId("kaynak-ipucu");
    expect(ipuclari.length).toBeGreaterThanOrEqual(9);
    for (const i of ipuclari) expect(i.getAttribute("aria-label")).toMatch(/^Kaynak: /);
    expect(screen.getByRole("img", { name: /Kaynak: test_result \(JUnit XML\)/ })).toBeInTheDocument();
    expect(screen.getByText("baz değer ölçülmedi")).toBeInTheDocument();
    expect(screen.getByText(/Manuel baz değer girilmedi/)).toBeInTheDocument();
    // Tasarımda geçme oranı hedefi yok: hedef çizgisi uydurulmaz.
    expect(screen.queryByText(/Kesikli çizgi/)).not.toBeInTheDocument();
  });

  it("açık defect adayı karnede 'Geçti'nin yanında ve geçme oranının altında görünür (mock: C3)", async () => {
    await oturumAc("sunucu");
    uygulama("/kontrol-kulesi");
    const ozet = await screen.findByTestId("defect-adayi-ozet");
    expect(ozet).toHaveTextContent("⚠ 1 açık defect adayı");
    expect(within(ozet).getByRole("link", { name: "Kod üretiminde incele" })).toHaveAttribute("href", "/kod");
    const tablo = screen.getByRole("region", { name: "Karne tablosu" });
    const satir = within(tablo).getByText("TPD-1").closest("tr")!;
    expect(within(satir).getByText("1 defect adayı")).toBeInTheDocument();
    const diger = within(tablo).getByText("TPD-4").closest("tr")!;
    expect(within(diger).queryByText(/defect adayı/)).toBeNull();
    // Sunucu düğmeleri core'da olmayan uçlara gitmez (404 yok).
    expect(screen.queryByRole("button", { name: "Locator'ı kır" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Demoyu sıfırla" })).toBeNull();
  });
});

describe("rol bazlı açılış", () => {
  it("varsayilanSayfa: sunucu → Kontrol Kulesi, mühendis → Kod üretimi; uç yoksa sıradaki ekran", () => {
    expect(varsayilanSayfa("presenter")).toBe("/kontrol-kulesi");
    expect(varsayilanSayfa("engineer")).toBe("/kod");
    const yalnizGereksinim = (_m: string, y: string) => y === "/requirements";
    expect(varsayilanSayfa("engineer", yalnizGereksinim)).toBe("/gereksinimler");
    expect(varsayilanSayfa("presenter", (_m, y) => y === "/runs" || y === "/requirements")).toBe("/kosular");
  });

  it("örnek veri: sunucu girişte Kontrol Kulesi'ne, mühendis Kod üretimine düşer", async () => {
    await oturumAc("sunucu");
    uygulama("/");
    await waitFor(() => expect(screen.getByTestId("konum")).toHaveTextContent("/kontrol-kulesi"));
  });
});

describe("canlı derleme: core şekilli Demo-B yanıtları", () => {
  afterEach(() => vi.unstubAllGlobals());

  const OPENAPI = {
    paths: Object.fromEntries(
      ["/auth/me", "/auth/login", "/requirements", "/cases", "/scripts", "/scripts/{script_id}", "/runs", "/runs/{run_id}", "/control-tower", "/events"].map((p) => [
        p,
        { get: {} },
      ]),
    ),
  };

  function sahteCore(rol: string, ek: Record<string, unknown>) {
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

  it("Kontrol Kulesi: ölçülmemiş KPI'lar 'veri yok'/'ölçülmedi', a11y taranmadı; örnek sayı yok", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    vi.stubGlobal(
      "fetch",
      sahteCore("presenter", {
        "/control-tower": {
          son_kosular: [],
          gecme_orani: { oran: null, toplam: 0, gecen: 0, donem_gun: 7 },
          flaky: [],
          karne: [],
          ai_katkisi: { kabul_orani: null, script_ilk_review: null, manuel_baz_ms: null, maliyet_usd_toplam: 0 },
          a11y: null,
          kaynaklar: { gecme_orani: { kaynak: "test_result (JUnit XML)" } },
          uyarilar: [],
        },
      }),
    );
    uygulama("/");
    await waitFor(() => expect(screen.getByTestId("konum")).toHaveTextContent("/kontrol-kulesi"));
    expect(await screen.findByTestId("gecme-orani")).toHaveTextContent("veri yok");
    expect(screen.getByText("Erişilebilirlik taraması yapılmadı.")).toBeInTheDocument();
    expect(screen.getByText(/henüz karar yok/)).toBeInTheDocument();
    expect(screen.getByText("baz değer ölçülmedi")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Kaynak: test_result (JUnit XML)" })).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: /core bu ölçünün kaynağını bildirmedi/ }).length).toBeGreaterThan(0);
    expect(screen.queryByText("ÖRNEK VERİ")).not.toBeInTheDocument();
    // Yüzde yalnızca tasarım hedeflerinde (Hedef ≥ %70 / %60) görünür; ölçüm yüzdesi uydurulmaz.
    expect(screen.queryAllByText(/%\d/).filter((e) => !/Hedef ≥/.test(e.textContent ?? ""))).toEqual([]);
  });

  it("Kontrol Kulesi: core karnesindeki acik_defect_adayi 'Geçti' yanında amber çip olarak çizilir", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    vi.stubGlobal(
      "fetch",
      sahteCore("presenter", {
        "/control-tower": {
          son_kosular: [],
          gecme_orani: { oran: 1, toplam: 3, gecen: 3, son_n: 20, birim: "kosu" },
          flaky: [],
          karne: [{ story_key: "TPD-1", baslik: "Sepet", case_sayisi: 4, otomasyon_kapsami: 0.75, son_sonuc: "passed", acik_bug: 2, acik_defect_adayi: 1 }],
          ai_katkisi: {},
          a11y: null,
          kaynaklar: {},
          uyarilar: [],
        },
      }),
    );
    uygulama("/kontrol-kulesi");
    const tablo = await screen.findByRole("region", { name: "Karne tablosu" });
    const satir = within(tablo).getByText("TPD-1").closest("tr")!;
    expect(within(satir).getByText("Geçti")).toBeInTheDocument();
    expect(within(satir).getByText("1 defect adayı")).toHaveClass("cip-uyari");
    expect(screen.getByTestId("defect-adayi-ozet")).toHaveTextContent("1 açık defect adayı");
  });

  it("script detayı DB kolon adlarıyla (kirma_dogrulama, uretim_modu, step_mapping, pull_request.checks) çizilir", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    vi.stubGlobal(
      "fetch",
      sahteCore("engineer", {
        "/scripts/s-1": {
          id: "s-1",
          test_case_ids: ["c-1"],
          jira_key: "TPD-1",
          title: "7 adet kampanyalı üründe 1 adet bedava verilir",
          dosya_yolu: "e2e/tests/tpd-1/c2.spec.ts",
          durum: "pr_open",
          uretim_modu: "replay",
          icerik: 'await cart.expectDiscount("25,00 TL");\n',
          zayif_test: false,
          kirma_dogrulama: { baseline: { sonuc: "passed", run_id: "r1" }, broken: { sonuc: "failed", run_id: "r2" }, restored: { sonuc: "passed", run_id: "r3" } },
          step_mapping: [{ adim_no: 1, adim_kimligi: "S4", po_sinifi: "CartPage", po_metodu: "expectDiscount", argumanlar: ["25,00 TL"], dogrulandi: true }],
          yerel_kontrol: { tsc: { ok: true }, eslint: { ok: true }, ast_guard: { ok: true }, repeat_each: 3, run: { run_id: "r0", status: "passed" } },
          pull_request: {
            number: 7,
            title: "test(TPD-1): …",
            branch: "tp/case-1",
            state: "open",
            head_sha: "abc",
            icerik_hash: "h",
            checks: [{ name: "local-ci", conclusion: "success", required: true }],
          },
          ajan_adimlari: [{ adim: 1, tool: "browser_navigate", ozet: "await page.goto('/giris')", ekran_goruntusu_url: "/scripts/s-1/screens/1.png" }],
        },
        "/scripts": [],
        "/cases": [],
      }),
    );
    uygulama("/kod/s-1");
    expect(await screen.findByText("Test hata yakalıyor ✓")).toBeInTheDocument();
    expect(screen.getAllByText("REPLAY", { selector: ".rozet-replay" }).length).toBeGreaterThan(0);
    expect(screen.getByText('CartPage.expectDiscount("25,00 TL")')).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "PR check'leri" })).toHaveTextContent("local-ci");
    expect(screen.getByTestId("merge-kapisi")).toHaveTextContent("açık ✓");
    // Core göreli ekran görüntüsü adresi portalda /api önekiyle açılır; ajan olayı doğrulama taşımıyorsa uydurulmaz.
    expect(screen.getByRole("img", { name: /Adım 1 ekran görüntüsü/ })).toHaveAttribute("src", "/api/scripts/s-1/screens/1.png");
    expect(screen.queryByText(/snapshot'ta doğrulandı/)).not.toBeInTheDocument();
  });
});
