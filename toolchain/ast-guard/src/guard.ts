// AST koruması çekirdeği (Constitution VI, TEKNIK-TASARIM §8.7).
//
// repair modu: değişen her dosya <root>/pages/**/locators.ts olmalı; export ve anahtar kümeleri,
//   role/name/intent (ve testId dışındaki tüm alanlar) aynı kalmalı; yalnızca testId string
//   değerleri değişebilir. Dosya metni, testId literal'leri dışında bayt bayt aynı olmalı.
//   Tek istisna web testlerinin diğer dillerdeki kimlik bağlarıdır (<root>'un kardeşi
//   e2e-java/**/ekranlar/Kimlikler.java, e2e-csharp/Pages/Kimlikler.cs, e2e-python/pages/kimlikler.py):
//   aynı onarımda yalnızca string literal değerleri ve YALNIZCA bu diff'teki locators.ts testId
//   değişiklikleriyle birebir aynı (önce → sonra) çiftler olarak değişebilir; metnin geri kalanı
//   bayt bayt aynı olmalı. Uygulama (mobil/masaüstü) testlerinin Kimlikler dosyaları kapsam dışıdır.
// pr modu: değişen/eklenen locators.ts dosyalarının saf veri kaldığını doğrular ve değişen
//   testId'leri raporlar; <root>/tsconfig.json değiştiyse tsc --strict kapısının gevşetilmediğini
//   doğrular (tsconfig-gate.ts); başka dosya değişikliklerine karışmaz.
import { parseLocators, type LocatorEntry, type ParsedLocators, type Violation } from "./locators.js";
import type { Source } from "./sources.js";
import { checkTsconfig, tsconfigPath } from "./tsconfig-gate.js";

export type Mode = "repair" | "pr";
export type ChangeStatus = "added" | "modified" | "deleted";

export interface ChangedFile {
  path: string;
  status: ChangeStatus;
  locator: boolean;
  /** Web testlerinin başka dildeki kimlik bağı (repair modunda yalnız eşli literal değişebilir). */
  binding?: boolean;
}

export interface TestIdChange {
  file: string;
  entry: string;
  before: string;
  after: string;
}

export interface Report {
  tool: "ast-guard";
  schema_version: 1;
  mode: Mode;
  ok: boolean;
  /** pr modunda <root>/pages/** ve <root>/tsconfig.json değişmediyse true (no-op, başarılı) */
  noop: boolean;
  base: string;
  head: string;
  root: string;
  changed_files: ChangedFile[];
  testid_changes: TestIdChange[];
  added_entries: string[];
  removed_entries: string[];
  violations: Violation[];
  summary: string;
}

export interface GuardOptions {
  mode: Mode;
  /** Uygulama e2e kökü (pages/ bunun altında), repo/dizin köküne göre; "." = kök */
  root: string;
}

export function normalizeRoot(root: string): string {
  let r = root.replace(/\\/g, "/").trim();
  while (r.startsWith("./")) r = r.slice(2);
  r = r.replace(/\/+$/, "");
  if (r === "." || r === "") return "";
  if (r.startsWith("/") || r.split("/").includes("..")) {
    throw new Error(`--root göreli ve repo içinde olmalı: ${root}`);
  }
  return r;
}

/** Kök göreli yol; kök dışındaysa undefined. */
function underRoot(path: string, root: string): string | undefined {
  if (root === "") return path;
  return path.startsWith(`${root}/`) ? path.slice(root.length + 1) : undefined;
}

export function isLocatorPath(path: string, root: string): boolean {
  const rel = underRoot(path, root);
  return rel !== undefined && /^pages\/(?:[^/]+\/)*locators\.ts$/.test(rel);
}

/** Web e2e kökünün kardeşi olan diğer dil kimlik bağları (kök `demo-app/e2e` → `demo-app/…`). */
const BINDING_RES: readonly RegExp[] = [
  /^e2e-java\/src\/test\/java\/(?:[^/]+\/)*ekranlar\/Kimlikler\.java$/,
  /^e2e-csharp\/Pages\/Kimlikler\.cs$/,
  /^e2e-python\/pages\/kimlikler\.py$/,
];

