// Gereksinim sayfası üretim UX'i (D5 şerit B): çift tıklama tek istek (UX-1), 409 "durum: X" eşlemesi,
// kip seçimi ve düğme metni (UX-4), kayıtlı kip tercihi (D1), cases_ready'de birincil "Case review" ve
// onaylı "Yeniden üret…", Gherkin indir (UX-14), K22 terimleri.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import { ayar, mockVerisi } from "../api/mock/handlers";
import type { GereksinimDetay as Detay, IsYaniti } from "../api/types";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { kipDugmeMetni, uretimCakismaMesaji, uretimSecenekleriYanitiUyarla } from "../lib/uretimSecenekleri";
import { oturumAc } from "../test/yardimci";
import { caseUretHatasi } from "./GereksinimDetay";

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

const T = { timeout: 15_000 };
const AGIR = 60_000;
const gereksinim = (id: string) => mockVerisi().gereksinimler.find((g) => g.id === id)! as Detay;

/** TPD-4'ü PO onaylı, üretim bekleyen hâle getirir. */
function poOnayli(): Detay {
  const g = gereksinim("req-tpd-4");
  g.durum = "po_approved";
  g.ac_missing = false;
  g.po = { durum: "approved", onaylayan: "po", zaman: "2026-11-01T10:00:00Z", kanal: "jira" };
  return g;
}

