// Portal review bulgularının düzeltmeleri (3. tur):
//  1. Case üretimi hata ile bitince portal üretimi yeniden denetir (yeni PO teyidi istemez), tutarlılık
//     kartı "denetim tamamlanmadı" demez, akış göstergesi düşen adımda durur.
//  2. Canlı derleme (VITE_MOCK=0): core'un sunmadığı ekranlar örnek veri değil "bu fazda yok" gösterir,
//     menüde pasiftir; ölçülmemiş manuel baz değer / kazanç yüzdesi uydurulmaz.
//  3. Case düzeltmesinde "beklenen sonuç anlamca değişti mi?" insan kararı sorulur ve gönderilir;
//     kartta küçük düzeltme ✓/✗ ve nedeni görünür.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { BU_FAZDA_YOK, yapilandir } from "../api/http";
import { mockVerisi } from "../api/mock/handlers";
import type { GereksinimDetay as Detay, TestCase } from "../api/types";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { CaseKarti, kucukDuzeltmeDurumu } from "../components/CaseKarti";
import { HataKutusu } from "../components/ui";
import { adimAdi, akisAdimi, hataAdimi } from "../lib/akis";
import { oturumAc, sar } from "../test/yardimci";
import { bosBulguMetni, DENETIM_HATALI, poYenidenDenemedeGecerli, uretimHatasiMi } from "./GereksinimDetay";
import { KontrolKulesi } from "./KontrolKulesi";

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

const gereksinim = (id: string) => mockVerisi().gereksinimler.find((g) => g.id === id)! as Detay;

const URETIM_HATASI = {
  neden: "REPLAY-MISS: kayıtlı çıktı yok",
  zaman: null,
  job_tur: "cases.generate",
  is_hatasi: "REPLAY-MISS",
  oneri: "Ayrıntı iş kaydında; yeniden denemek işe yarayabilir.",
  yeniden_denemek_ise_yarar: true,
};

/** TPD-1'i "PO onaylı, case üretimi düştü" hâline getirir (gözlenen e720f989 durumu). */
function uretimiDusur(po: "approved" | "not_requested") {
  const g = gereksinim("req-tpd-1");
  g.durum = "failed";
  delete g.adim;
  g.son_hata = { ...URETIM_HATASI };
  if (po === "not_requested") g.po = { durum: "not_requested", onaylayan: null, zaman: null, kanal: "jira" };
  return g;
}

