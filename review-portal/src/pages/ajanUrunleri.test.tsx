// Agent Probe ajan ürünleri (011 F6, K10): ürün sayfası, gereksinimi ajan ürününe bağlama, case
// akışının kapanması, ajan testi talebinin ilerlemesi ve sonucu (mock; simülasyon açıkça yazılı).
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ApiError, yapilandir } from "../api/http";
import { mockVerisi } from "../api/mock/handlers";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { AJAN_URUNU_NEDENI } from "../lib/ajanProbe";
import { oturumAc } from "../test/yardimci";

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

const RID = "req-ft-1";
// Yük altındaki makinede (paralel derlemeler) ilk çizim yavaş olabilir.
const T = { timeout: 20000 };

function poOnayli() {
  const g = mockVerisi().gereksinimler.find((x) => x.id === RID)!;
  g.durum = "po_approved";
  g.ac_missing = false;
  g.po = { ...g.po, durum: "approved", onaylayan: "po", zaman: "2026-11-11T10:00:00Z", kanal: "portal", onaylanan_hash: g.icerik_hash };
  return g;
}

describe("Ajan ürünleri sayfası", { timeout: 60000 }, () => {
  it("yalnız hazır ürünleri listeler ve simülasyonu açıkça söyler", async () => {
    await oturumAc("analist");
    uygulama("/ajan-urunleri");
    const tablo = await screen.findByRole("table", undefined, T);
    expect(within(tablo).getByText("Müşteri destek asistanı")).toBeInTheDocument();
    expect(within(tablo).getByText("kredi-danismani")).toBeInTheDocument();
    expect(within(tablo).queryByText("kampanya-onerici")).toBeNull();
    expect(within(tablo).getAllByRole("row")).toHaveLength(3); // başlık + 2 hazır ürün
    expect(screen.getByText("Simülasyon")).toBeInTheDocument();
    expect(screen.getByTestId("simulasyon-aciklamasi")).toHaveTextContent(/simüle edilir/);
    // Simülasyon açıklaması sayfada tek yerde (tekrar eden paragraf yok).
    expect(screen.getAllByText(/Agent Probe bu sürümde simüle edilir/)).toHaveLength(1);
  });

  it("'Bağlı gereksinim' sütunu: bağlı gereksinim bağlantı, yoksa '—'", async () => {
    await oturumAc("analist");
    await api.ajanUrunuBagla(RID, "kredi-danismani");
    uygulama("/ajan-urunleri");
    const tablo = await screen.findByRole("table", undefined, T);
    expect(within(tablo).getByRole("columnheader", { name: "Bağlı gereksinim" })).toBeInTheDocument();
    const kredi = within(tablo).getByRole("row", { name: /Kredi ön değerlendirme ajanı/ });
    const g = mockVerisi().gereksinimler.find((x) => x.id === RID)!;
    expect(within(kredi).getByRole("link", { name: g.jira_key ?? g.baslik })).toHaveAttribute("href", `/gereksinimler/${RID}`);
    const destek = within(tablo).getByRole("row", { name: /Müşteri destek asistanı/ });
    expect(within(destek).getByTestId("bagli-gereksinim-yok")).toHaveTextContent("Bağlı gereksinim yok");
  });

  it("core alanı sunmuyorsa sütun '—' gösterir", async () => {
    await oturumAc("analist");
    vi.spyOn(api, "ajanUrunleri").mockResolvedValue({
      kip: "sim",
      simulasyon: true,
      urunler: [{ kod: "x", ad: "Eski ürün", aciklama: "a", hazir: true }],
    });
    uygulama("/ajan-urunleri");
    const tablo = await screen.findByRole("table", undefined, T);
    expect(within(tablo).getByTestId("bagli-gereksinim-yok")).toBeInTheDocument();
    vi.restoreAllMocks();
  });

  it("menüde bağlantısı var", async () => {
    await oturumAc("analist");
    uygulama("/gereksinimler");
    const menu = await screen.findByRole("navigation", { name: "Ana menü" }, T);
    expect(within(menu).getByRole("link", { name: /Ajan ürünleri/ })).toHaveAttribute("href", "/ajan-urunleri");
  });
});

