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

  it("yetkisiz rolde gereken rol görünür yazılır ve düğmeye bağlanır", async () => {
    await oturumAc("testci");
    sar(
      <IslemDugmesi roller={["analyst"]} title="Yazılır ve yeniden kontrol başlar">
        Düzeltmeleri uygula
      </IslemDugmesi>,
    );
    const d = await screen.findByRole("button", { name: "Düzeltmeleri uygula" });
    await waitFor(() => expect(d).toHaveAccessibleDescription("Bu işlem için gereken rol: Analist"));
    expect(d).toBeDisabled();
    expect(d).toHaveAttribute("data-yetkisiz", "true");
    expect(screen.getByText("Bu işlem için gereken rol: Analist")).toHaveClass("dugme-neden");
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
        <IslemDugmesi roller={["analyst"]}>Yeniden denetle</IslemDugmesi>
        <IslemDugmesi roller={["analyst"]}>Case üret</IslemDugmesi>
        <IslemDugmesi roller={["analyst", "po"]}>Ölçüm gir</IslemDugmesi>
      </div>,
    );
    const a = await screen.findByRole("button", { name: "Yeniden denetle" });
    const b = screen.getByRole("button", { name: "Case üret" });
    const c = screen.getByRole("button", { name: "Ölçüm gir" });
    await waitFor(() => expect(container.querySelectorAll(".dugme-neden")).toHaveLength(2));
    const neden = screen.getByText("Bu işlem için gereken rol: Analist");
    expect(a.getAttribute("aria-describedby")).toBe(neden.id);
    expect(b.getAttribute("aria-describedby")).toBe(neden.id);
    expect(b).toHaveAccessibleDescription("Bu işlem için gereken rol: Analist");
    expect(b.parentElement).not.toHaveClass("neden-var");
    // Farklı metinli neden kendi altında kalır.
    expect(c).toHaveAccessibleDescription("Bu işlem için gereken rol: Analist / Ürün sahibi (PO)");
  });

  it("farklı gruplarda neden ayrı ayrı yazılır", async () => {
    await oturumAc("testci");
    const { container } = sar(
      <>
        <div className="eylemler">
          <IslemDugmesi roller={["analyst"]}>Bir</IslemDugmesi>
        </div>
        <div className="eylemler">
          <IslemDugmesi roller={["analyst"]}>İki</IslemDugmesi>
        </div>
      </>,
    );
    await screen.findByRole("button", { name: "Bir" });
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
  it("Koşular: iki tetik düğmesine açıklama eklenmez (açıklamaları zaten görünür ve bağlı)", async () => {
    await oturumAc("sunucu");
    const { container } = uygulama("/kosular");
    const gece = await screen.findByRole("button", { name: "Gece koşusunu şimdi başlat" });
    const deploy = screen.getByRole("button", { name: "Deploy sonrası testleri koş" });
    expect(gece).toHaveAttribute("aria-describedby", "kosular-gece-aciklama");
    expect(deploy).toHaveAttribute("aria-describedby", "kosular-deploy-aciklama");
    expect(container.querySelector(".dugme-neden")).toBeNull();
  });

  it("Koşular (yetkisiz rol): nedenGizli rol nedenini bastırmaz; grupta bir kez yazılır, açıklamayla birlikte bağlı", async () => {
    // Mühendis Koşular ekranını açabilir ama koşu tetikleyemez (tetik yalnız sunucuda).
    await oturumAc("muhendis");
    const { container } = uygulama("/kosular");
    const gece = await screen.findByRole("button", { name: "Gece koşusunu şimdi başlat" });
    const deploy = screen.getByRole("button", { name: "Deploy sonrası testleri koş" });
    expect(gece).toBeDisabled();
    await waitFor(() => expect(container.querySelectorAll(".dugme-neden")).toHaveLength(1));
    const neden = container.querySelector(".dugme-neden")!;
    expect(neden).toHaveTextContent(/^Bu işlem için gereken rol: /);
    expect(gece.getAttribute("aria-describedby")).toBe(`kosular-gece-aciklama ${neden.id}`);
    expect(deploy.getAttribute("aria-describedby")).toBe(`kosular-deploy-aciklama ${neden.id}`);
  });

  it("Script detay (defect adayı): kutu nedeni zaten yazdığı için 'Kırarak doğrula' yanında tekrar yok", async () => {
    await oturumAc("muhendis");
    uygulama("/kod/scr-3");
    const d = await screen.findByRole("button", { name: "Kırarak doğrula" });
    expect(d).toBeDisabled();
    expect(d).toHaveAttribute("title", expect.stringMatching(/^Defect adayı/));
    // Görünür "Kırarak doğrulama kapalı" kutusu düğmeye bağlı.
    expect(d).toHaveAttribute("aria-describedby", "kirma-kapali-neden");
    expect(d).toHaveAccessibleDescription(/^Kırarak doğrulama kapalı/);
    expect(d.parentElement).not.toHaveClass("neden-var");
  });

  it("Script detay (defect adayı, analist): kutu bağlı kalır, rol nedeni de görünür yazılır", async () => {
    await oturumAc("analist");
    uygulama("/kod/scr-3");
    const d = await screen.findByRole("button", { name: "Kırarak doğrula" });
    expect(d).toBeDisabled();
    const neden = await screen.findByText("Bu işlem için gereken rol: Mühendis");
    expect(d.getAttribute("aria-describedby")).toBe(`kirma-kapali-neden ${neden.id}`);
    expect(d).toHaveAccessibleDescription(/^Kırarak doğrulama kapalı.*Bu işlem için gereken rol: Mühendis$/);
  });

  it("Script detay (analist): PR ret grubundaki iki düğmede rol nedeni bir kez yazılır", async () => {
    await oturumAc("analist");
    const { container } = uygulama("/kod/scr-2");
    const reddet = await screen.findByRole("button", { name: "Reddet" });
    const degisiklik = screen.getByRole("button", { name: "Değişiklik iste" });
    await waitFor(() => expect(reddet).toHaveAccessibleDescription("Bu işlem için gereken rol: Mühendis"));
    expect(degisiklik).toHaveAccessibleDescription("Bu işlem için gereken rol: Mühendis");
    const grup = reddet.closest(".eylemler")!;
    expect(grup.querySelectorAll(".dugme-neden")).toHaveLength(1);
    // Her eylem grubunda en fazla bir eş neden.
    for (const g of container.querySelectorAll(".eylemler")) {
      const metinler = [...g.querySelectorAll(".dugme-neden")].map((n) => n.textContent);
      expect(new Set(metinler).size).toBe(metinler.length);
    }
  });

  it("Case review: yayın yetkisi olmayan rolde 'Yayın önizleme' nedeni görünür ve bağlı", async () => {
    await oturumAc("po");
    uygulama("/gereksinimler/req-tpd-1/caseler");
    const d = await screen.findByRole("button", { name: "Yayın önizleme" });
    expect(d).toBeDisabled();
    expect(d).toHaveAttribute("title", "Yayın analist rolü gerektirir");
    expect(d).toHaveAccessibleDescription("Yayın analist rolü gerektirir");
  });

  it("Case review (karar verilmiş case): 'Yeniden aç' satırı metin + düğme karışık grup; neden düğmenin sarıcısında", async () => {
    await oturumAc("testci");
    const { container } = uygulama("/gereksinimler/req-tpd-1/caseler");
    await screen.findAllByRole("button", { name: "Yeniden aç" });
    const satirlar = [...container.querySelectorAll(".satir-ogeler")].filter((g) => g.querySelector(":scope > .dugme-neden-sarici.neden-var"));
    expect(satirlar.length).toBeGreaterThan(0);
    for (const g of satirlar) {
      // Karışık satır: düğme dışı doğrudan çocuk (paragraf) var → CSS sarıcıyı sütun bırakır (grup nedeni değil).
      expect(g.querySelector(":scope > p")).not.toBeNull();
      const sarici = g.querySelector(":scope > .dugme-neden-sarici.neden-var")!;
      expect(sarici.querySelector(":scope > button")).toHaveTextContent("Yeniden aç");
      expect(sarici.querySelector(":scope > .dugme-neden")).toHaveTextContent("Bu işlem için gereken rol: Analist");
    }
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
