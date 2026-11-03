// Faz 3 portal düzeltmeleri (canlı core şekilli yanıtlarla):
// - merge kapısı: core `merge_engelleri` tek kaynak; zayıf test / kırma yok → açık kabul isteyen uyarı
// - kırarak doğrulama: assertion dışı kırmızı "beklendiği gibi" denmez; çift nokta yok
// - koşu bağlantıları: toolchain etiketleri (cg-…) /kosular/:id'ye bağlanmaz (422)
// - eşleme: parametresiz doğrulama, değerin case cümlesinde vurgulanması
// - defect adayı: tekrarlanan hata gruplanır, banner iş diliyle, ajanın sepet görüntüsü
// - Koşular: kısa koşu adı, JUnit/Allure bağlantıları, kırma süzgeci yalnızca kırma koşusu varsa
// - Kod üretimi: kapatılanlar gizli, "Yeniden üret"
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { yapilandir } from "../api/http";
import { kosuUyarla } from "../api/uyumDemoB";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { kosuKimligiMi } from "../lib/kapi";
import { hatalariGrupla, nedenTemizle } from "./ScriptDetay";

const OPENAPI = {
  paths: Object.fromEntries(
    ["/auth/me", "/auth/login", "/cases", "/scripts", "/scripts/{script_id}", "/runs", "/runs/{run_id}", "/events", "/code/generate", "/prs/{number}/merge"].map(
      (p) => [p, { get: {}, post: {} }],
    ),
  ),
};

type Cagri = { url: string; method: string; govde: unknown };

function sahteCore(rol: string, ek: Record<string, unknown>, cagrilar: Cagri[] = []) {
  return vi.fn().mockImplementation((url: string, init?: RequestInit) => {
    const j = (status: number, govde: unknown) =>
      Promise.resolve(new Response(JSON.stringify(govde), { status, headers: { "Content-Type": "application/json" } }));
    const method = (init?.method ?? "GET").toUpperCase();
    if (url === "/api/openapi.json") return j(200, OPENAPI);
    if (url === "/api/auth/me") return j(200, { id: "u1", kullanici_adi: rol, rol });
    const yol = url.replace(/^\/api/, "").split("?")[0];
    if (method !== "GET") {
      cagrilar.push({ url: yol, method, govde: init?.body ? JSON.parse(String(init.body)) : null });
      const k = `${method} ${yol}`;
      if (k in ek) return j(200, ek[k]);
      return j(202, { job_id: "j1", durum: "queued", mesaj: "Kuyruğa alındı." });
    }
    if (yol in ek) return j(200, ek[yol]);
    return j(404, { detail: "Not Found" });
  });
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

const ASAMA = (ad: string, sonuc: string, run_id: string | null) => ({ ad, sonuc, run_id, zaman: "2026-10-31T12:00:00+00:00" });

/** core `views.detail` şekli (alan adları birebir). */
function coreScript(ek: Record<string, unknown> = {}) {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    case_ids: ["c-1"],
    requirement_id: "r-1",
    requirement_key: "TPD-1",
    case_ref: "TPD-1-C1",
    test_key: "TPD-1-T1",
    baslik: "Sepete ekleyince sepet adedi artar",
    dosya_yolu: "e2e/tests/generated/tpd-1-c1.spec.ts",
    branch: "tp/case-c1",
    durum: "pr_open",
    pr: {
      number: 3,
      url: null,
      baslik: "test(TPD-1): C1",
      branch: "tp/case-c1",
      durum: "open",
      ci: "passed",
      icerik_hash: "h1",
      head_sha: "abc1234",
      checks: [{ ad: "local-ci", durum: "passed", zorunlu: true, url: null, aciklama: null }],
      forge: "local",
    },
    pass_at_1: true,
    zayif_test: true,
    break_verify: {
      durum: "weak",
      asamalar: [ASAMA("baseline", "passed", "cg-a0d0d45b-local-check-515752"), ASAMA("broken", "passed", "cg-a0d0d45b-break-red-31f726"), ASAMA("restored", "passed", "cg-a0d0d45b-break-green-9a1b2c")],
      neden: "Uygulama kırıldığında test yeşil kaldı: zayıf test.",
    },
    yerel_sinif: "gecti",
    mode: "replay",
    engel: null,
    olusturma: "2026-10-31T11:00:00+00:00",
    hata: null,
    kod: "await cart.expectCartCount(\"1\");\n",
    adimlar: [],
    eslemeler: [
      { adim_no: 1, step_id: "S1", po: "CatalogPage", method: "addToCart", args: ["Portakal Gazozu"], beklenen: false, verified: true, kaynak_metin: null, kanit_ref: "snap-1" },
      { adim_no: 2, step_id: null, po: "CartPage", method: "expectCartCount", args: ["1"], beklenen: true, verified: true, kaynak_metin: "Sepet rozeti   1 adet gösterir", kanit_ref: null },
      { adim_no: 3, step_id: null, po: "CheckoutPage", method: "expectCheckoutEnabled", args: [], beklenen: true, verified: true, kaynak_metin: null, kanit_ref: null },
    ],
    yerel_kontrol: {
      tsc: true,
      eslint: true,
      ast_guard: true,
      tekrar: 3,
      sonuc: "passed",
      sinif: "gecti",
      aciklama: null,
      run_id: "cg-8908c645-local-check-515752",
      duzeltme_turu: 0,
      basarisiz: [],
      atlandi: false,
    },
    merge_engelleri: [],
    uyarilar: ["Eşleme REPLAY kaydından geldi (hazırlanmış örnek çıktı; canlı model değil)."],
    ...ek,
  };
}

