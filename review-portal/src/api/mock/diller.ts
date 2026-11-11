// 011 üretim dili örnek verisi: `GET /code/languages` yanıtı, dile göre şablon çıktısı (web + Java tam
// hat; C# ve Python doğrulanmamış kaynak) ve iki örnek script — C9 web + Java PR'ı, C8 doğrulanmamış
// Python kaynağı. Yalnızca örnek veri (mock kipi); gerçek değerler core'dan gelir
// (specs/011-uretim-dili/plan.md §2.3, §2.7). Model kod yazmaz ilkesi örnekte de korunur: kod eşleme
// tablosundan (ajan adımları) deterministik üretilir.

import type { AjanAdimi, KodDilleri, ScriptDetay } from "../types";
import { DIL_CATISI, DIL_ETIKETI, gecerliDiller, type Dil } from "../../lib/dil";
import type { Platform } from "../../lib/platform";
import { ekranGoruntusu } from "./ekran";
import { eslemeler, t, TPD1_GOLDEN_CASELER } from "./fixtures";

/** Örnek depodaki elle yazılmış test sayıları (algılamanın dayanağı): web'de TypeScript çoğunlukta. */
const WEB_SAYILARI: Record<Dil, number> = { ts: 9, java: 4, csharp: 0, python: 0 };

/** `GET /code/languages?platform=` örnek yanıtı (core şekli, §2.3). */
export function kodDilleriYaniti(platform: Platform): KodDilleri {
  if (platform !== "web") {
    return {
      platform,
      algilanan: "java",
      kaynak: "algilandi",
      sayilar: { java: 6 },
      secenekler: [{ dil: "java", etiket: "Java", cati: DIL_CATISI(platform, "java")!, hat: "tam", kullanilabilir: true, neden: null }],
    };
  }
  return {
    platform,
    algilanan: "ts",
    kaynak: "algilandi",
    sayilar: { ...WEB_SAYILARI },
    secenekler: gecerliDiller(platform).map((dil) => ({
      dil,
      etiket: DIL_ETIKETI[dil],
      cati: DIL_CATISI(platform, dil)!,
      hat: dil === "ts" || dil === "java" ? "tam" : "dogrulanmamis",
      kullanilabilir: true,
      neden: null,
    })),
  };
}

/** Örnek depodaki algılanan dil (kodUret `dil` gelmezse). */
export function algilananDil(platform: Platform): Dil {
  return kodDilleriYaniti(platform).algilanan;
}

// ------------------------------------------------------------------ dile göre şablon çıktısı

const JAVA_WEB_KOK = "demo-app/e2e-java/src/test/java/com/antreklabs/bayi";
const PO_DEGISKEN: Record<string, string> = { LoginPage: "login", CatalogPage: "catalog", CartPage: "cart", OrderPage: "order" };

/**
 * Java'da `goto` ayrılmış sözcüktür: page object eşitliği (§2.5) bu tek metotta birebir olamaz.
 * Örnek veri `open` adını kullanır; gerçek adı Ş4 (e2e-java) / Ş2 (şablon) belirler.
 */
const JAVA_METOT: Record<string, string> = { goto: "open" };

const snake = (x: string) => x.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase();
const pascal = (x: string) => x.charAt(0).toUpperCase() + x.slice(1);
/** Dize ve sayı değişmezleri JSON biçimiyle her üç dilde de geçerlidir (çift tırnak, kaçışlı). */
const literal = (x: unknown) => JSON.stringify(x);

function poAdimlari(adimlar: AjanAdimi[]) {
  return adimlar.filter((a) => a.po && a.method) as (AjanAdimi & { po: string; method: string })[];
}

function kullanilanPolar(adimlar: AjanAdimi[]): string[] {
  return [...new Set(poAdimlari(adimlar).map((a) => a.po))].sort();
}

/** Sınıf/dosya adı parçası: "TPD-1" + C9 + kısa hash → "TPD1C9_9a1b2c3d". */
function adKoku(story: string | null, siraNo: number, kisa: string): string {
  return `${(story ?? "SERBEST").replace(/[^A-Za-z0-9]/g, "")}C${siraNo}_${kisa}`;
}

export interface DilCiktisi {
  dosya_yolu: string;
  kod: string;
}