describe("mock Agent Probe: talep ilerlemesi ve case üretimi engeli", { timeout: 60000 }, () => {
  it("bağlı gereksinimde generate-cases 409 ajan_urunu; talep refresh ile queued → running → failed (kredi ajanı)", async () => {
    // 012: bağlama Analistin (`requirement.review`); case üretimi ve ajan testi Testçinin.
    await oturumAc("analist");
    poOnayli();
    await api.ajanUrunuBagla(RID, "kredi-danismani");
    await expect(api.ajanTestiBaslat(RID)).rejects.toMatchObject({ status: 403 });
    await oturumAc("testci");
    const hata = await api.caseUret(RID).catch((e: unknown) => e);
    expect(hata).toBeInstanceOf(ApiError);
    expect((hata as ApiError).status).toBe(409);
    expect((hata as ApiError).kod).toBe("ajan_urunu");

    const ilk = await api.ajanTestiBaslat(RID);
    expect(ilk.talep).toMatchObject({ durum: "queued", simulasyon: true });
    expect(ilk.talep!.talep_no).toMatch(/^APT-\d{4}-\d+$/);
    expect(ilk.baslatilabilir).toBe(false);
    // D4: GET yalnız okur; sonuç işleme POST …/agent-test/refresh ile.
    expect((await api.ajanTesti(RID)).talep!.durum).toBe("queued");
    expect((await api.ajanTestiYenile(RID)).talep!.durum).toBe("running");
    const son = await api.ajanTestiYenile(RID);
    expect(son.talep).toMatchObject({ durum: "failed", surec: "bulgu", sonuc: { toplam: 4, gecen: 2, kalan: 2 } });
    expect(son.baslatilabilir).toBe(true);
  });

  it("hazır olmayan ürün bağlanamaz (409 ajan_urunu_baglanamaz); yalnız analist bağlar", async () => {
    await oturumAc("analist");
    const e = await api.ajanUrunuBagla(RID, "kampanya-onerici").catch((x: unknown) => x);
    expect((e as ApiError).kod).toBe("ajan_urunu_baglanamaz");
    for (const rol of ["po", "testci"]) {
      await oturumAc(rol);
      const y = await api.ajanUrunuBagla(RID, "destek-asistani").catch((x: unknown) => x);
      expect((y as ApiError).status).toBe(403);
    }
  });
});

