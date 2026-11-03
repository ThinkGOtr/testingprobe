import { describe, expect, it } from "vitest";
import { dokumanBloklari, sablonBolumu } from "./dokuman";

// core parse_description çıktısı (TPD-1, kısaltılmış): bloklar boş satırla, maddeler tek satırla.
const TPD1 = [
  "🎯 Objective (Amaç)",
  "Bayi, katalogdan ürünleri sepete ekleyip kampanya indirimiyle siparişini onaylayabilmelidir.",
  "🚀 Scope (Kapsam)",
  "- Katalogdan sepete ürün ekleme ve sepet sayacı\n- \"6 al 1 bedava\" kampanya hesabı",
  "🔄 User Flow (Kullanıcı Akışı)",
  "1. Bayi giriş yapar ve ürün kataloğunu açar.\n2. Ürünleri adetleriyle sepete ekler.",
  "ℹ️ Other Information & Assets (Diğer Bilgiler & Kaynaklar)",
  "Not applicable",
  "🧪 QA Checklist",
  "- Mutlu yol: ürün sepete eklenir (AC1)",
].join("\n\n");

describe("sablonBolumu", () => {
  it("emoji, parantezli dil ve Türkçe büyük harf farkını tanır", () => {
    expect(sablonBolumu("🎯 Objective (Amaç)")).toBe("objective");
    expect(sablonBolumu("🎯Objective")).toBe("objective");
    expect(sablonBolumu("ℹ️ Other Information & Assets (Diğer Bilgiler & Kaynaklar)")).toBe("other");
    expect(sablonBolumu("KULLANICI AKIŞI")).toBe("user_flow");
    expect(sablonBolumu("Dependencies and Integration")).toBe("dependencies");
    expect(sablonBolumu(":test_tube: QA Checklist")).toBe("qa_checklist");
    expect(sablonBolumu("Kapsam dışı işler şunlardır")).toBeNull();
  });
});

describe("dokumanBloklari", () => {
  it("şablonu başlık, madde ve numaralı listeye ayırır; AC yerini QA Checklist'ten önce işaretler", () => {
    const { bloklar, sablon } = dokumanBloklari(TPD1);
    expect(sablon).toBe(true);
    expect(bloklar.map((b) => b.tur)).toEqual([
      "baslik", "paragraf", "baslik", "liste", "baslik", "liste", "baslik", "paragraf", "ac", "baslik", "liste",
    ]);
    expect(bloklar[3]).toEqual({
      tur: "liste",
      numarali: false,
      maddeler: ["Katalogdan sepete ürün ekleme ve sepet sayacı", "\"6 al 1 bedava\" kampanya hesabı"],
    });
    expect(bloklar[5]).toMatchObject({ tur: "liste", numarali: true });
  });

  it("QA Checklist yoksa AC yeri sona konur", () => {
    const { bloklar } = dokumanBloklari("🎯 Objective\n\nAmaç.\n\n🚀 Scope\n\n- x");
    expect(bloklar.at(-1)).toEqual({ tur: "ac" });
  });

  it("şablonsuz açıklama tek paragraf kalır, satır sonları korunur, AC yeri işaretlenmez", () => {
    const { bloklar, sablon } = dokumanBloklari("Birinci satır\nikinci satır");
    expect(sablon).toBe(false);
    expect(bloklar).toEqual([{ tur: "paragraf", satirlar: ["Birinci satır", "ikinci satır"] }]);
  });

  it("tek bir bölüm adı şablon sayılmaz", () => {
    expect(dokumanBloklari("Açıklama.\n\nKapsam\n\nMetin.").sablon).toBe(false);
  });
});
