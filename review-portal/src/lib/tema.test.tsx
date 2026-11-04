import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { oturumAc } from "../test/yardimci";
import temaOnKaynagi from "../tema-on.js?raw";
import { sonrakiTema, temaKaydet, temaOku, temaUygula, useTema } from "./tema";

const kok = () => document.documentElement;

/** Yalnız tema anahtarlarına yapılan yazmalar (oturum vb. diğer anahtarlar sayılmaz). */
function temaYazmalari(casus: { mock: { calls: unknown[][] } }) {
  return casus.mock.calls.filter(([anahtar]) => anahtar === "tp-tema" || anahtar === "tp-tema-v");
}

afterEach(() => {
  kok().removeAttribute("data-theme");
});

describe("temaOku (göç dahil)", () => {
  it("depolama boşsa koyu döner ve işareti yazar", () => {
    expect(temaOku()).toBe("koyu");
    expect(localStorage.getItem("tp-tema-v")).toBe("2");
    expect(localStorage.getItem("tp-tema")).toBeNull();
  });

  it("işaretsiz eski tp-tema=sistem kaydı silinir: iki ardışık okumada da koyu", () => {
    localStorage.setItem("tp-tema", "sistem");
    expect(temaOku()).toBe("koyu");
    expect(localStorage.getItem("tp-tema")).toBeNull();
    expect(temaOku()).toBe("koyu");
    expect(localStorage.getItem("tp-tema-v")).toBe("2");
  });

  it("işaretsiz eski açık/koyu kayıtları da göçte silinir", () => {
    localStorage.setItem("tp-tema", "acik");
    expect(temaOku()).toBe("koyu");
    expect(localStorage.getItem("tp-tema")).toBeNull();
  });

  it("işaretli kayıt korunur (sistem dahil)", () => {
    localStorage.setItem("tp-tema-v", "2");
    localStorage.setItem("tp-tema", "sistem");
    expect(temaOku()).toBe("sistem");
    expect(temaOku()).toBe("sistem");
    localStorage.setItem("tp-tema", "acik");
    expect(temaOku()).toBe("acik");
    localStorage.setItem("tp-tema", "koyu");
    expect(temaOku()).toBe("koyu");
  });

  it("tanınmayan değer koyu sayılır", () => {
    localStorage.setItem("tp-tema-v", "2");
    localStorage.setItem("tp-tema", "dark");
    expect(temaOku()).toBe("koyu");
    localStorage.setItem("tp-tema", "");
    expect(temaOku()).toBe("koyu");
  });

  it("başka bir sürüm işareti de göçü tetikler", () => {
    localStorage.setItem("tp-tema-v", "1");
    localStorage.setItem("tp-tema", "acik");
    expect(temaOku()).toBe("koyu");
    expect(localStorage.getItem("tp-tema-v")).toBe("2");
  });

  it("depolama istisna atarsa koyu döner", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("engelli", "SecurityError");
    });
    expect(temaOku()).toBe("koyu");
  });

  it("localStorage erişimi istisna atarsa koyu döner", () => {
    const erisim = vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
      throw new DOMException("engelli", "SecurityError");
    });
    try {
      expect(temaOku()).toBe("koyu");
    } finally {
      erisim.mockRestore(); // setup.ts'teki afterEach localStorage.clear() çağırır
    }
  });
});

describe("temaUygula ve döngü", () => {
  it("koyu → dark, açık → light, sistem → öznitelik yok", () => {
    temaUygula("koyu");
    expect(kok()).toHaveAttribute("data-theme", "dark");
    temaUygula("acik");
    expect(kok()).toHaveAttribute("data-theme", "light");
    temaUygula("sistem");
    expect(kok()).not.toHaveAttribute("data-theme");
  });

  it("döngü sırası koyu → açık → sistem → koyu", () => {
    expect(sonrakiTema("koyu")).toBe("acik");
    expect(sonrakiTema("acik")).toBe("sistem");
    expect(sonrakiTema("sistem")).toBe("koyu");
  });

  it("temaKaydet yazma istisnasını yutar", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("dolu", "QuotaExceededError");
    });
    expect(() => temaKaydet("acik")).not.toThrow();
  });

  it("kaydedilen tercih sonraki açılışta okunur", () => {
    temaKaydet("sistem");
    expect(temaOku()).toBe("sistem");
  });
});

