// Görünür pasiflik nedeni (§4.5, .dugme-neden): native disabled düğmenin title'ı klavyede okunmaz;
// neden düğmenin dışında görünür yazılır ve aria-describedby ile bağlanır.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { OturumProvider } from "../auth";
import { oturumAc, sar } from "../test/yardimci";
import { BildirimProvider } from "./Bildirim";
import { IslemDugmesi } from "./ui";

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

describe("IslemDugmesi görünür pasiflik nedeni", () => {
  it("pasif düğmenin nedeni düğmenin dışında görünür ve aria-describedby ile bağlı; title korunur", async () => {
    await oturumAc("analist");
    sar(
      <IslemDugmesi disabled title="Önce ret nedeni seçin">
        Reddet
      </IslemDugmesi>,
    );
    const d = screen.getByRole("button", { name: "Reddet" });
    const neden = screen.getByText("Önce ret nedeni seçin");
    expect(d).toBeDisabled();
    expect(d).toHaveAttribute("title", "Önce ret nedeni seçin");
    expect(neden).toHaveClass("dugme-neden");
    expect(d).not.toContainElement(neden);
    expect(d.getAttribute("aria-describedby")).toBe(neden.id);
    expect(d).toHaveAccessibleDescription("Önce ret nedeni seçin");
    expect(neden.parentElement).toHaveClass("dugme-neden-sarici", "neden-var");
  });

  it("etkin düğmede title yalnız ipucu kalır: görünür neden ve aria-describedby yok", async () => {
    await oturumAc("analist");
    const { container } = sar(<IslemDugmesi title="Yeniden kontrol turu başlar">Uygula</IslemDugmesi>);
    const d = screen.getByRole("button", { name: "Uygula" });
    expect(d).toBeEnabled();
    expect(d).not.toHaveAttribute("aria-describedby");
    expect(container.querySelector(".dugme-neden")).toBeNull();
    expect(container.querySelector(".neden-var")).toBeNull();
  });

  it("nedeni olmayan pasif düğmeye boş neden çizilmez", async () => {
    await oturumAc("analist");
    const { container } = sar(<IslemDugmesi disabled>Yayınla</IslemDugmesi>);
    expect(screen.getByRole("button", { name: "Yayınla" })).not.toHaveAttribute("aria-describedby");
    expect(container.querySelector(".dugme-neden")).toBeNull();
  });

  it("yetkisiz rolde düğme yerine tek satır 'kimi bekliyoruz' yazılır (IA-10)", async () => {
    await oturumAc("testci");
    sar(
      <IslemDugmesi izin="requirement.review" title="Yazılır ve yeniden kontrol başlar">
        Düzeltmeleri uygula
      </IslemDugmesi>,
    );
    const satir = await screen.findByTestId("bekleyen-rol");
    expect(satir).toHaveTextContent("Bu adım Analist rolünde: Cengizhan Gunaydin bekleniyor");
    expect(satir).toHaveClass("dugme-neden");
    expect(satir.parentElement).toHaveAttribute("data-yetkisiz", "true");
    expect(screen.queryByRole("button", { name: "Düzeltmeleri uygula" })).toBeNull();
    expect(screen.queryByText("Yazılır ve yeniden kontrol başlar")).toBeNull();
  });

  it("çalışırken (meşgul) neden yazılmaz", async () => {
    await oturumAc("analist");
    const { container } = sar(
      <IslemDugmesi disabled calisiyor title="Önce gerekçe yazın">
        Taslağı reddet
      </IslemDugmesi>,
    );
    expect(screen.getByRole("button", { name: "Taslağı reddet" })).toHaveAttribute("aria-busy", "true");
    expect(container.querySelector(".dugme-neden")).toBeNull();
  });

  it("nedenGizli: görünür neden çizilmez, title ve çağıranın aria-describedby'si korunur", async () => {
    await oturumAc("analist");
    const { container } = sar(
      <>
        <p id="dis-aciklama">Ayrıca yazılı açıklama</p>
        <IslemDugmesi disabled nedenGizli title="Kontrol turu sınırına ulaşıldı" aria-describedby="dis-aciklama">
          Uygula
        </IslemDugmesi>
      </>,
    );
    const d = screen.getByRole("button", { name: "Uygula" });
    expect(d).toHaveAttribute("title", "Kontrol turu sınırına ulaşıldı");
    expect(d).toHaveAttribute("aria-describedby", "dis-aciklama");
    expect(container.querySelector(".dugme-neden")).toBeNull();
  });

  it("çağıranın aria-describedby'si görünür nedenle birleştirilir", async () => {
    await oturumAc("analist");
    sar(
      <>
        <p id="dis-aciklama">Ek bağlam</p>
        <IslemDugmesi disabled title="Önce uyarıyı kabul edin" aria-describedby="dis-aciklama">
          Merge et
        </IslemDugmesi>
      </>,
    );
    const d = screen.getByRole("button", { name: "Merge et" });
    const neden = screen.getByText("Önce uyarıyı kabul edin");
    expect(d.getAttribute("aria-describedby")).toBe(`dis-aciklama ${neden.id}`);
    expect(d).toHaveAccessibleDescription("Ek bağlam Önce uyarıyı kabul edin");
  });

  it("neden belirip kaybolurken düğme yeniden bağlanmaz (öğe kimliği korunur)", async () => {
    await oturumAc("analist");
    function Deneme() {
      const [pasif, setPasif] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setPasif((p) => !p)}>
            Değiştir
          </button>
          <IslemDugmesi disabled={pasif} title={pasif ? "Önce ret nedeni seçin" : undefined}>
            Reddet
          </IslemDugmesi>
        </>
      );
    }
    const { container } = sar(<Deneme />);
    const once = screen.getByRole("button", { name: "Reddet" });
    fireEvent.click(screen.getByRole("button", { name: "Değiştir" }));
    expect(screen.getByRole("button", { name: "Reddet" })).toBe(once);
    expect(container.querySelector(".dugme-neden")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Değiştir" }));
    expect(screen.getByRole("button", { name: "Reddet" })).toBe(once);
    expect(container.querySelector(".dugme-neden")).toBeNull();
  });
});

