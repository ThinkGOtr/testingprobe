// tsc --strict kapısının güvencesi (Constitution IV; TEKNIK-TASARIM §8.5).
//
// CI (`demo-app/ci/run-checks.sh`) ve toolchain `tsc --noEmit` katılığı PR commit'indeki
// `<root>/tsconfig.json`'dan alır. Bir PR `"strict": false` yazarak zorunlu "tsc --strict"
// kapısını sessizce gevşetemesin diye, tsconfig değiştiğinde head sürümü burada doğrulanır:
//   - dosya silinemez ve JSONC olarak ayrıştırılabilir olmalı;
//   - `compilerOptions.strict` açıkça `true` olmalı;
//   - strict ailesinden hiçbir bayrak `false` yapılamaz;
//   - `extends` kullanılamaz (katılık başka dosyadan gevşetilemesin);
//   - `files` / `include` / `exclude` tabandakiyle aynı kalmalı (test dosyaları kapsam dışına
//     alınarak tsc'den kaçırılamasın).
import { ts } from "ts-morph";
import type { Violation } from "./locators.js";

export const STRICT_FAMILY: readonly string[] = [
  "noImplicitAny",
  "strictNullChecks",
  "strictFunctionTypes",
  "strictBindCallApply",
  "strictPropertyInitialization",
  "strictBuiltinIteratorReturn",
  "noImplicitThis",
  "useUnknownInCatchVariables",
  "alwaysStrict",
];

const SCOPE_KEYS = ["files", "include", "exclude"] as const;

export function tsconfigPath(root: string): string {
  return root === "" ? "tsconfig.json" : `${root}/tsconfig.json`;
}

function parse(file: string, text: string): { config?: Record<string, unknown>; error?: string } {
  const res = ts.parseConfigFileTextToJson(file, text);
  if (res.error) {
    return { error: ts.flattenDiagnosticMessageText(res.error.messageText, "\n") };
  }
  const cfg: unknown = res.config;
  if (cfg === null || typeof cfg !== "object" || Array.isArray(cfg)) {
    return { error: "tsconfig kökü bir nesne olmalı" };
  }
  return { config: cfg as Record<string, unknown> };
}

/** tsconfig değişikliğini doğrular; ihlalleri döndürür. `headText` undefined = dosya silindi. */
export function checkTsconfig(file: string, baseText: string | undefined, headText: string | undefined): Violation[] {
  const out: Violation[] = [];
  const v = (code: string, message: string, extra: Partial<Violation> = {}): void => {
    out.push({ code, file, message, ...extra });
  };
  if (headText === undefined) {
    v("tsconfig_deleted", "tsconfig.json silinemez (tsc --strict kapısı bu dosyaya dayanır)");
    return out;
  }
  const head = parse(file, headText);
  if (!head.config) {
    v("tsconfig_invalid", `tsconfig.json ayrıştırılamadı: ${head.error ?? "bilinmeyen hata"}`);
    return out;
  }
  const cfg = head.config;
  if ("extends" in cfg) {
    v("tsconfig_extends", "tsconfig.json 'extends' kullanamaz (katılık başka dosyadan gevşetilemez)");
  }
  const opts = cfg["compilerOptions"];
  const co = opts !== null && typeof opts === "object" && !Array.isArray(opts) ? (opts as Record<string, unknown>) : {};
  if (co["strict"] !== true) {
    v("tsconfig_not_strict", "compilerOptions.strict açıkça true olmalı (Constitution IV: tsc --strict)", {
      field: "strict",
      after: JSON.stringify(co["strict"] ?? null),
    });
  }
  for (const flag of STRICT_FAMILY) {
    if (flag in co && co[flag] !== true) {
      v("tsconfig_strict_weakened", `compilerOptions.${flag} kapatılamaz (strict ailesi)`, {
        field: flag,
        after: JSON.stringify(co[flag]),
      });
    }
  }
  if (baseText !== undefined) {
    const base = parse(file, baseText);
    if (base.config) {
      for (const key of SCOPE_KEYS) {
        const b = JSON.stringify(base.config[key] ?? null);
        const a = JSON.stringify(cfg[key] ?? null);
        if (a !== b) {
          v("tsconfig_scope_changed", `tsconfig.json '${key}' değiştirilemez (tsc kapsamı daraltılamaz)`, {
            field: key,
            before: b,
            after: a,
          });
        }
      }
    }
  }
  return out;
}