const SID = "11111111-1111-4111-8111-111111111111";

describe("merge kapısı: core tek kaynak, zayıf test kabul isteyen uyarı", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("kampanya dışı test (C1, zayıf): core kapıyı açık sayar → kabul kutusuyla merge edilir, kabul notu gövdede", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    const cagrilar: Cagri[] = [];
    vi.stubGlobal("fetch", sahteCore("engineer", { [`/scripts/${SID}`]: coreScript(), "/scripts": [], "/cases": [] }, cagrilar));
    const u = userEvent.setup();
    uygulama(`/kod/${SID}`);
    const kapi = await screen.findByTestId("merge-kapisi");
    expect(kapi).toHaveTextContent("açık ✓");
    expect(kapi).not.toHaveTextContent("kapalı");
    const dugme = screen.getByRole("button", { name: "Merge et" });
    expect(dugme).toBeDisabled();
    await u.click(within(kapi).getByRole("checkbox", { name: /zayıf test olarak merge et/ }));
    expect(dugme).toBeEnabled();
    await u.click(dugme);
    await waitFor(() => expect(cagrilar.some((c) => c.url === "/prs/3/merge")).toBe(true));
    const merge = cagrilar.find((c) => c.url === "/prs/3/merge")!;
    expect(merge.govde).toEqual({ icerik_hash: "h1", head_sha: "abc1234", onay_notu: "Zayıf test olarak merge edildi (insan kabulü)." });
  });

  it("uyarısız (hata yakalayan) testte kabul kutusu yok ve not gönderilmez", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    const cagrilar: Cagri[] = [];
    const s = coreScript({
      zayif_test: false,
      break_verify: { durum: "passed", asamalar: [ASAMA("baseline", "passed", null), ASAMA("broken", "failed", null), ASAMA("restored", "passed", null)], neden: null },
    });
    vi.stubGlobal("fetch", sahteCore("engineer", { [`/scripts/${SID}`]: s, "/scripts": [], "/cases": [] }, cagrilar));
    const u = userEvent.setup();
    uygulama(`/kod/${SID}`);
    await screen.findByTestId("merge-kapisi");
    expect(screen.queryByTestId("merge-uyarilari")).not.toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Merge et" }));
    await waitFor(() => expect(cagrilar.some((c) => c.url === "/prs/3/merge")).toBe(true));
    expect(cagrilar.find((c) => c.url === "/prs/3/merge")!.govde).toEqual({ icerik_hash: "h1", head_sha: "abc1234" });
  });

  it("core engel gönderirse (check kırmızı) kabul kutusu gösterilmez, düğme kapalı kalır", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    vi.stubGlobal(
      "fetch",
      sahteCore("engineer", { [`/scripts/${SID}`]: coreScript({ merge_engelleri: ["Zorunlu kontrol 'local-ci': failed"] }), "/scripts": [], "/cases": [] }),
    );
    uygulama(`/kod/${SID}`);
    const kapi = await screen.findByTestId("merge-kapisi");
    expect(kapi).toHaveTextContent("kapalı");
    expect(kapi).toHaveTextContent("Zorunlu kontrol 'local-ci': failed");
    expect(screen.queryByTestId("merge-uyarilari")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Merge et" })).toBeDisabled();
  });
});

