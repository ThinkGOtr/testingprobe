// Rol/izin modeli v2 (specs/012-rol-yetki/ANALIZ.md §3–§6): portal kataloğu core `yetki.py` ile aynı,
// `useIzin` / `IzinGerekli` `/auth/me` → `izinler`'den okur, menü rolün izinleriyle çizilir.
import { render, screen, waitFor, within } from "@testing-library/react";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { mockOturumuAyarla } from "../api/http";
import type { Kullanici, Rol } from "../api/types";
import { OturumProvider, useIzin } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { IzinGerekli } from "../components/IzinGerekli";
import { oturumAc, sar } from "../test/yardimci";
import { IZINLER, izinNedeni, normalizeRol, oturumIzinleri, ROL_ETIKETLERI, rolEtiketi, rolIzinleri, ROLLER, ROTA_IZINLERI, type Izin } from "./yetki";

const YETKI_PY = resolve(__dirname, "../../../core/src/tp_core/auth/yetki.py");

/** yetki.py'deki `IZINLER` sözlüğünü ve sabitlerini düz metinden okur (Python çalıştırmadan). */
function cekirdekKatalogu(): { izinler: Record<string, string[]>; etiketler: Record<string, string> } {
  const py = readFileSync(YETKI_PY, "utf8");
  const sabit: Record<string, string> = {};
  for (const m of py.matchAll(/^([A-Z]+): Final = "([a-z]+)"$/gm)) sabit[m[1]] = m[2];
  const hepsi = Object.values(sabit).filter((v) => (ROLLER as readonly string[]).includes(v));
  const isRolleri = /_IS_ROLLERI = frozenset\(\{([^}]*)\}\)/.exec(py)![1].split(",").map((x) => sabit[x.trim()]);
  const blok = /IZINLER: Final\[.*\] = \{([\s\S]*?)\n\}/.exec(py)![1];
  const izinler: Record<string, string[]> = {};
  for (const m of blok.matchAll(/"([a-z_.]+)": (_HEPSI|_IS_ROLLERI|_r\(([^)]*)\))/g)) {
    izinler[m[1]] = m[2] === "_HEPSI" ? hepsi : m[2] === "_IS_ROLLERI" ? isRolleri : m[3].split(",").map((x) => sabit[x.trim()]);
  }
  const etiketBlok = /ROL_ETIKETLERI: Final\[.*\] = \{([\s\S]*?)\n\}/.exec(py)![1];
  const etiketler: Record<string, string> = {};
  for (const m of etiketBlok.matchAll(/([A-Z]+): "([^"]+)"/g)) etiketler[sabit[m[1]]] = m[2];
  return { izinler, etiketler };
}

describe("katalog: portal kopyası core ile aynı", () => {
  it.skipIf(!existsSync(YETKI_PY))("IZINLER ve ROL_ETIKETLERI yetki.py ile birebir", () => {
    const { izinler, etiketler } = cekirdekKatalogu();
    expect(Object.keys(izinler).length).toBeGreaterThan(20);
    const sirali = (o: Record<string, readonly string[]>) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, [...v].sort()]));
    expect(sirali(IZINLER)).toEqual(sirali(izinler));
    expect(ROL_ETIKETLERI).toEqual(etiketler);
  });

  it("kaldırılan presenter → admin; bilinmeyen rolün izni yok", () => {
    expect(normalizeRol("presenter")).toBe("admin");
    expect(rolEtiketi("presenter")).toBe("Sistem Yöneticisi");
    expect(rolIzinleri("presenter")).toEqual(rolIzinleri("admin"));
    expect(rolIzinleri("yok")).toEqual([]);
    expect(rolIzinleri(null)).toEqual([]);
  });

  it("görev sahiplikleri (ANALIZ §4.1)", () => {
    const sahip = (i: Izin) => [...IZINLER[i]].sort();
    expect(sahip("case.decide")).toEqual(["tester"]);
    expect(sahip("case.approve")).toEqual(["analyst"]);
    expect(sahip("case.publish")).toEqual(["tester"]);
    expect(sahip("token.issue")).toEqual(["tester"]);
    expect(sahip("run.trigger_manual")).toEqual(["developer", "engineer"]);
    expect(sahip("demo.manage")).toEqual(["admin", "engineer"]);
    expect(sahip("baseline.manage")).toEqual(["po"]);
    expect(rolIzinleri("viewer")).not.toContain("events.read");
    expect(rolIzinleri("auditor")).not.toContain("events.read");
  });

  it("011 izinleri (dev birleştirmesi): model kararı ve ajan testi Testçi, PO'ya soru Analist, analiz okuma developer hariç", () => {
    const sahip = (i: Izin) => [...IZINLER[i]].sort();
    expect(sahip("design_model.decide")).toEqual(["tester"]);
    expect(sahip("agent_test.run")).toEqual(["tester"]);
    expect(sahip("case.ask_po")).toEqual(["analyst"]);
    expect(sahip("case.analysis_read")).toEqual(["admin", "analyst", "engineer", "po", "tester"]);
    for (const r of ["developer", "viewer", "auditor"] as const) expect(rolIzinleri(r)).not.toContain("case.analysis_read");
    // Açık soru yanıtlarını okuma: `case.ask_po` ya da `case.decide` (Analist veya Testçi).
    expect(izinNedeni("case.ask_po", "case.decide")).toBe("Bu işlem için gereken rol: Analist / Testçi");
    expect(ROTA_IZINLERI["/ajan-urunleri"]).toEqual(["requirement.read"]);
  });

  it("oturum izinleri: core `izinler` verdiyse o, yoksa katalog", () => {
    expect([...oturumIzinleri({ rol: "engineer", izinler: ["run.read"] })]).toEqual(["run.read"]);
    expect(oturumIzinleri({ rol: "tester" }).has("case.decide")).toBe(true);
    expect(oturumIzinleri(null).size).toBe(0);
    expect(izinNedeni("case.decide", "case.approve")).toBe("Bu işlem için gereken rol: Testçi / Analist");
  });
});