export function isBindingPath(path: string, kok: string): boolean {
  const root = normalizeRoot(kok);
  if (root === "") return false;
  const i = root.lastIndexOf("/");
  const parent = i < 0 ? "" : root.slice(0, i);
  const rel = parent === "" ? path : path.startsWith(`${parent}/`) ? path.slice(parent.length + 1) : undefined;
  return rel !== undefined && BINDING_RES.some((re) => re.test(rel));
}

export function isPagesPath(path: string, root: string): boolean {
  const rel = underRoot(path, root);
  return rel !== undefined && rel.startsWith("pages/");
}

export function diffSources(base: Source, head: Source, root: string): ChangedFile[] {
  const a = base.list();
  const b = head.list();
  const out: ChangedFile[] = [];
  for (const [path, entry] of b) {
    const prev = a.get(path);
    if (!prev) out.push(changedFile(path, "added", root));
    else if (prev.id !== entry.id) out.push(changedFile(path, "modified", root));
  }
  for (const path of a.keys()) {
    if (!b.has(path)) out.push(changedFile(path, "deleted", root));
  }
  return out.sort((x, y) => (x.path < y.path ? -1 : x.path > y.path ? 1 : 0));
}

function changedFile(path: string, status: ChangeStatus, root: string): ChangedFile {
  const cf: ChangedFile = { path, status, locator: isLocatorPath(path, root) };
  if (isBindingPath(path, root)) cf.binding = true;
  return cf;
}

export function runGuard(base: Source, head: Source, opts: GuardOptions): Report {
  const root = normalizeRoot(opts.root);
  const changed = diffSources(base, head, root);
  const report: Report = {
    tool: "ast-guard",
    schema_version: 1,
    mode: opts.mode,
    ok: true,
    noop: false,
    base: base.label,
    head: head.label,
    root: root === "" ? "." : root,
    changed_files: changed,
    testid_changes: [],
    added_entries: [],
    removed_entries: [],
    violations: [],
    summary: "",
  };

  if (opts.mode === "repair") checkRepair(base, head, changed, report);
  else checkPr(base, head, changed, root, report);

  report.ok = report.violations.length === 0;
  report.summary = summarize(report);
  return report;
}

function checkRepair(base: Source, head: Source, changed: ChangedFile[], report: Report): void {
  const bindings: ChangedFile[] = [];
  for (const cf of changed) {
    if (!cf.locator && cf.binding && cf.status === "modified") {
      bindings.push(cf); // locators.ts testId değişiklikleri toplandıktan sonra denetlenir
      continue;
    }
    if (!cf.locator) {
      report.violations.push({
        code: "non_locator_file_changed",
        file: cf.path,
        message: `Onarım yalnızca pages/**/locators.ts dosyalarını değiştirebilir; değişen dosya (${cf.status})`,
      });
      continue;
    }
    if (cf.status === "added") {
      report.violations.push({ code: "locator_file_added", file: cf.path, message: "Onarım yeni locator dosyası ekleyemez" });
      continue;
    }
    if (cf.status === "deleted") {
      report.violations.push({ code: "locator_file_deleted", file: cf.path, message: "Onarım locator dosyası silemez" });
      continue;
    }
    const baseText = base.read(cf.path);
    const headText = head.read(cf.path);
    const before = parseLocators(cf.path, baseText);
    const after = parseLocators(cf.path, headText);
    if (before.violations.length > 0) {
      report.violations.push({
        code: "base_not_pure",
        file: cf.path,
        message: "Taban sürümdeki locators.ts saf veri değil; onarım güvenle karşılaştırılamaz",
      });
    }
    report.violations.push(...after.violations);
    if (before.violations.length > 0 || after.violations.length > 0) continue;

    const structural = compareStructure(before, after, report, true);
    if (structural > 0) continue;

    // Metin denetimi: head'deki testId literal'leri tabandakilerle değiştirildiğinde metin
    // birebir tabana eşit olmalı (yorum, sıra, biçim, tırnak değişikliği yakalanır).
    const restored = restoreTestIds(headText, after, before);
    if (restored !== baseText) {
      report.violations.push({
        code: "non_testid_change",
        file: cf.path,
        message: "testId değerleri dışında metin değişikliği var (yorum, sıra, biçim veya tırnak)",
      });
    }
  }
  const pairs = new Set(report.testid_changes.map((c) => `${c.before}\u0000${c.after}`));
  for (const cf of bindings) checkBinding(base.read(cf.path), head.read(cf.path), cf.path, pairs, report);
}