describe("kırarak doğrulama ve koşu bağlantıları", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("assertion dışı kırmızı (locator): 'beklendiği gibi' denmez, amber; neden tek noktayla biter; cg- etiketleri bağlantı değil", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    const s = coreScript({
      zayif_test: false,
      break_verify: {
        durum: "failed",
        asamalar: [ASAMA("baseline", "passed", "cg-a0d0d45b-local-check-515752"), ASAMA("broken", "failed", "cg-a0d0d45b-break-red-31f726"), ASAMA("restored", "passed", "cg-a0d0d45b-break-green-1")],
        neden: "Kırık koşu assertion dışında bir nedenle kırmızı (locator); hata yakalama kanıtı sayılmaz.",
      },
    });
    vi.stubGlobal("fetch", sahteCore("engineer", { [`/scripts/${SID}`]: s, "/scripts": [], "/cases": [] }));
    const { container } = uygulama(`/kod/${SID}`);
    const zaman = await screen.findByRole("list", { name: "Kırarak doğrulama zaman çizelgesi" });
    const [, kirik] = within(zaman).getAllByRole("listitem");
    expect(kirik).not.toHaveTextContent("beklendiği gibi");
    expect(kirik).toHaveTextContent("Kırmızı ama assertion dışı (locator / eşleme hatası) — kanıt sayılmaz");
    expect(kirik).toHaveClass("kirma-sonucsuz");
    expect(kirik).toHaveTextContent("cg-a0d0d45b-break-red-31f726");
    const neden = screen.getByText(/Kırık koşu assertion dışında/);
    expect(neden.textContent).toContain("Doğrulama tamamlanamadı: Kırık koşu assertion dışında bir nedenle kırmızı (locator); hata yakalama kanıtı sayılmaz. Koşu");
    expect(neden.textContent).not.toContain("..");
    // Sayfadaki her koşu bağlantısı açılabilir bir koşuya gider (UUID); cg- etiketleri düz metin.
    const kosuBaglantilari = [...container.querySelectorAll<HTMLAnchorElement>("a[href^='/kosular/']")];
    for (const a of kosuBaglantilari) expect(kosuKimligiMi(decodeURIComponent(a.getAttribute("href")!.slice("/kosular/".length)))).toBe(true);
    expect(container.querySelector("a[href*='cg-']")).toBeNull();
    expect(screen.getByText("cg-8908c645-local-check-515752")).toHaveAttribute("title", expect.stringMatching(/Toolchain koşu etiketi/));
  });

  it("zayıf test: kırık uygulamada yeşil — 'beklenmeyen sonuç' yeşil tik değil uyarı simgesiyle", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    const s = coreScript({
      zayif_test: true,
      break_verify: {
        durum: "weak",
        asamalar: [ASAMA("baseline", "passed", "cg-1-local"), ASAMA("broken", "passed", "cg-1-red"), ASAMA("restored", "passed", "cg-1-green")],
      },
    });
    vi.stubGlobal("fetch", sahteCore("engineer", { [`/scripts/${SID}`]: s, "/scripts": [], "/cases": [] }));
    uygulama(`/kod/${SID}`);
    const zaman = await screen.findByRole("list", { name: "Kırarak doğrulama zaman çizelgesi" });
    const [ilk, kirik] = within(zaman).getAllByRole("listitem");
    expect(kirik).toHaveTextContent("beklenmeyen sonuç");
    expect(kirik).toHaveClass("kirma-sonucsuz");
    expect(within(kirik).getByText("⚠")).toBeInTheDocument();
    expect(ilk).not.toHaveClass("kirma-sonucsuz");
  });

  it("assertion ile kırmızı: 'beklendiği gibi'; UUID koşu bağlantı olur", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    const uuid = "9106b437-0770-4afb-9f58-c9d437cf659d";
    const s = coreScript({
      zayif_test: false,
      break_verify: {
        durum: "passed",
        asamalar: [ASAMA("baseline", "passed", null), { ...ASAMA("broken", "failed", uuid), sinif: "assertion" }, ASAMA("restored", "passed", null)],
        neden: "Test hata yakalıyor ✓ (yeşil → kırmızı → yeşil).",
      },
    });
    vi.stubGlobal("fetch", sahteCore("engineer", { [`/scripts/${SID}`]: s, "/scripts": [], "/cases": [] }));
    uygulama(`/kod/${SID}`);
    const zaman = await screen.findByRole("list", { name: "Kırarak doğrulama zaman çizelgesi" });
    const [, kirik] = within(zaman).getAllByRole("listitem");
    expect(kirik).toHaveTextContent("Kırmızı · beklendiği gibi");
    expect(within(kirik).getByRole("link", { name: "koşu 9106b437" })).toHaveAttribute("href", `/kosular/${uuid}`);
  });

  it("birleştirilmiş PR: core 'durum: merged' engeli yerine birleştirme bilgisi; merge/doğrula düğmesi yok", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    const s = coreScript({
      durum: "merged",
      pr: { ...coreScript().pr, durum: "merged", merge_sha: "5b06333deadbeef", merge_eden: "muhendis", merge_zamani: "2026-10-31T13:15:00+00:00" },
      merge_engelleri: ["PR merge edilebilir durumda değil (durum: merged)"],
    });
    vi.stubGlobal("fetch", sahteCore("engineer", { [`/scripts/${SID}`]: s, "/scripts": [], "/cases": [] }));
    uygulama(`/kod/${SID}`);
    const kapi = await screen.findByTestId("merge-kapisi");
    expect(kapi).toHaveTextContent(/✓ Birleştirildi — muhendis, .*merge commit 5b06333/);
    expect(kapi).not.toHaveTextContent("merged");
    expect(screen.queryByRole("button", { name: "Merge et" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^(Kırarak|Yeniden) doğrula$/ })).not.toBeInTheDocument();
  });
});

