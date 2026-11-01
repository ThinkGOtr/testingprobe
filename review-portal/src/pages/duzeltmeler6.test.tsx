// Faz 5 inceleme düzeltmeleri (portal): yol haritasında kasıtlı kırma taslağı, simülatör notları ve
// "hazır (golden)" metni; `done` sonrası 14 adımlı akış adımı; Kontrol Kulesi kazanç ipucu; demo
// kontrollerinde onarım sonrası çelişkili ara durum ve PR numarası; defect adayında kırma aşamaları.
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ayar } from "../api/mock/handlers";
import type { BugTaslagi, DemoDurumu, GereksinimDetay, HataAnalizi, Kosu, Script, TestCase } from "../api/types";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { guncelAdim, demoAdimlari, jiraSimMi, kirmaTaslagiMi, modOzeti, type YolGirdisi } from "../lib/yolHaritasi";
import { oturumAc } from "../test/yardimci";
import { onarimPrHatalardan } from "./DemoKontrolleri";
import { KirmaZaman } from "./ScriptDetay";

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
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

// ------------------------------------------------------------------ ortak sahne: tamamlanmış TPD-1

const BOS: YolGirdisi = { gereksinim: null, caseler: [], scriptler: [], kosular: [], hatalar: [], bugTaslaklari: [], kule: null, demo: null };
const g = {
  id: "r1",
  jira_key: "TPD-1",
  jira_url: "http://127.0.0.1:8090/browse/TPD-1",
  durum: "done",
  kaynak: "jira",
  kabul_kriterleri: [{ ref: "AC1", metin: "" }],
  kontrol_turu: 2,
  kontrol_turu_ust_sinir: 3,
  po: { durum: "approved", onaylayan: "po@sim.local", zaman: null, kanal: "jira", onaylanan_hash: "h" },
  icerik_hash: "h",
  sayaclar: { bulgu_acik: 0, case_toplam: 2, case_onayli: 2 },
} as unknown as GereksinimDetay;
const c = (n: number) => ({ id: `c${n}`, requirement_id: "r1", sira_no: n, durum: "published", jira_test_key: `TPD-${8 + n}`, mode: "replay" }) as unknown as TestCase;
const bv = (durum: string) => ({ durum, asamalar: [] });
const scriptler = [
  { id: "s2", case_ids: ["c2"], requirement_key: "TPD-1", durum: "merged", pr: { number: 3, durum: "merged", merge_eden: "muhendis", merge_zamani: "2026-11-01T10:00:00Z" }, break_verify: bv("passed"), zayif_test: false, yerel_sinif: "gecti", engel: null, mode: "replay", olusturma: "2026-11-01T09:00:00Z" },
  { id: "s3", case_ids: ["c3"], requirement_key: "TPD-1", durum: "blocked", pr: null, break_verify: bv("not_started"), zayif_test: false, yerel_sinif: "defect_adayi", engel: { tur: "defect_candidate", neden: null }, mode: "replay", olusturma: "2026-11-01T09:00:00Z", failure_id: "f3" },
] as unknown as Script[];
const kosu = (id: string, tetik: string, ek: Partial<Kosu> = {}) =>
  ({ id, tetik, kaynak: "local", durum: "passed", baslangic: `2026-11-01T1${id.length % 10}:00:00Z`, junit_url: "/api/j", allure_url: "/api/a", break_campaign: false, ...ek }) as unknown as Kosu;
const KIRMA_KOSUSU = kosu("kirma", "break_verify", { durum: "failed" });
const kosular = [kosu("1", "push"), kosu("2", "deploy"), KIRMA_KOSUSU];
const hatalar = [
  { id: "f3", run_id: "1", script_id: "s3", sinif: "product_defect", karar_kaynagi: "rule", test_adi: "TPD-1 C3 6 adet", zaman: "2026-11-01T09:30:00Z", oneri: { tur: "bug_draft", bug_draft_id: "b1" }, mode: null },
  { id: "fk", run_id: "kirma", script_id: "s2", sinif: "product_defect", karar_kaynagi: "rule", test_adi: "TPD-1 C2 kırma", zaman: "2026-11-01T09:40:00Z", oneri: { tur: "bug_draft", bug_draft_id: "bk" }, mode: null },
] as unknown as HataAnalizi[];
const bug = (id: string, ek: Partial<BugTaslagi>) => ({ id, icerik: { story_key: "TPD-1" }, failure_id: null, mode: "replay", ...ek }) as unknown as BugTaslagi;
const buglar = [
  bug("b1", { failure_id: "f3", durum: "published", karar: "link", link_key: "TPD-5", jira_key: "TPD-5", jira_browse_url: "http://127.0.0.1:8090/browse" }),
  bug("b2", { durum: "published", karar: "link", link_key: "TPD-5", jira_key: "TPD-5" }),
  bug("b4", { durum: "published", karar: "new", jira_key: "TPD-18" }),
  // Demo-B kırarak doğrulamanın kasıtlı kırmızısından: bilerek açık bırakılır.
  bug("bk", { failure_id: "fk", durum: "draft", karar: null }),
];
const kule = { son_kosular: [{}], gecme_orani: { oran: 1 }, flaky: [] } as unknown as YolGirdisi["kule"];
const demo = { forge: {}, uygulama: {}, web_yenileme_istegi: null, locator_demo: { destekleniyor: true, neden: null } } as unknown as DemoDurumu;
const TAM: YolGirdisi = { ...BOS, gereksinim: g, caseler: [c(2), c(3)], scriptler, kosular, hatalar, bugTaslaklari: buglar, kule, demo };

