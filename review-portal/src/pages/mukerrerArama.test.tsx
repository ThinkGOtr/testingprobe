// Tutarlılık denetimi bug taslaklarında core henüz Jira mükerrer araması yapmıyor: boş aday listesi
// "bulunamadı" olarak gösterilmez (yanlış iddia; Demo-A F2 taslağı TPD-5'in mükerreri).
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { mockVerisi } from "../api/mock/handlers";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { oturumAc } from "../test/yardimci";
import { mukerrerAramasiYapilmadi } from "./BugTaslaklari";

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

describe("mükerrer araması yapılmadı", () => {
  it("yalnızca adaysız tutarlılık taslağı için doğru", () => {
    expect(mukerrerAramasiYapilmadi({ kaynak: "consistency", mukerrer_adaylari: [] })).toBe(true);
    expect(mukerrerAramasiYapilmadi({ kaynak: "triage", mukerrer_adaylari: [] })).toBe(false);
    const aday = mockVerisi().bugTaslaklari.find((b) => b.id === "bug-1")!.mukerrer_adaylari;
    expect(mukerrerAramasiYapilmadi({ kaynak: "consistency", mukerrer_adaylari: aday })).toBe(false);
  });

  it("tutarlılık taslağı detayı 'bulunamadı' demez, aramanın yapılmadığını ve onay uyarısını gösterir", async () => {
    const b = mockVerisi().bugTaslaklari.find((x) => x.kaynak === "consistency" && x.durum === "draft" && x.mukerrer_adaylari.length === 0)!;
    await oturumAc("testci");
    uygulama(`/bug-taslaklari/${b.id}`);
    expect(await screen.findByText("Mükerrer araması yapılmadı (Faz 4).")).toBeInTheDocument();
    expect(screen.queryByText("Jira'da benzer açık bug bulunamadı.")).toBeNull();
    const uyari = screen.getByText("Onaylamadan önce Jira'yı kontrol edin").closest("[role=note]")!;
    expect(uyari).toHaveTextContent("Mevcut kayda bağla");
    expect(uyari).toHaveTextContent("bu taslağı \"Onayla ve Jira'da aç\" ile onaylamayın");
  });

  it("adayı olan taslak adayları gösterir, uyarı çıkmaz", async () => {
    await oturumAc("testci");
    uygulama("/bug-taslaklari/bug-1");
    expect(await screen.findByText("TPD-5")).toBeInTheDocument();
    expect(screen.queryByText(/Mükerrer araması yapılmadı/)).toBeNull();
    expect(screen.queryByText("Onaylamadan önce Jira'yı kontrol edin")).toBeNull();
  });

  it("triage taslağında adaysız durum hâlâ 'bulunamadı' (arama triage akışında yapılır)", async () => {
    const b = mockVerisi().bugTaslaklari.find((x) => x.id === "bug-1")!;
    b.mukerrer_adaylari = [];
    await oturumAc("testci");
    uygulama("/bug-taslaklari/bug-1");
    expect(await screen.findByText("Jira'da benzer açık bug bulunamadı.")).toBeInTheDocument();
    expect(screen.queryByText("Onaylamadan önce Jira'yı kontrol edin")).toBeNull();
  });

  it("liste, adaysız tutarlılık taslağında '—' yerine 'Arama yapılmadı' yazar", async () => {
    await oturumAc("testci");
    uygulama("/bug-taslaklari");
    const tablo = await screen.findByRole("region", { name: "Bug taslakları tablosu" });
    const tutarlilik = mockVerisi().bugTaslaklari.filter((x) => mukerrerAramasiYapilmadi(x));
    expect(tutarlilik.length).toBeGreaterThan(0);
    expect(within(tablo).getAllByText("Arama yapılmadı")).toHaveLength(tutarlilik.length);
    const satir = within(tablo).getByText(mockVerisi().bugTaslaklari.find((x) => x.id === "bug-1")!.icerik.summary).closest("tr")!;
    expect(within(satir).getByText("TPD-5")).toBeInTheDocument();
  });
});