describe("eşleme tablosu ve defect adayı", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("parametresiz doğrulama 'Değer yok'; değer case cümlesinde vurgulanır; 'core bildirmedi' yok", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    vi.stubGlobal("fetch", sahteCore("engineer", { [`/scripts/${SID}`]: coreScript(), "/scripts": [], "/cases": [] }));
    uygulama(`/kod/${SID}`);
    const tablo = await screen.findByRole("region", { name: "Eşlenen adımlar tablosu" });
    expect(tablo).not.toHaveTextContent("core bildirmedi");
    const parametresiz = within(tablo).getByText("CheckoutPage.expectCheckoutEnabled()").closest("tr")!;
    expect(parametresiz).toHaveTextContent("Değer yok (parametresiz doğrulama)");
    const sayim = within(tablo).getByText('CartPage.expectCartCount("1")').closest("tr")!;
    const vurgu = sayim.querySelector("mark.kaynak-deger");
    expect(vurgu?.textContent).toBe("1");
    expect(sayim.querySelector("q")?.textContent).toBe("Sepet rozeti 1 adet gösterir");
  });

  it("defect adayı (C3): 3 tekrar tek satırda, banner iş diliyle, ajanın sepet görüntüsüne bağlantı", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    const hata = {
      test_adi: "TPD-1 · C3 › 6 adet → bedava yok",
      hata_mesaji: "Error: expect(locator).toHaveText(expected) failed\n\nExpected: \"0\"",
      beklenen: "0",
      gerceklesen: "1",
    };
    const s = coreScript({
      durum: "blocked",
      pr: null,
      zayif_test: false,
      break_verify: { durum: "not_started", asamalar: [], neden: null },
      yerel_sinif: "defect_adayi",
      engel: { tur: "defect_candidate", neden: "Yerel CI başarısız: run — TPD-1 · C3 › 6 adet → bedava yok." },
      hata: "Yerel CI başarısız: run — TPD-1 · C3 › 6 adet → bedava yok.",
      merge_engelleri: ["PR merge edilebilir durumda değil (durum: blocked)"],
      adimlar: [
        { sira: 1, tur: "arac", step_id: "", arac: "browser_navigate", aciklama: "Katalog", arguman: {}, po: null, method: null, args: [], verified: true, izinli: true, ekran_goruntusu_url: `/api/scripts/${SID}/screenshots/1`, zaman: "2026-10-31T12:00:00+00:00" },
        { sira: 2, tur: "arac", step_id: "", arac: "browser_snapshot", aciklama: "Sepet: Bedava 1", arguman: {}, po: null, method: null, args: [], verified: true, izinli: true, ekran_goruntusu_url: `/api/scripts/${SID}/screenshots/2`, zaman: "2026-10-31T12:00:01+00:00" },
        { sira: 3, tur: "arac", step_id: "", arac: "browser_snapshot", aciklama: "Son", arguman: {}, po: null, method: null, args: [], verified: true, izinli: true, ekran_goruntusu_url: null, zaman: "2026-10-31T12:00:02+00:00" },
      ],
      yerel_kontrol: {
        tsc: true,
        eslint: true,
        ast_guard: true,
        tekrar: 3,
        sonuc: "failed",
        sinif: "defect_adayi",
        aciklama: null,
        run_id: "cg-8908c645-local-check-515752",
        duzeltme_turu: 0,
        basarisiz: [hata, hata, hata],
        atlandi: false,
      },
    });
    vi.stubGlobal("fetch", sahteCore("engineer", { [`/scripts/${SID}`]: s, "/scripts": [], "/cases": [] }));
    uygulama(`/kod/${SID}`);
    const banner = await screen.findByText(/Yerel kontrol: beklenen 0, gerçekleşen 1 \(3\/3 tekrar\)\./);
    expect(banner.textContent).not.toMatch(/run —|Yerel CI/);
    expect(screen.getByRole("link", { name: "Ajanın gördüğü sepet (adım 2)" })).toHaveAttribute("href", `/api/scripts/${SID}/screenshots/2`);
    const liste = screen.getByRole("list", { name: "Başarısız testler" });
    expect(within(liste).getAllByRole("listitem")).toHaveLength(1);
    expect(liste).toHaveTextContent("3/3 tekrarda aynı hata");
    // PR yokken merge kapısı gösterilmez (core merge_engelleri = []); PR kartı nedenini söyler.
    expect(screen.queryByTestId("merge-kapisi")).toBeNull();
  });

  it("hatalariGrupla / nedenTemizle", () => {
    const h = { test_adi: "t", hata_mesaji: "e\nayrıntı", beklenen: "0", gerceklesen: "1", adim: null };
    expect(hatalariGrupla([h, { ...h, hata_mesaji: "e\nbaşka satır" }, { ...h, gerceklesen: "2" }]).map((g) => g.adet)).toEqual([2, 1]);
    expect(nedenTemizle("Yerel CI başarısız: run — X.")).toBe("Yerel kontrol: X");
    expect(nedenTemizle("sayılmaz..")).toBe("sayılmaz");
    expect(nedenTemizle(null)).toBeNull();
  });
});

