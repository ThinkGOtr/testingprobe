// 011 üretim dili örnek verisi: `GET /code/languages` yanıtı, dile göre şablon çıktısı (web + Java tam
// hat; C# ve Python doğrulanmamış kaynak) ve iki örnek script — C9 web + Java PR'ı, C8 doğrulanmamış
// Python kaynağı. Yalnızca örnek veri (mock kipi); gerçek değerler core'dan gelir
// (specs/011-uretim-dili/plan.md §2.3, §2.7). Model kod yazmaz ilkesi örnekte de korunur: kod eşleme
// tablosundan (ajan adımları) deterministik üretilir.

import type { AjanAdimi, KodDilleri, ScriptDetay } from "../types";
import { DIL_CATISI, DIL_ETIKETI, gecerliDiller, type Dil } from "../../lib/dil";
import type { Platform } from "../../lib/platform";
import { sha256Hex } from "../../lib/sha256";
import { ekranGoruntusu } from "./ekran";
import { eslemeler, t, TPD1_GOLDEN_CASELER } from "./fixtures";

/** Örnek depodaki elle yazılmış test sayıları (algılamanın dayanağı): web'de TypeScript çoğunlukta. */
const WEB_SAYILARI: Record<Dil, number> = { ts: 9, java: 4, csharp: 0, python: 0 };

/** core `codegen.service.DEPO_OKUNAMADI`: depo okunamadığında her seçeneğin nedeni (seçenek açık kalır). */
export const DEPO_OKUNAMADI = "Depo okunamadı; bu dilin test projesi doğrulanamadı (kullanılabilirlik bilinmiyor)";

/**
 * `GET /code/languages?platform=` örnek yanıtı (core şekli, §2.3). `depoOkunamadi` (mock senaryosu
 * `depo-okunamadi`): core'un forge'u kuramadığı/okuyamadığı durum — kaynak `varsayilan`, sayılar 0,
 * üst düzey `neden` dolu ve her seçenekte `DEPO_OKUNAMADI` (kullanılabilir kalır).
 */
export function kodDilleriYaniti(platform: Platform, secenek: { depoOkunamadi?: boolean } = {}): KodDilleri {
  const okunamadi = !!secenek.depoOkunamadi;
  const neden = okunamadi ? "Dil algılanamadı (forge kurulamadı: ConnectError); varsayılan dil önerildi" : null;
  const secenekNedeni = okunamadi ? DEPO_OKUNAMADI : null;
  if (platform !== "web") {
    return {
      platform,
      algilanan: "java",
      kaynak: okunamadi ? "varsayilan" : "algilandi",
      sayilar: { java: okunamadi ? 0 : 6 },
      secenekler: [{ dil: "java", etiket: "Java", cati: DIL_CATISI(platform, "java")!, hat: "tam", kullanilabilir: true, neden: secenekNedeni }],
      neden,
    };
  }
  return {
    platform,
    algilanan: "ts",
    kaynak: okunamadi ? "varsayilan" : "algilandi",
    sayilar: okunamadi ? { ts: 0, java: 0, csharp: 0, python: 0 } : { ...WEB_SAYILARI },
    secenekler: gecerliDiller(platform).map((dil) => ({
      dil,
      etiket: DIL_ETIKETI[dil],
      cati: DIL_CATISI(platform, dil)!,
      hat: dil === "ts" || dil === "java" ? "tam" : "dogrulanmamis",
      kullanilabilir: true,
      neden: secenekNedeni,
    })),
    neden,
  };
}

/** Örnek depodaki algılanan dil (kodUret `dil` gelmezse). */
export function algilananDil(platform: Platform): Dil {
  return kodDilleriYaniti(platform).algilanan;
}

// ------------------------------------------------------------------ dile göre şablon çıktısı
//
// Biçim gerçek şablon çıktılarıyla AYNIDIR (core/tests/unit/features/codegen/golden/:
// `TPD1WebC2_3f9b1c2eTest.java`, `TPD1WebC2_3f9b1c2eTests.cs`, `test_tpd_1_c2_3f9b1c2e.py.golden`):
// başlık yorumu, importlar, sınıf/test adları, adım etiketleri (`S<n> — <case adımı>`), "Beklenen
// sonuç" bloğu ve yollar (011 K-T6). Doğrulanmamış dillerde başlık "Elle düzenlemeyin" demez; gereken
// page object imzalarını listeler, Python'da marker kaydı için `conftest.py` parçası verir (K-T9).

