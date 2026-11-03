// Faz 4 inceleme düzeltmeleri (portal): engellenen onarımın dürüst gösterimi, triage gözlemleri,
// kanıt bağlantısı tekilleştirme, ürün hatasında olası mükerrer satırı, mükerrer sıralaması
// yapılamayınca uydurma AI önerisi olmaması, özet 120 karakter sınırı ve Türkçe şema hatası,
// demo sıfırlama özeti ve kırılma ilerlemesinin geri kurulması.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ayar } from "../api/mock/handlers";
import type { BugTaslagi, DemoDurumu, HataAnalizi, LocatorOnarimi } from "../api/types";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { oturumAc } from "../test/yardimci";
import { icerikHatasi, OZET_AZAMI, semaHatasiTurkce } from "./BugTaslaklari";
import { demoOlayMetni, kirmaGeriYukle, sifirlamaOzeti, zatenKirik } from "./DemoKontrolleri";
import { ariaAsamaAdi, dogrulamaIsareti, olasiMukerrerMetni, onarimAsamalari, tekilLinkler } from "./HataDetay";

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
});

const ONARIM: LocatorOnarimi = {
  tur: "locator_fix",
  dosya: "demo-app/e2e/pages/catalog/locators.ts",
  anahtar: "catalog.addToCart",
  eski_test_id: "add-to-cart",
  yeni_test_id: "cart-add",
  rol: "button",
  ad: "Sepete ekle",
  dogrulama: [],
  durum: "proposed",
  pr: null,
};

/** shots/stale-3: yoklamada engellenen onarım (sha farklı), eski/yeni testId yok. */
const ENGELLENEN: LocatorOnarimi = {
  ...ONARIM,
  eski_test_id: null,
  yeni_test_id: null,
  durum: "failed",
  dogrulama_kaynagi: "onarim",
  dogrulama: ["Çalışan uygulama sha eşleşmesi: farkli", "Engellendi (yoklama): Çalışan uygulama koşulan commit'ten farklı; öneri üretilmez"],
  neden: "yoklama: Çalışan uygulama koşulan commit'ten farklı; öneri üretilmez",
};

function hata(oneri: HataAnalizi["oneri"], ek: Partial<HataAnalizi> = {}): HataAnalizi {
  return {
    id: "f-x",
    run_id: "run-x",
    test_adi: "katalog › sepete ekle",
    hata_imzasi: "sig",
    hata_mesaji: "locator 0 eleman",
    sinif: "test_maintenance",
    alt_tur: "locator",
    eslesen_sinyaller: [],
    karar_kaynagi: "rule",
    kural: "test_maintenance/locator",
    llm_yorumu: null,
    oneri,
    kanit_linkleri: [],
    mode: null,
    zaman: "2026-10-31T10:00:00Z",
    ...ek,
  };
}

