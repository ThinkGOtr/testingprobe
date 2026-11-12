// 011 üretim dili: dil ayrı bir boyuttur, platformdan türetilmez (specs/011-uretim-dili/plan.md §2.1).
// Tek kaynak core `features/codegen/platform.py` (`DILLER`, `TAM_HAT_DILLERI`, `DOGRULANMAMIS_DILLER`);
// buradaki sabitler onun portal karşılığıdır. Araç/ortam sorusu platforma (lib/platform.ts), kod/derleme
// sorusu dile bakar.
import type { Platform } from "./platform";

export const DILLER = ["ts", "java", "csharp", "python"] as const;
export type Dil = (typeof DILLER)[number];

/** Tam hat: derleme + koruma + koşu + PR + kırarak doğrulama. */
export const TAM_HAT_DILLERI: readonly Dil[] = ["ts", "java"];
/** Doğrulanmamış: kod üretilir ama derlenmez/koşulmaz; PR açılmaz, merge edilemez (K3). */
export const DOGRULANMAMIS_DILLER: readonly Dil[] = ["csharp", "python"];

export const DIL_ETIKETI: Record<Dil, string> = {
  ts: "TypeScript",
  java: "Java",
  csharp: "C#",
  python: "Python",
};

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

export function tamHatMi(dil: Dil | null | undefined): boolean {
  return !!dil && TAM_HAT_DILLERI.includes(dil);
}

export function dogrulanmamisDilMi(dil: Dil | null | undefined): boolean {
  return !!dil && DOGRULANMAMIS_DILLER.includes(dil);
}

/** Geçerli (platform, dil): web × herhangi bir dil; android | ios | windows × yalnız java. */
export function gecerliCift(platform: Platform, dil: Dil): boolean {
  return platform === "web" ? true : dil === "java";
}

/** Platformda üretilebilen diller (seçici sırasıyla). */
export function gecerliDiller(platform: Platform): Dil[] {
  return DILLER.filter((d) => gecerliCift(platform, d));
}

/** Algılama yoksa / eski kayıt: web → ts, uygulama → java (geriye uyum). */
export function varsayilanDil(platform: Platform): Dil {
  return platform === "web" ? "ts" : "java";
}

const WEB_CATISI: Record<Dil, string> = {
  ts: "Playwright Test",
  java: "Playwright for Java + TestNG",
  csharp: "Playwright .NET + NUnit",
  python: "pytest-playwright",
};

/** (platform, dil) çiftinin test çatısı; geçersiz çiftte null (uydurulmaz). */
export function DIL_CATISI(platform: Platform, dil: Dil): string | null {
  if (!gecerliCift(platform, dil)) return null;
  return platform === "web" ? WEB_CATISI[dil] : "Appium + TestNG";
}

/**
 * Yerel kontrol adımlarının görünen adları (core `yerel_kontrol.adimlar[].ad`; ts: tsc / eslint /
 * ast_guard, java: deps / guard / compile). Tanınmayan ad ham gösterilir.
 */
export const KONTROL_ADIMI: Record<string, string> = {
  tsc: "tsc --strict",
  eslint: "eslint --no-inline-config",
  ast_guard: "AST koruması",
  deps: "pom kilidi",
  guard: "Java AST koruması",
  compile: "derleme",
};

/** Yerel kontrolün koşu adımının adı: araç platforma, sürüm dile bakar. */
export function kosuAraci(platform: Platform | null | undefined, dil: Dil | null | undefined): string {
  if (platform && platform !== "web") return "Appium";
  return dil === "java" ? "Playwright (Java)" : "Playwright";
}

/** Dilin statik kontrol adımları (koşu hariç), sırasıyla. Doğrulanmamış dilde yok. */
export function kontrolAdimlari(dil: Dil | null | undefined): string[] {
  if (dil === "java") return ["deps", "guard", "compile"];
  if (dogrulanmamisDilMi(dil)) return [];
  return ["tsc", "eslint", "ast_guard"];
}

/** Yerel kontrol zincirinin tek satırlık özeti: "pom kilidi · Java AST koruması · derleme · Playwright (Java)". */
export function kontrolZinciri(platform: Platform | null | undefined, dil: Dil | null | undefined): string {
  return [...kontrolAdimlari(dil).map((a) => KONTROL_ADIMI[a]), kosuAraci(platform, dil)].join(" · ");
}
