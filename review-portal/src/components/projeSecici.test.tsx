// Çok proje, Şerit 6 (TP-COK-PROJE-PLANI §6.3): proje seçici, ortak değiştirici entegrasyonu
// (`AIProbeSwitcher.setProjects` + `aiprobe:project-change`), iki sekme 409 `proje_degisti`, 403
// `proje_rolu_yok` ekranı ve seçili projedeki rollerle sınırlı "Rol değiştir". Örnek veri `cok-proje`
// senaryosuyla (api/mock/projeler.ts) çalışır.
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useState } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { PROJE_BASLIGI, projeBasliklari, sekmeninProjesi } from "../api/http";
import { ayar } from "../api/mock/handlers";
import { mockProjeRolunuKaldir, mockProjeSec, mockSeciliProje } from "../api/mock/projeler";
import type { AiprobeHesabi, Kullanici, ProjeListesi } from "../api/types";
import { OturumProvider, projeRolleri } from "../auth";
import { gezinti, kimlikKipiniAyarla } from "../lib/kimlikKipi";
import { degistiriciProjeVerisi, PROJE_OLAYI, projeDili, projeGecisiniSifirla, projeHedefYolu, projeMetni, projeRolEtiketi } from "../lib/proje";
import { oturumAc } from "../test/yardimci";
import { BildirimProvider } from "./Bildirim";
import { Kabuk } from "./Kabuk";
import { oturumdanListe } from "./ProjeSecici";
import { projedekiHesaplar } from "./RolSecici";

vi.mock("../lib/degistirici", () => ({
  DEGISTIRICI_SURUMU: "1.2.0",
  degistiriciyiYukle: async () => {
    if (customElements.get("aiprobe-switcher")) return;
    customElements.define(
      "aiprobe-switcher",
      class extends HTMLElement {
        me: unknown = undefined;
        close() {}
      },
    );
  },
}));

/** Açılışta proje kapsamlı bir uç çağıran sayfa (409/403 yolunu tetikler). */
function CaseSayfasi() {
  const [n, setN] = useState<number | null>(null);
  useEffect(() => {
    api
      .caseler()
      .then((c) => setN(c.length))
      .catch(() => undefined);
  }, []);
  return <p>case sayısı: {n ?? "…"}</p>;
}