describe("onarım hattı: engellenen onarım ve aria aşaması", () => {
  it("eski/yeni testId yoksa Öneri aşaması başarısız; aria aşaması yalnızca aria kaydından (triage gözlemi ✓ yapmaz)", () => {
    const a = onarimAsamalari(ENGELLENEN);
    expect(a[0]).toMatchObject({ durum: "hata", ayrinti: "öneri üretilmedi" });
    expect(a[1].durum).toBe("bekliyor");
    // Önerildi durumunda triage gözlemleri varken bile aria aşaması bekliyor.
    expect(onarimAsamalari({ ...ONARIM, dogrulama: ["Rol + ad tek eleman"] })[1].durum).toBe("bekliyor");
    expect(onarimAsamalari({ ...ONARIM, aria_dogrulama: { eslesti: true, aciklama: null, run_id: null, kaynak: "son_yesil_kosu" } })[1].durum).toBe("tamam");
  });

  it("aria aşamasının etiketi kanıt kaynağını söyler", () => {
    expect(ariaAsamaAdi({ aria_dogrulama: { eslesti: true, aciklama: null, run_id: null, kaynak: "sozlesme_testi" } })).toBe(
      "Son yeşil koşuda locators sözleşme testi (aria dosyası yok)",
    );
    expect(ariaAsamaAdi({ aria_dogrulama: { eslesti: true, aciklama: null, run_id: null, kaynak: "son_yesil_kosu" } })).toContain("aria snapshot");
    expect(ariaAsamaAdi({ aria_dogrulama: null })).toBe("Son yeşil kanıtla rol + ad doğrulaması");
  });

  it("kontrol satırları önemine göre işaretlenir", () => {
    expect(dogrulamaIsareti("Engellendi (yoklama): öneri üretilmez").isaret).toBe("✗");
    expect(dogrulamaIsareti("Çalışan uygulama sha eşleşmesi: farkli")).toMatchObject({ isaret: "✗", ton: "hata" });
    expect(dogrulamaIsareti("Çalışan uygulama sha eşleşmesi: dogrulanamadi")).toMatchObject({ isaret: "!", ton: "uyari" });
    expect(dogrulamaIsareti("Çalışan uygulama sha eşleşmesi: eslesiyor").isaret).toBe("✓");
    expect(dogrulamaIsareti("AST koruması ihlal buldu").isaret).toBe("✗");
    expect(dogrulamaIsareti("Yerel kontrol (tam paket): kırmızı").isaret).toBe("✗");
  });

  it("ekranda: boş fark yok, engel ✗ ile, mühendise 'Yeniden dene'", async () => {
    await oturumAc("muhendis");
    vi.spyOn(api, "hata").mockResolvedValue(hata(ENGELLENEN));
    const f = vi.spyOn(api, "onarimPrAc").mockResolvedValue({ job_id: "j1", durum: "queued", mesaj: "yeniden" });
    const u = userEvent.setup();
    uygulama("/hatalar/f-x");
    expect(await screen.findByTestId("oneri-yok")).toHaveTextContent("catalog.addToCart.testId için değişiklik önerisi üretilmedi");
    expect(screen.queryByLabelText("Locator değişikliği")).toBeNull();
    const k = screen.getByRole("list", { name: "Onarım kontrolleri" });
    const satirlar = within(k).getAllByRole("listitem");
    expect(satirlar[0]).toHaveTextContent("✗");
    expect(satirlar[1]).toHaveTextContent(/^✗ Engellendi/);
    expect(k).not.toHaveTextContent("✓");
    expect(screen.queryByRole("button", { name: "Onarım PR'ı aç" })).toBeNull();
    await u.click(screen.getByRole("button", { name: "Yeniden dene" }));
    expect(f).toHaveBeenCalledWith("f-x");
  });

  it("triage önerisi: gözlemler onay işaretsiz; kardeş hatada PR düğmesi yok", async () => {
    await oturumAc("muhendis");
    vi.spyOn(api, "hata").mockResolvedValue(hata({ ...ONARIM, dogrulama: ["trace DOM snapshot'ında 'add-to-cart' yok"], dogrulama_kaynagi: "triage" }));
    uygulama("/hatalar/f-x");
    const g = await screen.findByRole("list", { name: "Triage gözlemleri" });
    expect(g).not.toHaveTextContent("✓");
    vi.restoreAllMocks();
  });

  it("kardeş hata (pr_open, PR ve onarım kaydı yok): bilgi notu, PR düğmesi yok", async () => {
    await oturumAc("muhendis");
    vi.spyOn(api, "hata").mockResolvedValue(hata({ ...ONARIM, durum: "pr_open", dogrulama_kaynagi: "triage" }));
    uygulama("/hatalar/f-x");
    expect(await screen.findByText("Onarım kardeş hata üzerinden yürüyor")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Onarım PR'ı aç" })).toBeNull();
  });
});

describe("kanıt bağlantıları ve olası mükerrer", () => {
  it("aynı adrese giden bağlantılar bir kez, en açıklayıcı etiketle", () => {
    const l = tekilLinkler([
      { etiket: "Playwright trace", url: "/api/a/trace.zip" },
      { etiket: "Ekran görüntüsü", url: "/api/a/s.png" },
      { etiket: "error-context", url: "/api/a/error-context.md" },
      { etiket: "Playwright trace", url: "/api/a/trace.zip" },
      { etiket: "Hata anı sayfa snapshot'ı (error-context)", url: "/api/a/error-context.md" },
      { etiket: "Ekran görüntüsü", url: "/api/a/s.png" },
      { etiket: "runner log", url: null },
      { etiket: "runner log", url: null },
    ]);
    expect(l.map((x) => x.etiket)).toEqual(["Playwright trace", "Ekran görüntüsü", "Hata anı sayfa snapshot'ı (error-context)", "runner log"]);
  });

  it("ekranda kanıt bağlantıları tekrarlanmaz", async () => {
    await oturumAc("muhendis");
    vi.spyOn(api, "hata").mockResolvedValue(
      hata(null, {
        kanit_linkleri: [
          { etiket: "Playwright trace", url: "/api/a/trace.zip" },
          { etiket: "Playwright trace", url: "/api/a/trace.zip" },
        ],
      }),
    );
    uygulama("/hatalar/f-x");
    const l = await screen.findByRole("list", { name: "Kanıt bağlantıları" });
    expect(within(l).getAllByRole("listitem")).toHaveLength(1);
  });

  it("olası mükerrer metni: AI'lı, AI'sız (REPLAY-MISS), aranıyor", () => {
    const aday = { key: "TPD-5", summary: "Kampanya indirimi sepette yanlış hesaplanıyor", durum: "Open", gerekce: "Aynı belirti", sinyaller: [], olasilik: "high" as const, sira: 1, url: null };
    expect(olasiMukerrerMetni({ mukerrer_adaylari: [aday], mukerrer_arama: null })).toBe(
      "Olası mükerrer: TPD-5 — Kampanya indirimi sepette yanlış hesaplanıyor (yüksek olasılık, AI sıralaması)",
    );
    const arama = { durum: "yapildi" as const, jql: null, oneri: null, oneri_link_key: null, mode: "replay_miss" as const, hata: null };
    expect(olasiMukerrerMetni({ mukerrer_adaylari: [{ ...aday, gerekce: "", olasilik: null }], mukerrer_arama: arama })).toContain(
      "AI sıralaması yok (REPLAY-MISS); Jira arama sırası",
    );
    expect(olasiMukerrerMetni({ mukerrer_adaylari: [], mukerrer_arama: { ...arama, durum: "suruyor" } })).toContain("aranıyor");
  });

  it("ürün hatası triage ekranı en olası mükerrer adayı gösterir (§2 adım 12)", async () => {
    await oturumAc("testci");
    uygulama("/hatalar/fail-4");
    expect(await screen.findByTestId("olasi-mukerrer")).toHaveTextContent(/Olası mükerrer: TPD-5 .*yüksek olasılık, AI sıralaması/);
  });
});

function taslak(ek: Partial<BugTaslagi> = {}): BugTaslagi {
  return {
    id: "bx",
    kaynak: "consistency",
    failure_id: null,
    finding_id: "fnd-4",
    icerik: {
      summary: "Kredi limiti aşımında sipariş reddedilmiyor",
      steps: ["Sepete ürün ekle", "Ödemeye geç"],
      expected: "Red",
      actual: "Kabul",
      environment: "demo",
      evidence: [],
      story_key: "TPD-1",
      test_case_key: null,
      severity_suggestion: "major",
      labels: ["AI-generated"],
    },
    mukerrer_adaylari: [{ key: "TPD-5", summary: "Kampanya", durum: "Open", gerekce: "", sinyaller: [], olasilik: null, sira: null, url: null }],
    mukerrer_arama: { durum: "yapildi", jql: "x", oneri: null, oneri_link_key: null, mode: "replay_miss", hata: null, ai_onerisi_yok: "REPLAY-MISS: kayıtlı sıralama yok" },
    karar: null,
    durum: "draft",
    link_key: null,
    icerik_hash: "sha256:x",
    onaylayan: null,
    onay_zamani: null,
    jira_key: null,
    jira_url: null,
    jira_browse_url: null,
    yayin_hatasi: null,
    yayin_suruyor: false,
    ret_gerekcesi: null,
    mode: "replay",
    olusturma: "2026-10-31T10:00:00Z",
    ...ek,
  } as BugTaslagi;
}

describe("bug taslağı: sıralama yapılamayınca ve özet sınırı", () => {
  it("sıralama yok: 'AI önerisi yok (REPLAY-MISS…)' + REPLAY-MISS rozeti; 'adaylar aynı hata değil' uydurulmaz", async () => {
    await oturumAc("testci");
    vi.spyOn(api, "bugTaslagi").mockResolvedValue(taslak());
    uygulama("/bug-taslaklari/bx");
    const o = await screen.findByTestId("mukerrer-onerisi");
    expect(o).toHaveTextContent("AI önerisi yok (REPLAY-MISS: kayıtlı sıralama yok)");
    expect(screen.queryByText(/adaylar aynı hata değil/)).toBeNull();
    expect(screen.queryByText(/ReplayNoOutput/)).toBeNull();
    expect(screen.getAllByText("REPLAY-MISS").length).toBeGreaterThan(0);
  });

  it("özet alanı 120 karakterle sınırlı, sayaç gösterir; gönderimden önce denetlenir", async () => {
    await oturumAc("testci");
    vi.spyOn(api, "bugTaslagi").mockResolvedValue(taslak());
    uygulama("/bug-taslaklari/bx");
    const ozet = await screen.findByLabelText("Özet");
    expect(ozet).toHaveAttribute("maxLength", String(OZET_AZAMI));
    expect(screen.getByTestId("ozet-sayac")).toHaveTextContent(`43/${OZET_AZAMI} karakter`);
    expect(icerikHatasi({ summary: "x".repeat(124), expected: "a", actual: "b", environment: "c" }, ["s"])).toBe(
      "Özet en fazla 120 karakter olabilir (şu an 124).",
    );
    expect(icerikHatasi({ summary: "ok", expected: " ", actual: "b", environment: "c" }, ["s"])).toBe("Beklenen boş olamaz.");
    expect(icerikHatasi({ summary: "ok", expected: "a", actual: "b", environment: "c" }, ["s"])).toBeNull();
  });

  it("core 422 şema hatası Türkçe alan mesajına çevrilir (İngilizce jsonschema metni gösterilmez)", async () => {
    expect(semaHatasiTurkce("Bug taslağı şemaya uymuyor — summary: 'Sepet; çok uzun özet (testçi düzenledi)' is too long")).toBe(
      "Taslak kaydedilemedi: Özet en fazla 120 karakter olabilir.",
    );
    expect(semaHatasiTurkce("Bug taslağı şemaya uymuyor — steps: [] should be non-empty; severity_suggestion: 'x' is not one of ['critical']")).toBe(
      "Taslak kaydedilemedi: Adımlar boş olamaz; Önem önerisi geçerli bir değer değil.",
    );
    expect(semaHatasiTurkce("Başka bir hata")).toBe("Başka bir hata");

    await oturumAc("testci");
    vi.spyOn(api, "bugTaslagi").mockResolvedValue(taslak());
    const { ApiError } = await import("../api/http");
    vi.spyOn(api, "bugKarari").mockRejectedValue(new ApiError(422, "Bug taslağı şemaya uymuyor — summary: 'x' is too long"));
    const u = userEvent.setup();
    uygulama("/bug-taslaklari/bx");
    await u.click(await screen.findByRole("button", { name: "Onayla ve Jira'da aç" }));
    const uyari = await screen.findByRole("alert");
    expect(uyari).toHaveTextContent("Özet en fazla 120 karakter olabilir");
    expect(uyari).not.toHaveTextContent("is too long");
  });
});

describe("demo kontrolleri", () => {
  const KIRIK: DemoDurumu = {
    forge: { main: "21b36dec0000", testid: "cart-add", baseline: "aaaa", main_baseline_mi: false },
    uygulama: { sha: "21b36dec0000", main_ile_eslesiyor: true },
    web_yenileme_istegi: { istek_id: "i1", eylem: "break", sha: "21b36dec0000", zaman: new Date(Date.now() - 60_000).toISOString(), isteyen: "sunucu" },
  };

  it("sıfırlama özeti: yapılmayanlar açıkça (jira atlandı → make demo-reset, kararlar → make reset)", () => {
    const s = sifirlamaOzeti({
      forge: { degisti: true, main_sonra: "baseline123456" },
      kapanan_prlar: [{ pr: 3, hata: null }],
      web: { durum: "bekleniyor" },
      jira: { durum: "atlandi", neden: "core-worker'da JIRA_SIM_ADMIN_TOKEN yok" },
      veritabani: { durum: "dokunulmadi" },
    });
    const metin = s.map((x) => x.metin).join("\n");
    expect(metin).toContain("Forge main demo-baseline'a döndü");
    expect(metin).toContain("Açık demo PR'ları kapatıldı: 1");
    expect(metin).toMatch(/Jira sıfırlanmadı.*make demo-reset/);
    expect(metin).toMatch(/Kararlar.*korunur.*make reset/);
    expect(s.find((x) => x.metin.startsWith("Jira"))?.ton).toBe("uyari");
    expect(sifirlamaOzeti({ jira: { durum: "tamam" } })[0]).toEqual({ ton: "basari", metin: "jira-sim seed durumuna döndü." });
  });

  it("kart metni düğmenin yapmadığı şeyi vaat etmez", async () => {
    await oturumAc("sunucu");
    uygulama("/demo");
    await screen.findByRole("button", { name: "Demo'yu sıfırla" });
    expect(screen.queryByText(/jira-sim seed, forge ana dalı/)).toBeNull();
    expect(screen.getByText(/Kararlar, bug taslakları ve koşu geçmişi korunur/)).toBeInTheDocument();
  });

  it("web bekleme olayı host yönergesini taşır", () => {
    const m = demoOlayMetni({ type: "demo.web_waiting", data: { eylem: "break", yonerge: "host'ta scripts/demo-web-sync.sh çalıştırın." } });
    expect(m?.mesaj).toContain("scripts/demo-web-sync.sh");
  });

  it("main zaten kırıksa kır düğmesi pasif; ilerleme /demo/status'tan geri kurulur", async () => {
    expect(zatenKirik(KIRIK)).toBe(true);
    expect(zatenKirik({ ...KIRIK, forge: { ...KIRIK.forge, main_baseline_mi: true, testid: "add-to-cart" } })).toBe(false);
    expect(kirmaGeriYukle(KIRIK)).toMatchObject({ geriYuklendi: true, bitti: false });
    expect(kirmaGeriYukle({ ...KIRIK, web_yenileme_istegi: { eylem: "baseline", zaman: KIRIK.forge.main } })).toBeNull();

    await oturumAc("sunucu");
    vi.spyOn(api, "demoDurumu").mockResolvedValue(KIRIK);
    uygulama("/demo");
    const d = await screen.findByRole("button", { name: "Buton kimliği zaten değişti" });
    expect(d).toBeDisabled();
    expect(screen.getByTestId("zaten-kirik")).toHaveTextContent("cart-add");
    await waitFor(() => expect(screen.getByRole("list", { name: "Locator kırılması ilerlemesi" })).toHaveTextContent("Kırılma istendi"));
  });
});
