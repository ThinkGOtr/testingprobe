// Platform başına depo (aip-review/platform-depo ANALIZ §7 Şerit T3): uyarlayıcıların `depo`/`depo_adi`
// okuması, PR eylemlerinin `?depo=` taşıması (varsayılan depoda sorgu yok), depo çipi (yalnız
// varsayılan dışı depoda), mock PR eşleşmesinin depo ile yapılması ve platform bazlı gece özeti.
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api, prDepoSorgusu } from "../api/client";
import { ApiError, yapilandir } from "../api/http";
import { ayar, mockVerisi } from "../api/mock/handlers";
import { ANDROID_DEPOSU } from "../api/mock/platformlar";
import type { Kosu } from "../api/types";
import { depoAlanlari, kosuUyarla, prUyarla, scriptUyarla } from "../api/uyumDemoB";
import { onarimUyarla } from "../api/uyumTriage";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { DepoCipi, depoGosterimi } from "../components/Depo";
import { oturumAc } from "../test/yardimci";
import { geceOzeti, GeceOzeti } from "./Kosular";

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

describe("uyarlayıcılar: depo / depo_adi", () => {
  it("alan yoksa '' ve null (eski core: tek depo)", () => {
    expect(depoAlanlari({})).toEqual({ depo: "", depo_adi: null });
    expect(prUyarla({ number: 3 })).toMatchObject({ depo: "", depo_adi: null });
    const k = kosuUyarla({ id: "r1", tetik: "nightly" });
    expect(k.depo).toBe("");
  });

  it("ayrı depo: depo_adi yoksa sahip/ad gösterim adıdır", () => {
    expect(depoAlanlari({ depo: "acme/mobil" })).toEqual({ depo: "acme/mobil", depo_adi: "acme/mobil" });
    expect(depoAlanlari({ depo: "acme/mobil", depo_adi: "Acme/Mobil" })).toEqual({ depo: "acme/mobil", depo_adi: "Acme/Mobil" });
  });

  it("koşu: core `depo` yoksa `ortam.depo`", () => {
    const k = kosuUyarla({ id: "r2", tetik: "nightly", ortam: { platform: "android", depo: "acme/mobil" } });
    expect(k).toMatchObject({ platform: "android", depo: "acme/mobil", depo_adi: "acme/mobil" });
    // Üst düzey alan önce gelir.
    expect(kosuUyarla({ id: "r3", depo: "", ortam: { depo: "acme/mobil" } }).depo).toBe("");
  });

  it("script: depo script'ten; gömülü PR'da depo yoksa script'inki PR'a yazılır", () => {
    const s = scriptUyarla({ id: "s1", platform: "android", depo: "acme/mobil", pr: { number: 7, branch: "tp/case-android-x" } });
    expect(s.depo).toBe("acme/mobil");
    expect(s.pr).toMatchObject({ number: 7, depo: "acme/mobil" });
    // PR'ın kendi deposu öncelikli; script alanı yoksa PR'dan alınır.
    const s2 = scriptUyarla({ id: "s2", pr: { number: 8, depo: "acme/ios" } });
    expect(s2.depo).toBe("acme/ios");
    expect(s2.pr?.depo).toBe("acme/ios");
    // pr_no'dan kurulan PR da script'in deposunu alır.
    expect(scriptUyarla({ id: "s3", pr_no: 9, depo: "acme/win" }).pr?.depo).toBe("acme/win");
  });

  it("onarım PR'ı (pr_no biçimi) depo taşır", () => {
    const o = onarimUyarla({ tur: "locator_fix", pr_no: 4, branch: "tp/fix", depo: "acme/mobil" });
    expect(o.pr?.depo).toBe("acme/mobil");
  });
});

