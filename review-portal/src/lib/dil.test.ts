// 011: üretim dili yardımcıları (geçerli çift, çatı, doğrulanmamış diller, kontrol adımları).
import { describe, expect, it } from "vitest";
import {
  DIL_CATISI,
  DIL_ETIKETI,
  DILLER,
  dilKaynagiUyarla,
  dilUyarla,
  dogrulanmamisDilMi,
  gecerliCift,
  gecerliDiller,
  kontrolZinciri,
  kosuAraci,
  tamHatMi,
  varsayilanDil,
} from "./dil";
import { PLATFORMLAR } from "./platform";

describe("dil yardımcıları", () => {
  it("DILLER sözleşme sırasıyla dört dil; her birinin etiketi var", () => {
    expect(DILLER).toEqual(["ts", "java", "csharp", "python"]);
    expect(DILLER.map((d) => DIL_ETIKETI[d])).toEqual(["TypeScript", "Java", "C#", "Python"]);
  });

  it("geçerli çift: web × her dil; uygulama × yalnız java", () => {
    for (const d of DILLER) expect(gecerliCift("web", d)).toBe(true);
    for (const p of PLATFORMLAR.filter((x) => x !== "web")) {
      expect(gecerliDiller(p)).toEqual(["java"]);
      expect(gecerliCift(p, "ts")).toBe(false);
      expect(gecerliCift(p, "python")).toBe(false);
    }
  });

  it("varsayılan dil (algılama yoksa / eski kayıt): web → ts, uygulama → java", () => {
    expect(varsayilanDil("web")).toBe("ts");
    expect(varsayilanDil("android")).toBe("java");
    expect(varsayilanDil("windows")).toBe("java");
  });

  it("DIL_CATISI: web çatıları, uygulamada Appium + TestNG; geçersiz çift null (uydurulmaz)", () => {
    expect(DIL_CATISI("web", "ts")).toBe("Playwright Test");
    expect(DIL_CATISI("web", "java")).toBe("Playwright for Java + TestNG");
    expect(DIL_CATISI("web", "csharp")).toBe("Playwright .NET + NUnit");
    expect(DIL_CATISI("web", "python")).toBe("pytest-playwright");
    expect(DIL_CATISI("ios", "java")).toBe("Appium + TestNG");
    expect(DIL_CATISI("ios", "csharp")).toBeNull();
  });

  it("tam hat ts ve java; doğrulanmamış csharp ve python; null güvenli", () => {
    expect(DILLER.filter(tamHatMi)).toEqual(["ts", "java"]);
    expect(DILLER.filter(dogrulanmamisDilMi)).toEqual(["csharp", "python"]);
    expect(dogrulanmamisDilMi(null)).toBe(false);
    expect(tamHatMi(undefined)).toBe(false);
  });

  it("dilUyarla: sözleşme adları ve yaygın yazımlar; bilinmeyen null", () => {
    expect(dilUyarla(" Java ")).toBe("java");
    expect(dilUyarla("TypeScript")).toBe("ts");
    expect(dilUyarla("C#")).toBe("csharp");
    expect(dilUyarla("py")).toBe("python");
    expect(dilUyarla("kotlin")).toBeNull();
    expect(dilUyarla(3)).toBeNull();
    expect(dilKaynagiUyarla("secildi")).toBe("secildi");
    expect(dilKaynagiUyarla("tahmin")).toBeNull();
  });

  it("kontrol zinciri dile göre: web+java pom kilidi · Java AST koruması · derleme · Playwright (Java)", () => {
    expect(kontrolZinciri("web", "java")).toBe("pom kilidi · Java AST koruması · derleme · Playwright (Java)");
    expect(kontrolZinciri("web", "ts")).toBe("tsc --strict · eslint --no-inline-config · AST koruması · Playwright");
    expect(kosuAraci("android", "java")).toBe("Appium");
    expect(kontrolZinciri("web", "python")).toBe("Playwright");
  });
});