describe("case üretimi hata ile bitti: yeniden denenir, denetim yeniden başlatılmaz", () => {
  it("'Case üretimini yeniden dene' etkin; tıklanınca generate-cases çağrılır ve gereksinim generating olur", async () => {
    await oturumAc("analist");
    const g = uretimiDusur("approved");
    const spy = vi.spyOn(api, "caseUret");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-tpd-1");
    const dugme = await screen.findByRole("button", { name: "Case üretimini yeniden dene" });
    expect(dugme).toBeEnabled();
    expect(dugme).toHaveAttribute("title", expect.stringMatching(/sunucuda yeniden doğrulanır/));
    // Yeniden denetle ikincil ve yeni PO teyidi gerektirdiğini söyler.
    expect(screen.getByRole("button", { name: "Yeniden denetle" })).toHaveAttribute("title", expect.stringMatching(/yeni PO teyidi/));
    await u.click(dugme);
    await waitFor(() => expect(spy).toHaveBeenCalledWith("req-tpd-1"));
    await waitFor(() => expect(g.durum).not.toBe("failed"));
    expect(["generating", "cases_ready"]).toContain(g.durum);
  });

  it("core failed'da PO onayını göstermese de (not_requested) yeniden deneme açık; PO kartı 'henüz istenmedi' demez", async () => {
    await oturumAc("analist");
    uretimiDusur("not_requested");
    uygulama("/gereksinimler/req-tpd-1");
    expect(await screen.findByRole("button", { name: "Case üretimini yeniden dene" })).toBeEnabled();
    expect(screen.getByTestId("po-uretim-hatasi")).toHaveTextContent("PO teyidi verilmişti");
    expect(screen.queryByText(/Henüz istenmedi/)).not.toBeInTheDocument();
  });

  it("tutarlılık kartı 'denetim tamamlanmadı (iş hata ile bitti)' demez; akış case adımında (4) durur", async () => {
    await oturumAc("analist");
    uretimiDusur("approved");
    uygulama("/gereksinimler/req-tpd-1");
    const kart = await screen.findByRole("region", { name: /Tutarlılık bulguları/ });
    expect(kart).not.toHaveTextContent(DENETIM_HATALI);
    const simdi = document.querySelector('[aria-current="step"]');
    expect(simdi).toHaveTextContent(adimAdi(4));
  });

  it("onaylanan içerik değiştiyse yeniden deneme kapalı; bekleyen PO teyidi de geçersiz", () => {
    const g = uretimiDusur("approved");
    g.icerik_hash = "sha256:yeni";
    g.po = { ...g.po, onaylanan_hash: "sha256:eski" };
    expect(uretimHatasiMi(g)).toBe(true);
    expect(poYenidenDenemedeGecerli(g)).toBe(false);
    expect(poYenidenDenemedeGecerli({ po: { ...g.po, durum: "pending" }, icerik_hash: "" })).toBe(false);
    expect(poYenidenDenemedeGecerli({ po: { ...g.po, durum: "not_requested" }, icerik_hash: "" })).toBe(true);
  });

  it("bosBulguMetni: yalnızca denetim işi (ya da bilinmeyen iş) düştüyse DENETIM_HATALI", () => {
    const temiz = { mode: "replay" as const, bulgu: 0, dogrulanan: 0, elenen: 0, zaman: null };
    const g = (job_tur: string | null) =>
      ({ durum: "failed", kontrol_turu: 1, son_kontrol: temiz, son_hata: { ...URETIM_HATASI, job_tur } }) as unknown as Detay;
    expect(bosBulguMetni(g("cases.generate"), 0, 0)).toBe("Bulgu yok: doküman kod ve veriyle tutarlı.");
    expect(bosBulguMetni(g("requirements.review"), 0, 0)).toBe(DENETIM_HATALI);
    expect(bosBulguMetni(g("requirements.consistency"), 0, 0)).toBe(DENETIM_HATALI);
    expect(bosBulguMetni(g(null), 0, 0)).toBe(DENETIM_HATALI);
    expect(bosBulguMetni(g("bilinmeyen.is"), 0, 0)).toBe(DENETIM_HATALI);
  });

  it("akış adımı: failed + API ipucu yoksa düşen işin adımı", () => {
    expect(akisAdimi("failed", hataAdimi("cases.generate"))).toBe(4);
    expect(akisAdimi("failed", hataAdimi("requirements.review"))).toBe(2);
    expect(akisAdimi("failed", hataAdimi("requirements.po_request"))).toBe(3);
    expect(akisAdimi("failed", hataAdimi(null))).toBe(1);
  });
});