/** Web + Java (Playwright for Java + TestNG): e2e-java projesi, `uretilen` paketi. */
export function javaWebCiktisi(story: string | null, siraNo: number, kisa: string, caseId: string, baslik: string, adimlar: AjanAdimi[]): DilCiktisi {
  const sinif = `${adKoku(story, siraNo, kisa)}Test`;
  const polar = kullanilanPolar(adimlar);
  const govde = poAdimlari(adimlar)
    .map((a) => `    // ${a.step_id} — ${a.aciklama}\n    ${PO_DEGISKEN[a.po] ?? "ekran"}.${JAVA_METOT[a.method] ?? a.method}(${a.args.map(literal).join(", ")});`)
    .join("\n");
  const kod = `// AI-generated — AI Testing Probe (CasesToCode). Elle düzenlemeyin; değişiklik case'in yeniden
// onayı ve yeniden üretimle yapılır.
// Case: ${story ?? "SERBEST"} C${siraNo} · Platform: web · Dil: Java (Playwright for Java + TestNG)
package com.antreklabs.bayi.uretilen;

import com.antreklabs.bayi.altyapi.Bayi;
import com.antreklabs.bayi.altyapi.TestTabani;
${polar.map((p) => `import com.antreklabs.bayi.ekranlar.${p};`).join("\n")}
import org.testng.annotations.Test;

@Bayi("bayi1")
public class ${sinif} extends TestTabani {
  @Test(groups = {"uretilen", "web", "tp-case-${caseId}"}, description = ${literal(baslik)})
  public void senaryo() {
${polar.map((p) => `    ${p} ${PO_DEGISKEN[p] ?? "ekran"} = new ${p}(page());`).join("\n")}

${govde}
  }
}
`;
  return { dosya_yolu: `${JAVA_WEB_KOK}/uretilen/${sinif}.java`, kod };
}

/** Python (pytest-playwright), doğrulanmamış: depoya yazılmaz; önerilen yol bilgi amaçlıdır. */
export function pythonCiktisi(story: string | null, siraNo: number, kisa: string, caseId: string, baslik: string, adimlar: AjanAdimi[]): DilCiktisi {
  const ad = snake(adKoku(story, siraNo, kisa));
  const polar = kullanilanPolar(adimlar);
  const govde = poAdimlari(adimlar)
    .map((a) => `    # ${a.step_id} — ${a.aciklama}\n    ${PO_DEGISKEN[a.po] ?? "ekran"}.${snake(a.method)}(${a.args.map(literal).join(", ")})`)
    .join("\n");
  const kod = `# AI-generated — AI Testing Probe (CasesToCode). DOĞRULANMAMIŞ: bu kod derlenmedi ve koşulmadı;
# PR açılmadı. Adımlar tarayıcıda doğrulandı; değerler onaylı case metninden.
# Case: ${story ?? "SERBEST"} C${siraNo} · Platform: web · Dil: Python (pytest-playwright)
import pytest
from playwright.sync_api import Page

from pages import ${polar.join(", ")}


@pytest.mark.uretilen
@pytest.mark.tp_case(${literal(caseId)})
def test_${ad}(page: Page) -> None:
    """${baslik.replace(/"""/g, "")}"""
${polar.map((p) => `    ${PO_DEGISKEN[p] ?? "ekran"} = ${p}(page)`).join("\n")}

${govde}
`;
  return { dosya_yolu: `demo-app/e2e-python/tests/uretilen/test_${ad}.py`, kod };
}

/** C# (Playwright .NET + NUnit), doğrulanmamış: metot adları PascalCase. */
export function csharpCiktisi(story: string | null, siraNo: number, kisa: string, caseId: string, baslik: string, adimlar: AjanAdimi[]): DilCiktisi {
  const sinif = `${adKoku(story, siraNo, kisa)}Tests`;
  const polar = kullanilanPolar(adimlar);
  const govde = poAdimlari(adimlar)
    .map((a) => `        // ${a.step_id} — ${a.aciklama}\n        await ${PO_DEGISKEN[a.po] ?? "ekran"}.${pascal(a.method)}(${a.args.map(literal).join(", ")});`)
    .join("\n");
  const kod = `// AI-generated — AI Testing Probe (CasesToCode). DOĞRULANMAMIŞ: bu kod derlenmedi ve koşulmadı;
// PR açılmadı. Adımlar tarayıcıda doğrulandı; değerler onaylı case metninden.
// Case: ${story ?? "SERBEST"} C${siraNo} · Platform: web · Dil: C# (Playwright .NET + NUnit)
using Bayi.E2E.Pages;
using Microsoft.Playwright.NUnit;
using NUnit.Framework;

namespace Bayi.E2E.Uretilen;

[TestFixture]
[Category("uretilen")]
[Category("tp-case-${caseId}")]
public class ${sinif} : PageTest
{
    [Test(Description = ${literal(baslik)})]
    public async Task Senaryo()
    {
${polar.map((p) => `        var ${PO_DEGISKEN[p] ?? "ekran"} = new ${p}(Page);`).join("\n")}

${govde}
    }
}
`;
  return { dosya_yolu: `demo-app/e2e-dotnet/Uretilen/${sinif}.cs`, kod };
}

