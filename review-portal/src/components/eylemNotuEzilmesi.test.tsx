// YD-01 / CL-01 regresyonu: eylem grubunda düğme yokken (yetkisiz rol, yalnız "Bu adım <Rol> rolünde: … bekleniyor"
// notu) grup nedeni kuralının `contain: inline-size`'ı notun içsel genişliğini sıfırlıyor, grup 0 px'e eziliyor ve metin
// harf harf dikey akıyordu. jsdom yerleşim hesaplamaz: (1) DOM sözleşmesi (not, düğmesiz grubun doğrudan sarıcısında,
// `data-yetkisiz` + `.bekleyen-rol`; boş eş sarıcı `neden-var` taşımaz) ve (2) CSS sözleşmesi (düğmesiz grupta
// contain: none + en az genişlik; özet kartında tam genişlik satır) doğrulanır. Geometri e2e/duman.spec.ts'te.
import { screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { oturumAc, sar } from "../test/yardimci";
import { OzetKarti } from "./DetaySayfasi";
import { IslemDugmesi } from "./ui";

const css = readFileSync(resolve(__dirname, "../styles.css"), "utf8");
const DUGMESIZ = ".eylemler:not(:has(button, a[href], input, select, textarea))";

/** `secici { … }` bloğunun gövdesi (ilk eşleşme); yoksa null. */
function kural(secici: string): string | null {
  const i = css.indexOf(`${secici} {`);
  if (i < 0) return null;
  return css.slice(i, css.indexOf("}", i));
}

describe("YD-01: düğmesiz eylem grubundaki 'kimi bekliyoruz' notu ezilmez", () => {
  it("özet kartında yalnız yetkisiz düğmeler varken grup yalnız notu taşır (düğme yok, eş not tek)", async () => {
    await oturumAc("muhendis");
    sar(
      <OzetKarti
        baslik="Karar tabloları"
        siradaki="1 tablo PO onayı bekliyor."
        eylemler={
          <>
            <IslemDugmesi izin="requirement.review">AI taslağı üret</IslemDugmesi>
            <IslemDugmesi izin="requirement.review">Boş tablo ekle</IslemDugmesi>
          </>
        }
      />,
    );
    const notlar = await screen.findAllByTestId("bekleyen-rol");
    const grup = screen.getByRole("group", { name: "Sayfa eylemleri" });
    expect(grup).toHaveClass("eylemler", "ds-ozet-eylemler");
    expect(grup.querySelector("button, a[href], input, select, textarea")).toBeNull();
    expect(notlar).toHaveLength(1);
    expect(notlar[0]).toHaveClass("dugme-neden", "bekleyen-rol");
    expect(notlar[0].parentElement).toHaveClass("dugme-neden-sarici", "neden-var");
    expect(notlar[0].parentElement).toHaveAttribute("data-yetkisiz", "true");
    expect(notlar[0].parentElement?.parentElement).toBe(grup);
    // Eş sarıcı boş ve `neden-var` taşımıyor: CSS onu düğmesiz grupta gizler.
    const bos = [...grup.children].filter((c) => c !== notlar[0].parentElement);
    expect(bos.every((c) => !c.classList.contains("neden-var") && c.textContent === "")).toBe(true);
  });

  it("rolNotlari={false}: özet kartında not çizilmez (kimi beklediğimizi Sıradaki adım söyler, YD-05)", async () => {
    await oturumAc("muhendis");
    sar(<OzetKarti baslik="X" siradaki="Analist bekleniyor." rolNotlari={false} eylemler={<IslemDugmesi izin="requirement.review">Ön incelemeyi başlat</IslemDugmesi>} />);
    // Oturum yüklenince düğme kalkar; not da çizilmez.
    await waitFor(() => expect(screen.queryByRole("button", { name: "Ön incelemeyi başlat" })).toBeNull());
    expect(screen.queryByTestId("bekleyen-rol")).toBeNull();
  });

  it("CSS: düğmesiz grupta not içsel genişliğini korur (contain: none, en az 16rem, sıfıra inmez)", () => {
    const k = kural(`${DUGMESIZ} > .dugme-neden-sarici.neden-var[data-yetkisiz] > .dugme-neden.bekleyen-rol`);
    expect(k).not.toBeNull();
    expect(k).toMatch(/contain:\s*none/);
    expect(k).toMatch(/min-width:\s*min\(16rem,\s*100%\)/);
    expect(k).toMatch(/flex:\s*0 1 auto/);
    expect(css).toContain(`${DUGMESIZ} > .dugme-neden-sarici:not(.neden-var) {`);
  });

  it("CSS: özet kartında düğmesiz grup sağ sütuna sıkışmaz, gövdenin altında tam genişlik satıra iner", () => {
    const k = kural(".ds-ozet.sayfa-basligi > .ds-ozet-eylemler.eylemler:not(:has(button, a[href], input, select, textarea))");
    expect(k).not.toBeNull();
    expect(k).toMatch(/grid-column:\s*1 \/ -1/);
    expect(k).toMatch(/margin-left:\s*0/);
    expect(k).toMatch(/justify-content:\s*flex-start/);
  });

  it("CSS: grup nedeni kuralı (contain: inline-size) düğmeli grupta kalır — kural silinip sorun gizlenmedi", () => {
    expect(css).toMatch(/\.eylemler > \.neden-var > \.dugme-neden,\s*\.satir-ogeler > \.neden-var > \.dugme-neden \{[^}]*contain: inline-size/);
  });
});