describe("grupta ortak neden (tekrar yok)", () => {
  it("aynı gruptaki eş rol nedeni bir kez yazılır; her düğme aynı nedene bağlı", async () => {
    await oturumAc("testci");
    const { container } = sar(
      <div className="eylemler">
        <IslemDugmesi izin="requirement.review">Yeniden denetle</IslemDugmesi>
        <IslemDugmesi izin="requirement.import">Jira'dan çek</IslemDugmesi>
        <IslemDugmesi izin={["requirement.review", "baseline.manage"]}>Ölçüm gir</IslemDugmesi>
      </div>,
    );
    await waitFor(() => expect(container.querySelectorAll(".dugme-neden")).toHaveLength(2));
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.getAllByText("Bu adım Analist rolünde: Cengizhan Gunaydin bekleniyor")).toHaveLength(1);
    // Farklı metinli satır ayrı yazılır.
    expect(screen.getByText("Bu adım Analist / Ürün Sahibi (PO) rolünde: Cengizhan Gunaydin bekleniyor")).toBeInTheDocument();
  });

  it("farklı gruplarda neden ayrı ayrı yazılır", async () => {
    await oturumAc("testci");
    const { container } = sar(
      <>
        <div className="eylemler">
          <IslemDugmesi izin="requirement.review">Bir</IslemDugmesi>
        </div>
        <div className="eylemler">
          <IslemDugmesi izin="requirement.review">İki</IslemDugmesi>
        </div>
      </>,
    );
    await waitFor(() => expect(container.querySelectorAll(".dugme-neden")).toHaveLength(2));
  });

  it("sahibin nedeni kalkınca sıradaki düğme nedeni kendisi yazar", async () => {
    await oturumAc("analist");
    function Deneme() {
      const [ilkPasif, setIlkPasif] = useState(true);
      return (
        <>
          <button type="button" onClick={() => setIlkPasif(false)}>
            Aç
          </button>
          <div className="eylemler">
            <IslemDugmesi disabled={ilkPasif} title="Önce ret nedeni seçin">
              Değişiklik iste
            </IslemDugmesi>
            <IslemDugmesi disabled title="Önce ret nedeni seçin">
              Reddet
            </IslemDugmesi>
          </div>
        </>
      );
    }
    const { container } = sar(<Deneme />);
    const reddet = screen.getByRole("button", { name: "Reddet" });
    expect(container.querySelectorAll(".dugme-neden")).toHaveLength(1);
    expect(reddet).toHaveAccessibleDescription("Önce ret nedeni seçin");
    fireEvent.click(screen.getByRole("button", { name: "Aç" }));
    expect(container.querySelectorAll(".dugme-neden")).toHaveLength(1);
    const neden = screen.getByText("Önce ret nedeni seçin");
    expect(reddet.getAttribute("aria-describedby")).toBe(neden.id);
    expect(reddet.parentElement).toContainElement(neden);
    expect(screen.getByRole("button", { name: "Değişiklik iste" })).not.toHaveAttribute("aria-describedby");
  });
});