const JAVA_WEB_KOK = "demo-app/e2e-java/src/test/java/com/antreklabs/bayi";
const CS_KOK = "demo-app/e2e-csharp/tests/Generated";
const PY_KOK = "demo-app/e2e-python/tests/generated";

/** core `platform.JAVA_AD_ESLEME`: `goto` Java'da ayrılmış sözcük → e2e-java `LoginPage.goTo()`. */
const JAVA_AD_ESLEME: Record<string, string> = { goto: "goTo" };

/** Web + Java eşlemesi Java page object adlarıyla saklanır (core `java_eslemesi`: `goto` → `goTo`). */
export function javaAdimlari(adimlar: AjanAdimi[]): AjanAdimi[] {
  return adimlar.map((a) => (a.method && JAVA_AD_ESLEME[a.method] ? { ...a, method: JAVA_AD_ESLEME[a.method] } : a));
}

const snake = (x: string) => x.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase();
const pascal = (x: string) => x.charAt(0).toUpperCase() + x.slice(1);
const deve = (x: string) => x.charAt(0).toLowerCase() + x.slice(1);
/** Dize ve sayı değişmezleri JSON biçimiyle her üç dilde de geçerlidir (çift tırnak, kaçışlı). */
const literal = (x: unknown) => JSON.stringify(x);
/** Ondalık değer C#'ta `double`, Python'da `float`; tam sayı `int`; dize `string`/`str`. */

/**
 * Referans (TS) sembol tablosundaki parametre adları ve türleri (`demo-app/e2e/pages`): imza listesi
 * değerden değil tablodan türetilir (TS `number` → C# `double`, Python `float`; golden ile aynı).
 */
type TsTur = "string" | "number" | "boolean";
const PO_PARAMETRELERI: Record<string, [string, TsTur][]> = {
  login: [["username", "string"], ["password", "string"]],
  addToCart: [["productCode", "string"], ["quantity", "number"]],
  expectCartCount: [["count", "number"]],
  expectLineQuantity: [["productCode", "string"], ["quantity", "number"]],
  expectFreeQuantity: [["productCode", "string"], ["quantity", "number"]],
  expectSubtotal: [["amount", "string"]],
  expectDiscount: [["amount", "string"]],
  expectTotal: [["amount", "string"]],
  expectConfirmedTotal: [["amount", "string"]],
  expectMinOrderWarning: [["message", "string"]],
};
function parametreler(metot: string, args: unknown[]): [string, TsTur][] {
  return PO_PARAMETRELERI[metot] ?? args.map((a, i) => [`p${i + 1}`, typeof a === "number" ? "number" : typeof a === "boolean" ? "boolean" : "string"]);
}
const CS_TUR: Record<TsTur, string> = { string: "string", number: "double", boolean: "bool" };
const PY_TUR: Record<TsTur, string> = { string: "str", number: "float", boolean: "bool" };

type Cagri = AjanAdimi & { po: string; method: string };

function poAdimlari(adimlar: AjanAdimi[]): Cagri[] {
  return adimlar.filter((a) => a.po && a.method) as Cagri[];
}

/** Şablon girdisi: case kimliği, onaylı case metni (adım etiketleri) ve doğrulanmış eşleme. */
export interface CiktiGirdisi {
  story: string | null;
  siraNo: number;
  /** Case kimliğinin kısa hash'i (gerçekte uuid'nin ilk 8 hanesi). */
  kisa: string;
  caseId: string;
  baslik: string;
  adimlar: AjanAdimi[];
  /** Onaylı case adımları: etiket `S<n> — <action>` (yoksa ajan açıklaması). */
  caseAdimlari?: { id: string; action: string }[];
  testKey?: string | null;
  mode?: string;
}

export interface DilCiktisi {
  dosya_yolu: string;
  kod: string;
}

