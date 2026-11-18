// Rol/izin modeli v2 ekranları (specs/012-rol-yetki/ANALIZ.md §5–§6): case inceleme Test Uzmanı kararı →
// Analist son onayı, developer salt okunur, demo kontrolleri yalnız demo kipinde.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { mockOrtam, mockVerisi } from "../api/mock/handlers";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
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

const CASELER = "/gereksinimler/req-tpd-1/caseler";
const kart = (sira: number) => screen.getAllByRole("article").find((a) => within(a).queryByText(new RegExp(`^#${sira}$`)))!;

describe("case inceleme: Test Uzmanı kararı → Analist son onayı", () => {
  it("Test Uzmanı taslağı kabul eder → 'Onaya hazır'; Analist onaylar → 'Onaylı'", async () => {
    await oturumAc("testci");
    const u = userEvent.setup();
    const ilk = uygulama(CASELER);
    await screen.findAllByRole("article");
    // Test Uzmanı yayın önizlemesine gider (case.publish).
    expect(screen.getByRole("link", { name: "Yayın önizleme" })).toBeInTheDocument();
    const k = kart(6);
    await waitFor(() => expect(within(k).getByRole("button", { name: "Kabul et" })).toBeEnabled());
    expect(within(k).queryByRole("button", { name: "Onayla" })).toBeNull();
    await u.click(within(k).getByRole("button", { name: "Kabul et" }));
    await waitFor(() => expect(within(k).getByText("Onaya hazır")).toBeInTheDocument());
    expect(within(k).queryByRole("button", { name: "Onayla" })).toBeNull();
    expect(mockVerisi().caseler.find((c) => c.id === "case-1-7")!.durum).toBe("ready");
    ilk.unmount();

    await oturumAc("analist");
    uygulama(CASELER);
    await screen.findAllByRole("article");
    expect(screen.getByText(/Onaya hazır \(1\)/)).toBeInTheDocument();
    const k2 = kart(6);
    // Analist Test Uzmanı kararlarını veremez; yayın önizlemesini salt okunur görür (publish.preview).
    expect(within(kart(7)).queryByRole("button", { name: "Kabul et" })).toBeNull();
    expect(screen.getByRole("link", { name: "Yayın önizleme" })).toBeInTheDocument();
    await waitFor(() => expect(within(k2).getByRole("button", { name: "Onayla" })).toBeEnabled());
    await u.click(within(k2).getByRole("button", { name: "Onayla" }));
    await waitFor(() => expect(within(k2).getByText("Onaylı")).toBeInTheDocument());
    expect(mockVerisi().caseler.find((c) => c.id === "case-1-7")).toMatchObject({ durum: "approved", testci: "testci", son_onay: { karar: "approve", veren: "analist" } });
    // Kart: Test Uzmanı kararı ve Analist son onayı ayrı etiketli satırlarda.
    expect(within(k2).getByTestId("case-testci-karari")).toHaveTextContent(/Test Uzmanı kararı:.*kabul.*Fatih Arslan/);
    expect(within(k2).getByTestId("case-son-onay")).toHaveTextContent(/Analist son onayı:.*onaylandı.*Cengizhan Gunaydin/);
  });

  it("Analist gerekçeyle geri gönderir → case taslağa döner ve gerekçe kartta görünür", async () => {
    const c = mockVerisi().caseler.find((x) => x.id === "case-1-7")!;
    c.durum = "ready";
    c.karar = "accept";
    c.testci_karari = "accept";
    c.karar_veren = "testci";
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama(CASELER);
    await screen.findAllByRole("article");
    const k = kart(6);
    await waitFor(() => expect(within(k).getByRole("button", { name: "Geri gönder" })).toBeEnabled());
    await u.click(within(k).getByRole("button", { name: "Geri gönder" }));
    await u.type(within(k).getByLabelText("Geri gönderme gerekçesi"), "Adım 3 beklenen sonucu eksik");
    await u.click(within(within(k).getByTestId("geri-gonder-formu")).getByRole("button", { name: "Geri gönder" }));
    await waitFor(() => expect(within(k).getByTestId("case-geri-gonderildi")).toHaveTextContent("Adım 3 beklenen sonucu eksik"));
    expect(within(k).getByText("Karar bekliyor")).toBeInTheDocument();
  });

  it("Geliştirici: salt okunur; yalnız onaylı/yayınlanmış case, özet ve karar düğmesi yok", async () => {
    await oturumAc("gelistirici");
    uygulama(CASELER);
    expect(await screen.findByText("Salt okunur görünüm")).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByRole("article").length).toBeGreaterThan(0));
    const durumlar = screen.getAllByRole("article").map((a) => a.className);
    expect(durumlar.every((s) => /case-(approved|published)/.test(s))).toBe(true);
    expect(screen.queryByRole("region", { name: "Özet" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Case filtresi" })).toBeNull();
    for (const a of screen.getAllByRole("article")) expect(within(a).queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "Yayın önizleme" })).toBeNull();
  });
});

describe("demo kontrolleri: ekran demo.read, eylemler admin + engineer, yalnız demo kipinde", () => {
  it("Test Uzmanı demo ekranını salt-okur görür; eylemler pasif ve gereken rolü söyler (demo.manage)", async () => {
    await oturumAc("testci");
    uygulama("/demo");
    expect(await screen.findByRole("heading", { name: "Demo kontrolleri", level: 1 })).toBeInTheDocument();
    expect(screen.queryByText("Bu ekran için yetkiniz yok.")).toBeNull();
    expect(await screen.findByText("Salt okunur görünüm")).toBeInTheDocument();
    const satirlar = await screen.findAllByText("Bu adım Otomasyon Mühendisi rolünde: Gokhan Sipahi bekleniyor");
    expect(satirlar.length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByRole("button", { name: "Demo'yu sıfırla" })).toBeNull();
    expect(screen.getByLabelText("Story")).toBeDisabled();
  });

  it("Geliştirici demo ekranına giremez (demo.read yok)", async () => {
    await oturumAc("gelistirici");
    uygulama("/demo");
    expect(await screen.findByText("Bu ekran için yetkiniz yok.")).toBeInTheDocument();
  });

  it("demo kipi kapalıyken kontroller yerine 'Demo kontrolleri kapalı' notu", async () => {
    mockOrtam.demoModu = false;
    mockOrtam.ortam = "staging";
    await oturumAc("muhendis");
    uygulama("/demo");
    expect(await screen.findByText("Demo kontrolleri kapalı")).toBeInTheDocument();
    expect(screen.getByText("staging")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Demo'yu sıfırla" })).toBeNull();
  });

  it("TP3-1: demo projesi olmayan projede 'Bu projede demo yok'; menüde demo öğeleri yok", async () => {
    mockOrtam.demoProjesi = false;
    await oturumAc("sunucu");
    uygulama("/demo");
    expect(await screen.findByText("Bu projede demo yok")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Demo'yu sıfırla" })).toBeNull();
    const menu = screen.getByRole("navigation", { name: "Ana menü" });
    await waitFor(() => expect(within(menu).queryByRole("link", { name: /Demo kontrolleri/ })).toBeNull());
    expect(within(menu).queryByRole("link", { name: /Demo yol haritası/ })).toBeNull();
  });

  it("demo kipinde Sistem Yöneticisi kontrolleri görür", async () => {
    await oturumAc("sunucu");
    uygulama("/demo");
    expect(await screen.findByRole("heading", { name: "Demo kontrolleri", level: 1 })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Demo kontrolleri kapalı")).toBeNull());
    expect(screen.queryByText("Bu ekran için yetkiniz yok.")).toBeNull();
  });
});
