#!/usr/bin/env node
// tp-symbols CLI: sembol tablosunu JSON olarak stdout'a yazar.
//
//   tp-symbols --root <e2e-kökü> [--pages pages]
//
// Çıkış: 0 = tablo üretildi (ayrıştırma sorunları `errors` içinde), 2 = kullanım/çalışma hatası
// (stdout'ta {"ok": false, "error": "..."}).
import { realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { extractSymbols } from "./extract.js";

const USAGE = "Kullanım: tp-symbols --root <e2e-kökü> [--pages pages]";

export interface CliIO {
  stdout: (s: string) => void;
  stderr: (s: string) => void;
}

const defaultIO: CliIO = {
  stdout: (s) => process.stdout.write(s),
  stderr: (s) => process.stderr.write(s),
};

export function main(argv: string[], io: CliIO = defaultIO): number {
  let values: Record<string, string | boolean | undefined>;
  try {
    ({ values } = parseArgs({
      args: argv,
      options: {
        root: { type: "string" },
        pages: { type: "string", default: "pages" },
        help: { type: "boolean", short: "h", default: false },
      },
      strict: true,
      allowPositionals: false,
    }));
  } catch (err) {
    io.stderr(`${(err as Error).message}\n${USAGE}\n`);
    return 2;
  }
  if (values["help"]) {
    io.stdout(`${USAGE}\n`);
    return 0;
  }
  const root = values["root"];
  if (typeof root !== "string" || root === "") {
    io.stderr(`--root zorunludur\n${USAGE}\n`);
    return 2;
  }
  try {
    const table = extractSymbols(root, String(values["pages"]));
    io.stdout(`${JSON.stringify(table)}\n`);
    return 0;
  } catch (err) {
    io.stdout(`${JSON.stringify({ ok: false, error: (err as Error).message })}\n`);
    io.stderr(`tp-symbols hata: ${(err as Error).message}\n`);
    return 2;
  }
}

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
