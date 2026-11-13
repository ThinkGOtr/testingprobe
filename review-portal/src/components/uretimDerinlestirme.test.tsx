// 011 §4.8: üretim formu (K5), derinleştirme paneli (P5/P6, K7), kapsam panelinin dalga 2 bölümleri
// (gözlemler, yapılandırma matrisi, test edilebilirlik boşlukları, otomasyon notları, üretim rozetleri).
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { V3_GEREKSINIM_ID, V3_ICERIKLER, V3_URETIM } from "../api/mock/caseV3";
import { KAYNAK } from "../api/mock/fixtures";
import { ayar, mockVerisi } from "../api/mock/handlers";
import type { CaseKapsamOzeti, IsYaniti, TestCase, UretimSecenekleriYaniti } from "../api/types";
import { OturumProvider } from "../auth";
import { uretimSecenekleriYanitiUyarla } from "../lib/uretimSecenekleri";
import { oturumAc, sar } from "../test/yardimci";
import { BildirimProvider } from "./Bildirim";
import { CaseKarti } from "./CaseKarti";
import { derinlestirmeAyari, DerinlestirmePaneli } from "./DerinlestirmePaneli";
import { KapsamPaneli } from "./KapsamPaneli";
import { UretimFormu } from "./UretimFormu";

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

const YANIT = (secenekler: unknown = null): UretimSecenekleriYaniti =>
  uretimSecenekleriYanitiUyarla({
    secenekler,
    varsayilan: { platformlar: [], test_seviyesi: "SYSTEM", benimsenen_standartlar: [], kapsam_disi: "", roller: "", ek_bilgi: {} },
  });

const ISLEM: IsYaniti = { job_id: "job-1", durum: "started", mesaj: "Case üretimi başlatıldı." };

function form(secenekler: unknown = null) {
  vi.spyOn(api, "uretimSecenekleri").mockResolvedValue(YANIT(secenekler));
  const gonder = vi.fn().mockResolvedValue(ISLEM);
  const basladi = vi.fn();
  const kapat = vi.fn();
  sar(<UretimFormu gereksinimId="req-tpd-4" gonder={gonder} basladi={basladi} kapat={kapat} />);
  return { gonder, basladi, kapat };
}

const platformKutusu = (ad: string) => screen.getByRole("checkbox", { name: ad });

