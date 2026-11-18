// 011 + 014: Java, C#, Kotlin ve Swift sözdizimi renklendirmesi; dil dosya uzantısından.
import { describe, expect, it } from "vitest";
import { belirtecle, dilBul, satirlaraBol, vurguDili, type VurguDili } from "./vurgula";

const tur = (kod: string, dil: VurguDili, metin: string) => belirtecle(kod, dil).find((x) => x.metin === metin)?.tur;

describe("dilBul ve vurguDili", () => {
  it("uzantıdan: .java, .cs, .py, .ts; bilinmeyen ve boş TypeScript", () => {
    expect(dilBul("demo-app/e2e-java/src/test/java/a/B.java")).toBe("java");
    expect(dilBul("Uretilen/Tpd1C8Tests.CS")).toBe("csharp");
    expect(dilBul("tests/test_a.py")).toBe("py");
    expect(dilBul("tests/a.spec.ts")).toBe("ts");
    expect(dilBul("app/src/androidTest/java/tp/uretilen/C2Test.kt")).toBe("kt");
    expect(dilBul("build.gradle.kts")).toBe("kt");
    expect(dilBul("BayiSiparisUITests/C2Tests.swift")).toBe("swift");
    expect(dilBul("README")).toBe("ts");
    expect(dilBul(null)).toBe("ts");
  });

  it("üretim dilinden sözdizimi: python → py; bilinmeyen null", () => {
    expect(vurguDili("python")).toBe("py");
    expect(vurguDili("csharp")).toBe("csharp");
    expect(vurguDili("java")).toBe("java");
    expect(vurguDili("kotlin")).toBe("kt");
    expect(vurguDili("swift")).toBe("swift");
    expect(vurguDili("rust")).toBeNull();
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

describe("Kotlin (Espresso)", () => {
  const kod = `package com.antreklabs.bayi.tp.uretilen

import androidx.test.ext.junit.runners.AndroidJUnit4
/* blok */
@RunWith(AndroidJUnit4::class)
class TPD1AndroidC2Test : EkranTesti() {
    // yorum
    @Test
    fun senaryo() {
        val adet = 6L
        sepet.urunEkle("KOLA-330", 6)
        sepet.toplamBekle("""150,00 TL""")
    }
}`;

  it("anahtar sözcük, @Annotation, tip, fonksiyon, dize, ham dize, sayı, yorum", () => {
    expect(tur(kod, "kt", "package")).toBe("anahtar");
    expect(tur(kod, "kt", "fun")).toBe("anahtar");
    expect(tur(kod, "kt", "val")).toBe("anahtar");
    expect(tur(kod, "kt", "@RunWith")).toBe("ek");
    expect(tur(kod, "kt", "@Test")).toBe("ek");
    expect(tur(kod, "kt", "AndroidJUnit4")).toBe("tip");
    expect(tur(kod, "kt", "senaryo")).toBe("fonksiyon");
    expect(tur(kod, "kt", '"KOLA-330"')).toBe("metin");
    expect(tur(kod, "kt", '"""150,00 TL"""')).toBe("metin");
    expect(tur(kod, "kt", "6L")).toBe("sayi");
    expect(tur(kod, "kt", "// yorum")).toBe("yorum");
    expect(tur(kod, "kt", "/* blok */")).toBe("yorum");
    // Kod metni kayıpsız: belirteçler birleşince aynı metin.
    expect(belirtecle(kod, "kt").map((b) => b.metin).join("")).toBe(kod);
  });
});

describe("Swift (XCUITest)", () => {
  const kod = `import XCTest

/// Belge yorumu
final class TPD1IosC2Tests: XCTestCase {
    @MainActor
    func testSenaryo() throws {
        let app = XCUIApplication()
        app.launch()
        sepet.urunEkle(kod: "KOLA-330", adet: 6)
        guard sepet.var else { return }
        let n = """
        çok satır
        """
    }
}`;

  it("anahtar sözcük, @attribute, tip, fonksiyon, dize, çok satırlı dize, sayı, yorum", () => {
    expect(tur(kod, "swift", "import")).toBe("anahtar");
    expect(tur(kod, "swift", "final")).toBe("anahtar");
    expect(tur(kod, "swift", "func")).toBe("anahtar");
    expect(tur(kod, "swift", "guard")).toBe("anahtar");
    expect(tur(kod, "swift", "@MainActor")).toBe("ek");
    expect(tur(kod, "swift", "XCTestCase")).toBe("tip");
    expect(tur(kod, "swift", "testSenaryo")).toBe("fonksiyon");
    expect(tur(kod, "swift", '"KOLA-330"')).toBe("metin");
    expect(tur(kod, "swift", '"""\n        çok satır\n        """')).toBe("metin");
    expect(tur(kod, "swift", "6")).toBe("sayi");
    expect(tur(kod, "swift", "/// Belge yorumu")).toBe("yorum");
    expect(belirtecle(kod, "swift").map((b) => b.metin).join("")).toBe(kod);
    expect(satirlaraBol(belirtecle(kod, "swift"))).toHaveLength(kod.split("\n").length);
  });
});