describe("gereksinim detayı: Ürün AI ajanı", { timeout: 90000 }, () => {
  it("bağlanınca case üretimi kapanır (nedenli), Agent Probe'da test başlar ve sonuç görünür", async () => {
    await oturumAc("analist");
    poOnayli();
    const u = userEvent.setup();
    const { unmount } = uygulama(`/gereksinimler/${RID}`);
    const kart = (await screen.findByRole("heading", { name: "Ürün AI ajanı" }, T)).closest("section")!;
    // Bağlı değilken tek satırlık özet; bağlama formu "Bağla" ile açılır (UX-11).
    const bagla = within(kart as HTMLElement).getByRole("button", { name: "Bağla" });
    expect(bagla).toHaveAttribute("aria-expanded", "false");
    expect(within(kart as HTMLElement).getByTestId("ajan-ozet")).toHaveTextContent("bağlı değil");
    expect(within(kart as HTMLElement).queryByLabelText("Ajan ürünü")).toBeNull();
    await u.click(bagla);
    expect(bagla).toHaveAttribute("aria-expanded", "true");
    const secim = await within(kart as HTMLElement).findByLabelText("Ajan ürünü", undefined, T);
    await waitFor(() => expect(within(secim).getAllByRole("option")).toHaveLength(3), T);
    await u.selectOptions(secim, "destek-asistani");
    await u.click(within(kart as HTMLElement).getByRole("button", { name: "Ürün AI ajanı olarak bağla" }));
    await within(kart as HTMLElement).findByText("Müşteri destek asistanı", undefined, T);
    // Analist ajan testini başlatamaz (`agent_test.run` Testçinin): düğme yetkisiz.
    expect(within(kart as HTMLElement).getByRole("button", { name: "Agent Probe'da test başlat" })).toBeDisabled();
    unmount();

    await oturumAc("testci");
    const ikinci = uygulama(`/gereksinimler/${RID}`);
    const kart2 = (await screen.findByRole("heading", { name: "Ürün AI ajanı" }, T)).closest("section")! as HTMLElement;
    await waitFor(() => expect(screen.getByRole("button", { name: "Tasarım modelini üret (iki tur)" })).toBeDisabled(), T);
    expect(screen.getByRole("button", { name: "Tasarım modelini üret (iki tur)" })).toHaveAttribute("title", AJAN_URUNU_NEDENI);

    await waitFor(() => expect(within(kart2).getByRole("button", { name: "Agent Probe'da test başlat" })).toBeEnabled(), T);
    await u.click(within(kart2).getByRole("button", { name: "Agent Probe'da test başlat" }));
    const talep = await within(kart2).findByTestId("ajan-talep", undefined, T);
    expect(talep).toHaveTextContent("Kuyrukta");
    expect(within(talep).getByText("Simülasyon")).toBeInTheDocument();
    ikinci.unmount();

    // Agent Probe tarafı ilerler (iki refresh) → sayfa yeniden açılınca sonuç ve süreç notu.
    await api.ajanTestiYenile(RID);
    await api.ajanTestiYenile(RID);
    uygulama(`/gereksinimler/${RID}`);
    const sonuc = await screen.findByTestId("ajan-talep", undefined, T);
    expect(sonuc).toHaveTextContent("Geçti");
    expect(screen.getByTestId("ajan-sayilar")).toHaveTextContent("Toplam 3 senaryo · geçen 3 · kalan 0");
    expect(sonuc).toHaveTextContent(/gereksinim tamamlandı/);
    expect(within(sonuc).getByRole("link", { name: /Agent Probe'da aç \(temsili\)/ })).toBeInTheDocument();
  });

  it("kalan senaryolar bulgu olarak listelenir", async () => {
    await oturumAc("analist");
    poOnayli();
    await api.ajanUrunuBagla(RID, "kredi-danismani");
    await oturumAc("testci");
    await api.ajanTestiBaslat(RID);
    await api.ajanTestiYenile(RID);
    await api.ajanTestiYenile(RID);
    uygulama(`/gereksinimler/${RID}`);
    const bulgular = await screen.findByTestId("ajan-bulgular", undefined, T);
    expect(bulgular).toHaveTextContent("Başka bayinin verisini isteme");
    expect(bulgular).toHaveTextContent("Kaynakta olmayan faiz oranı");
    expect(bulgular).not.toHaveTextContent("Limit sorgusu");
  });
});

describe("ajan testi yenileme: POST refresh, yoksa eski GET (D4)", () => {
  const yanit = (status: number, govde: unknown) =>
    new Response(JSON.stringify(govde), { status, headers: { "Content-Type": "application/json" } });
  const GORUNUM = { requirement_id: "r1", urun_kodu: "k", talep: null, gecmis: [], simulasyon: true, baslatilabilir: true, engel: null };
  afterEach(() => vi.unstubAllGlobals());

  it("refresh ucu varsa yalnız POST", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: false });
    const f = vi.fn().mockImplementation(() => Promise.resolve(yanit(200, GORUNUM)));
    vi.stubGlobal("fetch", f);
    expect(await api.ajanTestiYenile("r1")).toMatchObject({ urun_kodu: "k" });
    expect(f.mock.calls.map((c) => [(c[1] as RequestInit).method, c[0]])).toEqual([["POST", "/api/requirements/r1/agent-test/refresh"]]);
  });

  it.each([404, 405])("refresh %i dönerse eski GET ile devam eder", async (kod) => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: false });
    const f = vi.fn().mockImplementation((_url: string, init: RequestInit) =>
      Promise.resolve(init.method === "POST" ? yanit(kod, { detail: kod === 405 ? "Method Not Allowed" : "Not Found" }) : yanit(200, GORUNUM)),
    );
    vi.stubGlobal("fetch", f);
    expect(await api.ajanTestiYenile("r1")).toMatchObject({ urun_kodu: "k" });
    expect(f.mock.calls.map((c) => [(c[1] as RequestInit).method, c[0]])).toEqual([
      ["POST", "/api/requirements/r1/agent-test/refresh"],
      ["GET", "/api/requirements/r1/agent-test"],
    ]);
  });

  it("başka hata (ör. 409) geri dönüş yapmaz", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: false });
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(yanit(409, { detail: "Süren talep yok." }))));
    await expect(api.ajanTestiYenile("r1")).rejects.toMatchObject({ status: 409 });
  });
});
