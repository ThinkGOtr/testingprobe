// 009: platform yardımcıları (etiket, check adı, ajan aracı, süzgeç).
import { describe, expect, it } from "vitest";
import {
  aracEtiketi,
  checkEtiketi,
  checkPlatformu,
  dikeyEkranMi,
  platformaGoreSuz,
  platformSecimiOku,
  platformUyarla,
  uygulamaPlatformuMu,
} from "./platform";

describe("platform yardımcıları", () => {
  it("platformUyarla: dört değer tanınır (harf/boşluk duyarsız); bilinmeyen null (uydurulmaz)", () => {
    expect(platformUyarla("android")).toBe("android");
    expect(platformUyarla(" iOS ")).toBe("ios");
    expect(platformUyarla("WINDOWS")).toBe("windows");
    expect(platformUyarla("web")).toBe("web");
    expect(platformUyarla("macos")).toBeNull();
    expect(platformUyarla(null)).toBeNull();
    expect(platformUyarla(3)).toBeNull();
  });

  it("check adları: local-ci = Web, local-ci-<platform> dostu etiket; başka check null", () => {
    expect(checkEtiketi("local-ci")).toBe("Yerel CI · Web");
    expect(checkEtiketi("local-ci-android")).toBe("Yerel CI · Android");
    expect(checkEtiketi("local-ci-ios")).toBe("Yerel CI · iOS");
    expect(checkEtiketi("local-ci-windows")).toBe("Yerel CI · Windows");
    expect(checkEtiketi("local-ci-macos")).toBeNull();
    expect(checkEtiketi("semgrep")).toBeNull();
    expect(checkPlatformu("local-ci")).toBe("web");
    expect(checkPlatformu("local-ci-ios")).toBe("ios");
    expect(checkPlatformu("test-local")).toBeNull();
    // 011 K-T1: web + Java `local-ci-web-java`; `web-java` platform sanılmaz.
    expect(checkEtiketi("local-ci-web-java")).toBe("Yerel CI · Web · Java");
    expect(checkPlatformu("local-ci-web-java")).toBe("web");
    expect(checkEtiketi("local-ci-web")).toBeNull();
    expect(checkPlatformu("local-ci-web")).toBeNull();
    expect(checkEtiketi("local-ci-web-kotlin")).toBeNull();
  });

  it("app_* araçları Türkçe; browser_* ham kalır", () => {
    expect(aracEtiketi("app_launch")).toBe("Uygulamayı başlat");
    expect(aracEtiketi("app_snapshot")).toBe("Ekranı oku");
    expect(aracEtiketi("app_click")).toBe("Dokun");
    expect(aracEtiketi("app_type")).toBe("Yaz");
    expect(aracEtiketi("app_select_option")).toBe("Seç");
    expect(aracEtiketi("app_wait_for")).toBe("Bekle");
    expect(aracEtiketi("app_generate_locator")).toBe("Locator üret");
    expect(aracEtiketi("browser_click")).toBe("browser_click");
  });

  it("dikey ekran yalnız telefon; uygulama platformu web dışı", () => {
    expect(dikeyEkranMi("android")).toBe(true);
    expect(dikeyEkranMi("ios")).toBe(true);
    expect(dikeyEkranMi("windows")).toBe(false);
    expect(dikeyEkranMi("web")).toBe(false);
    expect(uygulamaPlatformuMu("windows")).toBe(true);
    expect(uygulamaPlatformuMu("web")).toBe(false);
    expect(uygulamaPlatformuMu(null)).toBe(false);
  });

  it("süzgeç: Tümü hepsini; platform seçimi yalnız o platformu (platformu bilinmeyen dışarıda)", () => {
    const liste = [
      { id: 1, p: "web" as const },
      { id: 2, p: "android" as const },
      { id: 3, p: null },
    ];
    expect(platformaGoreSuz(liste, "tumu", (x) => x.p).map((x) => x.id)).toEqual([1, 2, 3]);
    expect(platformaGoreSuz(liste, "android", (x) => x.p).map((x) => x.id)).toEqual([2]);
    expect(platformaGoreSuz(liste, "web", (x) => x.p).map((x) => x.id)).toEqual([1]);
    expect(platformSecimiOku("ios")).toBe("ios");
    expect(platformSecimiOku("bilinmeyen")).toBe("tumu");
    expect(platformSecimiOku(null)).toBe("tumu");
  });
});