describe("UretimFormu", () => {
  beforeEach(async () => {
    await oturumAc("testci");
  });

  it("kayıtlı seçenek yoksa varsayılanla açılır; platform seçilmeden ek bilgi alanı yok", async () => {
    form();
    await screen.findByRole("form", { name: "Üretim seçenekleri" });
    expect(screen.getByLabelText("Test seviyesi")).toHaveValue("SYSTEM");
    for (const p of ["Web", "Mobil-iOS", "Desktop-Linux", "API", "Data"]) expect(platformKutusu(p)).not.toBeChecked();
    expect(screen.queryByTestId("ek-bilgi-alanlari")).toBeNull();
    expect(screen.getByText("Platform seçilmezse üretim platformdan bağımsız yapılır.")).toBeInTheDocument();
  });

  it("kayıtlı son seçeneklerle ön dolar (K5)", async () => {
    form({ platformlar: ["Web"], test_seviyesi: "E2E", benimsenen_standartlar: ["WCAG 2.2 AA"], kapsam_disi: "Ödeme adımı", roller: "bayi", ek_bilgi: { tarayicilar: "Chrome" } });
    await screen.findByRole("form", { name: "Üretim seçenekleri" });
    expect(platformKutusu("Web")).toBeChecked();
    expect(screen.getByLabelText("Test seviyesi")).toHaveValue("E2E");
    expect(within(screen.getByTestId("standart-etiketleri")).getByText("WCAG 2.2 AA")).toBeInTheDocument();
    expect(screen.getByLabelText("Kapsam dışı")).toHaveValue("Ödeme adımı");
    expect(screen.getByLabelText("Roller")).toHaveValue("bayi");
    expect(screen.getByLabelText("Tarayıcılar")).toHaveValue("Chrome");
    expect(screen.getByText(/son üretiminde kullanılan seçeneklerle/)).toBeInTheDocument();
  });

  it("ek bilgi alanları seçili platforma göre görünür", async () => {
    const u = userEvent.setup();
    form();
    await screen.findByRole("form", { name: "Üretim seçenekleri" });
    await u.click(platformKutusu("Web"));
    const ek = () => screen.getByTestId("ek-bilgi-alanlari");
    expect(within(ek()).getByLabelText("Tarayıcılar")).toBeInTheDocument();
    expect(within(ek()).getByLabelText("Çözünürlükler")).toBeInTheDocument();
    expect(within(ek()).queryByLabelText("Cihaz sınıfları")).toBeNull();

    await u.click(platformKutusu("Mobil-Android"));
    expect(within(ek()).getByLabelText("Cihaz sınıfları")).toBeInTheDocument();
    expect(within(ek()).getByLabelText("Uygulama tipi")).toBeInTheDocument();
    expect(within(ek()).getByLabelText("İşletim sistemi / sürüm matrisi")).toBeInTheDocument();

    await u.click(platformKutusu("Web"));
    expect(within(ek()).queryByLabelText("Tarayıcılar")).toBeNull();

    await u.click(platformKutusu("API"));
    expect(within(ek()).queryByLabelText("API sözleşmesi (OpenAPI/endpoint tanımı)")).toBeNull();
    await u.click(within(ek()).getByRole("checkbox", { name: "API sözleşmesi var" }));
    expect(within(ek()).getByLabelText("API sözleşmesi (OpenAPI/endpoint tanımı)")).toBeInTheDocument();
  });

  it("standart etiketi: Enter ve virgülle eklenir, × ile silinir; sınır aşımı yazılır", async () => {
    const u = userEvent.setup();
    form();
    const giris = await screen.findByLabelText("Benimsenen standartlar");
    await u.type(giris, "WCAG 2.2 AA{Enter}");
    await u.type(giris, "OWASP MASVS L1,");
    const etiketler = screen.getByTestId("standart-etiketleri");
    expect(within(etiketler).getByText("WCAG 2.2 AA")).toBeInTheDocument();
    expect(within(etiketler).getByText("OWASP MASVS L1")).toBeInTheDocument();
    expect(giris).toHaveValue("");
    await u.click(screen.getByRole("button", { name: "WCAG 2.2 AA standardını kaldır" }));
    expect(within(screen.getByTestId("standart-etiketleri")).queryByText("WCAG 2.2 AA")).toBeNull();
    await u.type(giris, `${"x".repeat(41)}{Enter}`);
    expect(screen.getByRole("alert")).toHaveTextContent("en fazla 40 karakter");
  });

  it("gönderim: gövde yalnız görünen ve dolu ek bilgileri taşır; başarıda `basladi`", async () => {
    const u = userEvent.setup();
    const { gonder, basladi } = form();
    await screen.findByRole("form", { name: "Üretim seçenekleri" });
    await u.click(platformKutusu("Mobil-Android"));
    await u.click(platformKutusu("Web"));
    await u.selectOptions(screen.getByLabelText("Test seviyesi"), "E2E");
    await u.type(screen.getByLabelText("Tarayıcılar"), "Chrome");
    await u.selectOptions(screen.getByLabelText("Uygulama tipi"), "flutter");
    await u.type(screen.getByLabelText("Kapsam dışı"), "  Ödeme  ");
    // Yazılıp Enter'a basılmamış standart da gönderime katılır.
    await u.type(screen.getByLabelText("Benimsenen standartlar"), "WCAG 2.2 AA");
    await u.click(screen.getByRole("button", { name: "Üretimi başlat" }));
    await waitFor(() => expect(gonder).toHaveBeenCalledTimes(1));
    expect(gonder).toHaveBeenCalledWith({
      platformlar: ["Web", "Mobil-Android"],
      test_seviyesi: "E2E",
      benimsenen_standartlar: ["WCAG 2.2 AA"],
      kapsam_disi: "Ödeme",
      roller: "",
      ek_bilgi: { tarayicilar: "Chrome", uygulama_tipi: "flutter" },
    });
    await waitFor(() => expect(basladi).toHaveBeenCalledWith(ISLEM));
  });

  it("sunucu hatası formda gösterilir; `basladi` çağrılmaz", async () => {
    const u = userEvent.setup();
    const { gonder, basladi } = form();
    const { ApiError } = await import("../api/http");
    gonder.mockRejectedValueOnce(new ApiError(422, "Üretim seçenekleri geçersiz — x"));
    await screen.findByRole("form", { name: "Üretim seçenekleri" });
    await u.click(screen.getByRole("button", { name: "Üretimi başlat" }));
    expect(await screen.findByText(/Üretim seçenekleri geçersiz/)).toBeInTheDocument();
    expect(basladi).not.toHaveBeenCalled();
  });

  it("uç yoksa (eski core 404/501) varsayılanlarla açılır ve bunu söyler", async () => {
    const { ApiError } = await import("../api/http");
    vi.spyOn(api, "uretimSecenekleri").mockRejectedValue(new ApiError(501, "yok"));
    sar(<UretimFormu gereksinimId="req-tpd-4" gonder={vi.fn()} basladi={vi.fn()} kapat={vi.fn()} />);
    expect(await screen.findByText("Kayıtlı seçenek alınamadı")).toBeInTheDocument();
    expect(screen.getByLabelText("Test seviyesi")).toHaveValue("SYSTEM");
  });
});

