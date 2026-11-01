// Mükerrer araması (JQL + dup_rank, §8.12): boş aday listesi ancak arama yapıldıysa "bulunamadı"
// demektir. Faz 4'te tutarlılık taslakları da aramadan geçer; core arama durumunu göndermiyorsa
// adaysız tutarlılık taslağı "arama yapılmadı" sayılır (yanlış iddia yok).
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { mockVerisi } from "../api/mock/handlers";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { oturumAc } from "../test/yardimci";
import { mukerrerAramaDurumu, mukerrerAramasiYapilmadi } from "./BugTaslaklari";

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

describe("mükerrer araması durumu", () => {
  it("core durumu yoksa: yalnızca adaysız tutarlılık taslağı 'yapılmadı'", () => {
    expect(mukerrerAramasiYapilmadi({ kaynak: "consistency", mukerrer_adaylari: [] })).toBe(true);
    expect(mukerrerAramasiYapilmadi({ kaynak: "triage", mukerrer_adaylari: [] })).toBe(false);
    const aday = mockVerisi().bugTaslaklari.find((b) => b.id === "bug-1")!.mukerrer_adaylari;
    expect(mukerrerAramasiYapilmadi({ kaynak: "consistency", mukerrer_adaylari: aday })).toBe(false);
  });

  it("core durumu varsa ona uyulur", () => {
    const arama = { jql: null, oneri: null, oneri_link_key: null, mode: null, hata: null };
    expect(mukerrerAramaDurumu({ kaynak: "consistency", mukerrer_adaylari: [], mukerrer_arama: { ...arama, durum: "yapildi" } })).toBe("yapildi");
    expect(mukerrerAramaDurumu({ kaynak: "triage", mukerrer_adaylari: [], mukerrer_arama: { ...arama, durum: "suruyor" } })).toBe("suruyor");
  });

  it("aranmamış tutarlılık taslağı 'bulunamadı' demez, onay uyarısını gösterir", async () => {
    const b = mockVerisi().bugTaslaklari.find((x) => x.id === "bug-3")!;
    b.mukerrer_arama = null;
    b.mukerrer_adaylari = [];
    await oturumAc("testci");
    uygulama("/bug-taslaklari/bug-3");
    expect(await screen.findByText("Mükerrer araması yapılmadı.")).toBeInTheDocument();
    expect(screen.queryByText("Jira'da benzer açık bug bulunamadı.")).toBeNull();
    const uyari = screen.getByText("Onaylamadan önce Jira'yı kontrol edin").closest("[role=note]")!;
    expect(uyari).toHaveTextContent("Mevcut kayda bağla");
    expect(uyari).toHaveTextContent("bu taslağı \"Onayla ve Jira'da aç\" ile onaylamayın");
  });

  it("tutarlılık (F2) taslağı da aramadan geçer: TPD-5 yüksek olasılık, AI önerisi bağla", async () => {
    await oturumAc("testci");
    uygulama("/bug-taslaklari/bug-3");
    const liste = await screen.findByRole("list", { name: "Mükerrer adayları" });
    expect(within(liste).getByText("TPD-5")).toBeInTheDocument();
    expect(within(liste).getByText("yüksek olasılık")).toBeInTheDocument();
    expect(screen.getByTestId("mukerrer-onerisi")).toHaveTextContent("mevcut kayda bağla (TPD-5)");
    expect(screen.queryByText("Onaylamadan önce Jira'yı kontrol edin")).toBeNull();
  });

  it("adayı olan taslak adayları gösterir, uyarı çıkmaz", async () => {
    await oturumAc("testci");
    uygulama("/bug-taslaklari/bug-1");
    expect(await screen.findByRole("link", { name: /^TPD-5/ })).toHaveAttribute("href", "http://127.0.0.1:8090/browse/TPD-5");
    expect(screen.queryByText(/Mükerrer araması yapılmadı/)).toBeNull();
    expect(screen.queryByText("Onaylamadan önce Jira'yı kontrol edin")).toBeNull();
  });

  it("triage taslağında arama yapılıp aday çıkmadıysa 'bulunamadı'", async () => {
    const b = mockVerisi().bugTaslaklari.find((x) => x.id === "bug-1")!;
    b.mukerrer_adaylari = [];
    await oturumAc("testci");
    uygulama("/bug-taslaklari/bug-1");
    expect(await screen.findByText("Jira'da benzer açık bug bulunamadı.")).toBeInTheDocument();
    expect(screen.queryByText("Onaylamadan önce Jira'yı kontrol edin")).toBeNull();
  });

  it("liste, aranmamış taslakta '—' yerine 'Arama yapılmadı' yazar", async () => {
    const b = mockVerisi().bugTaslaklari.find((x) => x.id === "bug-3")!;
    b.mukerrer_arama = null;
    b.mukerrer_adaylari = [];
    await oturumAc("testci");
    uygulama("/bug-taslaklari");
    const tablo = await screen.findByRole("region", { name: "Bug taslakları tablosu" });
    expect(within(tablo).getAllByText("Arama yapılmadı")).toHaveLength(1);
    const satir = within(tablo).getByText(mockVerisi().bugTaslaklari.find((x) => x.id === "bug-1")!.icerik.summary).closest("tr")!;
    expect(within(satir).getByText(/^TPD-5/)).toBeInTheDocument();
  });
});
