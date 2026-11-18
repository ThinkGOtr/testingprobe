// UX şerit "pano": Kontrol Kulesi bölüm sekmeleri + KPI şeridi (IA-19/ET-08), Kod üretimi ayar düzeni (IA-13),
// Otomasyon kart başı (IA-25), Claude Code ve Yol haritası ortak bileşenleri.
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { mockVerisi } from "../api/mock/handlers";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { oturumAc, sekmeAc } from "../test/yardimci";

function Konum() {
  const k = useLocation();
  return <div data-testid="konum">{k.pathname + k.search}</div>;
}

function uygulama(yol: string) {
  return render(
    <MemoryRouter initialEntries={[yol]}>
      <OturumProvider>
        <BildirimProvider>
          <Rotalar />
          <Routes>
            <Route path="*" element={<Konum />} />
          </Routes>
        </BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

describe("Kontrol Kulesi: bölüm sekmeleri (IA-19)", () => {
  it("dört bölüm; varsayılan Özet, Hatalar sayılı; seçim ?bolum= adrese yazılır; gizli panel Tab sırasında değil", async () => {
    await oturumAc("sunucu");
    uygulama("/kontrol-kulesi");
    const liste = await screen.findByRole("tablist", { name: "Kontrol Kulesi bölümleri" });
    const adlar = within(liste)
      .getAllByRole("tab")
      .map((t) => t.textContent);
    expect(adlar[0]).toBe("Özet");
    expect(adlar.slice(2)).toEqual(["Kalite", "Hız ve maliyet"]);
    expect(adlar[1]).toMatch(/^Hatalar\s*\(?\d+\)?$/);
    expect(within(liste).getByRole("tab", { name: /^Özet/ })).toHaveAttribute("aria-selected", "true");
    // Özet: geçme oranı ve karne görünür; AI katkısı gizli panelde (erişilebilirlik ağacında yok).
    expect(screen.getByRole("region", { name: "Geçme oranı" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "AI katkısı" })).toBeNull();
    await sekmeAc("Hız ve maliyet");
    expect(screen.getByRole("region", { name: "AI katkısı" })).toBeInTheDocument();
    expect(screen.getByTestId("konum")).toHaveTextContent("bolum=hiz-maliyet");
  });

  it("derin bağlantı ?bolum=hatalar Hatalar sekmesini açar; platform süzgeci adreste korunur", async () => {
    await oturumAc("sunucu");
    uygulama("/kontrol-kulesi?bolum=hatalar&platform=web");
    expect(await screen.findByRole("tab", { name: /^Hatalar/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: "Flaky testler" })).toBeInTheDocument();
    await sekmeAc("Özet");
    expect(screen.getByTestId("konum")).toHaveTextContent("platform=web");
  });

  it("KPI şeridi en çok 6 karar göstergesi; ölçülmeyenler kutu değil tek satır", async () => {
    await oturumAc("sunucu");
    uygulama("/kontrol-kulesi");
    const serit = await screen.findByTestId("kule-kpi");
    expect(serit.children.length).toBeGreaterThanOrEqual(1);
    expect(serit.children.length).toBeLessThanOrEqual(6);
    expect(screen.getByTestId("kule-olculmeyenler").tagName).toBe("DETAILS");
  });

  it("grafik tablo alternatifi: 'Tablo olarak göster' açılırında her gün bir satır", async () => {
    await oturumAc("sunucu");
    uygulama("/kontrol-kulesi");
    const ozet = await screen.findByText("Tablo olarak göster");
    const tablo = ozet.closest("details")!.querySelector("table")!;
    // Sütun sayısı = tablo satırı (başlık hariç); gezinen tabindex: tek durak.
    const sutunlar = document.querySelectorAll(".grafik-hedef-alan");
    expect(within(tablo).getAllByRole("row").length).toBe(sutunlar.length + 1);
    expect([...sutunlar].filter((s) => s.getAttribute("tabindex") === "0")).toHaveLength(1);
  });
});

describe("Kod üretimi: ayar düzeni (IA-13)", () => {
  it("ayarlar tek blokta; aday listesi başlıklı ve 'Tümünü seç' tüm adayları seçer", async () => {
    await oturumAc("muhendis");
    uygulama("/kod");
    expect(await screen.findByTestId("kod-ayarlar")).toBeInTheDocument();
    const baslik = await screen.findByRole("heading", { name: /^Bu platformda kodu üretilmemiş onaylı case'ler \(\d+\)$/ });
    const n = Number(/\((\d+)\)/.exec(baslik.textContent ?? "")![1]);
    fireEvent.click(screen.getByRole("button", { name: "Tümünü seç" }));
    expect(screen.getByRole("button", { name: new RegExp(`^Seçilenler için kod üret \\(${n}\\)`) })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Seçimi temizle" }));
    expect(screen.getByRole("button", { name: /^Seçilenler için kod üret \(0\)/ })).toBeInTheDocument();
  });

  it("kuyruk boşken: tek satır boş durum + katlı ayar özeti (pano ekranı kaplamaz)", async () => {
    for (const c of mockVerisi().caseler) c.durum = "draft";
    await oturumAc("muhendis");
    uygulama("/kod");
    expect(await screen.findByText("Kodu üretilecek onaylı case yok.")).toBeInTheDocument();
    expect(screen.getByText("Kodu üretilecek onaylı case yok.").closest(".bos-durum")).toHaveClass("bos-durum-satir");
    const katli = screen.getByTestId("kod-pano-katli");
    expect(katli.tagName).toBe("DETAILS");
    expect(katli).not.toHaveAttribute("open");
    expect(within(katli).getByTestId("kod-ayarlar")).toBeInTheDocument();
  });
});

describe("Otomasyon: kart başı (IA-25)", () => {
  it("her kartta tek cümle etki; ayrıntı 'Nasıl çalışır?' açılırında; son tur MetaIzgara", async () => {
    await oturumAc("muhendis");
    uygulama("/otomasyon");
    expect(await screen.findByTestId("otokod-etki")).toBeInTheDocument();
    expect(screen.getByTestId("jira-tetik-etki")).toBeInTheDocument();
    expect(screen.getAllByText("Nasıl çalışır?")).toHaveLength(2);
    expect(screen.getByTestId("tetik-kapsam-notu").closest("details")).not.toBeNull();
    expect(screen.getByTestId("jira-tetik-son-tur").querySelector("dl.meta-izgara")).not.toBeNull();
  });
});

describe("Claude Code kanalı ve Yol haritası: ortak bileşenler", () => {
  it("Claude Code: boş token listesi sonraki adımı söyler (satır boş durumu)", async () => {
    await oturumAc("testci");
    uygulama("/claude-code");
    const bos = await screen.findByText("Henüz token yok.");
    expect(bos.closest(".bos-durum")).toHaveClass("bos-durum-satir");
    expect(bos.closest(".bos-durum")).toHaveTextContent(/token oluşturun/);
  });

  it("Yol haritası: adım türü ortak Cip (yerel .yh-tur hap kopyası yok)", async () => {
    await oturumAc("sunucu");
    uygulama("/yol-haritasi");
    const adim = await screen.findByTestId("yh-adim-1");
    const tur = adim.querySelector(".yh-tur")!;
    expect(tur).toHaveClass("cip");
  });
});