describe("Gereksinim detayı: 'Seçeneklerle üret…'", () => {
  beforeEach(() => {
    ayar.isAdimiMs = 0;
  });

  it("PO onaylı gereksinimde formu açar; gönderim generate-cases'i seçili kip ve seçeneklerle çağırır", async () => {
    const u = userEvent.setup();
    await oturumAc("testci");
    const g = mockVerisi().gereksinimler.find((x) => x.id === "req-tpd-4")!;
    g.durum = "po_approved";
    g.po = { durum: "approved", onaylayan: "po", zaman: "2026-11-01T10:00:00Z", kanal: "jira" };
    const uret = vi.spyOn(api, "caseUret");
    uygulama("/gereksinimler/req-tpd-4");
    const ac = await screen.findByRole("button", { name: "Seçeneklerle üret…" });
    expect(screen.getByRole("button", { name: "Tasarım modelini üret (iki tur)" })).toBeEnabled();
    await u.click(ac);
    const f = await screen.findByRole("form", { name: "Üretim seçenekleri" });
    // UX-4: kip seçimi formun ilk alanı (fieldset + legend radyo grubu); form açıkken sayfada tek kip grubu.
    const ilkAlan = f.querySelector("fieldset, input, select, textarea")!;
    expect(ilkAlan.tagName).toBe("FIELDSET");
    expect(within(f).getAllByRole("group")[0]).toBe(ilkAlan);
    expect(ilkAlan.querySelector("legend")).toHaveTextContent("Üretim kipi");
    expect(within(f).getByRole("radio", { name: /İki tur \(önerilen\)/ })).toBeChecked();
    expect(screen.getAllByTestId("uretim-kipi")).toHaveLength(1);
    await u.click(screen.getByRole("checkbox", { name: "API" }));
    await u.click(screen.getByRole("button", { name: "Üretimi başlat" }));
    await waitFor(() => expect(uret).toHaveBeenCalledTimes(1));
    expect(uret.mock.calls[0][0]).toBe("req-tpd-4");
    // Seçili kip (varsayılan iki tur) seçeneklerle birlikte gider (011 K1 + K5).
    expect(uret.mock.calls[0][1]).toBe("iki_tur");
    expect(uret.mock.calls[0][2]).toMatchObject({ platformlar: ["API"], test_seviyesi: "SYSTEM" });
    await waitFor(() => expect(screen.queryByRole("form", { name: "Üretim seçenekleri" })).toBeNull());
    expect((await api.uretimSecenekleri("req-tpd-4")).secenekler?.platformlar).toEqual(["API"]);
  });

  it("PO onayı yoksa düğme pasif", async () => {
    await oturumAc("testci");
    uygulama("/gereksinimler/req-tpd-4");
    expect(await screen.findByRole("button", { name: "Seçeneklerle üret…" })).toBeDisabled();
  });
});

