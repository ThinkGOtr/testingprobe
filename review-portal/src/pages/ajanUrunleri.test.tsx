// Agent Probe ajan ürünleri (011 F6, K10): ürün sayfası, gereksinimi ajan ürününe bağlama, case
// akışının kapanması, ajan testi talebinin ilerlemesi ve sonucu (mock; simülasyon açıkça yazılı).
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ApiError } from "../api/http";
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
  });

  it("menüde bağlantısı var", async () => {
    await oturumAc("analist");
    uygulama("/gereksinimler");
    const menu = await screen.findByRole("navigation", { name: "Ana menü" }, T);
    expect(within(menu).getByRole("link", { name: /Ajan ürünleri/ })).toHaveAttribute("href", "/ajan-urunleri");
  });
});

describe("mock Agent Probe: talep ilerlemesi ve case üretimi engeli", { timeout: 60000 }, () => {
  it("bağlı gereksinimde generate-cases 409 ajan_urunu; talep queued → running → failed (kredi ajanı)", async () => {
    await oturumAc("analist");
    poOnayli();
    await api.ajanUrunuBagla(RID, "kredi-danismani");
    const hata = await api.caseUret(RID).catch((e: unknown) => e);
    expect(hata).toBeInstanceOf(ApiError);
    expect((hata as ApiError).status).toBe(409);
    expect((hata as ApiError).kod).toBe("ajan_urunu");

    const ilk = await api.ajanTestiBaslat(RID);
    expect(ilk.talep).toMatchObject({ durum: "queued", simulasyon: true });
    expect(ilk.talep!.talep_no).toMatch(/^APT-\d{4}-\d+$/);
    expect(ilk.baslatilabilir).toBe(false);
    expect((await api.ajanTesti(RID)).talep!.durum).toBe("running");
    const son = await api.ajanTesti(RID);
    expect(son.talep).toMatchObject({ durum: "failed", surec: "bulgu", sonuc: { toplam: 4, gecen: 2, kalan: 2 } });
    expect(son.baslatilabilir).toBe(true);
  });

  it("hazır olmayan ürün bağlanamaz (409 ajan_urunu_baglanamaz); yalnız analist bağlar", async () => {
    await oturumAc("analist");
    const e = await api.ajanUrunuBagla(RID, "kampanya-onerici").catch((x: unknown) => x);
    expect((e as ApiError).kod).toBe("ajan_urunu_baglanamaz");
    await oturumAc("po");
    const y = await api.ajanUrunuBagla(RID, "destek-asistani").catch((x: unknown) => x);
    expect((y as ApiError).status).toBe(403);
  });
});

describe("gereksinim detayı: Ürün AI ajanı", { timeout: 90000 }, () => {
  it("bağlanınca case üretimi kapanır (nedenli), Agent Probe'da test başlar ve sonuç görünür", async () => {
    await oturumAc("analist");
    poOnayli();
    const u = userEvent.setup();
    const { unmount } = uygulama(`/gereksinimler/${RID}`);
    const kart = (await screen.findByRole("heading", { name: "Ürün AI ajanı" }, T)).closest("section")!;
    const secim = await within(kart as HTMLElement).findByLabelText("Ajan ürünü", undefined, T);
    await waitFor(() => expect(within(secim).getAllByRole("option")).toHaveLength(3), T);
    await u.selectOptions(secim, "destek-asistani");
    await u.click(within(kart as HTMLElement).getByRole("button", { name: "Ürün AI ajanı olarak bağla" }));
    await within(kart as HTMLElement).findByText("Müşteri destek asistanı", undefined, T);

    await waitFor(() => expect(screen.getByRole("button", { name: "Case üret" })).toBeDisabled(), T);
    expect(screen.getByRole("button", { name: "Case üret" })).toHaveAttribute("title", AJAN_URUNU_NEDENI);

    await u.click(within(kart as HTMLElement).getByRole("button", { name: "Agent Probe'da test başlat" }));
    const talep = await within(kart as HTMLElement).findByTestId("ajan-talep", undefined, T);
    expect(talep).toHaveTextContent("Kuyrukta");
    expect(within(talep).getByText("Simülasyon")).toBeInTheDocument();
    unmount();

    // Agent Probe tarafı ilerler (iki sorgu) → sayfa yeniden açılınca sonuç ve süreç notu.
    await api.ajanTesti(RID);
    await api.ajanTesti(RID);
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
    await api.ajanTestiBaslat(RID);
    await api.ajanTesti(RID);
    uygulama(`/gereksinimler/${RID}`);
    const bulgular = await screen.findByTestId("ajan-bulgular", undefined, T);
    expect(bulgular).toHaveTextContent("Başka bayinin verisini isteme");
    expect(bulgular).toHaveTextContent("Kaynakta olmayan faiz oranı");
    expect(bulgular).not.toHaveTextContent("Limit sorgusu");
  });
});