const STRING_LITERAL = /"([^"\\\n]*)"/g;

/**
 * Kimlik bağı dosyası (Java/C#/Python): string literal'ler sırayla eşlenir; farklı olan her
 * literal, aynı diff'teki bir locators.ts testId değişikliğiyle (önce → sonra) birebir aynı
 * olmalı; head'deki literal'ler tabandakilerle değiştirildiğinde metin tabana bayt bayt eşit olmalı.
 */
function checkBinding(baseText: string, headText: string, file: string, pairs: Set<string>, report: Report): void {
  const b = [...baseText.matchAll(STRING_LITERAL)];
  const h = [...headText.matchAll(STRING_LITERAL)];
  if (b.length !== h.length) {
    report.violations.push({
      code: "binding_structure_changed",
      file,
      message: "Kimlik bağı dosyasında string literal sayısı değişti; onarım yalnızca değerleri değiştirebilir",
    });
    return;
  }
  let text = headText;
  let degisen = 0;
  for (let i = h.length - 1; i >= 0; i--) {
    const mb = b[i];
    const m = h[i];
    if (!mb || !m) continue;
    const before = mb[1] ?? "";
    const after = m[1] ?? "";
    if (before !== after) {
      degisen++;
      if (!pairs.has(`${before}\u0000${after}`)) {
        report.violations.push({
          code: "binding_change_unpaired",
          file,
          before,
          after,
          message: `Kimlik bağında '${before}' → '${after}' değişikliği locators.ts'deki bir testId onarımına karşılık gelmiyor`,
        });
      } else {
        report.testid_changes.push({ file, entry: "", before, after });
      }
    }
    const start = m.index ?? 0;
    text = text.slice(0, start) + mb[0] + text.slice(start + m[0].length);
  }
  if (text !== baseText || degisen === 0) {
    report.violations.push({
      code: "non_testid_change",
      file,
      message: "Kimlik bağında eşli kimlik değerleri dışında metin değişikliği var",
    });
  }
}

function checkPr(base: Source, head: Source, changed: ChangedFile[], root: string, report: Report): void {
  const tsconfig = tsconfigPath(root);
  const tsChange = changed.find((cf) => cf.path === tsconfig);
  if (tsChange) {
    const baseText = tsChange.status === "added" ? undefined : base.read(tsconfig);
    const headText = tsChange.status === "deleted" ? undefined : head.read(tsconfig);
    report.violations.push(...checkTsconfig(tsconfig, baseText, headText));
  }
  const pages = changed.filter((cf) => isPagesPath(cf.path, root));
  if (pages.length === 0) {
    report.noop = tsChange === undefined;
    return;
  }
  const baseFiles = base.list();
  for (const cf of pages) {
    if (!cf.locator || cf.status === "deleted") continue;
    const after = parseLocators(cf.path, head.read(cf.path));
    report.violations.push(...after.violations);
    if (after.violations.length > 0) continue;
    if (cf.status === "added") {
      report.added_entries.push(...[...after.entries.keys()].map((k) => `${cf.path}#${k}`));
      continue;
    }
    if (!baseFiles.has(cf.path)) continue;
    const before = parseLocators(cf.path, base.read(cf.path));
    if (before.violations.length > 0) {
      // Taban saf değildi (ör. eski biçim); yalnızca head'in saflığı zorunlu.
      report.added_entries.push(...[...after.entries.keys()].map((k) => `${cf.path}#${k}`));
      continue;
    }
    compareStructure(before, after, report, false);
  }
}