interface Bolumler {
  ref: string;
  story: string | null;
  dealer: string | null;
  /** Case adımları (eylemler) sırayla, adım kimliğine göre gruplu. */
  adimlar: { etiket: string; cagrilar: Cagri[] }[];
  /** Beklenen sonuç çağrıları (değerler onaylı case metninden). */
  beklenen: Cagri[];
  /** Kullanılan page object sınıfları (alfabetik) ve her birinin metot imzaları (ilk görülen argümanlarla). */
  nesneler: { sinif: string; metotlar: { ad: string; args: unknown[] }[] }[];
  basliklar: string[];
}

function bolumle(g: CiktiGirdisi): Bolumler {
  const story = g.story && /^[A-Z][A-Z0-9]*-\d+$/.test(g.story) ? g.story : null;
  const ref = `${story ?? "SERBEST"} C${g.siraNo}`;
  const eylem = new Map((g.caseAdimlari ?? []).map((a) => [a.id, a.action]));
  const cagrilar = poAdimlari(g.adimlar);
  const adimlar: Bolumler["adimlar"] = [];
  const beklenen: Cagri[] = [];
  for (const c of cagrilar) {
    if (c.method.startsWith("expect")) {
      beklenen.push(c);
      continue;
    }
    const son = adimlar[adimlar.length - 1];
    if (son && son.etiket.startsWith(`${c.step_id} — `)) son.cagrilar.push(c);
    else adimlar.push({ etiket: `${c.step_id} — ${eylem.get(c.step_id) ?? c.aciklama}`, cagrilar: [c] });
  }
  const nesneMap = new Map<string, Map<string, unknown[]>>();
  // İmza sırası şablondaki çağrı sırası: önce adımlar, sonra beklenen sonuç.
  for (const c of [...adimlar.flatMap((a) => a.cagrilar), ...beklenen]) {
    const m = nesneMap.get(c.po) ?? new Map<string, unknown[]>();
    if (!m.has(c.method)) m.set(c.method, c.args);
    nesneMap.set(c.po, m);
  }
  const nesneler = [...nesneMap.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([sinif, m]) => ({ sinif, metotlar: [...m.entries()].map(([ad, args]) => ({ ad, args })) }));
  const login = cagrilar.find((c) => c.method === "login" && typeof c.args[0] === "string");
  const kok = sha256Hex(`${g.caseId}|${g.baslik}`);
  return {
    ref,
    story,
    dealer: login ? String(login.args[0]) : null,
    adimlar,
    beklenen,
    nesneler,
    basliklar: [
      `Case: ${ref} (${g.caseId}) · Story: ${story ?? "-"} · Jira Test: ${g.testKey ?? "-"}`,
      `Onaylı case hash: ${kok}`,
    ],
  };
}

function eslemeSatirlari(g: CiktiGirdisi, dilEtiketi: string): string[] {
  const h = sha256Hex(`${g.caseId}|eşleme|${dilEtiketi}`);
  return [
    `Eşleme: verify_and_map · platform: web · dil: ${dilEtiketi} · mod: ${g.mode ?? "replay"} · bundle: ${sha256Hex("bundle")}`,
    `Eşleme hash: ${h} · şablon: ${sha256Hex(`şablon|${dilEtiketi}`)}`,
  ];
}

const TAM_HAT_BASLIGI = ["AI-generated — AI Testing Probe (CasesToCode). Elle düzenlemeyin; değişiklik case'in yeniden", "onayı ve yeniden üretimle yapılır."];

/** Doğrulanmamış dillerin başlığı (K-T9): "Elle düzenlemeyin" yok; kodu projeye uyarlamak serbesttir. */
const DOGRULANMAMIS_BASLIGI = [
  "AI-generated — AI Testing Probe (CasesToCode). Hedef projeye uyarlanmak üzere verilir:",
  "page object adlarını ve imzalarını projenize göre düzenleyebilirsiniz.",
  "Doğrulanmamış çıktı: adımlar tarayıcıda doğrulandı; bu kod derlenmedi ve koşulmadı; page object kütüphanesi TypeScript tablosundan türetilen adları varsayar.",
];