function kabuk(yol = "/gereksinimler") {
  return render(
    <MemoryRouter initialEntries={[yol]}>
      <OturumProvider>
        <BildirimProvider>
          <Routes>
            <Route element={<Kabuk />}>
              <Route path="/gereksinimler" element={<p>liste</p>} />
              <Route path="/gereksinimler/:id" element={<p>ayrıntı</p>} />
              <Route path="/caseler" element={<CaseSayfasi />} />
            </Route>
          </Routes>
        </BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

let gidilen: string[];

beforeEach(() => {
  ayar.senaryolar.add("cok-proje");
  gidilen = [];
  vi.spyOn(gezinti, "git").mockImplementation((u: string) => {
    gidilen.push(u);
  });
  projeGecisiniSifirla();
});

afterEach(() => {
  delete window.AIProbeSwitcher;
});

async function secici(): Promise<HTMLElement> {
  return screen.findByTestId("proje-secici");
}

describe("ProjeSecici (kendi seçicisi; ortak değiştirici yok)", () => {
  it("'Organizasyon · Proje' seçiciyle birleşir; sekmenin projesi X-TP-Proje başlığına yazılır", async () => {
    await oturumAc("analist");
    kabuk();
    const s = await secici();
    const dugme = within(s).getByRole("button", { name: /Proje: Örnek Holding · Web Portalı/ });
    expect(dugme).toHaveAttribute("aria-haspopup", "listbox");
    expect(dugme).toHaveAttribute("aria-expanded", "false");
    // Ayrı "proje-baglami" satırı yok (seçiciyle birleşti).
    expect(screen.queryByTestId("proje-baglami")).toBeNull();
    expect(sekmeninProjesi()).toBe("prj-web");
    expect(projeBasliklari()).toEqual({ [PROJE_BASLIGI]: "prj-web" });
  });

  it("listeden seçim: PUT /proje, seçim sunucuda, ayrıntı sayfasından liste sayfasına tam yenileme", async () => {
    await oturumAc("analist");
    sessionStorage.setItem("tp-asistan-test", "x");
    kabuk("/gereksinimler/req-1");
    const u = userEvent.setup();
    await u.click(within(await secici()).getByRole("button"));
    const liste = screen.getByRole("listbox", { name: "Projeleriniz" });
    const secenekler = within(liste).getAllByRole("option");
    expect(secenekler).toHaveLength(3);
    expect(secenekler[0]).toHaveAttribute("aria-selected", "true");
    // Satırda organizasyon ve o projedeki roller.
    expect(secenekler[1]).toHaveTextContent("Mobil Uygulama");
    expect(secenekler[1]).toHaveTextContent("Roller: Analist, Görüntüleyici");
    await u.click(secenekler[1]);
    await waitFor(() => expect(gidilen).toEqual(["/gereksinimler"]));
    expect(mockSeciliProje()).toBe("prj-mobil");
  });

  it("klavye: liste odak alır, ok/End/Home gezinir, Enter seçer; Esc kapatır ve odak düğmeye döner", async () => {
    await oturumAc("analist");
    kabuk("/gereksinimler");
    const u = userEvent.setup();
    const dugme = within(await secici()).getByRole("button");
    dugme.focus();
    await u.keyboard("{Enter}");
    const liste = screen.getByRole("listbox");
    expect(liste).toHaveFocus();
    expect(liste.getAttribute("aria-activedescendant")).toMatch(/oge-0$/);
    await u.keyboard("{End}");
    expect(liste.getAttribute("aria-activedescendant")).toMatch(/oge-2$/);
    await u.keyboard("{Home}{ArrowDown}");
    expect(liste.getAttribute("aria-activedescendant")).toMatch(/oge-1$/);
    await u.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(dugme).toHaveFocus();
    expect(gidilen).toEqual([]);
    await u.keyboard("{Enter}");
    await u.keyboard("{ArrowUp}{Enter}");
    await waitFor(() => expect(gidilen).toEqual(["/gereksinimler"]));
    expect(mockSeciliProje()).toBe("prj-masaustu");
  });

  it("seçili projeyi yeniden seçmek istek göndermez", async () => {
    await oturumAc("analist");
    kabuk();
    const u = userEvent.setup();
    const put = vi.spyOn(api, "projeDegistir");
    await u.click(within(await secici()).getByRole("button"));
    await u.click(screen.getAllByRole("option")[0]);
    expect(put).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("tek projeli kullanıcı (projeler_sayisi 1): liste istenmez, yalnız 'Organizasyon · Proje' yazılır", async () => {
    const tek: Kullanici = {
      id: "u1",
      kullanici_adi: "a",
      rol: "analyst",
      organizasyon: { id: "o", ad: "Org" },
      proje: { pid: "p1", ad: "Tek Proje" },
      roller: ["analyst"],
      projeler_sayisi: 1,
    };
    vi.spyOn(api, "me").mockResolvedValue(tek);
    const liste = vi.spyOn(api, "projeler");
    kabuk();
    expect(await screen.findByTestId("proje-baglami")).toHaveTextContent("Org · Tek Proje");
    expect(screen.queryByTestId("proje-secici")).toBeNull();
    expect(liste).not.toHaveBeenCalled();
  });

  it("çok proje uçları yokken (senaryo kapalı, eski core) seçici çizilmez", async () => {
    ayar.senaryolar.delete("cok-proje");
    await oturumAc("analist");
    kabuk();
    await screen.findByText("liste");
    expect(screen.queryByTestId("proje-secici")).toBeNull();
    expect(sekmeninProjesi()).toBeNull();
  });

  it("dar ekran çekmecesinde aynı seçici (geniş ekranda DOM'da ikinci seçici yok)", async () => {
    await oturumAc("analist");
    kabuk();
    await secici();
    expect(screen.queryByTestId("proje-secici-menu")).toBeNull();
    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: "Menü" }));
    const menu = await screen.findByTestId("proje-secici-menu");
    expect(within(menu).getByRole("button")).toHaveAccessibleName(/Web Portalı/);
  });
});

describe("Ortak değiştirici (1.1.0) proje menüsü", () => {
  it("değiştirici varsa portal seçicisi çizilmez; liste setProjects ile verilir; olay iptal edilip geçiş portalda", async () => {
    const setProjects = vi.fn();
    window.AIProbeSwitcher = { setProjects };
    kimlikKipiniAyarla({ kip: "aiprobe", home: "https://home.test", urun: "testing-probe" });
    await oturumAc("analist");
    kabuk("/gereksinimler/req-9");
    await waitFor(() => expect(setProjects).toHaveBeenCalledWith(expect.objectContaining({ activeId: "prj-web" })));
    const veri = setProjects.mock.calls.at(-1)![0];
    expect(veri.projects).toHaveLength(3);
    expect(veri.projects[1]).toEqual({ pid: "prj-mobil", name: "Mobil Uygulama", org_name: "Örnek Holding", roles: ["analyst", "viewer"] });
    expect(veri.roleLabels.viewer).toEqual({ tr: "Görüntüleyici", en: "Viewer" });
    expect(screen.queryByTestId("proje-secici")).toBeNull();
    expect(screen.queryByTestId("proje-baglami")).toBeNull();

    const olay = new CustomEvent(PROJE_OLAYI, { cancelable: true, bubbles: true, detail: { pid: "prj-mobil" } });
    act(() => {
      window.dispatchEvent(olay);
    });
    expect(olay.defaultPrevented).toBe(true);
    await waitFor(() => expect(gidilen).toEqual(["/gereksinimler"]));
    expect(mockSeciliProje()).toBe("prj-mobil");
  });
});

describe("İki sekme ve rol yok", () => {
  it("başka sekmede proje değişince (409 proje_degisti) kullanıcıya söylenir ve sekme yeni projede yenilenir", async () => {
    await oturumAc("analist");
    // Bu sekme Web Portalı'nda açıldı; öteki sekme Mobil'e geçti.
    kabuk("/gereksinimler");
    await secici();
    mockProjeSec("prj-mobil");
    // Kabuk'ta yeni bir ekran açılınca (istek X-TP-Proje: prj-web ile) 409 gelir.
    render(
      <MemoryRouter initialEntries={["/caseler"]}>
        <CaseSayfasi />
      </MemoryRouter>,
    );
    expect(await screen.findByText(projeMetni("baskaSekme"))).toBeInTheDocument();
    await waitFor(() => expect(gidilen).toEqual(["/gereksinimler"]), { timeout: 3000 });
  });

  it("seçili projede rol yoksa (403 proje_rolu_yok) ekran yerine proje seçtiren bilgi; seçimle geçilir", async () => {
    await oturumAc("analist");
    kabuk("/caseler");
    await secici();
    mockProjeRolunuKaldir("prj-web");
    // Rol kaldırıldıktan sonraki ilk istek (ekran yeniden açılır).
    await act(async () => {
      await api.caseler().catch(() => undefined);
    });
    const ekran = await screen.findByTestId("proje-rol-yok");
    expect(within(ekran).getByRole("heading", { name: "Bu projede rolünüz yok" })).toHaveFocus();
    const u = userEvent.setup();
    await u.click(within(ekran).getByRole("button", { name: "Örnek Holding · Mobil Uygulama" }));
    await waitFor(() => expect(gidilen).toEqual(["/caseler"]));
    expect(mockSeciliProje()).toBe("prj-mobil");
  });
});

describe("yardımcılar", () => {
  it("projeHedefYolu: liste sayfası korunur, ayrıntıdan listeye, listesiz ayrıntıdan ana sayfaya", () => {
    expect(projeHedefYolu("/")).toBe("/");
    expect(projeHedefYolu("/kosular")).toBe("/kosular");
    expect(projeHedefYolu("/gereksinimler/r1/caseler")).toBe("/gereksinimler");
    expect(projeHedefYolu("/kod/s1")).toBe("/kod");
    expect(projeHedefYolu("/hatalar/h1")).toBe("/");
  });

  it("rol etiketi: sunucu etiketi (dil) → portal kataloğu → kod", () => {
    const l: Pick<ProjeListesi, "rolEtiketleri"> = { rolEtiketleri: { viewer: { tr: "İzleyen", en: "Watcher" }, po: "Ürün Sahibi" } };
    expect(projeRolEtiketi("viewer", l, "en")).toBe("Watcher");
    expect(projeRolEtiketi("viewer", l, "tr")).toBe("İzleyen");
    expect(projeRolEtiketi("po", l)).toBe("Ürün Sahibi");
    expect(projeRolEtiketi("analyst", null)).toBe("Analist");
    expect(projeRolEtiketi("bilinmeyen", null)).toBe("bilinmeyen");
  });

  it("i18n: <html lang='en'> İngilizce metinler", () => {
    document.documentElement.lang = "en";
    try {
      expect(projeDili()).toBe("en");
      expect(projeMetni("projeler")).toBe("Your projects");
    } finally {
      document.documentElement.lang = "tr";
    }
    expect(projeMetni("projeler")).toBe("Projeleriniz");
  });

  it("değiştirici verisi ve oturumdan tek satırlık liste", () => {
    expect(degistiriciProjeVerisi(null)).toBeNull();
    const k: Kullanici = { id: "u", kullanici_adi: "a", rol: "po", organizasyon: { id: "o", ad: "Org" }, proje: { id: "p9", ad: "Eski" } };
    const l = oturumdanListe(k);
    expect(l).toEqual({ projeler: [{ pid: "p9", ad: "Eski", kod: null, org_ad: "Org", roller: ["po"] }], secili: "p9" });
    expect(degistiriciProjeVerisi(l)).toEqual({
      enabled: true,
      projects: [{ pid: "p9", name: "Eski", org_name: "Org", roles: ["po"] }],
      activeId: "p9",
      roleLabels: { po: { tr: "PO", en: "PO" } },
    });
    expect(oturumdanListe({ ...k, proje: null })).toBeNull();
  });

  it("'Rol değiştir' yalnız seçili projedeki rolleri listeler (etkin hesap her zaman kalır)", () => {
    const h = (id: string, rol: AiprobeHesabi["rol"]): AiprobeHesabi => ({ id, kullanici_adi: id, rol, gorunen_ad: id });
    const hesaplar = [h("u1", "analyst"), h("u2", "po"), h("u3", "viewer")];
    const k: Kullanici = { id: "u1", kullanici_adi: "u1", rol: "analyst", roles: ["analyst", "po", "viewer"], roller: ["analyst", "viewer"] };
    expect(projedekiHesaplar(hesaplar, k).map((x) => x.id)).toEqual(["u1", "u3"]);
    expect(projedekiHesaplar(hesaplar, { ...k, roller: undefined })).toHaveLength(3);
    expect(projeRolleri(k)).toEqual(["analyst", "viewer"]);
    expect(projeRolleri({ ...k, roller: undefined })).toEqual(["analyst", "po", "viewer"]);
  });
});
