// Hakan geri bildirimi (2026-11-09): (1) story'den bağımsız "Test case'leri" ekranı,
// (2) Kod üretimi / Koşular yalnız mühendis ve sunucuya görünür (menü + liste rotası).
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { OturumProvider, varsayilanSayfa } from "../auth";
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

const menu = () => screen.getByRole("navigation", { name: "Ana menü" });

describe("Test case'leri ekranı", () => {
  it("tüm story'lerin güncel case'lerini listeler; satır story'nin case inceleme ekranına götürür", async () => {
    await oturumAc("analist");
    const tum = await api.caseler();
    const guncel = tum.filter((c) => c.durum !== "superseded");
    expect(guncel.length).toBeGreaterThan(0);
    uygulama("/caseler");
    expect(await screen.findByRole("heading", { name: "Test case'leri", level: 1 })).toBeInTheDocument();
    const tablo = await screen.findByRole("table");
    expect(within(tablo).getAllByRole("row")).toHaveLength(guncel.length + 1);
    expect(screen.getByTestId("case-sayisi")).toHaveTextContent(`${guncel.length} case`);
    const ilk = guncel[0];
    const baglanti = within(tablo).getAllByRole("link", { name: ilk.icerik.title })[0];
    expect(baglanti).toHaveAttribute("href", `/gereksinimler/${ilk.requirement_id}/caseler`);
  });

  it("durum ve arama süzgeci listeyi daraltır; boş sonuçta süzgeç temizlenebilir", async () => {
    await oturumAc("testci");
    const guncel = (await api.caseler()).filter((c) => c.durum !== "superseded");
    const durum = guncel[0].durum;
    const beklenen = guncel.filter((c) => c.durum === durum).length;
    const u = userEvent.setup();
    uygulama("/caseler");
    const tablo = await screen.findByRole("table");
    await u.selectOptions(screen.getByLabelText("Durum"), durum);
    expect(within(tablo).getAllByRole("row")).toHaveLength(beklenen + 1);
    expect(screen.getByTestId("case-sayisi")).toHaveTextContent(`${beklenen} / ${guncel.length} case`);
    await u.type(screen.getByLabelText("Ara"), "böyle-bir-case-yok-xyz");
    expect(await screen.findByText("Süzgece uyan test case'i yok.")).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Süzgeci temizle" }));
    expect(within(await screen.findByRole("table")).getAllByRole("row")).toHaveLength(guncel.length + 1);
  });

  it("menüde her role görünür", async () => {
    await oturumAc("po");
    uygulama("/gereksinimler");
    await screen.findByRole("heading", { name: "Gereksinimler", level: 1 });
    expect(within(menu()).getByRole("link", { name: /Test case'leri/ })).toHaveAttribute("href", "/caseler");
  });
});

describe("Kod üretimi ve Koşular yalnız otomasyon rollerinde", () => {
  it.each(["analist", "po", "testci"])("%s menüde görmez, liste adresinde yetki mesajı alır", async (kullanici) => {
    await oturumAc(kullanici);
    const { unmount } = uygulama("/kod");
    expect(await screen.findByText("Bu ekran için yetkiniz yok.")).toBeInTheDocument();
    expect(within(menu()).queryByText("Kod üretimi")).toBeNull();
    expect(within(menu()).queryByText("Koşular")).toBeNull();
    unmount();
    uygulama("/kosular");
    expect(await screen.findByText("Bu ekran için yetkiniz yok.")).toBeInTheDocument();
  });

  it.each(["muhendis", "sunucu"])("%s menüde görür ve ekranları açar", async (kullanici) => {
    await oturumAc(kullanici);
    const { unmount } = uygulama("/kod");
    expect(await screen.findByRole("heading", { name: "Kod üretimi", level: 1 })).toBeInTheDocument();
    expect(within(menu()).getByRole("link", { name: /Kod üretimi/ })).toBeInTheDocument();
    expect(within(menu()).getByRole("link", { name: /Koşular/ })).toBeInTheDocument();
    unmount();
    uygulama("/kosular");
    expect(await screen.findByRole("heading", { name: "Koşular", level: 1 })).toBeInTheDocument();
  });

  it("kanıt bağlantılarının götürdüğü tekil koşu ekranı testçiye açık kalır", async () => {
    await oturumAc("testci");
    const kosu = (await api.kosular())[0];
    uygulama(`/kosular/${kosu.id}`);
    expect(await screen.findByRole("main")).toBeInTheDocument();
    await screen.findAllByRole("heading");
    expect(screen.queryByText("Bu ekran için yetkiniz yok.")).toBeNull();
  });

  it("testçinin açılış ekranı sırası Koşular'ı içermez", () => {
    expect(varsayilanSayfa("tester")).toBe("/bug-taslaklari");
    expect(varsayilanSayfa("tester", (_m, yol) => yol !== "/bug-drafts")).toBe("/caseler");
  });
});