/** Web + Java (Playwright for Java + TestNG): e2e-java projesi, `uretilen` paketi (golden biçimi). */
export function javaWebCiktisi(g: CiktiGirdisi): DilCiktisi {
  const b = bolumle(g);
  const sinif = `${(b.story ?? "Serbest").replace(/[^A-Za-z0-9]/g, "")}WebC${g.siraNo}_${g.kisa}Test`;
  const gruplar = ["uretilen", "web", `tp-case-${g.caseId}`, ...(b.story ? [b.story] : [])];
  const satir = (c: Cagri) => `    ${deve(c.po)}().${JAVA_AD_ESLEME[c.method] ?? c.method}(${c.args.map(literal).join(", ")});`;
  const kod = [
    ...[...TAM_HAT_BASLIGI, ...b.basliklar, ...eslemeSatirlari(g, "java")].map((x) => `// ${x}`),
    "package com.antreklabs.bayi.uretilen;",
    "",
    "import com.antreklabs.bayi.altyapi.Bayi;",
    "import com.antreklabs.bayi.altyapi.TestTabani;",
    "import org.testng.annotations.Test;",
    "",
    ...(b.dealer ? [`@Bayi(${literal(b.dealer)})`] : []),
    `public class ${sinif} extends TestTabani {`,
    `  @Test(groups = {${gruplar.map(literal).join(", ")}}, description = ${literal(g.baslik)})`,
    "  public void senaryo() {",
    ...b.adimlar.flatMap((a) => [`    // ${a.etiket}`, ...a.cagrilar.map(satir)]),
    "    // Beklenen sonuç (değerler onaylı case metninden)",
    ...b.beklenen.map(satir),
    "  }",
    "}",
    "",
  ].join("\n");
  return { dosya_yolu: `${JAVA_WEB_KOK}/uretilen/${sinif}.java`, kod };
}

/** C# (Playwright .NET + NUnit), doğrulanmamış: PascalCase `…Async` metotlar (golden biçimi). */
export function csharpCiktisi(g: CiktiGirdisi): DilCiktisi {
  const b = bolumle(g);
  const sinif = `${(b.story ?? "Serbest").replace(/[^A-Za-z0-9]/g, "")}WebC${g.siraNo}_${g.kisa}Tests`;
  const metot = (m: string) => `${pascal(m)}Async`;
  const imzalar = b.nesneler.flatMap((n) => [
    `  ${n.sinif}`,
    ...n.metotlar.map((m) => `    Task ${metot(m.ad)}(${parametreler(m.ad, m.args).map(([ad, t]) => `${CS_TUR[t]} ${ad}`).join(", ")})`),
  ]);
  const satir = (c: Cagri) => `        await ${deve(c.po)}.${metot(c.method)}(${c.args.map(literal).join(", ")});`;
  const kod = [
    ...[
      ...DOGRULANMAMIS_BASLIGI,
      ...b.basliklar,
      ...eslemeSatirlari(g, "csharp (Playwright .NET + NUnit)"),
      "",
      "Varsayılan page object imzaları (Antreklabs.Bayi.Pages; kurucu: new <Sınıf>(IPage page)):",
      ...imzalar,
    ].map((x) => (x ? `// ${x}` : "//")),
    "using System.Threading.Tasks;",
    "using Antreklabs.Bayi.Pages;",
    "using Microsoft.Playwright.NUnit;",
    "using NUnit.Framework;",
    "",
    "namespace Antreklabs.Bayi.Tests.Generated;",
    "",
    "[TestFixture]",
    '[Category("uretilen")]',
    '[Category("web")]',
    `[Category(${literal(`tp-case-${g.caseId}`)})]`,
    ...(b.story ? [`[Category(${literal(b.story)})]`] : []),
    ...(b.dealer ? [`[Property("dealerUsername", ${literal(b.dealer)})]`] : []),
    `public class ${sinif} : PageTest`,
    "{",
    "    [Test]",
    `    [Description(${literal(g.baslik)})]`,
    "    public async Task Senaryo()",
    "    {",
    ...b.nesneler.map((n) => `        var ${deve(n.sinif)} = new ${n.sinif}(Page);`),
    "",
    ...b.adimlar.flatMap((a) => [`        // ${a.etiket}`, ...a.cagrilar.map(satir)]),
    "        // Beklenen sonuç (değerler onaylı case metninden)",
    ...b.beklenen.map(satir),
    "    }",
    "}",
    "",
  ].join("\n");
  return { dosya_yolu: `${CS_KOK}/${sinif}.cs`, kod };
}