describe("depo çipi", () => {
  it("yalnız varsayılan dışı depoda çizilir", () => {
    expect(depoGosterimi({ depo: "" })).toBeNull();
    expect(depoGosterimi(null)).toBeNull();
    expect(depoGosterimi({ depo: "acme/mobil", depo_adi: null })).toBe("acme/mobil");
    const { container, rerender } = render(<DepoCipi kaynak={{ depo: "", depo_adi: "acme/web" }} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<DepoCipi kaynak={{ depo: "acme/mobil", depo_adi: "acme/mobil" }} />);
    expect(screen.getByTestId("depo-cipi")).toHaveTextContent("Depo: acme/mobil");
  });
});

describe("istemci: /prs/{n}/…?depo=", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("varsayılan depoda sorgu yok; ayrı depoda ?depo= eklenir", async () => {
    expect(prDepoSorgusu("")).toBeUndefined();
    expect(prDepoSorgusu(null)).toBeUndefined();
    expect(prDepoSorgusu(" acme/mobil ")).toEqual({ depo: "acme/mobil" });
    yapilandir({ mockZorunlu: false });
    const f = vi.fn().mockImplementation(() => Promise.resolve(new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } })));
    vi.stubGlobal("fetch", f);
    const sha = "a".repeat(40);
    const cagrilar: [() => Promise<unknown>, string][] = [
      [() => api.prBirlestir({ number: 12, icerik_hash: "h", head_sha: sha }), "/api/prs/12/merge"],
      [() => api.prBirlestir({ number: 12, depo: "", icerik_hash: "h", head_sha: sha }), "/api/prs/12/merge"],
      [() => api.prBirlestir({ number: 12, depo: "acme/mobil", icerik_hash: "h", head_sha: sha }), "/api/prs/12/merge?depo=acme%2Fmobil"],
      [() => api.prDaliGuncelle(5), "/api/prs/5/update-branch"],
      [() => api.prDaliGuncelle(5, "acme/mobil"), "/api/prs/5/update-branch?depo=acme%2Fmobil"],
      [
        () => api.prReview(6, { karar: "reddet", ret_nedeni: "duplicate", icerik_hash: "h", head_sha: sha }, "acme/mobil"),
        "/api/prs/6/review?depo=acme%2Fmobil",
      ],
    ];
    for (const [fn, url] of cagrilar) {
      f.mockClear();
      await fn().catch(() => undefined);
      const urller = f.mock.calls.map((c) => c[0] as string).filter((u) => u.startsWith("/api/prs/"));
      expect(urller).toEqual([url]);
    }
  });
});

describe("mock: PR depo ile eşleşir", () => {
  it("Android PR'ı ayrı depoda: depo olmadan bulunmaz, ?depo= ile birleşir", async () => {
    await oturumAc("muhendis");
    const s = mockVerisi().scriptler.find((x) => x.id === "scr-and")!;
    expect(s.depo).toBe(ANDROID_DEPOSU);
    expect(s.pr?.depo).toBe(ANDROID_DEPOSU);
    const pr = s.pr!;
    await expect(api.prDaliGuncelle(pr.number)).rejects.toSatisfy((e: unknown) => e instanceof ApiError && e.status === 404);
    await expect(api.prDaliGuncelle(pr.number, pr.depo)).resolves.toMatchObject({ durum: "queued" });
  });

  it("varsayılan depodaki PR (iOS) depo sorgusu olmadan bulunur", async () => {
    await oturumAc("muhendis");
    const pr = mockVerisi().scriptler.find((x) => x.id === "scr-ios")!.pr!;
    expect(pr.depo ?? "").toBe("");
    await expect(api.prDaliGuncelle(pr.number)).resolves.toMatchObject({ durum: "queued" });
  });
});

const kosuOrnegi = (id: string, ek: Partial<Kosu>): Kosu =>
  ({
    id,
    tetik: "nightly",
    kaynak: "github",
    commit: "abc",
    pr_no: null,
    durum: "passed",
    baslangic: "2026-11-17T02:00:00Z",
    sure_ms: 1000,
    toplam: 3,
    gecen: 3,
    basarisiz: 0,
    flaky: 0,
    atlanan: 0,
    allure_url: null,
    rapor_url: null,
    sauce_url: null,
    ci_url: null,
    break_campaign: false,
    script_id: null,
    saglik_hatasi: null,
    depo: "",
    depo_adi: null,
    ...ek,
  }) as Kosu;