describe("Koşular: adlandırma ve bağlantılar", () => {
  afterEach(() => vi.unstubAllGlobals());
  const RID = "9106b437-0770-4afb-9f58-c9d437cf659d";
  const kosu = {
    id: RID,
    tetik: "pr",
    kaynak: "local",
    commit: "abc1234",
    pr_no: 3,
    durum: "passed",
    baslangic: "2026-10-31T12:00:00+00:00",
    sure_ms: 1200,
    toplam: 1,
    gecen: 1,
    basarisiz: 0,
    flaky: 0,
    atlanan: 0,
    allure_url: `/api/artifacts/runs/${RID}/src/e2e/results/allure-results`,
    rapor_url: `/api/artifacts/runs/${RID}/src/e2e/results/html/index.html`,
    sauce_url: null,
    ci_url: null,
    log_url: `/api/artifacts/runs/${RID}/runner.log`,
    break_campaign: false,
    script_id: null,
    saglik_hatasi: null,
    raporlar: { junit: true, json: true },
    sonuclar: [],
    uyarilar: [],
  };

  it("liste: kısa koşu adı (tam UUID ipucunda); kırma koşusu yoksa kırma süzgeci gösterilmez", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    vi.stubGlobal("fetch", sahteCore("presenter", { "/runs": [kosu] }));
    uygulama("/kosular");
    const bag = await screen.findByRole("link", { name: "9106b437" });
    expect(bag).toHaveAttribute("title", `Koşu kimliği: ${RID}`);
    expect(screen.queryByText(RID)).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /Kasıtlı kırma koşuları/ })).not.toBeInTheDocument();
  });

  it("liste: kırma koşusu varsa süzgeç görünür", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    vi.stubGlobal("fetch", sahteCore("presenter", { "/runs": [kosu, { ...kosu, id: "2106b437-0770-4afb-9f58-c9d437cf659d", tetik: "break_verify", break_campaign: true }] }));
    uygulama("/kosular");
    expect(await screen.findByRole("checkbox", { name: /Kasıtlı kırma koşuları/ })).toBeInTheDocument();
  });

  it("detay: başlıkta tetik + kısa ad; JUnit XML bağlantısı; allure ham sonuçlar doğru adlandırılır", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    vi.stubGlobal("fetch", sahteCore("presenter", { [`/runs/${RID}`]: kosu }));
    uygulama(`/kosular/${RID}`);
    const baslik = await screen.findByRole("heading", { level: 1 });
    expect(baslik).toHaveTextContent("PR koşusu 9106b437");
    const kart = screen.getByRole("region", { name: "Raporlar ve bağlantılar" });
    expect(within(kart).getByRole("link", { name: /JUnit XML/ })).toHaveAttribute("href", `/api/artifacts/runs/${RID}/src/e2e/results/junit.xml`);
    expect(within(kart).getByRole("link", { name: /Allure ham sonuçları \(JSON listesi\)/ })).toBeInTheDocument();
  });

  it("kosuUyarla: core junit_url öncelikli; JUnit yoksa türetilmez", () => {
    expect(kosuUyarla({ ...kosu, junit_url: "/api/x/junit.xml" }).junit_url).toBe("/api/x/junit.xml");
    expect(kosuUyarla({ ...kosu, raporlar: { junit: false } }).junit_url).toBeNull();
    expect(kosuUyarla({ ...kosu, rapor_url: null }).junit_url).toBeNull();
  });
});

