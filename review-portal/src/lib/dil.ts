// 011 üretim dili + 014 test dilleri: dil ayrı bir boyuttur, platformdan türetilmez
// (specs/011-uretim-dili/plan.md §2.1; aip-review/test-dilleri/TASARIM.md §1.3, §2).
// Tek kaynak core `features/codegen/platform.py` (`CATILAR[(platform, dil)]`, `Hat`); buradaki tablo onun
// portal aynasıdır (yalnız gösterim ve uç yokken yedek). Hangi çiftin AÇIK olduğu (değerlendirmeden geçti)
// portalda TUTULMAZ: tek kaynak TP `rules/diller.yaml`, portala `GET /code/languages` `durum` alanıyla gelir.
import type { Platform } from "./platform";

export const DILLER = ["ts", "java", "csharp", "python", "kotlin", "swift"] as const;
export type Dil = (typeof DILLER)[number];

/**
 * Hat (core `Hat`):
 * - `tam`: TP derler, korur, koşar, kırarak doğrular, PR açar (ts, java, python, csharp).
 * - `musteri_ci`: TP üretir + statik koruma + PR; derleme ve koşu müşterinin GitHub Actions'ında, sonuç
 *   `tp-results` artefaktından okunur; kırarak doğrulama YOK (kotlin/Espresso, swift/XCUITest).
 * - `dogrulanmamis`: 011'in yalnız kaynak üreten web C#/Python hattı (emekli; eski kayıtlar okunur kalır).
 */
export const HATLAR = ["tam", "musteri_ci", "dogrulanmamis"] as const;
export type Hat = (typeof HATLAR)[number];

/** Dil kapısı durumu (TP `rules/diller.yaml`): `yakinda` = değerlendirmeden geçmedi, seçilemez. */
export const DIL_DURUMLARI = ["acik", "yakinda"] as const;
export type DilDurumu = (typeof DIL_DURUMLARI)[number];

/** core: `yakinda` seçeneğin nedeni (seçenek `kullanilabilir=false`). */
export const YAKINDA_NEDENI = "Değerlendirme sürüyor";

export const DIL_ETIKETI: Record<Dil, string> = {
  ts: "TypeScript",
  java: "Java",
  csharp: "C#",
  python: "Python",
  kotlin: "Kotlin",
  swift: "Swift",
};

export const HAT_ETIKETI: Record<Hat, string> = {
  tam: "tam hat",
  musteri_ci: "müşteri CI",
  dogrulanmamis: "doğrulanmamış",
};

/** Müşteri CI hattının kalıcı notu (kullanıcı kararı 2: portal ve PR'da rozet). */
export const KIRARAK_DOGRULANMADI = "Kırarak doğrulanmadı";
export const KIRARAK_DOGRULANMADI_ACIKLAMA =
  "Bu dilde test müşterinin GitHub Actions iş akışında derlenir ve koşulur; müşteri uygulamasında kırılma bayrağı olmadığı için kırarak doğrulama yapılmaz. Merge için yeşil CI yeterlidir.";

interface CatiTanimi {
  cati: string;
  hat: Hat;
}

/** (platform, dil) → çatı + hat (TASARIM §2.1 matrisi; core `CATILAR` aynası). Tabloda olmayan çift geçersizdir. */
const CATILAR: Partial<Record<Platform, Partial<Record<Dil, CatiTanimi>>>> = {
  web: {
    ts: { cati: "Playwright Test", hat: "tam" },
    java: { cati: "Playwright for Java + TestNG", hat: "tam" },
    csharp: { cati: "Playwright .NET + NUnit", hat: "tam" },
    python: { cati: "pytest + pytest-playwright", hat: "tam" },
  },
  android: {
    java: { cati: "Appium + TestNG", hat: "tam" },
    python: { cati: "pytest + Appium", hat: "tam" },
    kotlin: { cati: "Espresso (AndroidX Test)", hat: "musteri_ci" },
  },
  ios: {
    java: { cati: "Appium + TestNG", hat: "tam" },
    python: { cati: "pytest + Appium", hat: "tam" },
    swift: { cati: "XCUITest", hat: "musteri_ci" },
  },
  windows: {
    java: { cati: "Appium + TestNG", hat: "tam" },
    python: { cati: "pytest + Appium", hat: "tam" },
    csharp: { cati: "Appium .NET + NUnit", hat: "tam" },
  },
};

/**
 * 011'in doğrulanmamış hattı (yalnız web C#/Python kaynak üretimi). Yeni üretimde yoktur (kullanıcı
 * kararı 3a); eski `unverified` kayıtlar ve 014 öncesi core yanıtı (`hat` yoksa) için tutulur.
 */
export const ESKI_DOGRULANMAMIS_DILLER: readonly Dil[] = ["csharp", "python"];

/** Dilin nereden geldiği (core `script.dil_kaynagi`). */
export const DIL_KAYNAKLARI = ["algilandi", "secildi", "varsayilan"] as const;
export type DilKaynagi = (typeof DIL_KAYNAKLARI)[number];

export const DIL_KAYNAGI_ETIKETI: Record<DilKaynagi, string> = {
  algilandi: "repodan algılandı",
  secildi: "elle seçildi",
  varsayilan: "varsayılan",
};

const DIL_KUMESI = new Set<string>(DILLER);
const DIL_KAYNAGI_KUMESI = new Set<string>(DIL_KAYNAKLARI);

export function dilMi(x: unknown): x is Dil {
  return typeof x === "string" && DIL_KUMESI.has(x);
}

/** Yaygın yazımlar (toolchain `lang`, dosya uzantısı) → sözleşme adı. */
const DIL_ESADI: Record<string, Dil> = {
  typescript: "ts",
  "c#": "csharp",
  cs: "csharp",
  py: "python",
  kt: "kotlin",
};