describe("gece koşusu: platform bazlı", () => {
  it("platform başına en son gece koşusu; platformsuz ve gece dışı koşu atlanır", () => {
    const kosular = [
      kosuOrnegi("w1", { platform: "web", baslangic: "2026-11-16T02:00:00Z" }),
      kosuOrnegi("w2", { platform: "web", baslangic: "2026-11-17T02:00:00Z", durum: "failed" }),
      kosuOrnegi("a1", { platform: "android", depo: "acme/mobil", depo_adi: "acme/mobil" }),
      kosuOrnegi("x", { platform: null }),
      kosuOrnegi("p", { platform: "ios", tetik: "pr" }),
    ];
    const o = geceOzeti(kosular)!;
    expect(o.map((x) => [x.platform, x.kosu.id])).toEqual([
      ["web", "w2"],
      ["android", "a1"],
    ]);
  });

  it("tek platform + varsayılan depo: özet yok (ekran bugünküyle aynı)", () => {
    expect(geceOzeti([kosuOrnegi("w1", { platform: "web" })])).toBeNull();
    expect(geceOzeti([])).toBeNull();
    // Tek platform ama ayrı depo: özet var.
    expect(geceOzeti([kosuOrnegi("a1", { platform: "android", depo: "acme/mobil" })])).toHaveLength(1);
  });

  it("tablo: platform, depo (varsayılan depo yazılır), durum ve koşu bağlantısı", () => {
    render(
      <MemoryRouter>
        <GeceOzeti
          kosular={[
            kosuOrnegi("w1", { platform: "web" }),
            kosuOrnegi("a1", { platform: "android", depo: "acme/mobil", depo_adi: "acme/mobil", durum: "failed", gecen: 1 }),
          ]}
        />
      </MemoryRouter>,
    );
    const tablo = screen.getByTestId("gece-ozeti");
    const satirlar = within(tablo).getAllByRole("row").slice(1);
    expect(satirlar[0]).toHaveTextContent("Web");
    expect(satirlar[0]).toHaveTextContent("Varsayılan depo");
    expect(satirlar[1]).toHaveTextContent("Android");
    expect(satirlar[1]).toHaveTextContent("acme/mobil");
    expect(satirlar[1]).toHaveTextContent("1/3");
    expect(within(satirlar[1]).getByRole("link", { name: "a1" })).toHaveAttribute("href", "/kosular/a1");
  });
});

describe("ekranlar (mock)", () => {
  it("Script detayı: Android script'inde depo çipi (başlık + PR kartı)", async () => {
    await oturumAc("muhendis");
    uygulama("/kod/scr-and");
    await screen.findByRole("list", { name: "Ajan adımları" });
    const cipler = screen.getAllByTestId("depo-cipi");
    expect(cipler.length).toBeGreaterThanOrEqual(2);
    cipler.forEach((c) => expect(c).toHaveTextContent(ANDROID_DEPOSU));
  });

  it("web script'inde depo çipi yok", async () => {
    await oturumAc("muhendis");
    uygulama("/kod/scr-2");
    await screen.findByRole("heading", { name: "Ajan adımları (Playwright MCP)" });
    expect(screen.queryByTestId("depo-cipi")).toBeNull();
  });

  it("Koşular: Android gece koşusu ayrı depoda → platform bazlı gece özeti", async () => {
    await oturumAc("muhendis");
    uygulama("/kosular");
    const tablo = await screen.findByTestId("gece-ozeti");
    expect(tablo).toHaveTextContent("Android");
    expect(tablo).toHaveTextContent(ANDROID_DEPOSU);
  });
});