describe("DerinlestirmePaneli", () => {
  beforeEach(() => {
    ayar.isAdimiMs = 0;
    derinlestirmeAyari.aralikMs = 20;
  });
  let eski: typeof KAYNAK.case_deepening;
  beforeEach(() => {
    eski = KAYNAK.case_deepening;
  });
  afterEach(() => {
    KAYNAK.case_deepening = eski;
    derinlestirmeAyari.aralikMs = 2000;
  });

  it("cases_ready değilse düğmeler pasif ve nedeni yazılı", async () => {
    await oturumAc("testci");
    sar(<DerinlestirmePaneli gereksinim={{ id: "req-tpd-4", durum: "new" }} tazele={vi.fn()} />);
    const negatif = await screen.findByRole("button", { name: "Negatif kapsamı genişlet" });
    expect(negatif).toBeDisabled();
    expect(screen.getByRole("button", { name: "Teknikle derinleştir" })).toBeDisabled();
    expect(negatif).toHaveAccessibleDescription(/yalnız "Case review aşamasında" olan gereksinimde/);
  });

  it("Testçi olmayan rolde (012: Analist de) pasif ve gereken rol yazılı", async () => {
    await oturumAc("analist");
    sar(<DerinlestirmePaneli gereksinim={{ id: V3_GEREKSINIM_ID, durum: "cases_ready" }} tazele={vi.fn()} />);
    const negatif = await screen.findByRole("button", { name: "Negatif kapsamı genişlet" });
    expect(negatif).toBeDisabled();
    expect(negatif).toHaveAccessibleDescription(/gereken rol: Testçi/);
  });

  it("başlat → çalışıyor → 'N yeni taslak eklendi'; bitince tazele bir kez", async () => {
    const u = userEvent.setup();
    await oturumAc("testci");
    const g = mockVerisi().gereksinimler.find((x) => x.id === "req-tpd-1")!;
    g.durum = "cases_ready";
    KAYNAK.case_deepening = { "teknik-bva/TPD-1": { girdi_ac: [], cases: [V3_ICERIKLER[0], V3_ICERIKLER[1]] } };
    ayar.isAdimiMs = 150;
    const tazele = vi.fn();
    const istek = vi.spyOn(api, "derinlestir");
    sar(<DerinlestirmePaneli gereksinim={{ id: "req-tpd-1", durum: "cases_ready" }} tazele={tazele} />);
    const teknik = await screen.findByRole("button", { name: "Teknikle derinleştir" });
    await waitFor(() => expect(teknik).toBeEnabled());
    await u.selectOptions(screen.getByLabelText("Teknik"), "BVA");
    await u.click(teknik);
    expect(istek).toHaveBeenCalledWith("req-tpd-1", { tur: "teknik", teknik: "BVA" });
    expect(await screen.findByText(/Teknik derinleştirme \(BVA — Sınır değer analizi\) çalışıyor/)).toBeInTheDocument();
    // Core tek iş tutar: diğer düğme pasif ve nedeni yazılı; başlatan düğme "çalışıyor".
    expect(screen.getByRole("button", { name: "Negatif kapsamı genişlet" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Negatif kapsamı genişlet" })).toHaveAccessibleDescription("Diğer derinleştirme sürüyor");
    expect(screen.getByRole("button", { name: "Teknikle derinleştir" })).toHaveAttribute("aria-busy", "true");
    expect(await within(screen.getByTestId("derinlestirme-durumu")).findByText(/^2 yeni taslak eklendi/, {}, { timeout: 3000 })).toBeInTheDocument();
    expect(tazele).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Negatif kapsamı genişlet" })).toBeEnabled();
  });

  it("golden yoksa hata metni (REPLAY-MISS) ve tazele", async () => {
    const u = userEvent.setup();
    await oturumAc("testci");
    KAYNAK.case_deepening = {};
    const tazele = vi.fn();
    sar(<DerinlestirmePaneli gereksinim={{ id: V3_GEREKSINIM_ID, durum: "cases_ready" }} tazele={tazele} />);
    const negatif = await screen.findByRole("button", { name: "Negatif kapsamı genişlet" });
    await waitFor(() => expect(negatif).toBeEnabled());
    await u.click(negatif);
    const durum = screen.getByTestId("derinlestirme-durumu");
    expect(await within(durum).findByText("Negatif genişletme başarısız", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(within(durum).getByText("REPLAY-MISS: bu girdi için kayıtlı model çıktısı yok")).toBeInTheDocument();
    await waitFor(() => expect(tazele).toHaveBeenCalledTimes(1));
  });

  it("tamam ama sıfır case: 'Yeni taslak eklenmedi' + uyarılar", async () => {
    await oturumAc("testci");
    vi.spyOn(api, "derinlestirmeDurumu").mockResolvedValue({
      durum: "tamam",
      tur: "negatif",
      teknik: null,
      uretim_no: 3,
      yeni_case_sayisi: 0,
      uyarilar: ["Tüm geçersiz bölümler zaten kapsanıyor."],
      hata: null,
    });
    sar(<DerinlestirmePaneli gereksinim={{ id: V3_GEREKSINIM_ID, durum: "cases_ready" }} tazele={vi.fn()} />);
    expect(await screen.findByText("Yeni taslak eklenmedi.")).toBeInTheDocument();
    expect(screen.getByText("Tüm geçersiz bölümler zaten kapsanıyor.")).toBeInTheDocument();
  });

  it("yoklama ardışık 3 hatada durur, 'Durum alınamadı — Tekrar dene'; sürdürünce biter, 'göster' üretime süzer", async () => {
    const u = userEvent.setup();
    await oturumAc("testci");
    const calisiyor = { durum: "calisiyor" as const, tur: "negatif" as const, teknik: null, uretim_no: 4, yeni_case_sayisi: null, uyarilar: [], hata: null };
    const oku = vi
      .spyOn(api, "derinlestirmeDurumu")
      .mockResolvedValueOnce(calisiyor)
      .mockRejectedValueOnce(new Error("ağ"))
      .mockRejectedValueOnce(new Error("ağ"))
      .mockRejectedValueOnce(new Error("ağ"))
      .mockResolvedValue({ ...calisiyor, durum: "tamam", yeni_case_sayisi: 3 });
    const tazele = vi.fn();
    const goster = vi.fn();
    sar(<DerinlestirmePaneli gereksinim={{ id: V3_GEREKSINIM_ID, durum: "cases_ready" }} tazele={tazele} goster={goster} />);
    const kutu = await screen.findByTestId("derinlestirme-yoklama-hatasi", {}, { timeout: 3000 });
    expect(kutu).toHaveTextContent("Durum alınamadı");
    expect(oku).toHaveBeenCalledTimes(4);
    // Durdu: yeni okuma yok.
    await new Promise((r) => setTimeout(r, 100));
    expect(oku).toHaveBeenCalledTimes(4);
    expect(tazele).not.toHaveBeenCalled();
    await u.click(within(kutu).getByRole("button", { name: "Tekrar dene" }));
    const sonuc = await screen.findByTestId("derinlestirme-sonucu", {}, { timeout: 3000 });
    expect(sonuc).toHaveTextContent("3 yeni taslak eklendi — göster");
    expect(tazele).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("derinlestirme-yoklama-hatasi")).toBeNull();
    await u.click(within(sonuc).getByRole("button", { name: "Üretim 4 ile eklenen 3 taslağı listede göster" }));
    expect(goster).toHaveBeenCalledWith(4);
  });

  it("Case review sayfasında 'göster' URL'ye ?uretim= yazar ve case kararlarına gider", async () => {
    const u = userEvent.setup();
    await oturumAc("testci");
    vi.spyOn(api, "derinlestirmeDurumu").mockResolvedValue({ durum: "tamam", tur: "negatif", teknik: null, uretim_no: 2, yeni_case_sayisi: 1, uyarilar: [], hata: null });
    uygulama(`/gereksinimler/${V3_GEREKSINIM_ID}/caseler`);
    const dugme = await screen.findByRole("button", { name: "Üretim 2 ile eklenen 1 taslağı listede göster" }, { timeout: 3000 });
    await u.click(dugme);
    // Durum şeridindeki bağlantılar güncel aramayı taşır: URL'de uretim=2 var.
    await waitFor(() => expect(screen.getByTestId("serit-bekleyen").getAttribute("href")).toContain("uretim=2"));
    await waitFor(() => expect(document.activeElement?.id).toBe("case-kararlari"));
  });

  it("uç yoksa (eski core) panel görünmez", async () => {
    await oturumAc("testci");
    const { ApiError } = await import("../api/http");
    vi.spyOn(api, "derinlestirmeDurumu").mockRejectedValue(new ApiError(404, "Not Found"));
    const { container } = sar(<DerinlestirmePaneli gereksinim={{ id: V3_GEREKSINIM_ID, durum: "cases_ready" }} tazele={vi.fn()} />);
    await waitFor(() => expect(container.querySelector(".derinlestirme-paneli")).toBeNull());
  });

  it("Case review sayfasında görünür (case'i olan gereksinim)", async () => {
    await oturumAc("testci");
    uygulama(`/gereksinimler/${V3_GEREKSINIM_ID}/caseler`);
    expect(await screen.findByRole("button", { name: "Negatif kapsamı genişlet" })).toBeInTheDocument();
  });
});

const OZET = (uretimler = [V3_URETIM]): CaseKapsamOzeti => ({
  requirement_id: V3_GEREKSINIM_ID,
  uretimler,
  kapsam_matrisi: [{ item: "AC1", tur: "ac", tanim: "t", valid: null, covered_by: [1], gerekce: null }],
  oranlar: {
    gereksinim_kapsami: { kapsanan: 1, toplam: 1, oran: 1 },
    oge_kapsami: { kapsanan: 0, toplam: 0, oran: null },
    negatif_karar_kapsami: { kapsanan: 0, toplam: 0, oran: null },
  },
  teknik_dagilimi: {},
  readiness_dagilimi: {},
  kapsanmayan: [],
  uyarilar: [],
});

describe("KapsamPaneli: dalga 2 bölümleri", () => {
  it("gözlem (beklenen sonuç değildir), yapılandırma matrisi tablosu + PICT notu, boşluk tablosu, otomasyon notları", () => {
    const u = {
      ...V3_URETIM,
      config_matrix: { parameters: [{ name: "tarayici", values: ["Chrome", "Firefox"] }, { name: "dil", values: ["tr", "en"] }], constraints: ["IF tarayici = Firefox THEN dil = tr"] },
    };
    render(<KapsamPaneli ozet={OZET([u])} caseSayisi={1} />);
    const gozlem = screen.getByTestId("kapsam-gozlemler");
    expect(gozlem).toHaveTextContent("Gözlem — beklenen sonuç değildir");
    expect(within(gozlem).getByText("OWASP ASVS V5.3")).toBeInTheDocument();

    const yap = screen.getByTestId("kapsam-yapilandirma");
    expect(yap).toHaveTextContent("kombinasyon satırları PICT ile üretilir");
    const tablo = within(yap).getByRole("table");
    expect(within(tablo).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Parametre", "Değerler"]);
    expect(within(tablo).getByText("Chrome, Firefox")).toBeInTheDocument();
    expect(within(yap).getByText("IF tarayici = Firefox THEN dil = tr")).toBeInTheDocument();

    const bosluk = within(screen.getByTestId("kapsam-bosluklar")).getByRole("table");
    expect(within(bosluk).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Kontrol", "Eksik"]);
    expect(within(bosluk).getByText("Sipariş notu metin alanı")).toBeInTheDocument();
    expect(within(bosluk).getByText("test_id")).toBeInTheDocument();

    expect(screen.getByTestId("kapsam-otomasyon")).toHaveTextContent("data-testid");
    // Tek üretim (tur=uretim): üretim listesi/rozet yok.
    expect(screen.queryByTestId("kapsam-uretimler")).toBeNull();
  });

  it("derinleştirme üretimleri rozetle listelenir", () => {
    const bos = { ...V3_URETIM, observations: [], automation_open_points: [], testability_gaps: [], open_questions: [], assumptions: [] };
    render(
      <KapsamPaneli
        ozet={OZET([V3_URETIM, { ...bos, uretim_no: 2, tur: "negatif", case_sayisi: 3 }, { ...bos, uretim_no: 3, tur: "teknik" }])}
        caseSayisi={5}
      />,
    );
    const liste = screen.getByTestId("kapsam-uretimler");
    expect(within(liste).getByText("Negatif genişletme")).toBeInTheDocument();
    expect(within(liste).getByText("Teknik derinleştirme")).toBeInTheDocument();
    expect(liste).toHaveTextContent("Üretim 2 Negatif genişletme · 3 case");
  });
});

describe("CaseKarti: platform ve gerçek cihaz", () => {
  it("platform, 'Gerçek cihaz gerekir' ve standart atıfları görünür", async () => {
    await oturumAc("testci");
    const tc = (await api.caseler(V3_GEREKSINIM_ID))[0];
    const c: TestCase = { ...tc, icerik: { ...tc.icerik, platform: "Mobil-iOS", requires_real_device: true, standard_refs: ["OWASP MASVS L1"] } };
    sar(<CaseKarti tc={c} guncellendi={vi.fn()} yenile={vi.fn()} />);
    const dd = screen.getByText("Gerçek cihaz gerekir").closest("dd")!;
    expect(dd).toHaveTextContent("Mobil-iOS · Gerçek cihaz gerekir");
    expect(screen.getByText("OWASP MASVS L1")).toBeInTheDocument();
  });
});