describe("Kod üretimi listesi", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("kapatılanlar varsayılan gizli (aç/kapa); insana düşen için 'Yeniden üret' aynı case ile /code/generate çağırır", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    const cagrilar: Cagri[] = [];
    const bloklu = coreScript({ id: "22222222-2222-4222-8222-222222222222", durum: "blocked", pr: null, case_ids: ["c-7"], baslik: "C7 testi" });
    const kapali = coreScript({ id: "33333333-3333-4333-8333-333333333333", durum: "closed", pr: null, case_ids: ["c-7"], baslik: "C7 testi", mode: null });
    vi.stubGlobal("fetch", sahteCore("engineer", { "/scripts": [bloklu, kapali], "/cases": [] }, cagrilar));
    const u = userEvent.setup();
    uygulama("/kod");
    const tablo = await screen.findByRole("region", { name: "Üretilen testler tablosu" });
    expect(within(tablo).getAllByRole("link", { name: "C7 testi" })).toHaveLength(1);
    await u.click(screen.getByRole("checkbox", { name: /Kapatılanları göster \(1\)/ }));
    expect(within(screen.getByRole("region", { name: "Üretilen testler tablosu" })).getAllByRole("link", { name: "C7 testi" })).toHaveLength(2);
    await u.click(screen.getByRole("button", { name: "Yeniden üret" }));
    await waitFor(() => expect(cagrilar.find((c) => c.url === "/code/generate")?.govde).toEqual({ case_ids: ["c-7"] }));
  });
});
