// 011 + 014: üretim dili yardımcıları (6 dil, (platform, dil) matrisi, hat, durum, kontrol adımları).
import { describe, expect, it } from "vitest";
import {
  ciftHati,
  DIL_CATISI,
  DIL_ETIKETI,
  dilDurumuUyarla,
  DILLER,
  dilKaynagiUyarla,
  dilUyarla,
  gecerliCift,
  gecerliDiller,
  hatMi,
  kontrolAdimiEtiketi,
  kontrolAdimlari,
  kontrolZinciri,
  kosuAraci,
  musteriCiMi,
  varsayilanDil,
} from "./dil";

describe("dil yardımcıları", () => {
  it("DILLER sözleşme sırasıyla altı dil; her birinin etiketi var", () => {
    expect(DILLER).toEqual(["ts", "java", "csharp", "python", "kotlin", "swift"]);
    expect(DILLER.map((d) => DIL_ETIKETI[d])).toEqual(["TypeScript", "Java", "C#", "Python", "Kotlin", "Swift"]);
  });

  it("geçerli çift = TASARIM §2.1 matrisi (core CATILAR aynası)", () => {
    expect(gecerliDiller("web")).toEqual(["ts", "java", "csharp", "python"]);
    expect(gecerliDiller("android")).toEqual(["java", "python", "kotlin"]);
    expect(gecerliDiller("ios")).toEqual(["java", "python", "swift"]);
    expect(gecerliDiller("windows")).toEqual(["java", "csharp", "python"]);
    expect(gecerliCift("web", "kotlin")).toBe(false);
    expect(gecerliCift("android", "swift")).toBe(false);
    expect(gecerliCift("ios", "csharp")).toBe(false);
    expect(gecerliCift("android", "ts")).toBe(false);
  });

  it("hat: ts/java/python/csharp tam, kotlin/swift müşteri CI; geçersiz çift null", () => {
    expect(ciftHati("web", "python")).toBe("tam");
    expect(ciftHati("windows", "csharp")).toBe("tam");
    expect(ciftHati("android", "kotlin")).toBe("musteri_ci");
    expect(ciftHati("ios", "swift")).toBe("musteri_ci");
    expect(ciftHati("web", "swift")).toBeNull();
    expect(musteriCiMi("android", "kotlin")).toBe(true);
    expect(musteriCiMi("android", "java")).toBe(false);
    expect(musteriCiMi(null, "kotlin")).toBe(false);
    expect(hatMi("musteri_ci")).toBe(true);
    expect(hatMi("yerel")).toBe(false);
    expect(dilDurumuUyarla("yakinda")).toBe("yakinda");
    expect(dilDurumuUyarla("soon")).toBeNull();
  });

  it("varsayılan dil (algılama yoksa / eski kayıt): web → ts, uygulama → java", () => {
    expect(varsayilanDil("web")).toBe("ts");
    expect(varsayilanDil("android")).toBe("java");
    expect(varsayilanDil("windows")).toBe("java");
  });

  it("DIL_CATISI: matris çatıları; geçersiz çift null (uydurulmaz)", () => {
    expect(DIL_CATISI("web", "ts")).toBe("Playwright Test");
    expect(DIL_CATISI("web", "java")).toBe("Playwright for Java + TestNG");
    expect(DIL_CATISI("web", "csharp")).toBe("Playwright .NET + NUnit");
    expect(DIL_CATISI("web", "python")).toBe("pytest + pytest-playwright");
    expect(DIL_CATISI("ios", "java")).toBe("Appium + TestNG");
    expect(DIL_CATISI("android", "python")).toBe("pytest + Appium");
    expect(DIL_CATISI("windows", "csharp")).toBe("Appium .NET + NUnit");
    expect(DIL_CATISI("android", "kotlin")).toBe("Espresso (AndroidX Test)");
    expect(DIL_CATISI("ios", "swift")).toBe("XCUITest");
    expect(DIL_CATISI("ios", "csharp")).toBeNull();
  });

  it("dilUyarla: sözleşme adları ve yaygın yazımlar; bilinmeyen null", () => {
    expect(dilUyarla(" Java ")).toBe("java");
    expect(dilUyarla("TypeScript")).toBe("ts");
    expect(dilUyarla("C#")).toBe("csharp");
    expect(dilUyarla("py")).toBe("python");
    expect(dilUyarla("Kotlin")).toBe("kotlin");
    expect(dilUyarla("kt")).toBe("kotlin");
    expect(dilUyarla("swift")).toBe("swift");
    expect(dilUyarla("rust")).toBeNull();
    expect(dilUyarla(3)).toBeNull();
    expect(dilKaynagiUyarla("secildi")).toBe("secildi");
    expect(dilKaynagiUyarla("tahmin")).toBeNull();
  });

  it("kontrol zinciri dile göre; aynı adım adı dile göre farklı araç", () => {
    expect(kontrolZinciri("web", "java")).toBe("pom kilidi · Java AST koruması · derleme · Playwright (Java)");
    expect(kontrolZinciri("web", "ts")).toBe("tsc --strict · eslint --no-inline-config · AST koruması · Playwright");
    expect(kontrolZinciri("web", "python")).toBe("kilit (requirements.lock) · Python AST koruması · py_compile · Playwright (pytest)");
    expect(kontrolZinciri("windows", "csharp")).toBe("NuGet kilidi · Roslyn koruması · dotnet build · Appium (.NET)");
    expect(kontrolZinciri("android", "kotlin")).toBe("Kotlin koruması (tree-sitter) · Müşteri CI (GitHub Actions)");
    expect(kontrolZinciri("ios", "swift")).toBe("Swift koruması (tree-sitter) · Müşteri CI (GitHub Actions)");
    // 011 eski doğrulanmamış kayıt: statik adım yok.
    expect(kontrolAdimlari("python", "dogrulanmamis")).toEqual([]);
    expect(kosuAraci("android", "java")).toBe("Appium");
    expect(kontrolAdimiEtiketi("guard")).toBe("Java AST koruması");
    expect(kontrolAdimiEtiketi("guard", "swift")).toBe("Swift koruması (tree-sitter)");
    expect(kontrolAdimiEtiketi("bilinmeyen", "python")).toBe("bilinmeyen");
  });
});