describe("canlı derleme (VITE_MOCK=0): uydurma KPI yok", () => {
  const OPENAPI = {
    paths: {
      "/auth/me": { get: {} },
      "/auth/login": { post: {} },
      "/requirements": { get: {} },
      "/bug-drafts": { get: {} },
      "/audit": { get: {} },
      "/tokens": { get: {} },
      "/events": { get: {} },
    },
  };

  function sahteCore() {
    return vi.fn().mockImplementation((url: string) => {
      const j = (status: number, govde: unknown) =>
        Promise.resolve(new Response(JSON.stringify(govde), { status, headers: { "Content-Type": "application/json" } }));
      if (url === "/api/openapi.json") return j(200, OPENAPI);
      if (url === "/api/auth/me") return j(200, { id: "u1", kullanici_adi: "sunucu", rol: "presenter" });
      if (url.startsWith("/api/requirements")) return j(200, []);
      return j(404, { detail: "Not Found" });
    });
  }

  afterEach(() => vi.unstubAllGlobals());

  it("Kontrol Kulesi: core ucu yoksa 'bu fazda yok' boş durumu; örnek KPI (geçme oranı, kazanç) gösterilmez", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    const f = sahteCore();
    vi.stubGlobal("fetch", f);
    uygulama("/kontrol-kulesi");
    expect(await screen.findByTestId("bu-fazda-yok")).toHaveTextContent("Bu ekran bu fazda yok");
    expect(screen.queryByText(/Kazanç/)).not.toBeInTheDocument();
    expect(screen.queryByText("Geçme oranı")).not.toBeInTheDocument();
    expect(screen.queryByText("ÖRNEK VERİ")).not.toBeInTheDocument();
    // /control-tower'a hiç istek atılmadı (uç listesinde yok).
    expect(f.mock.calls.map((c) => c[0])).not.toContain("/api/control-tower");
  });

  it("menü: core'un sunmadığı ekranlar pasif ('bu fazda yok'), sunulanlar bağlantı", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    vi.stubGlobal("fetch", sahteCore());
    uygulama("/gereksinimler");
    const menu = await screen.findByRole("navigation", { name: "Ana menü" });
    await waitFor(() => expect(within(menu).getByText("Kontrol Kulesi").closest("[aria-disabled]")).toHaveAttribute("aria-disabled", "true"));
    for (const ad of ["Kod üretimi", "Koşular"]) {
      expect(within(menu).getByText(ad).closest("a")).toBeNull();
    }
    for (const ad of ["Gereksinimler", "Bug taslakları", "Denetim"]) {
      expect(within(menu).getByText(ad).closest("a")).not.toBeNull();
    }
  });

  it("HataKutusu: BU_FAZDA_YOK hata değil boş durum olarak çizilir (tekrar dene yok)", () => {
    render(<HataKutusu hata={BU_FAZDA_YOK} yenile={() => {}} />);
    expect(screen.getByTestId("bu-fazda-yok")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tekrar dene" })).not.toBeInTheDocument();
  });

  it("örnek veri modunda da manuel baz değer uydurulmaz: 'ölçülmedi', kazanç yüzdesi yok; tam genişlik ÖRNEK VERİ bandı", async () => {
    await oturumAc("sunucu");
    sar(<KontrolKulesi />);
    // F4: Hazırlık kazancı AI katkısı kartından KPI şeridine taşındı (§5); bölge "AI katkısı" kalır.
    expect(await screen.findByRole("region", { name: "AI katkısı" })).toBeInTheDocument();
    const serit = screen.getByTestId("kule-kpi");
    expect(within(serit).getByText("ölçülmüş baz yok")).toBeInTheDocument();
    expect(serit).not.toHaveTextContent(/Kazanç %/);
    // Uydurma kazanç yüzdesi hiçbir kartta yok (şerit, AI katkısı, hazırlık tablosu dahil tüm sayfa).
    expect(document.body).not.toHaveTextContent(/Kazanç %/);
    expect(screen.getByRole("region", { name: "AI katkısı" })).not.toHaveTextContent(/Kazanç/);
  });

  it("örnek veri (tümü REPLAY): 'Case başına AI + review' ölçülmedi; AI süresi sayı olarak yazılmaz (core eşi)", async () => {
    await oturumAc("sunucu");
    sar(<KontrolKulesi />);
    const ai = await screen.findByRole("region", { name: "AI katkısı" });
    const metrik = within(ai).getByText("Case başına AI + review").closest(".metrik") as HTMLElement;
    expect(within(metrik).getByText(/ölçülmedi/)).toBeInTheDocument();
    expect(metrik).not.toHaveTextContent(/AI \d/);
  });

  it("örnek veri modunda her ekranın üstünde 'ÖRNEK VERİ — gerçek değil' bandı", async () => {
    await oturumAc("sunucu");
    uygulama("/kontrol-kulesi");
    expect(await screen.findByTestId("ornek-veri-bandi")).toHaveTextContent("ÖRNEK VERİ — gerçek değil");
  });
});

