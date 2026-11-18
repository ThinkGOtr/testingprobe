// Canlı UX doğrulaması, detay şeridi (YD-04, YD-07, YD-10, YD-12) yardımcı kuralları.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { kisiAdiCevir } from "../auth";
import { KullaniciMetni } from "../components/ui";
import { AtifliMetin } from "../components/VeriAtfi";
import { adimMetniSade, bugVeriAtiflari } from "./BugTaslaklari";
import { testKisaAdi } from "./HataDetay";
import { ekKisaEtiketi } from "./KosuSonuclari";
import { nedenTemizle } from "./ScriptDetay";

describe("YD-04 bug taslağı adımları", () => {
  it("metindeki elle numara atılır (<ol> numarasıyla çift görünmez)", () => {
    expect(adimMetniSade("1. bayi1 ile giriş yap")).toBe("bayi1 ile giriş yap");
    expect(adimMetniSade("12) Sepete git")).toBe("Sepete git");
    expect(adimMetniSade("7 adet gir")).toBe("7 adet gir");
  });

  it("{veri:…} atfı çipe döner; parola gibi gizli anahtar maskelenir, ham belirteç görünmez", () => {
    const m = "bayi1 / {veri:ortak.demo_parola} ile giriş yap";
    const { container } = render(<AtifliMetin metin={m} veri={bugVeriAtiflari(m)} />);
    expect(container.textContent).not.toContain("{veri:");
    const cip = container.querySelector(".veri-atif")!;
    expect(cip).toHaveAttribute("data-durum", "gizli");
    expect(cip).toHaveTextContent("••• (gizli)");
    expect(bugVeriAtiflari("{veri:urun.kod} ekle")).toBeUndefined();
  });
});

describe("YD-07 iç kodlar kullanıcı diline", () => {
  it("Sauce ayar adı çevrilir, ham metin Teknik ayrıntı'da", () => {
    render(<KullaniciMetni ham="Sauce bu tetikte koşmaz (pr); SAUCE_TETIKLER=push,deploy,nightly" />);
    expect(screen.getByText(/^Bu koşu türünde Sauce çalıştırılmıyor/)).toBeInTheDocument();
    expect(screen.getByText("Teknik ayrıntı").closest("details")).toHaveTextContent("SAUCE_TETIKLER=push,deploy,nightly");
  });

  it("script engel nedeninde adım/bulgu kodları", () => {
    expect(nedenTemizle("S4: page object'te eksik metot (TPD-1 tutarlılık bulgusu F4: code_defect)")).toBe(
      "Adım 4: page object'te eksik metot (TPD-1 tutarlılık bulgusu F4: kod/veri hatalı)",
    );
  });

  it("AI Probe iç hesap adı görünen ada çevrilir; eşlemedeki ad önceliklidir", () => {
    expect(kisiAdiCevir({}, "gokhan.sipahi-engineer")).toBe("Gokhan Sipahi");
    expect(kisiAdiCevir({}, "ayse-tester-1a2b")).toBe("Ayse");
    expect(kisiAdiCevir({ "gokhan.sipahi-engineer": "Gökhan Sipahi · Otomasyon Mühendisi" }, "gokhan.sipahi-engineer")).toBe("Gökhan Sipahi · Otomasyon Mühendisi");
    expect(kisiAdiCevir({}, "muhendis")).toBe("muhendis");
  });
});

describe("YD-10/12 triage ve koşu", () => {
  it("triage kısa adı: @etiketler atılır, ' · ' öncesi", () => {
    expect(testKisaAdi("TPD-1 C10 · Kampanyalı siparişte uyarı @tp-uretilen")).toBe("TPD-1 C10");
    expect(testKisaAdi(null)).toBe("Hata");
  });

  it("birden çok denemenin ekleri deneme numarasıyla ayrılır; tek denemede ad yalın", () => {
    const ekler = [
      { ad: "screenshot", url: "/a/test-x/shot.png", tur: "image/png" },
      { ad: "trace", url: "/a/test-x/trace.zip", tur: null },
      { ad: "screenshot", url: "/a/test-x-retry1/shot.png", tur: "image/png" },
    ] as Parameters<typeof ekKisaEtiketi>[1];
    expect(ekler.map((e) => ekKisaEtiketi(e, ekler))).toEqual(["screenshot · 1. deneme", "trace · 1. deneme", "screenshot · 2. deneme"]);
    expect(ekKisaEtiketi(ekler[0], ekler.slice(0, 2))).toBe("screenshot");
  });
});