/** Ham değeri dile çevirir (büyük/küçük harf ve boşluk duyarsız); tanınmazsa null (uydurulmaz). */
export function dilUyarla(x: unknown): Dil | null {
  if (typeof x !== "string") return null;
  const k = x.trim().toLowerCase();
  if (dilMi(k)) return k;
  return DIL_ESADI[k] ?? null;
}

export function dilKaynagiUyarla(x: unknown): DilKaynagi | null {
  return typeof x === "string" && DIL_KAYNAGI_KUMESI.has(x) ? (x as DilKaynagi) : null;
}

/** (platform, dil) çiftinin hattı (core `CATILAR`); geçersiz çiftte null. */
export function ciftHati(platform: Platform, dil: Dil): Hat | null {
  return CATILAR[platform]?.[dil]?.hat ?? null;
}

export function hatMi(x: unknown): x is Hat {
  return typeof x === "string" && (HATLAR as readonly string[]).includes(x);
}

export function dilDurumuUyarla(x: unknown): DilDurumu | null {
  return x === "acik" || x === "yakinda" ? x : null;
}

/** Çift müşteri CI hattında mı (kotlin/Espresso, swift/XCUITest). */
export function musteriCiMi(platform: Platform | null | undefined, dil: Dil | null | undefined): boolean {
  return !!platform && !!dil && ciftHati(platform, dil) === "musteri_ci";
}

/** Geçerli (platform, dil): core `CATILAR` matrisi (web: ts/java/csharp/python; android: java/python/kotlin …). */
export function gecerliCift(platform: Platform, dil: Dil): boolean {
  return ciftHati(platform, dil) !== null;
}

/** Platformda üretilebilen diller (seçici sırasıyla). */
export function gecerliDiller(platform: Platform): Dil[] {
  return DILLER.filter((d) => gecerliCift(platform, d));
}

/** Algılama yoksa / eski kayıt: web → ts, uygulama → java (geriye uyum). */
export function varsayilanDil(platform: Platform): Dil {
  return platform === "web" ? "ts" : "java";
}

/** (platform, dil) çiftinin test çatısı; geçersiz çiftte null (uydurulmaz). */
export function DIL_CATISI(platform: Platform, dil: Dil): string | null {
  return CATILAR[platform]?.[dil]?.cati ?? null;
}

/**
 * Yerel kontrol adımlarının görünen adları (core `yerel_kontrol.adimlar[].ad`). Aynı adım adı
 * (deps / guard / compile) dile göre farklı araçtır: `kontrolAdimiEtiketi(ad, dil)`. Bu tablo dil
 * bilinmeyen eski kayıtlar içindir (Java adları). Tanınmayan ad ham gösterilir.
 */
export const KONTROL_ADIMI: Record<string, string> = {
  tsc: "tsc --strict",
  eslint: "eslint --no-inline-config",
  ast_guard: "AST koruması",
  deps: "pom kilidi",
  guard: "Java AST koruması",
  compile: "derleme",
};

const DIL_KONTROL_ADIMI: Partial<Record<Dil, Record<string, string>>> = {
  python: { deps: "kilit (requirements.lock)", guard: "Python AST koruması", compile: "py_compile" },
  csharp: { deps: "NuGet kilidi", guard: "Roslyn koruması", compile: "dotnet build" },
  kotlin: { guard: "Kotlin koruması (tree-sitter)" },
  swift: { guard: "Swift koruması (tree-sitter)" },
};

/** Adımın dile göre görünen adı; dil bilinmiyorsa `KONTROL_ADIMI`, o da yoksa ham ad. */
export function kontrolAdimiEtiketi(ad: string, dil: Dil | null | undefined = null): string {
  return (dil && DIL_KONTROL_ADIMI[dil]?.[ad]) ?? KONTROL_ADIMI[ad] ?? ad;
}

/** Yerel kontrolün koşu adımının adı: araç platforma, sürüm dile bakar. Müşteri CI hattında koşu TP'de değildir. */
export function kosuAraci(platform: Platform | null | undefined, dil: Dil | null | undefined): string {
  if (musteriCiMi(platform, dil)) return "Müşteri CI (GitHub Actions)";
  if (platform && platform !== "web") return dil === "python" ? "Appium (pytest)" : dil === "csharp" ? "Appium (.NET)" : "Appium";
  if (dil === "java") return "Playwright (Java)";
  if (dil === "python") return "Playwright (pytest)";
  if (dil === "csharp") return "Playwright (.NET)";
  return "Playwright";
}

/**
 * Dilin statik kontrol adımları (koşu hariç), sırasıyla. `dogrulanmamis` (011 eski kaydı) verilirse adım
 * yoktur. Müşteri CI dillerinde yalnız koruma (tree-sitter) TP'de koşar.
 */
export function kontrolAdimlari(dil: Dil | null | undefined, hat: Hat | null = null): string[] {
  if (hat === "dogrulanmamis") return [];
  if (dil === "java" || dil === "python" || dil === "csharp") return ["deps", "guard", "compile"];
  if (dil === "kotlin" || dil === "swift") return ["guard"];
  return ["tsc", "eslint", "ast_guard"];
}

/** Yerel kontrol zincirinin tek satırlık özeti: "pom kilidi · Java AST koruması · derleme · Playwright (Java)". */
export function kontrolZinciri(platform: Platform | null | undefined, dil: Dil | null | undefined, hat: Hat | null = null): string {
  return [...kontrolAdimlari(dil, hat).map((a) => kontrolAdimiEtiketi(a, dil)), kosuAraci(platform, dil)].join(" · ");
}
