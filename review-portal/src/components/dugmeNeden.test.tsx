// Görünür pasiflik nedeni (§4.5, .dugme-neden): native disabled düğmenin title'ı klavyede okunmaz;
// neden düğmenin dışında görünür yazılır ve aria-describedby ile bağlanır.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
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

describe("ekranlarda görünür neden", () => {
  it("Koşular: iki tetik düğmesine eklenmez (açıklamaları zaten görünür ve bağlı)", async () => {
    await oturumAc("analist");
    const { container } = uygulama("/kosular");
    const gece = await screen.findByRole("button", { name: "Gece koşusunu şimdi başlat" });
    const deploy = screen.getByRole("button", { name: "Deploy sonrası testleri koş" });
    expect(gece).toBeDisabled();
    expect(gece).toHaveAttribute("aria-describedby", "kosular-gece-aciklama");
    expect(deploy).toHaveAttribute("aria-describedby", "kosular-deploy-aciklama");
    expect(container.querySelector(".dugme-neden")).toBeNull();
  });

  it("Case review: yayın yetkisi olmayan rolde 'Yayın önizleme' nedeni görünür ve bağlı", async () => {
    await oturumAc("po");
    uygulama("/gereksinimler/req-tpd-1/caseler");
    const d = await screen.findByRole("button", { name: "Yayın önizleme" });
    expect(d).toBeDisabled();
    expect(d).toHaveAttribute("title", "Yayın analist rolü gerektirir");
    expect(d).toHaveAccessibleDescription("Yayın analist rolü gerektirir");
  });
});