// ------------------------------------------------------------------ örnek scriptler

function adim(sira: number, step_id: string, arac: string, aciklama: string, po: string, method: string, args: unknown[], ekran: string, saat: string): AjanAdimi {
  return {
    sira,
    step_id,
    arac,
    aciklama,
    po,
    method,
    args,
    verified: true,
    ekran_goruntusu_url: ekran,
    zaman: t(31, saat),
    ham_cikti: arac === "browser_snapshot" ? `- generic [ref=e21]: ${args.length ? String(args[args.length - 1]) : "doğrulandı"}` : `- ${aciklama}`,
  };
}

/** C9 (kampanyalı sepette minimum tutar aranmaz) — web + Java için ajan adımları. */
export function c9Adimlari(): AjanAdimi[] {
  return [
    adim(1, "S1", "browser_navigate", "Giriş sayfası açıldı", "LoginPage", "goto", [], ekranGoruntusu("login", "login-username"), "10:01"),
    adim(2, "S2", "browser_type", "bayi1 ile giriş yapıldı", "LoginPage", "login", ["bayi1", "Demo123!"], ekranGoruntusu("login", "login-submit"), "10:02"),
    adim(3, "S3", "browser_click", "P-001 adedi 7 girildi ve \"Sepete ekle\" tıklandı", "CatalogPage", "addToCart", ["P-001", 7], ekranGoruntusu("catalog", "add-to-cart", 7), "10:03"),
    adim(4, "S3", "browser_snapshot", "Sepet sayacı doğrulandı: 7", "CatalogPage", "expectCartCount", [7], ekranGoruntusu("catalog", "qty-input-P-001", 7), "10:04"),
    adim(5, "S4", "browser_click", "Üst menüden sepete gidildi", "CatalogPage", "openCart", [], ekranGoruntusu("cart", "cart-line-P-001", 7), "10:05"),
    adim(6, "S4", "browser_snapshot", "Toplam doğrulandı: 150,00 TL", "CartPage", "expectTotal", ["150,00 TL"], ekranGoruntusu("cart", "cart-total", 7), "10:06"),
    adim(7, "S4", "browser_snapshot", "Minimum sipariş uyarısı yok doğrulandı", "CartPage", "expectNoMinOrderWarning", [], ekranGoruntusu("cart", "cart-total", 7), "10:07"),
    adim(8, "S4", "browser_snapshot", "\"Siparişi onayla\" aktif doğrulandı", "CartPage", "expectCheckoutEnabled", [], ekranGoruntusu("cart", "cart-total", 7), "10:08"),
  ];
}

/** C8 (sipariş onayı ve geçmiş) — doğrulanmamış Python için ajan adımları. */
export function c8Adimlari(): AjanAdimi[] {
  return [
    adim(1, "S1", "browser_navigate", "Giriş sayfası açıldı", "LoginPage", "goto", [], ekranGoruntusu("login", "login-username"), "10:21"),
    adim(2, "S2", "browser_type", "bayi1 ile giriş yapıldı", "LoginPage", "login", ["bayi1", "Demo123!"], ekranGoruntusu("login", "login-submit"), "10:22"),
    adim(3, "S3", "browser_click", "P-004 adedi 25 girildi ve \"Sepete ekle\" tıklandı", "CatalogPage", "addToCart", ["P-004", 25], ekranGoruntusu("catalog", "add-to-cart", 25), "10:23"),
    adim(4, "S3", "browser_snapshot", "Sepet sayacı doğrulandı: 25", "CatalogPage", "expectCartCount", [25], ekranGoruntusu("catalog", "qty-input-P-004", 25), "10:24"),
    adim(5, "S4", "browser_click", "Üst menüden sepete gidildi", "CatalogPage", "openCart", [], ekranGoruntusu("cart", "cart-total", 25), "10:25"),
    adim(6, "S4", "browser_snapshot", "Toplam doğrulandı: 750,00 TL", "CartPage", "expectTotal", ["750,00 TL"], ekranGoruntusu("cart", "cart-total", 25), "10:26"),
    adim(7, "S5", "browser_click", "\"Siparişi onayla\" tıklandı", "CartPage", "checkout", [], ekranGoruntusu("confirmation", "order-confirmation", 0), "10:27"),
    adim(8, "S5", "browser_snapshot", "Onaylanan toplam doğrulandı: 750,00 TL", "OrderPage", "expectConfirmedTotal", ["750,00 TL"], ekranGoruntusu("confirmation", "order-confirmation", 0), "10:28"),
    adim(9, "S5", "browser_snapshot", "Sipariş geçmişinde listelendiği doğrulandı", "OrderPage", "expectConfirmedOrderInHistory", [], ekranGoruntusu("confirmation", "order-confirmation", 0), "10:29"),
  ];
}

