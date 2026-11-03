import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Ikon } from "./Ikon";
import { basHarfler } from "./Kabuk";
import { DisBaglanti } from "./ui";

describe("ikon seti (§4.16)", () => {
  it("ikon dekoratiftir: aria-hidden, odaklanmaz, title yok, metin yok", () => {
    const { container } = render(<Ikon ad="menu" />);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveAttribute("focusable", "false");
    expect(svg.querySelector("title")).toBeNull();
    expect(svg.textContent).toBe("");
  });

  it("dış bağlantının erişilebilir adı ikonla değişmez; ↗ glifi metin olarak kalmaz", () => {
    render(<DisBaglanti href="https://ornek.test/x">Rapor</DisBaglanti>);
    const a = screen.getByRole("link", { name: /^Rapor\s*\(yeni sekmede açılır\)$/ });
    expect(a.querySelector("svg.ikon-dis")).not.toBeNull();
    expect(a.textContent).not.toContain("↗");
  });

  it("avatar baş harfleri: en çok iki, büyük harf (Türkçe)", () => {
    expect(basHarfler("Cengizhan Gunaydin")).toBe("CG");
    expect(basHarfler("sunucu")).toBe("S");
    expect(basHarfler("ilker çelik yılmaz")).toBe("İÇ");
    expect(basHarfler("po.kullanici")).toBe("PK");
  });
});
