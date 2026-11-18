// UX-T ortak tasarım bileşenleri: API sözleşmesi (sonraki ekran şeritleri bunlara dayanır).
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CASE_DURUMU } from "../lib/etiketler";
import { Ipucu } from "./Ipucu";
import { DurumCipi, EylemCubugu, Kimlik, kisalt, MetaIzgara, MetaSatiri, SegmentSecici, SuzgecCubugu, TabloSarici } from "./tasarim";
import { BosDurum, Cip, IslemDugmesi } from "./ui";

const SHA = "9f037ecd5b1e44a0c3f2d7e8a91b6c4d2e0f1a3b5c7d9e1f2a4b6c8d0e2f4888c";

describe("kisalt / Kimlik", () => {
  it("kısa değeri aynen, uzun değeri baş…son biçiminde kısaltır", () => {
    expect(kisalt("TPD-1", 7)).toBe("TPD-1");
    expect(kisalt(SHA, 10)).toBe("9f037e…888c");
    expect(kisalt(SHA, 10, "bas")).toBe("9f037ecd5b…");
    expect(kisalt("src/a/b/c/uzun-dosya.spec.ts", 12, "son")).toBe("…osya.spec.ts");
  });

  it("sha kısaltılır; tam değer klavye odağında ipucunda okunur, kopyala düğmesi panoya yazar", async () => {
    const yaz = vi.fn(() => Promise.resolve());
    Object.assign(navigator, { clipboard: { writeText: yaz } });
    render(<Kimlik deger={SHA} tur="sha" kopyala />);
    const kimlik = screen.getByText(kisalt(SHA, 7));
    expect(kimlik).toHaveClass("kimlik", "mono");
    const tetik = kimlik.closest(".ipucu") as HTMLElement;
    expect(tetik).toHaveAttribute("tabindex", "0");
    expect(tetik).toHaveAttribute("aria-description", SHA);
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.focus(tetik);
    expect(screen.getByRole("tooltip")).toHaveTextContent(SHA);
    fireEvent.keyDown(tetik, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: `Kopyala: ${SHA}` }));
    expect(yaz).toHaveBeenCalledWith(SHA);
  });

  it("kısa kimlik ipucusuz, düz mono", () => {
    render(<Kimlik deger="TPD-1" tur="jira" />);
    expect(screen.getByText("TPD-1").closest(".ipucu")).toBeNull();
  });
});

describe("Ipucu", () => {
  it("metin yoksa yalnız içerik çizilir", () => {
    const { container } = render(<Ipucu metin="">x</Ipucu>);
    expect(container.querySelector(".ipucu")).toBeNull();
  });
});

describe("Cip / DurumCipi", () => {
  it("bicim, boyut ve sar sınıfları; aciklama erişilebilir ipucu olur", () => {
    render(
      <>
        <Cip bicim="etiket" boyut="kucuk">AC5</Cip>
        <Cip bicim="duz">ikincil</Cip>
        <Cip sar aciklama="Uzun açıklama">neden</Cip>
      </>,
    );
    expect(screen.getByText("AC5")).toHaveClass("cip", "cip-notr", "cip-etiket", "cip-kucuk");
    expect(screen.getByText("ikincil")).toHaveClass("cip-duz");
    expect(screen.getByText("neden")).toHaveClass("cip-uzun");
    expect(screen.getByText("neden").closest(".ipucu")).toHaveAttribute("aria-description", "Uzun açıklama");
  });

  it("haritadan etiket+ton; bilinmeyen değer nötr ve aynen", () => {
    render(
      <>
        <DurumCipi harita={CASE_DURUMU} deger="approved" />
        <DurumCipi harita={CASE_DURUMU} deger="bilinmeyen_durum" />
      </>,
    );
    expect(screen.getByText(CASE_DURUMU.approved.etiket)).toHaveClass(`cip-${CASE_DURUMU.approved.ton}`);
    expect(screen.getByText("bilinmeyen_durum")).toHaveClass("cip-notr");
  });
});