describe("case düzeltmesi: 'beklenen sonuç anlamca değişti mi?' insan kararı", () => {
  const taslak = () => mockVerisi().caseler.find((c) => c.id === "case-1-5")!;

  async function duzeltmeyiAc(u: ReturnType<typeof userEvent.setup>) {
    await waitFor(() => expect(screen.getByRole("button", { name: "Düzelt" })).toBeEnabled());
    await u.click(screen.getByRole("button", { name: "Düzelt" }));
  }

  it("beklenen sonuç değişmediyse soru çıkmaz; false gönderilir", async () => {
    await oturumAc("analist");
    const spy = vi.spyOn(api, "caseKarari");
    const u = userEvent.setup();
    sar(<CaseKarti tc={taslak()} guncellendi={() => {}} />);
    await duzeltmeyiAc(u);
    expect(screen.queryByTestId("beklenen-anlam")).not.toBeInTheDocument();
    await u.type(screen.getByLabelText("Başlık"), " (düzeltildi)");
    await u.click(screen.getByRole("button", { name: "Düzeltip onayla" }));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy.mock.calls[0][1]).toMatchObject({ karar: "edit", beklenen_anlam_degisti: false });
  });

  it("beklenen sonuç değiştiyse seçim zorunlu; 'Hayır' → false gönderilir ve kart küçük düzeltme ✓ gösterir", async () => {
    await oturumAc("analist");
    const spy = vi.spyOn(api, "caseKarari");
    let son: TestCase | null = null;
    const u = userEvent.setup();
    const { rerender } = sar(<CaseKarti tc={taslak()} guncellendi={(t) => (son = t)} />);
    await duzeltmeyiAc(u);
    await u.type(screen.getByLabelText("Beklenen sonuç"), ".");
    const soru = screen.getByTestId("beklenen-anlam");
    expect(soru).toHaveTextContent("Beklenen sonuç anlamca değişti mi?");
    await u.click(screen.getByRole("button", { name: "Düzeltip onayla" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Evet ya da Hayır seçin");
    expect(spy).not.toHaveBeenCalled();
    await u.click(within(soru).getByLabelText(/Hayır/));
    await u.click(screen.getByRole("button", { name: "Düzeltip onayla" }));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy.mock.calls[0][1]).toMatchObject({ karar: "edit", beklenen_anlam_degisti: false });
    await waitFor(() => expect(son).not.toBeNull());
    rerender(
      <MemoryRouter>
        <OturumProvider>
          <BildirimProvider>
            <CaseKarti tc={son!} guncellendi={() => {}} />
          </BildirimProvider>
        </OturumProvider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("kucuk-duzeltme")).toHaveTextContent("küçük düzeltme ✓");
  });

  it("'Evet' → true gönderilir; kart küçük düzeltme ✗ ve nedenini gösterir", async () => {
    await oturumAc("analist");
    const spy = vi.spyOn(api, "caseKarari");
    let son: TestCase | null = null;
    const u = userEvent.setup();
    sar(<CaseKarti tc={taslak()} guncellendi={(t) => (son = t)} />);
    await duzeltmeyiAc(u);
    await u.type(screen.getByLabelText("Beklenen sonuç"), ".");
    await u.click(within(screen.getByTestId("beklenen-anlam")).getByLabelText(/Evet/));
    await u.click(screen.getByRole("button", { name: "Düzeltip onayla" }));
    await waitFor(() => expect(son).not.toBeNull());
    expect(spy.mock.calls[0][1]).toMatchObject({ beklenen_anlam_degisti: true });
    expect(son!.kucuk_duzeltme).toBe(false);
    expect(kucukDuzeltmeDurumu(son!)).toEqual({ kucuk: false, neden: "beklenen sonuç anlamca değişti" });
  });

  it("küçük düzeltme nedeni: core bayrağı yoksa ölçüden; ölçü eşiği aşılırsa 'ölçü > 0,15'", () => {
    expect(kucukDuzeltmeDurumu({ kucuk_duzeltme: undefined, duzeltme_olcusu: 0.3, duzeltme_nedeni: null })).toEqual({
      kucuk: false,
      neden: "ölçü > 0,15",
    });
    expect(kucukDuzeltmeDurumu({ kucuk_duzeltme: false, duzeltme_olcusu: 0.047, duzeltme_nedeni: null }).neden).toBe(
      "beklenen sonuç anlamca değişti",
    );
    expect(kucukDuzeltmeDurumu({ kucuk_duzeltme: true, duzeltme_olcusu: 0.047, duzeltme_nedeni: null }).kucuk).toBe(true);
  });
});