beforeEach(() => {
  ayar.isAdimiMs = 0;
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("409 'durum: X' eşlemesi", () => {
  it("üretim sürüyorsa 'Üretim zaten başladı (etiket)'; başka durumda kod yerine etiket; durum yoksa null", () => {
    expect(uretimCakismaMesaji("Bu durumda tasarım modeli üretilemez (durum: modeling).")).toBe("Üretim zaten başladı (Tasarım modeli üretiliyor)");
    expect(uretimCakismaMesaji("Bu durumda case üretilemez (durum: generating).")).toBe("Üretim zaten başladı (Case üretiliyor)");
    expect(uretimCakismaMesaji("Bu durumda case üretilemez (durum: cases_ready).")).toBe("Bu durumda case üretilemez (Case review aşamasında).");
    expect(uretimCakismaMesaji("PO teyidi olmadan case üretilemez.")).toBeNull();
  });

  it("caseUretHatasi 409'u eşler, kodu korur; durum taşımayan 409'a dokunmaz", () => {
    const yakala = (e: unknown) => {
      try {
        caseUretHatasi(e);
      } catch (x) {
        return x as ApiError;
      }
      throw new Error("fırlatmadı");
    };
    const e = yakala(new ApiError(409, "x (durum: modeling)", { kod: "durum" }));
    expect(e.detail).toBe("Üretim zaten başladı (Tasarım modeli üretiliyor)");
    expect(e.kod).toBe("durum");
    const ham = new ApiError(409, "PO teyidi olmadan case üretilemez.");
    expect(yakala(ham)).toBe(ham);
  });

  it("ekranda: arka planda üretim başladıysa düğme ham kodu değil etiketi gösterir", async () => {
    await oturumAc("analist");
    const g = poOnayli();
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-tpd-4");
    const dugme = await screen.findByRole("button", { name: "Tasarım modelini üret (iki tur)" }, T);
    g.durum = "modeling"; // başka bir sekmede üretim başladı; ekran henüz yenilenmedi
    await u.click(dugme);
    expect(await screen.findByText("Üretim zaten başladı (Tasarım modeli üretiliyor)", undefined, T)).toBeInTheDocument();
    expect(screen.queryByText(/durum: modeling/)).not.toBeInTheDocument();
  }, AGIR);
});

describe("UX-1: çift tıklama tek istek", () => {
  it("aynı olay döngüsündeki iki tıklama generate-cases'i bir kez çağırır; düğme beklerken meşgul", async () => {
    await oturumAc("analist");
    poOnayli();
    let bitir: (y: IsYaniti) => void = () => undefined;
    const spy = vi.spyOn(api, "caseUret").mockImplementation(() => new Promise<IsYaniti>((r) => (bitir = r)));
    uygulama("/gereksinimler/req-tpd-4");
    const dugme = await screen.findByRole("button", { name: "Tasarım modelini üret (iki tur)" }, T);
    fireEvent.click(dugme);
    fireEvent.click(dugme);
    expect(spy).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(dugme).toHaveAttribute("aria-busy", "true"));
    expect(dugme).toBeDisabled();
    bitir({ job_id: "j1", durum: "started" });
    await waitFor(() => expect(dugme).not.toHaveAttribute("aria-busy"));
    expect(spy).toHaveBeenCalledTimes(1);
  }, AGIR);
});

describe("UX-4: kip seçimi ve düğme metni", () => {
  it("düğme metni seçili kipi söyler; tek tur seçilince 'Case üret (tek tur)'", async () => {
    await oturumAc("analist");
    poOnayli();
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-tpd-4");
    const grup = await screen.findByRole("group", { name: "Üretim kipi" }, T);
    expect(within(grup).getByRole("radio", { name: /İki tur/ })).toBeChecked();
    expect(screen.getByRole("button", { name: "Tasarım modelini üret (iki tur)" })).toBeEnabled();
    await u.click(within(grup).getByRole("radio", { name: /Tek tur/ }));
    expect(screen.getByRole("button", { name: "Case üret (tek tur)" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Tasarım modelini üret (iki tur)" })).not.toBeInTheDocument();
    // İpucu kipin ne yaptığını doğru anlatır: iki turda onaydan sonra case'ler otomatik üretilir.
    expect(grup).toHaveTextContent("modeli onayladığınızda case'ler yalnız onaylı modelden otomatik üretilir");
    expect(grup).toHaveTextContent("Case'ler doğrudan üretilir");
    expect(grup).not.toHaveTextContent(/"Case üret" düğmesi/);
  }, AGIR);

  it("kayıtlı kip tercihi (D1) varsayılan gelir; gönderilen kip saklanır", async () => {
    await oturumAc("analist");
    poOnayli();
    (mockVerisi().uretimKipleri ??= {})["req-tpd-4"] = "tek_tur";
    uygulama("/gereksinimler/req-tpd-4");
    expect(await screen.findByRole("button", { name: "Case üret (tek tur)" }, T)).toBeEnabled();
    expect(screen.getByRole("radio", { name: /Tek tur/ })).toBeChecked();
  }, AGIR);

  it("generation-options kip uyarlaması: kayitli.kip, secenekler.kip, yoksa alan yok", async () => {
    expect(uretimSecenekleriYanitiUyarla({ kayitli: { kip: "tek_tur" } }).kip).toBe("tek_tur");
    expect(uretimSecenekleriYanitiUyarla({ secenekler: { kip: "iki_tur", platformlar: [] } }).kip).toBe("iki_tur");
    expect("kip" in uretimSecenekleriYanitiUyarla({ secenekler: null })).toBe(false);
    expect(uretimSecenekleriYanitiUyarla({ kayitli: { kip: "bilinmeyen" } }).kip).toBeUndefined();
    expect(kipDugmeMetni("iki_tur")).toBe("Tasarım modelini üret (iki tur)");
    expect(kipDugmeMetni("tek_tur")).toBe("Case üret (tek tur)");
    // Mock: açıkça gönderilen kip generation-options'ta döner.
    await oturumAc("analist");
    poOnayli();
    await api.caseUret("req-tpd-4", "tek_tur");
    expect((await api.uretimSecenekleri("req-tpd-4")).kip).toBe("tek_tur");
  });
});

describe("cases_ready: 'Case review' birincil, yeniden üretim ikincil ve onaylı", () => {
  function reviewAsamasinda(): Detay {
    const g = gereksinim("req-tpd-1");
    g.durum = "cases_ready";
    delete g.adim;
    return g;
  }

  it("birincil bağlantı case review'a gider; durum etiketi 'Case review aşamasında'; Gherkin indir yanında", async () => {
    await oturumAc("analist");
    reviewAsamasinda();
    uygulama("/gereksinimler/req-tpd-1");
    const review = await screen.findByRole("link", { name: "Case review" }, T);
    expect(review).toHaveClass("dugme-birincil");
    expect(review).toHaveAttribute("href", "/gereksinimler/req-tpd-1/caseler");
    const yeniden = screen.getByRole("button", { name: "Yeniden üret…" });
    expect(yeniden).toHaveClass("dugme-ikincil");
    expect(screen.queryByRole("button", { name: /Tasarım modelini üret|Case üret \(tek tur\)/ })).not.toBeInTheDocument();
    expect(screen.getAllByText("Case review aşamasında").length).toBeGreaterThan(0);
    expect(screen.queryByText("Case'ler hazır")).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Gherkin indir" }, T)).toBeInTheDocument();
    // Gherkin indir başlıkta, Case review bağlantısıyla aynı eylem grubunda.
    expect(review.closest(".eylemler")).toContainElement(screen.getByTestId("gherkin-indir"));
  }, AGIR);

  it("'Yeniden üret…' sayfa içi onay ister (mevcut sayılar); Vazgeç istek göndermez, onay üretimi başlatır", async () => {
    await oturumAc("analist");
    reviewAsamasinda();
    const confirm = vi.spyOn(window, "confirm");
    const spy = vi.spyOn(api, "caseUret");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-tpd-1");
    const yeniden = await screen.findByRole("button", { name: "Yeniden üret…" }, T);
    const guncel = mockVerisi().caseler.filter((c) => c.requirement_id === "req-tpd-1" && c.durum !== "superseded");
    const onayli = guncel.filter((c) => c.durum === "approved" || c.durum === "published").length;
    await waitFor(() => expect(yeniden).toBeEnabled(), T);
    await u.click(yeniden);
    const onay = await screen.findByTestId("yeniden-uret-onayi");
    expect(onay).toHaveTextContent(`Mevcut ${guncel.length} case (${onayli} onaylı) yerini yenilerine bırakır; onaylar geçersiz olur.`);
    expect(within(onay).getByRole("button", { name: "Vazgeç" })).toHaveFocus();
    await u.click(within(onay).getByRole("button", { name: "Vazgeç" }));
    expect(screen.queryByTestId("yeniden-uret-onayi")).not.toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
    await u.click(screen.getByRole("button", { name: "Yeniden üret…" }));
    await u.click(within(screen.getByTestId("yeniden-uret-onayi")).getByRole("button", { name: "Evet, yeniden üret" }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("req-tpd-1", "iki_tur"), T);
    expect(confirm).not.toHaveBeenCalled();
  }, AGIR);
});

describe("K22: tutarlılık kontrolü düğmesi", () => {
  it("kontrol turu varsa 'Yeniden kontrol et'; sürerken 'Kontrol sürüyor…' (meşgul)", async () => {
    await oturumAc("analist");
    const g = gereksinim("req-tpd-4");
    g.durum = "findings_open";
    g.kontrol_turu = 1;
    const { unmount } = uygulama("/gereksinimler/req-tpd-4");
    expect(await screen.findByRole("button", { name: "Yeniden kontrol et" }, T)).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Yeniden denetle" })).not.toBeInTheDocument();
    unmount();
    g.durum = "in_review";
    uygulama("/gereksinimler/req-tpd-4");
    const suruyor = await screen.findByRole("button", { name: "Kontrol sürüyor…" }, T);
    expect(suruyor).toHaveAttribute("aria-busy", "true");
  }, AGIR);
});
