// <aiprobe-switcher> bağlama (T042–T043): .me bağlanmadan öğe DOM'a girmez, "Rol değiştir" yalnız çok
// rollü AI Probe oturumunda yuvada, değiştiricinin "Çıkış"ı TP çıkışına yönlenir. Gerçek vendor dosyası
// burada yüklenmez (ağ çağrısı yapar); yerine aynı yüzeyi taşıyan sahte öğe.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { OturumProvider } from "../auth";
import { gezinti } from "../lib/kimlikKipi";
import { AIPROBE_KIPI, sahteSunucu } from "../test/sahteSunucu";
import { BildirimProvider } from "./Bildirim";
import { Kabuk } from "./Kabuk";

const baglanirkenMe: unknown[] = [];

vi.mock("../lib/degistirici", () => ({
  DEGISTIRICI_SURUMU: "1.0.1",
  degistiriciyiYukle: async () => {
    if (customElements.get("aiprobe-switcher")) return;
    customElements.define(
      "aiprobe-switcher",
      class extends HTMLElement {
        me: unknown = undefined;
        kapandi = 0;
        connectedCallback() {
          baglanirkenMe.push(this.me);
        }
        close() {
          this.kapandi += 1;
        }
      },
    );
  },
}));

const ME = {
  id: "u1",
  kullanici_adi: "ayse-analyst",
  rol: "analyst",
  gorunen_ad: "Ayşe · Analist",
  ad_soyad: "Ayşe",
  kisiler: {},
  product: "testing-probe",
  roles: ["analyst", "po"],
  products: { tp: ["analyst", "po"], ap: ["user"] },
};

function Konum() {
  return <output data-testid="konum">{useLocation().pathname + useLocation().search}</output>;
}

function kabuk() {
  return render(
    <MemoryRouter initialEntries={["/denetim?f=1"]}>
      <OturumProvider>
        <BildirimProvider>
          <Kabuk />
          <Konum />
        </BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

async function degistirici(): Promise<HTMLElement & { me: Record<string, unknown> }> {
  await waitFor(() => expect(document.querySelector("aiprobe-switcher")).not.toBeNull());
  return document.querySelector("aiprobe-switcher") as HTMLElement & { me: Record<string, unknown> };
}

describe("AiprobeDegistirici", () => {
  it("öznitelikler ve .me (products dahil) DOM'a girmeden bağlanır", async () => {
    sahteSunucu({ "GET /auth/me": { govde: ME } }, AIPROBE_KIPI);
    baglanirkenMe.length = 0;
    kabuk();
    const sw = await degistirici();
    expect(sw.getAttribute("product")).toBe("testing-probe");
    expect(sw.getAttribute("home-origin")).toBe("https://home.test");
    expect(sw.getAttribute("lang")).toBe("tr");
    expect(sw.getAttribute("logout-method")).toBe("get");
    expect(baglanirkenMe[0]).toMatchObject({ product: "testing-probe", roles: ["analyst", "po"], products: { ap: ["user"] } });
  });

  it("çok rollü oturumda 'Rol değiştir' product-menu yuvasında; tıklayınca /rol-sec?continue=", async () => {
    sahteSunucu({ "GET /auth/me": { govde: ME } }, AIPROBE_KIPI);
    kabuk();
    const sw = await degistirici();
    const dugme = await screen.findByRole("button", { name: "Rol değiştir" });
    expect(dugme.closest('[slot="product-menu"]')?.parentElement).toBe(sw);
    await userEvent.click(dugme);
    expect(screen.getByTestId("konum")).toHaveTextContent("/rol-sec?continue=%2Fdenetim%3Ff%3D1");
  });

  it("tek rollü oturumda yuva yok (değiştirici 'Bu ürün' bölümünü çizmez)", async () => {
    sahteSunucu({ "GET /auth/me": { govde: { ...ME, roles: ["analyst"] } } }, AIPROBE_KIPI);
    kabuk();
    const sw = await degistirici();
    expect(sw.querySelector('[slot="product-menu"]')).toBeNull();
    expect(screen.queryByRole("button", { name: "Rol değiştir" })).not.toBeInTheDocument();
  });

  it("değiştiricinin 'Çıkış'ı (aiprobe:navigate logout) engellenir, TP çıkışı + home çıkış sayfası", async () => {
    sahteSunucu(
      { "GET /auth/me": { govde: ME }, "POST /auth/logout": { govde: { ok: true, redirect: "https://home.test/logout?product=testing-probe" } } },
      AIPROBE_KIPI,
    );
    const git = vi.spyOn(gezinti, "git").mockImplementation(() => {});
    kabuk();
    const sw = await degistirici();
    const olay = new CustomEvent("aiprobe:navigate", { bubbles: true, composed: true, cancelable: true, detail: { kind: "logout" } });
    sw.dispatchEvent(olay);
    expect(olay.defaultPrevented).toBe(true);
    await waitFor(() => expect(git).toHaveBeenCalledWith("https://home.test/logout?product=testing-probe"));
  });
});