/** Yapısal karşılaştırma; strict=true ise farklar ihlaldir. Döndürülen: ihlal sayısı. */
function compareStructure(before: ParsedLocators, after: ParsedLocators, report: Report, strict: boolean): number {
  const file = after.file;
  let count = 0;
  const push = (v: Violation): void => {
    count++;
    report.violations.push(v);
  };

  if (strict) {
    const bExp = new Set(before.exports);
    const aExp = new Set(after.exports);
    for (const e of after.exports)
      if (!bExp.has(e)) push({ code: "export_added", file, message: `Yeni export eklenemez: ${e}`, entry: e });
    for (const e of before.exports)
      if (!aExp.has(e)) push({ code: "export_removed", file, message: `Export kaldırılamaz: ${e}`, entry: e });
  }

  for (const [id, a] of after.entries) {
    const b = before.entries.get(id);
    if (!b) {
      if (strict) push({ code: "key_added", file, message: `Yeni locator anahtarı eklenemez: ${id}`, entry: id, line: a.line });
      else report.added_entries.push(`${file}#${id}`);
      continue;
    }
    if (strict) count += compareFields(b, a, file, push);
    const bt = b.fields["testId"] ?? "";
    const at = a.fields["testId"] ?? "";
    if (bt !== at) report.testid_changes.push({ file, entry: id, before: bt, after: at });
  }
  for (const id of before.entries.keys()) {
    if (!after.entries.has(id)) {
      if (strict) push({ code: "key_removed", file, message: `Locator anahtarı kaldırılamaz: ${id}`, entry: id });
      else report.removed_entries.push(`${file}#${id}`);
    }
  }
  return count;
}

function compareFields(b: LocatorEntry, a: LocatorEntry, file: string, push: (v: Violation) => void): number {
  let n = 0;
  const keys = new Set([...Object.keys(b.fields), ...Object.keys(a.fields)]);
  for (const k of [...keys].sort()) {
    if (k === "testId") continue;
    const bv = b.fields[k];
    const av = a.fields[k];
    if (bv === undefined) {
      n++;
      push({ code: "field_added", file, entry: a.id, field: k, message: `${a.id}: yeni alan eklenemez: ${k}`, after: av ?? "", line: a.line });
    } else if (av === undefined) {
      n++;
      push({ code: "field_removed", file, entry: a.id, field: k, message: `${a.id}: alan kaldırılamaz: ${k}`, before: bv, line: a.line });
    } else if (bv !== av) {
      n++;
      push({
        code: "field_changed",
        file,
        entry: a.id,
        field: k,
        before: bv,
        after: av,
        message: `${a.id}: '${k}' değiştirilemez (yalnızca testId değişebilir)`,
        line: a.line,
      });
    }
  }
  return n;
}

function restoreTestIds(headText: string, after: ParsedLocators, before: ParsedLocators): string {
  const spans = [...after.entries.values()]
    .map((e) => ({ span: e.testIdSpan, baseSpan: before.entries.get(e.id)?.testIdSpan }))
    .filter((x): x is { span: NonNullable<LocatorEntry["testIdSpan"]>; baseSpan: NonNullable<LocatorEntry["testIdSpan"]> } =>
      Boolean(x.span && x.baseSpan),
    )
    .sort((x, y) => y.span.start - x.span.start);
  let text = headText;
  for (const { span, baseSpan } of spans) {
    text = text.slice(0, span.start) + baseSpan.text + text.slice(span.end);
  }
  return text;
}

function summarize(r: Report): string {
  if (r.mode === "pr" && r.noop) return "pages/** ve tsconfig.json değişmedi; AST koruması no-op (başarılı).";
  const head = r.ok ? "AST koruması geçti" : `AST koruması başarısız: ${r.violations.length} ihlal`;
  const parts = [
    `${head} (mod: ${r.mode})`,
    `değişen dosya: ${r.changed_files.length}`,
    `testId değişikliği: ${r.testid_changes.length}`,
  ];
  if (r.added_entries.length) parts.push(`eklenen locator: ${r.added_entries.length}`);
  if (r.removed_entries.length) parts.push(`kaldırılan locator: ${r.removed_entries.length}`);
  return parts.join(" · ");
}