describe("MetaIzgara / MetaSatiri", () => {
  it("etiket: değer ızgarası; boş değer —", () => {
    render(<MetaIzgara etiket="Ayrıntılar" ogeler={[{ etiket: "Giren", deger: "Ayşe" }, { etiket: "Not", deger: null }]} />);
    const dl = screen.getByLabelText("Ayrıntılar");
    expect(dl.tagName).toBe("DL");
    expect(dl).toHaveClass("meta-izgara", "meta-izgara-yan");
    expect(screen.getByText("Not").nextElementSibling).toHaveTextContent("—");
  });

  it("satır içi meta boş öğeyi atlar", () => {
    const { container } = render(<MetaSatiri ogeler={[{ etiket: "Story", deger: "TPD-1" }, { etiket: "Test", deger: "" }]} />);
    expect(container.querySelectorAll(".meta-satiri-oge")).toHaveLength(1);
    expect(container.textContent).toBe("Story TPD-1");
  });
});

describe("SuzgecCubugu / SegmentSecici", () => {
  it("segmentler aria-pressed ve sayılı ad; sonuç status bölgesinde", async () => {
    const degistir = vi.fn();
    render(
      <SuzgecCubugu etiket="Süzgeç" sonuc="3/10 test">
        <SegmentSecici
          etiket="Durum"
          deger=""
          degistir={degistir}
          secenekler={[
            { deger: "", ad: "Tümü", sayi: 10 },
            { deger: "f", ad: "Başarısız", sayi: 0, pasif: true },
          ]}
        />
      </SuzgecCubugu>,
    );
    expect(screen.getByRole("button", { name: "Tümü (10)" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Başarısız (0)" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("3/10 test");
    await userEvent.click(screen.getByRole("button", { name: "Tümü (10)" }));
    expect(degistir).toHaveBeenCalledWith("");
  });
});

describe("EylemCubugu (ET-07)", () => {
  it("içindeki kilitli IslemDugmesi aria-disabled: odaklanır, nedeni bağlı, tıklama çalışmaz", async () => {
    const tikla = vi.fn();
    render(
      <EylemCubugu hiza="son" etiket="Eylemler">
        <IslemDugmesi disabled title="Önce modeli onaylayın." onClick={tikla}>
          Üret
        </IslemDugmesi>
      </EylemCubugu>,
    );
    const d = screen.getByRole("button", { name: "Üret" });
    expect(d).not.toHaveAttribute("disabled");
    expect(d).toHaveAttribute("aria-disabled", "true");
    expect(d).toHaveAccessibleDescription("Önce modeli onaylayın.");
    d.focus();
    expect(d).toHaveFocus();
    await userEvent.click(d);
    expect(tikla).not.toHaveBeenCalled();
    expect(screen.getByRole("group", { name: "Eylemler" })).toHaveClass("eylemler", "eylem-cubugu-son");
  });

  it("dışında (varsayılan) yerel disabled korunur — geriye uyum", () => {
    render(<IslemDugmesi disabled>Üret</IslemDugmesi>);
    expect(screen.getByRole("button", { name: "Üret" })).toBeDisabled();
  });
});

describe("TabloSarici / BosDurum", () => {
  it("odaklanabilir bölge + tablo sınıfları (yığın/matris, sık, uzun)", () => {
    const { rerender } = render(
      <TabloSarici etiket="Koşular tablosu" yogunluk="sik" uzun>
        <tbody>
          <tr>
            <td>x</td>
          </tr>
        </tbody>
      </TabloSarici>,
    );
    const bolge = screen.getByRole("region", { name: "Koşular tablosu" });
    expect(bolge).toHaveAttribute("tabindex", "0");
    expect(bolge).toHaveClass("tablo-sarici", "tablo-sarici-uzun");
    expect(bolge.querySelector("table")).toHaveClass("tablo", "tablo-sik", "tablo-yigin");
    rerender(
      <TabloSarici etiket="Karar tablosu" darEkran="kaydir">
        <tbody />
      </TabloSarici>,
    );
    expect(screen.getByRole("region", { name: "Karar tablosu" }).querySelector("table")).toHaveClass("tablo-matris");
  });

  it("boş durum kipleri ve sonraki adım yuvası", () => {
    const { container } = render(
      <BosDurum baslik="Henüz koşu yok." kip="satir" eylem={<a href="/kod">Koşu başlat</a>}>
        açıklama
      </BosDurum>,
    );
    expect(container.firstChild).toHaveClass("bos-durum", "bos-durum-satir");
    expect(screen.getByRole("link", { name: "Koşu başlat" }).closest(".bos-durum-eylem")).not.toBeNull();
  });
});