const KIRMA_YOK: ScriptDetay["break_verify"] = {
  durum: "not_started",
  asamalar: (["baseline", "broken", "restored"] as const).map((ad) => ({ ad, sonuc: "pending" as const, run_id: null, zaman: null })),
};

/** Java web yerel kontrolünün dile göre adımları (core `adimlar: [{ad, durum}]`). */
export const JAVA_KONTROL_ACIKLAMASI = "pom kilidi ✓ · Java AST koruması ✓ · derleme ✓ · Playwright (Java) 3/3";

export function javaYerelGecti(run_id: string | null): ScriptDetay["yerel_kontrol"] {
  return {
    tsc: null,
    eslint: null,
    ast_guard: null,
    adimlar: [
      { ad: "deps", durum: true },
      { ad: "guard", durum: true },
      { ad: "compile", durum: true },
    ],
    tekrar: 3,
    sonuc: "passed",
    sinif: "gecti",
    aciklama: null,
    run_id,
    duzeltme_turu: 0,
    basarisiz: [],
    gecen: 3,
    toplam: 3,
    hata: null,
  };
}

/** C9 web + Java (PR açık, CI yeşil) ve C8 doğrulanmamış Python (PR yok, kod indirilebilir). */
export function dilScriptleri(): ScriptDetay[] {
  const c9 = c9Adimlari();
  const java = javaWebCiktisi("TPD-1", 9, "5d8e2f1a", "case-1-9", TPD1_GOLDEN_CASELER[8].title, c9);
  const c8 = c8Adimlari();
  const py = pythonCiktisi("TPD-1", 8, "7c4b9e03", "case-1-8", TPD1_GOLDEN_CASELER[7].title, c8);
  return [
    {
      id: "scr-java",
      case_ids: ["case-1-9"],
      requirement_key: "TPD-1",
      baslik: TPD1_GOLDEN_CASELER[8].title,
      dosya_yolu: java.dosya_yolu,
      branch: "tp/case-5d8e2f1a",
      platform: "web",
      dil: "java",
      dil_kaynagi: "secildi",
      dogrulanmamis: false,
      durum: "pr_open",
      pr: {
        number: 24,
        url: null,
        baslik: "test(TPD-1): kampanyalı siparişte minimum tutar aranmaz [Java] [AI-generated]",
        branch: "tp/case-5d8e2f1a",
        durum: "open",
        ci: "passed",
        icerik_hash: "",
        head_sha: "",
        // §2.6: web'de dil ne olursa olsun check adı `local-ci`.
        checks: [{ ad: "local-ci", durum: "passed", zorunlu: true, url: null, aciklama: JAVA_KONTROL_ACIKLAMASI }],
        forge: "local",
        dal: { geride: false, guncelleme: null, neden: null },
      },
      pass_at_1: true,
      zayif_test: false,
      break_verify: KIRMA_YOK,
      yerel_sinif: "gecti",
      mode: "replay",
      olusturma: t(31, "10:10"),
      hata: null,
      kod: java.kod,
      adimlar: c9,
      eslemeler: eslemeler(c9, { "7": "Sepet sayacı 7 olur", "150,00 TL": "Toplam 150,00 TL" }),
      yerel_kontrol: javaYerelGecti(null),
      merge_engelleri: null,
      uyarilar: [],
      engel: null,
    },
    {
      id: "scr-py",
      case_ids: ["case-1-8"],
      requirement_key: "TPD-1",
      baslik: TPD1_GOLDEN_CASELER[7].title,
      dosya_yolu: py.dosya_yolu,
      branch: "",
      platform: "web",
      dil: "python",
      dil_kaynagi: "secildi",
      dogrulanmamis: true,
      // §2.7: doğrulanmamış dil — commit/PR/yerel kontrol yok (verifying → unverified).
      durum: "unverified",
      pr: null,
      pass_at_1: null,
      zayif_test: false,
      break_verify: KIRMA_YOK,
      yerel_sinif: null,
      mode: "replay",
      olusturma: t(31, "10:30"),
      hata: null,
      kod: py.kod,
      adimlar: c8,
      eslemeler: eslemeler(c8, { "25": "Sepet sayacı 25 olur", "750,00 TL": "Toplam 750,00 TL" }),
      yerel_kontrol: null,
      merge_engelleri: null,
      uyarilar: [],
      engel: null,
    },
  ];
}
