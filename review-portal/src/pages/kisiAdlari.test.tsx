import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { mockVerisi } from "../api/mock/handlers";
import { OturumProvider, kisiAdiCevir } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { KisiAdi } from "../components/KisiAdi";
import { oturumAc } from "../test/yardimci";

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

describe("portal kişi adları (yalnızca gösterim)", () => {
  it("üst çubuk kişi adını ve rolü gösterir", async () => {
    await oturumAc("analist");
    const { container } = uygulama("/denetim");
    await screen.findByRole("heading", { name: "Denetim", level: 1 });
    const kutu = container.querySelector(".kullanici") as HTMLElement;
    expect(within(kutu).getByText("Cengizhan Gunaydin")).toHaveAttribute("title", "Cengizhan Gunaydin · Analist (analist)");
    expect(within(kutu).getByText("Analist")).toBeInTheDocument();
  });

  it("adı olmayan sunucu kullanıcı adıyla ve Sunucu rolüyle görünür", async () => {
    await oturumAc("sunucu");
    const { container } = uygulama("/denetim");
    await screen.findByRole("heading", { name: "Denetim", level: 1 });
    const kutu = container.querySelector(".kullanici") as HTMLElement;
    expect(kutu).toHaveTextContent("sunucu");
    expect(kutu).toHaveTextContent("Sunucu");
  });

  it("denetim tablosunda aktör görünen adla gösterilir; sistem aktörü aynen kalır", async () => {
    await oturumAc("testci");
    mockVerisi().denetim.push(
      { aktor: "po", eylem: "requirement.po_approved", nesne: "requirement:x", ozet: "-", zaman: new Date().toISOString() },
      { aktor: "system", eylem: "seed.applied", nesne: "-", ozet: "-", zaman: new Date().toISOString() },
    );
    uygulama("/denetim");
    expect(await screen.findAllByText("Cengizhan Gunaydin · PO")).not.toHaveLength(0);
    expect(screen.getAllByText("system").length).toBeGreaterThan(0);
  });

  it("çevirici eşlemede olmayan değeri aynen döndürür", () => {
    const kisiler = { muhendis: "Gokhan Sipahi · Mühendis" };
    expect(kisiAdiCevir(kisiler, "muhendis")).toBe("Gokhan Sipahi · Mühendis");
    expect(kisiAdiCevir(kisiler, "Muhendis")).toBe("Gokhan Sipahi · Mühendis");
    expect(kisiAdiCevir(kisiler, "712020:abc")).toBe("712020:abc");
    expect(kisiAdiCevir(undefined, "po")).toBe("po");
    expect(kisiAdiCevir(kisiler, null)).toBe("");
  });

  it("sağlayıcı dışında bileşen adı aynen gösterir", () => {
    render(<KisiAdi ad="testci" />);
    expect(screen.getByText("testci")).toBeInTheDocument();
  });
});