describe("ekranlarda görünür neden", () => {
  it("Koşular: tetik düğmelerine açıklama eklenmez (açıklamaları zaten görünür ve bağlı)", async () => {
    await oturumAc("muhendis");
    const { container } = uygulama("/kosular");
    const gece = await screen.findByRole("button", { name: "Gece koşusunu şimdi başlat" });
    const deploy = screen.getByRole("button", { name: "Deploy sonrası testleri koş" });
    const manuel = screen.getByRole("button", { name: "Manuel koşu başlat" });
    expect(gece).toHaveAttribute("aria-describedby", "kosular-gece-aciklama");
    expect(deploy).toHaveAttribute("aria-describedby", "kosular-deploy-aciklama");
    expect(manuel).toHaveAttribute("aria-describedby", "kosular-manuel-aciklama");
    expect(container.querySelector(".dugme-neden")).toBeNull();
  });

  it("Koşular: tetik izni olmayan rolde tetik düğmeleri ve açıklamaları çizilmez; developer yalnız manuel", async () => {
    await oturumAc("analist");
    const { unmount } = uygulama("/kosular");
    await screen.findByRole("heading", { name: "Koşular" });
    await waitFor(() => expect(screen.queryByRole("list", { name: "Tetik düğmeleri" })).toBeNull());
    for (const ad of ["Gece koşusunu şimdi başlat", "Deploy sonrası testleri koş", "Manuel koşu başlat"]) {
      expect(screen.queryByRole("button", { name: ad })).toBeNull();
    }
    unmount();
    await oturumAc("gelistirici");
    uygulama("/kosular");
    expect(await screen.findByRole("button", { name: "Manuel koşu başlat" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Gece koşusunu şimdi başlat" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Deploy sonrası testleri koş" })).toBeNull();
  });

  it("Script detay (defect adayı): kutu nedeni zaten yazdığı için 'Kırarak doğrula' yanında tekrar yok", async () => {
    await oturumAc("muhendis");
    uygulama("/kod/scr-3?sekme=kirarak-dogrula");
    const d = await screen.findByRole("button", { name: "Kırarak doğrula" });
    expect(d).toHaveAttribute("aria-disabled", "true");
    expect(d).toHaveAttribute("title", expect.stringMatching(/^Defect adayı/));
    // Görünür "Kırarak doğrulama kapalı" kutusu düğmeye bağlı.
    expect(d).toHaveAttribute("aria-describedby", "kirma-kapali-neden");
    expect(d).toHaveAccessibleDescription(/^Kırarak doğrulama kapalı/);
    expect(d.parentElement).not.toHaveClass("neden-var");
  });

  it("Script detay (defect adayı, analist): kutu bağlı kalır, rol nedeni de görünür yazılır", async () => {
    await oturumAc("analist");
    uygulama("/kod/scr-3?sekme=kirarak-dogrula");
    expect(await screen.findAllByText(/^Bu adım Otomasyon Mühendisi rolünde: Gokhan Sipahi bekleniyor$/)).not.toHaveLength(0);
    expect(screen.queryByRole("button", { name: "Kırarak doğrula" })).toBeNull();
  });

  it("Script detay (analist): PR ret grubundaki iki düğmede rol nedeni bir kez yazılır", async () => {
    await oturumAc("analist");
    const { container } = uygulama("/kod/scr-2");
    await screen.findAllByText("Bu adım Otomasyon Mühendisi rolünde: Gokhan Sipahi bekleniyor");
    expect(screen.queryByRole("button", { name: "Reddet" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Değişiklik iste" })).toBeNull();
    // Her eylem grubunda en fazla bir eş neden.
    for (const g of container.querySelectorAll(".eylemler")) {
      const metinler = [...g.querySelectorAll(".dugme-neden")].map((n) => n.textContent);
      expect(new Set(metinler).size).toBe(metinler.length);
    }
  });

  it("Yayın önizleme: yayın yetkisi olmayan rolde 'Seçilenleri yayınla' nedeni görünür ve bağlı", async () => {
    await oturumAc("po");
    uygulama("/gereksinimler/req-tpd-1/yayin");
    expect(await screen.findByText("Bu adım Test Uzmanı rolünde: Fatih Arslan bekleniyor")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Seçilenleri yayınla/ })).toBeNull();
  });

  it("Case review (karar verilmiş case, Analist): 'Taslağa al' yerine kimi beklediğimiz yazılır", async () => {
    await oturumAc("analist");
    uygulama("/gereksinimler/req-tpd-1/caseler");
    expect((await screen.findAllByText("Bu adım Test Uzmanı rolünde: Fatih Arslan bekleniyor")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Taslağa al" })).toBeNull();
  });
});

describe("Pasiflik nedeni yerleşim kuralları (review 3)", () => {
  const css = readFileSync(resolve(__dirname, "../styles.css"), "utf8");
  const blok = css;

  it("grup nedeni yalnız düğme gruplarında: tek düğmeli ve karışık gruplarda sarıcı sütun kalır", () => {
    expect(blok).toContain(".eylemler > .dugme-neden-sarici.neden-var:only-child");
    expect(blok).toContain(".satir-ogeler:has(> :not(.dugme-neden-sarici, .dugme)) > .dugme-neden-sarici.neden-var");
  });

  it("-8 px gap telafisi yalnız sağa yaslı sayfa başlığında; sola yaslı grupta neden düğme kenarından başlar", () => {
    expect(blok).toMatch(/\.eylemler > \.neden-var > \.dugme-neden,\s*\.satir-ogeler > \.neden-var > \.dugme-neden \{[^}]*margin-left: 0;/);
    expect(blok).toMatch(/\.sayfa-basligi > \.eylemler[^{]*> \.neden-var:not\(:only-child\) > \.dugme-neden \{\s*margin-left: -8px;/);
    expect(blok).not.toMatch(/^\.eylemler > \.neden-var > \.dugme-neden[^{]*\{[^}]*margin-left: -8px/m);
  });

  it("sayfa başlığı eylemleri sarınca da sağda; kart başlığı h2 her durumda 36 px satırın ortasında", () => {
    expect(blok).toMatch(/\.sayfa-basligi > \.eylemler \{\s*margin-left: auto;\s*justify-content: flex-end;/);
    expect(blok).toMatch(/\.kart-baslik > h2,[^{]*\{\s*padding-block: max\(0px, calc\(\(36px - 1lh\) \/ 2\)\);/);
  });
});

describe("ET-07: kilitli düğme klavyede erişilebilir (aria-disabled)", () => {
  it("ön koşulla kilitli düğme Tab sırasında kalır, nedeni okunur; tıklama ve form gönderimi engellenir", async () => {
    await oturumAc("analist");
    let tik = 0;
    let gonderim = 0;
    sar(
      <form
        onSubmit={(e) => {
          e.preventDefault();
          gonderim++;
        }}
      >
        <input aria-label="alan" />
        <IslemDugmesi type="submit" disabled title="Önce ret nedeni seçin" onClick={() => tik++}>
          Reddet
        </IslemDugmesi>
      </form>,
    );
    const d = screen.getByRole("button", { name: "Reddet" });
    expect(d).toHaveAttribute("aria-disabled", "true");
    expect(d).not.toHaveAttribute("disabled");
    d.focus();
    expect(d).toHaveFocus();
    expect(d).toHaveAccessibleDescription("Önce ret nedeni seçin");
    fireEvent.click(d);
    expect(tik).toBe(0);
    expect(gonderim).toBe(0);
  });

  it("çalışırken aria-busy + aria-disabled; odak düğmede kalır", async () => {
    await oturumAc("analist");
    sar(<IslemDugmesi calisiyor>Kaydet</IslemDugmesi>);
    const d = screen.getByRole("button", { name: "Kaydet" });
    d.focus();
    expect(d).toHaveAttribute("aria-busy", "true");
    expect(d).toHaveAttribute("aria-disabled", "true");
    expect(d).toHaveFocus();
  });

  it("nedenGizli: görünür neden yazılmaz ama erişilebilir açıklama olarak bağlanır", async () => {
    await oturumAc("analist");
    const { container } = sar(
      <IslemDugmesi disabled nedenGizli title="Önce seçenekleri belirleyin">
        Seçeneklerle üret…
      </IslemDugmesi>,
    );
    const d = screen.getByRole("button", { name: "Seçeneklerle üret…" });
    expect(container.querySelector(".dugme-neden")).toBeNull();
    expect(d).toHaveAccessibleDescription("Önce seçenekleri belirleyin");
  });
});