describe("yol haritası: kasıtlı kırma taslağı adım 13'ü bekletmez", () => {
  it("kırma koşusundan gelen açık taslak sayılmaz, ayrıca belirtilir; F2/C3 sahne notu artık gösterilmez", () => {
    expect(kirmaTaslagiMi(buglar[3], hatalar, kosular)).toBe(true);
    expect(kirmaTaslagiMi(buglar[0], hatalar, kosular)).toBe(false);
    const a13 = demoAdimlari(TAM)[12];
    expect(a13.hal).toBe("tamam");
    expect(a13.kanit).toBe("3 taslak · 3 karar verildi · 1 kasıtlı kırma taslağı (bilerek açık, sayılmaz)");
    expect(a13.ipucu).toBeNull();
  });

  it("BREAK_CAMPAIGN koşusu da kırma sayılır; gerçek bekleyen taslak varsa ve TPD-5 bağlıysa F2/C3 notu yerine genel not", () => {
    const kampanya = [kosu("1", "push"), kosu("kirma", "push", { break_campaign: true, durum: "failed" })];
    expect(kirmaTaslagiMi(buglar[3], hatalar, kampanya)).toBe(true);
    const a13 = demoAdimlari({ ...TAM, bugTaslaklari: [...buglar, bug("b9", { durum: "draft", karar: null })] })[12];
    expect(a13.hal).toBe("suruyor");
    expect(a13.ipucu).toBe("Kalan taslaklara testçi kararı verin (onayla / bağla / reddet).");
    const ilk = demoAdimlari({ ...TAM, bugTaslaklari: [bug("b1", { failure_id: "f3", durum: "draft", karar: null })] })[12];
    expect(ilk.ipucu).toMatch(/F2 ve C3 taslakları/);
  });

  it("tamamlanmış akış 14/14 (Sauce yerine yerel yedek dahil): ilk tamamlanmamış adım yok", () => {
    const a = demoAdimlari(TAM);
    expect(a.filter((x) => x.hal !== "tamam" && x.hal !== "yedek")).toEqual([]);
  });
});

