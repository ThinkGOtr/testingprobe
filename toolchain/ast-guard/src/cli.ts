#!/usr/bin/env node
// ast-guard CLI.
//
//   ast-guard --base <dizin|git-ref> --head <dizin|git-ref> [--mode repair|pr]
//             [--repo <git-repo>] [--root <e2e-kökü>] [--out <rapor.json>] [--quiet]
//
// Çıkış kodları: 0 = geçti (veya no-op), 1 = ihlal var, 2 = kullanım/çalışma hatası.
// JSON rapor stdout'a (ve --out verilirse dosyaya) yazılır; insan okunur özet stderr'e.
import { realpathSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { runGuard, type Mode, type Report } from "./guard.js";
import { openSource } from "./sources.js";

export const EXIT_OK = 0;
export const EXIT_VIOLATIONS = 1;
export const EXIT_ERROR = 2;

const USAGE = `Kullanım: ast-guard --base <dizin|git-ref> --head <dizin|git-ref> [--mode repair|pr]
                 [--repo <git-repo>] [--root <e2e-kökü>] [--out <rapor.json>] [--quiet]

  --mode repair  (varsayılan) yalnızca pages/**/locators.ts içindeki testId değerleri değişebilir
  --mode pr      değişen locators.ts dosyaları saf veri olmalı; değişen testId'ler raporlanır
  --repo         git ref'lerinin çözüldüğü repo (varsayılan: çalışma dizini)
  --root         pages/ dizinini içeren kök, repo/dizin köküne göre (ör. demo-app/e2e; varsayılan .)
Çıkış: 0 geçti · 1 ihlal · 2 hata`;

export interface CliIO {
  stdout: (s: string) => void;
  stderr: (s: string) => void;
}

const defaultIO: CliIO = {
  stdout: (s) => process.stdout.write(s),
  stderr: (s) => process.stderr.write(s),
};

export function main(argv: string[], io: CliIO = defaultIO, cwd = process.cwd()): number {
  let values: Record<string, string | boolean | undefined>;
  try {
    ({ values } = parseArgs({
      args: argv,
      options: {
        base: { type: "string" },
        head: { type: "string" },
        mode: { type: "string", default: "repair" },
        repo: { type: "string", default: cwd },
        root: { type: "string", default: "." },
        out: { type: "string" },
        quiet: { type: "boolean", default: false },
        help: { type: "boolean", short: "h", default: false },
      },
      strict: true,
      allowPositionals: false,
    }));
  } catch (err) {
    io.stderr(`${(err as Error).message}\n${USAGE}\n`);
    return EXIT_ERROR;
  }
  if (values["help"]) {
    io.stdout(`${USAGE}\n`);
    return EXIT_OK;
  }
  const base = values["base"];
  const head = values["head"];
  const mode = values["mode"];
  if (typeof base !== "string" || typeof head !== "string" || base === "" || head === "") {
    io.stderr(`--base ve --head zorunludur\n${USAGE}\n`);
    return EXIT_ERROR;
  }
  if (mode !== "repair" && mode !== "pr") {
    io.stderr(`--mode yalnızca 'repair' veya 'pr' olabilir (verilen: ${String(mode)})\n`);
    return EXIT_ERROR;
  }

  let report: Report;
  try {
    const repo = String(values["repo"]);
    report = runGuard(openSource(base, repo), openSource(head, repo), {
      mode: mode as Mode,
      root: String(values["root"]),
    });
  } catch (err) {
    const error = { tool: "ast-guard", schema_version: 1, ok: false, error: (err as Error).message };
    io.stdout(`${JSON.stringify(error, null, 2)}\n`);
    io.stderr(`ast-guard hata: ${(err as Error).message}\n`);
    return EXIT_ERROR;
  }

  const json = `${JSON.stringify(report, null, 2)}\n`;
  if (typeof values["out"] === "string") writeFileSync(values["out"], json);
  if (!values["quiet"]) io.stdout(json);
  io.stderr(`${report.summary}\n`);
  for (const v of report.violations) {
    io.stderr(`  ✗ [${v.code}] ${v.file}${v.line ? `:${v.line}` : ""} ${v.message}\n`);
  }
  for (const c of report.testid_changes) {
    io.stderr(`  • ${c.file}#${c.entry}: ${c.before} → ${c.after}\n`);
  }
  return report.ok ? EXIT_OK : EXIT_VIOLATIONS;
}

// Doğrudan çalıştırıldığında (bin) çık; test içe aktarırken çıkma.
function invokedDirectly(): boolean {
  const arg = process.argv[1];
  if (!arg) return false;
  try {
    return realpathSync(arg) === realpathSync(fileURLToPath(import.meta.url));
  } catch {
    return false;
  }
}
if (invokedDirectly()) {
  process.exitCode = main(process.argv.slice(2));
}