function IzinGoster({ izin }: { izin: Izin }) {
  return <span data-testid="izin">{String(useIzin(izin))}</span>;
}

describe("useIzin / IzinGerekli", () => {
  it("useIzin oturumdaki izinleri okur; oturum yokken false", async () => {
    const { unmount } = sar(<IzinGoster izin="case.decide" />);
    expect(screen.getByTestId("izin")).toHaveTextContent("false");
    unmount();
    await oturumAc("testci");
    sar(<IzinGoster izin="case.decide" />);
    await waitFor(() => expect(screen.getByTestId("izin")).toHaveTextContent("true"));
  });

  it("IzinGerekli izinsiz rolde yetki kartı ve gereken rolü gösterir", async () => {
    await oturumAc("analist");
    sar(
      <IzinGerekli izin="token.issue">
        <p>gizli</p>
      </IzinGerekli>,
    );
    expect(await screen.findByText("Bu ekran için yetkiniz yok.")).toBeInTheDocument();
    expect(screen.getByText("Gereken rol: Testçi")).toBeInTheDocument();
    expect(screen.queryByText("gizli")).toBeNull();
  });

  it("IzinGerekli birden çok izinden birini yeterli sayar", async () => {
    await oturumAc("testci");
    sar(
      <IzinGerekli izin={["audit.read_all", "audit.read_own"]}>
        <p>denetim</p>
      </IzinGerekli>,
    );
    expect(await screen.findByText("denetim")).toBeInTheDocument();
  });
});

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

const MENU: Record<string, string> = {
  "/gereksinimler": "Gereksinimler",
  "/kod": "Kod üretimi",
  "/kosular": "Koşular",
  "/bug-taslaklari": "Bug taslakları",
  "/yol-haritasi": "Demo yol haritası",
  "/kontrol-kulesi": "Kontrol Kulesi",
  "/demo": "Demo kontrolleri",
  "/denetim": "Denetim kaydı",
  "/claude-code": "Claude Code kanalı",
  "/ajan-urunleri": "Ajan ürünleri",
};

const HESAP: Record<Rol, string> = {
  admin: "sunucu",
  auditor: "denetci",
  analyst: "analist",
  po: "po",
  tester: "testci",
  engineer: "muhendis",
  developer: "gelistirici",
  viewer: "izleyici",
};

describe("menü: yalnız izinli ekranlar (ANALIZ §4.2)", () => {
  it.each(ROLLER.map((r) => [r]))("%s", async (rol) => {
    await oturumAc(HESAP[rol]);
    uygulama("/kontrol-kulesi");
    const menu = await screen.findByRole("navigation", { name: "Ana menü" });
    await waitFor(() => expect(within(menu).getByText("Kontrol Kulesi")).toBeInTheDocument());
    const izinler = new Set(rolIzinleri(rol));
    for (const [yol, ad] of Object.entries(MENU)) {
      const gorunur = ROTA_IZINLERI[yol].some((i) => izinler.has(i));
      if (gorunur) expect(within(menu).getByText(ad), `${rol}: ${ad}`).toBeInTheDocument();
      else expect(within(menu).queryByText(ad), `${rol}: ${ad}`).toBeNull();
    }
    // Kullanıcı kutusunda yeni rol etiketi.
    expect(document.querySelector(".kullanici-rol")).toHaveTextContent(ROL_ETIKETLERI[rol]);
  });

  it("beklenen menüler: Görüntüleyici yalnız Kontrol Kulesi + Koşular; Developer Claude Code ve Kod görmez", async () => {
    await oturumAc("izleyici");
    uygulama("/kontrol-kulesi");
    const menu = await screen.findByRole("navigation", { name: "Ana menü" });
    await waitFor(() => expect(within(menu).getAllByRole("link").map((a) => a.querySelector("span")?.textContent)).toEqual(["Koşular", "Kontrol Kulesi"]));
    // Canlı olay göstergesi yok (events.read yok).
    expect(screen.queryByText("Olaylar: örnek veri")).toBeNull();
  });

  it("izinsiz rotaya doğrudan gelen rol yetki kartını görür (developer → /kod)", async () => {
    await oturumAc("gelistirici");
    uygulama("/kod");
    expect(await screen.findByText("Bu ekran için yetkiniz yok.")).toBeInTheDocument();
  });

  it("core izinleri menüyü belirler (rol adı değil)", async () => {
    const k: Kullanici = { id: "u-x", kullanici_adi: "x", rol: "engineer", izinler: ["dashboard.read", "run.read"] };
    const me = api.me;
    api.me = async () => k;
    mockOturumuAyarla(k);
    try {
      uygulama("/kontrol-kulesi");
      const menu = await screen.findByRole("navigation", { name: "Ana menü" });
      await waitFor(() => expect(within(menu).getAllByRole("link").map((a) => a.querySelector("span")?.textContent)).toEqual(["Koşular", "Kontrol Kulesi"]));
    } finally {
      api.me = me;
    }
  });
});
