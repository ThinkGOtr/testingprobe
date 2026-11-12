// 011: Java ve C# sözdizimi renklendirmesi; dil dosya uzantısından.
import { describe, expect, it } from "vitest";
import { belirtecle, dilBul, satirlaraBol, vurguDili, type VurguDili } from "./vurgula";

const tur = (kod: string, dil: VurguDili, metin: string) => belirtecle(kod, dil).find((x) => x.metin === metin)?.tur;

describe("dilBul ve vurguDili", () => {
  it("uzantıdan: .java, .cs, .py, .ts; bilinmeyen ve boş TypeScript", () => {
    expect(dilBul("demo-app/e2e-java/src/test/java/a/B.java")).toBe("java");
    expect(dilBul("Uretilen/Tpd1C8Tests.CS")).toBe("csharp");
    expect(dilBul("tests/test_a.py")).toBe("py");
    expect(dilBul("tests/a.spec.ts")).toBe("ts");
    expect(dilBul("README")).toBe("ts");
    expect(dilBul(null)).toBe("ts");
  });

  it("üretim dilinden sözdizimi: python → py; bilinmeyen null", () => {
    expect(vurguDili("python")).toBe("py");
    expect(vurguDili("csharp")).toBe("csharp");
    expect(vurguDili("java")).toBe("java");
    expect(vurguDili("kotlin")).toBeNull();
    expect(vurguDili(null)).toBeNull();
  });
});

describe("Java", () => {
  const kod = `// yorum
package com.antreklabs.bayi.uretilen;
/* blok
   yorum */
@Bayi("bayi1")
public class C9Test extends TestTabani {
  @Test(groups = {"uretilen", "web"}, description = "7 adet")
  public void senaryo() {
    cart.expectTotal("150,00 TL");
    long n = 25L;
  }
}`;

  it("anahtar sözcük, açıklama, dize, @Annotation, tip, fonksiyon, sayı", () => {
    expect(tur(kod, "java", "package")).toBe("anahtar");
    expect(tur(kod, "java", "public")).toBe("anahtar");
    expect(tur(kod, "java", "void")).toBe("anahtar");
    expect(tur(kod, "java", "// yorum")).toBe("yorum");
    expect(tur(kod, "java", "/* blok\n   yorum */")).toBe("yorum");
    expect(tur(kod, "java", '"150,00 TL"')).toBe("metin");
    expect(tur(kod, "java", "@Bayi")).toBe("ek");
    expect(tur(kod, "java", "@Test")).toBe("ek");
    expect(tur(kod, "java", "TestTabani")).toBe("tip");
    expect(tur(kod, "java", "expectTotal")).toBe("fonksiyon");
    expect(tur(kod, "java", "25L")).toBe("sayi");
  });

  it("dize içindeki // ve @ yorum/ek sayılmaz", () => {
    const b = belirtecle('String u = "http://a@b";', "java");
    expect(b.some((x) => x.tur === "yorum" || x.tur === "ek")).toBe(false);
    expect(b.find((x) => x.tur === "metin")?.metin).toBe('"http://a@b"');
  });
});

describe("C#", () => {
  const kod = `using NUnit.Framework;
namespace Bayi.E2E.Uretilen;

[TestFixture]
[Category("tp-case-1")]
public class Tpd1Tests : PageTest
{
    [Test(Description = "C8")]
    public async Task Senaryo()
    {
        var yol = @"C:\\dosya";
        await cart.ExpectTotal("750,00 TL"); // toplam
        var x = items[0];
    }
}`;

  it("anahtar sözcük, [Attribute], dize (@\"…\" dahil), açıklama, tip, fonksiyon", () => {
    expect(tur(kod, "csharp", "using")).toBe("anahtar");
    expect(tur(kod, "csharp", "namespace")).toBe("anahtar");
    expect(tur(kod, "csharp", "async")).toBe("anahtar");
    expect(tur(kod, "csharp", "[TestFixture]")).toBe("ek");
    expect(tur(kod, "csharp", '[Category("tp-case-1")]')).toBe("ek");
    expect(tur(kod, "csharp", '[Test(Description = "C8")]')).toBe("ek");
    expect(tur(kod, "csharp", '@"C:\\dosya"')).toBe("metin");
    expect(tur(kod, "csharp", '"750,00 TL"')).toBe("metin");
    expect(tur(kod, "csharp", "// toplam")).toBe("yorum");
    expect(tur(kod, "csharp", "PageTest")).toBe("tip");
    expect(tur(kod, "csharp", "ExpectTotal")).toBe("tip");
  });

  it("satır içi dizi erişimi ([0]) öznitelik sayılmaz", () => {
    expect(belirtecle(kod, "csharp").some((x) => x.tur === "ek" && x.metin.includes("0"))).toBe(false);
  });
});

describe("Python dekoratörü ve güvenlik", () => {
  it("satır başı @decorator ek; @ işleci (matris) değil", () => {
    expect(tur("@pytest.mark.uretilen\ndef test_a(page):\n    pass", "py", "@pytest.mark.uretilen")).toBe("ek");
    expect(belirtecle("c = a @ b", "py").some((x) => x.tur === "ek")).toBe(false);
  });

  it("belirteçler metin olarak kalır (HTML üretilmez); satırlara bölünür", () => {
    const s = satirlaraBol(belirtecle('String a = "<img onerror=x>";\nint b = 2;', "java"));
    expect(s).toHaveLength(2);
    expect(s[0].some((x) => x.metin === '"<img onerror=x>"')).toBe(true);
  });
});