/** Python (pytest-playwright), doğrulanmamış: snake_case adlar, marker kaydı başlıkta (golden biçimi). */
export function pythonCiktisi(g: CiktiGirdisi): DilCiktisi {
  const b = bolumle(g);
  const slug = `${(b.story ?? "serbest").toLowerCase()}-c${g.siraNo}-${g.kisa}`;
  const ad = `test_${slug.replace(/-/g, "_")}`;
  const imzalar = b.nesneler.flatMap((n) => [
    `  pages.${snake(n.sinif)}.${n.sinif}`,
    ...n.metotlar.map((m) => `    def ${snake(m.ad)}(${["self", ...parametreler(m.ad, m.args).map(([ad, t]) => `${snake(ad)}: ${PY_TUR[t]}`)].join(", ")}) -> None`),
  ]);
  const satir = (c: Cagri) => `    ${snake(c.po)}.${snake(c.method)}(${c.args.map(literal).join(", ")})`;
  const kod = [
    ...[
      ...DOGRULANMAMIS_BASLIGI,
      ...b.basliklar.slice(0, 1),
      `Başlık: ${g.baslik}`,
      ...b.basliklar.slice(1),
      ...eslemeSatirlari(g, "python (pytest-playwright)"),
      "",
      "Varsayılan page object imzaları (kurucu: <Sınıf>(page: Page); metotlar None döner):",
      ...imzalar,
      "",
      "--strict-markers kullanıyorsanız işaretleri conftest.py'de kaydedin:",
      "  def pytest_configure(config):",
      '      config.addinivalue_line("markers", "uretilen: AI Testing Probe tarafından üretilen test")',
      '      config.addinivalue_line("markers", "web: web platformu testi")',
      '      config.addinivalue_line("markers", "tp_case(case_id): AI Testing Probe test case kimliği")',
      '      config.addinivalue_line("markers", "story(anahtar): Jira story anahtarı")',
      '      config.addinivalue_line("markers", "dealer(kullanici): testin sabitlendiği e2e bayisi")',
    ].map((x) => (x ? `# ${x}` : "#")),
    "import pytest",
    "from playwright.sync_api import Page",
    "",
    ...b.nesneler.map((n) => `from pages.${snake(n.sinif)} import ${n.sinif}`),
    "",
    "",
    "@pytest.mark.uretilen",
    "@pytest.mark.web",
    `@pytest.mark.tp_case(${literal(g.caseId)})`,
    ...(b.story ? [`@pytest.mark.story(${literal(b.story)})`] : []),
    ...(b.dealer ? [`@pytest.mark.dealer(${literal(b.dealer)})`] : []),
    `def ${ad}(page: Page) -> None:`,
    ...b.nesneler.map((n) => `    ${snake(n.sinif)} = ${n.sinif}(page)`),
    "",
    ...b.adimlar.flatMap((a) => [`    # ${a.etiket}`, ...a.cagrilar.map(satir)]),
    "    # Beklenen sonuç (değerler onaylı case metninden)",
    ...b.beklenen.map(satir),
    "",
  ].join("\n");
  return { dosya_yolu: `${PY_KOK}/${ad}.py`, kod };
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
      { ad: "deps", durum: "passed" },
      { ad: "guard", durum: "passed" },
      { ad: "compile", durum: "passed" },
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
  // Web + Java eşlemesi Java adlarıyla (`LoginPage.goTo()`), core `java_eslemesi` ile aynı.
  const c9 = javaAdimlari(c9Adimlari());
  const C9 = TPD1_GOLDEN_CASELER[8];
  const java = javaWebCiktisi({ story: "TPD-1", siraNo: 9, kisa: "5d8e2f1a", caseId: "case-1-9", baslik: C9.title, adimlar: c9, caseAdimlari: C9.steps, testKey: "TPD-13" });
  const c8 = c8Adimlari();
  const C8 = TPD1_GOLDEN_CASELER[7];
  const py = pythonCiktisi({ story: "TPD-1", siraNo: 8, kisa: "7c4b9e03", caseId: "case-1-8", baslik: C8.title, adimlar: c8, caseAdimlari: C8.steps, testKey: "TPD-12" });
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
        // 011 K-T1: web + Java check adı `local-ci-web-java` (web + TS `local-ci`).
        checks: [{ ad: "local-ci-web-java", durum: "passed", zorunlu: true, url: null, aciklama: JAVA_KONTROL_ACIKLAMASI }],
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