describe("yol haritası: simülatör notları ve 'hazır (golden)' metni", () => {
  it("1, 7, 8 ve 14. adımlar simülatörü adıyla söyler; 9 yerel yedek kalır", () => {
    const a = demoAdimlari(TAM);
    expect(a[0].simulator).toMatch(/jira-sim/);
    expect(a[6].simulator).toMatch(/LocalForge/);
    expect(a[7].simulator).toMatch(/yerel CI/);
    expect(a[13].simulator).toMatch(/jira-sim/);
    expect(a[8].hal).toBe("yedek");
  });

  it("gerçek Jira Cloud / GitHub / bulut CI'da simülatör notu yazılmaz", () => {
    const bulut = {
      ...TAM,
      gereksinim: { ...g, jira_url: "https://acme.atlassian.net/browse/TPD-1" },
      bugTaslaklari: buglar.map((b) => ({ ...b, jira_browse_url: null })),
      kosular: kosular.map((k) => ({ ...k, kaynak: "github" as const })),
      demo: { ...demo, locator_demo: { destekleniyor: false, neden: "GitHub" } },
    };
    const a = demoAdimlari(bulut);
    expect([a[0], a[6], a[7], a[13]].map((x) => x.simulator ?? null)).toEqual([null, null, null, null]);
    expect(jiraSimMi({ gereksinim: null, bugTaslaklari: [] })).toBeNull();
  });

  it("gözlemden REPLAY metni 'kayıtlı' demez: hazır (golden) çıktı", () => {
    const m = modOzeti({ ...BOS, caseler: [c(1)] });
    expect(m.metin).toBe("REPLAY — ekrandaki 1 çıktının hepsi hazır (golden) çıktıdan");
    expect(m.metin).not.toMatch(/kayıtlı/);
  });

  it("ekran: simülatör çipi adım satırında görünür", async () => {
    await oturumAc("sunucu");
    uygulama("/yol-haritasi");
    expect(await screen.findByRole("heading", { level: 1, name: "Demo yol haritası" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("yh-adim-1")).toHaveAttribute("data-hal", "tamam"));
    const sim = within(screen.getByTestId("yh-adim-1")).queryByTestId("yh-simulator-1");
    // Örnek veride Jira adresi yerel (jira-sim): not görünür.
    if (sim) expect(sim).toHaveTextContent("jira-sim");
  });
});

describe("14 adımlı akış: done sonrası adım kanıtlardan", () => {
  it("done + merge + CI + triage + bug → akış tamam (5'te takılmaz); kanıt okunamazsa durum adımı", () => {
    const { gereksinim: _g, ...kanit } = TAM;
    expect(guncelAdim(g, kanit, 5)).toBe(15);
    expect(guncelAdim(g, null, 5)).toBe(5);
    // Kod yoksa 5. adımda kalır.
    expect(guncelAdim(g, { ...kanit, scriptler: [] }, 5)).toBe(5);
    // Bug kararı bekliyorsa 13.
    expect(guncelAdim(g, { ...kanit, bugTaslaklari: [bug("b1", { failure_id: "f3", durum: "draft", karar: null })] }, 5)).toBe(13);
    // done olmayan gereksinim durum adımını korur.
    expect(guncelAdim({ ...g, durum: "cases_ready" }, kanit, 4)).toBe(4);
  });

  it("gereksinim listesi done story için '5/14 Kod taslağı' demez; detay adımı 5'i güncel göstermez", async () => {
    await oturumAc("analist");
    const { gereksinim: _g, ...kanit } = TAM;
    vi.spyOn(api, "scriptler").mockResolvedValue(kanit.scriptler);
    vi.spyOn(api, "kosular").mockResolvedValue(kanit.kosular);
    vi.spyOn(api, "hatalar").mockResolvedValue(kanit.hatalar);
    vi.spyOn(api, "bugTaslaklari").mockResolvedValue(kanit.bugTaslaklari);
    vi.spyOn(api, "kontrolKulesi").mockResolvedValue(kule as never);
    vi.spyOn(api, "demoDurumu").mockResolvedValue(demo);
    const ozet = { ...g, id: "req-tpd-1", baslik: "Kampanyalı sepet", ac_missing: false, adim: null };
    vi.spyOn(api, "gereksinimler").mockResolvedValue([ozet as never]);
    uygulama("/gereksinimler");
    const satir = (await screen.findByRole("link", { name: "Kampanyalı sepet" })).closest("tr")!;
    await waitFor(() => expect(satir).toHaveTextContent("14/14"));
    expect(satir).toHaveTextContent("akış tamam");
    expect(satir).not.toHaveTextContent("5/14");
  });
});

describe("Kontrol Kulesi: kazanç ipucu kazanc_orani kaynağını gösterir", () => {
  it("Hazırlık kazancı KPI'ı kazanc_orani kaynak metnini; tablo başlığı manuel_baz kaynağını taşır", async () => {
    await oturumAc("sunucu");
    uygulama("/kontrol-kulesi");
    const kazanc = await screen.findByTestId("hazirlik-kazanci");
    const kpi = kazanc.closest(".metrik")!;
    const ipucu = within(kpi as HTMLElement).getByTestId("kaynak-ipucu");
    expect(ipucu.getAttribute("aria-label")).toMatch(/1 − Σ\(AI \+ review süresi\) \/ Σ\(manuel baz\)/);
    expect(ipucu.getAttribute("aria-label")).not.toMatch(/requirement_baz_deger/);
    const tablo = screen.queryByRole("region", { name: "Story bazında hazırlık tablosu" });
    if (tablo) {
      const baslik = within(tablo).getByRole("columnheader", { name: /Manuel baz/ });
      expect(within(baslik).getByTestId("kaynak-ipucu").getAttribute("aria-label")).toMatch(/TP_MANUAL_BASELINE_S/);
    }
  });
});

describe("demo kontrolleri: onarım sonrası", () => {
  const BASLA = Date.now() - 10 * 60_000;
  const t = (dk: number) => new Date(BASLA + dk * 60_000).toISOString();
  const k = (p: Partial<Kosu> & Pick<Kosu, "id" | "tetik" | "commit" | "durum" | "baslangic">): Kosu =>
    ({ kaynak: "local", pr_no: null, sure_ms: 1, toplam: 36, gecen: p.durum === "passed" ? 36 : 33, basarisiz: 0, flaky: 0, atlanan: 0, allure_url: null, rapor_url: null, sauce_url: null, ci_url: null, break_campaign: false, script_id: null, saglik_hatasi: null, ...p }) as Kosu;
  const KIRMIZI = k({ id: "add31d72-0000-4000-8000-000000000001", tetik: "push", commit: "21b36dec0000", durum: "failed", baslangic: t(1) });
  // PR koşusu yok: numara koşulardan bulunamaz, triage kaydından gelir.
  const YESIL = k({ id: "f1e796b8-0000-4000-8000-000000000003", tetik: "push", commit: "94683fc00000", durum: "passed", baslangic: t(6) });
  const ONARILDI: DemoDurumu = {
    forge: { main: "94683fc000001111", testid: "cart-add", baseline: "aaaa", main_baseline_mi: false },
    uygulama: { sha: "94683fc000001111", main_ile_eslesiyor: true },
    web_yenileme_istegi: { istek_id: "i1", eylem: "break", sha: "21b36dec0000", zaman: new Date(BASLA).toISOString(), isteyen: "sunucu" },
  };
  const LOC = {
    id: "fl",
    run_id: KIRMIZI.id,
    sinif: "test_maintenance",
    zaman: t(2),
    oneri: { tur: "locator_fix", durum: "merged", pr: { number: 5, durum: "merged" } },
  } as unknown as HataAnalizi;

  it("onarimPrHatalardan: en son merge edilen locator onarımının PR'ı; yoksa null", () => {
    expect(onarimPrHatalardan([LOC])).toBe(5);
    expect(onarimPrHatalardan([{ ...LOC, oneri: { ...(LOC.oneri as object), durum: "pr_open" } } as HataAnalizi])).toBeNull();
    expect(onarimPrHatalardan([])).toBeNull();
  });

  it("açılışta yeşil 'onarıldı' ile 'uygulama kurulmadı' / 'CI bekleniyor' aynı anda görünmez; PR #5 triage kaydından", async () => {
    await oturumAc("sunucu");
    vi.spyOn(api, "demoDurumu").mockResolvedValue(ONARILDI);
    vi.spyOn(api, "kosular").mockResolvedValue([YESIL, KIRMIZI]);
    vi.spyOn(api, "hatalar").mockResolvedValue([LOC]);
    vi.spyOn(api, "kosu").mockImplementation(
      async () => ({ ...KIRMIZI, testler: [{ ad: "sepet", durum: "failed", hata: { id: "fl", sinif: "test_maintenance" } }] }) as never,
    );
    uygulama("/demo");
    expect(await screen.findByTestId("onarildi")).toBeInTheDocument();
    // Her ara karede: onarıldı varken bekleme uyarısı ve "CI bekleniyor" yok.
    const kontrol = () => {
      if (screen.queryByTestId("onarildi")) {
        expect(screen.queryByText("Demo uygulaması hâlâ yeniden kurulmadı")).toBeNull();
        expect(screen.queryByText(/merge ve yeniden kurulum sonrası başlar/)).toBeNull();
      }
    };
    kontrol();
    await waitFor(() => expect(screen.getByTestId("onarildi")).toHaveTextContent("Onarım PR #5 merge edildi"));
    kontrol();
    const adimlar = await screen.findByRole("list", { name: "Locator kırılması ilerlemesi" });
    kontrol();
    expect(adimlar).toHaveTextContent(KIRMIZI.id.slice(0, 8));
    await waitFor(() => expect(adimlar).toHaveTextContent("Onarım PR'ı #5"));
    expect(adimlar).not.toHaveTextContent("numara bulunamadı");
  });
});

describe("defect adayında kırarak doğrulama aşamaları", () => {
  const bvBos = {
    durum: "not_started",
    asamalar: [
      { ad: "baseline", sonuc: "pending", run_id: null, zaman: null },
      { ad: "broken", sonuc: "pending", run_id: null, zaman: null },
      { ad: "restored", sonuc: "pending", run_id: null, zaman: null },
    ],
  } as never;

  it("uygulanmaz: aşamalar 'Bekliyor' yerine 'Uygulanmaz (defect adayı)'", () => {
    render(<KirmaZaman bv={bvBos} uygulanmaz />);
    expect(screen.getAllByTestId("kirma-uygulanmaz")).toHaveLength(3);
    expect(screen.queryByText("Bekliyor")).toBeNull();
    expect(screen.getAllByText("Uygulanmaz (defect adayı)")).toHaveLength(3);
  });

  it("normal script'te başlamamış aşama 'Bekliyor' kalır", () => {
    render(<KirmaZaman bv={bvBos} />);
    expect(screen.getAllByText("Bekliyor")).toHaveLength(3);
  });
});