describe("useTema", () => {
  it("mount tp-tema yazmaz; yalnız uygular", () => {
    temaOku(); // main.tsx'teki önyükleme: göç burada yapılır
    const yaz = vi.spyOn(Storage.prototype, "setItem");
    const sil = vi.spyOn(Storage.prototype, "removeItem");
    const { result } = renderHook(() => useTema());
    expect(result.current[0]).toBe("koyu");
    expect(kok()).toHaveAttribute("data-theme", "dark");
    expect(temaYazmalari(yaz)).toEqual([]);
    expect(temaYazmalari(sil)).toEqual([]);
  });

  it("değiştir döngüyü izler, html'i günceller ve yalnız o zaman yazar", () => {
    const { result } = renderHook(() => useTema());
    expect(localStorage.getItem("tp-tema")).toBeNull();
    act(() => result.current[1]());
    expect(result.current[0]).toBe("acik");
    expect(kok()).toHaveAttribute("data-theme", "light");
    expect(localStorage.getItem("tp-tema")).toBe("acik");
    act(() => result.current[1]());
    expect(result.current[0]).toBe("sistem");
    expect(kok()).not.toHaveAttribute("data-theme");
    expect(localStorage.getItem("tp-tema")).toBe("sistem");
    act(() => result.current[1]());
    expect(result.current[0]).toBe("koyu");
    expect(kok()).toHaveAttribute("data-theme", "dark");
    expect(localStorage.getItem("tp-tema")).toBe("koyu");
    expect(localStorage.getItem("tp-tema-v")).toBe("2");
  });
});

describe("Kabuk tema düğmesi", () => {
  it("varsayılan koyu; açılışta tema yazılmaz; tıklama döngüyü izler", async () => {
    await oturumAc("analist");
    temaOku();
    const yaz = vi.spyOn(Storage.prototype, "setItem");
    const u = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/denetim"]}>
        <OturumProvider>
          <BildirimProvider>
            <Rotalar />
          </BildirimProvider>
        </OturumProvider>
      </MemoryRouter>,
    );
    await screen.findByRole("heading", { name: "Denetim", level: 1 });
    // Tema, Kabuk'un useEffect'inde uygulanır. Kabuk oturum çözülünce act dışı bir güncellemeyle bağlanır;
    // findByRole başlığı DOM'a yazıldığı anda bulur, pasif efekt henüz çalışmamış olabilir (yük altında
    // ~30 koşuda 1 kez data-theme null görülüyordu). Efekti bekle.
    await waitFor(() => expect(kok()).toHaveAttribute("data-theme", "dark"));
    expect(temaYazmalari(yaz)).toEqual([]);
    await u.click(screen.getByRole("button", { name: "Tema: koyu (değiştir)" }));
    expect(kok()).toHaveAttribute("data-theme", "light");
    expect(localStorage.getItem("tp-tema")).toBe("acik");
    await u.click(screen.getByRole("button", { name: "Tema: açık (değiştir)" }));
    expect(kok()).not.toHaveAttribute("data-theme");
    expect(screen.getByRole("button", { name: "Tema: sistem (değiştir)" })).toBeInTheDocument();
  });
});

describe("tema-on.js (ilk boyama betiği) temaOku + temaUygula ile aynı sonucu verir", () => {
  const calistir = () => new Function(temaOnKaynagi)();
  const durumlar: [string, Record<string, string>][] = [
    ["depolama boş", {}],
    ["işaretli açık", { "tp-tema-v": "2", "tp-tema": "acik" }],
    ["işaretli sistem", { "tp-tema-v": "2", "tp-tema": "sistem" }],
    ["işaretli koyu", { "tp-tema-v": "2", "tp-tema": "koyu" }],
    ["işaretli tanınmayan", { "tp-tema-v": "2", "tp-tema": "mor" }],
    ["işaretsiz eski açık (göç: koyu)", { "tp-tema": "acik" }],
    ["işaretsiz eski sistem (göç: koyu)", { "tp-tema": "sistem" }],
  ];
  it.each(durumlar)("%s", (_ad, kayit) => {
    const yukle = () => {
      localStorage.clear();
      for (const [k, v] of Object.entries(kayit)) localStorage.setItem(k, v);
      kok().setAttribute("data-theme", "dark"); // index.html varsayılanı
    };
    yukle();
    const yaz = vi.spyOn(Storage.prototype, "setItem");
    calistir();
    const betik = kok().getAttribute("data-theme");
    expect(temaYazmalari(yaz)).toEqual([]); // betik depolamaya yazmaz
    yaz.mockRestore();
    yukle();
    temaUygula(temaOku());
    expect(betik).toBe(kok().getAttribute("data-theme"));
  });

  it("depolama erişimi hata verirse koyu kalır", () => {
    kok().setAttribute("data-theme", "dark");
    const oku = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("engelli");
    });
    calistir();
    oku.mockRestore();
    expect(kok()).toHaveAttribute("data-theme", "dark");
  });
});
