// Sembol tablosu çıkarıcı (TEKNIK-TASARIM §8.4, MIMARI-SOZLESME §2 `POST /symbols`).
//
// Girdi: e2e kökü (içinde `pages/`). Çıktı: page object sınıfları, public metotları
// (ad, parametre adları + türleri, dönüş türü, JSDoc, kind: action | expect) ve sınıfın
// kullandığı `locators.ts` girişleri ({testId, role, name, intent, within?}).
//
// Kaynak yalnızca AYRIŞTIRILIR (ts-morph); hiçbir dosya çalıştırılmaz. Kod güvenilmeyen
// girdidir: locators.ts saf veri değilse giriş atlanır ve `errors` listesine yazılır
// (saf veri denetiminin asıl sahibi ast-guard'dır).
import { readdirSync, lstatSync } from "node:fs";
import { dirname, join, posix, relative, resolve, sep } from "node:path";
import {
  Node,
  Project,
  Scope,
  ts,
  type ClassDeclaration,
  type MethodDeclaration,
  type ObjectLiteralExpression,
  type SourceFile,
} from "ts-morph";

export const SCHEMA_VERSION = 1;

export interface ParamSymbol {
  name: string;
  type: string;
  optional: boolean;
  default?: string;
}

export interface MethodSymbol {
  name: string;
  params: ParamSymbol[];
  returns: string;
  kind: "action" | "expect";
  async: boolean;
  doc: string;
  line: number;
}

export interface LocatorSymbol {
  testId: string;
  role: string;
  name: string;
  intent: string;
  within?: string;
  /** Sonu `-` ile biten testId önektir (ürün kodu / sipariş no eklenir). */
  prefix: boolean;
  file: string;
  line: number;
}

export interface PageObjectSymbol {
  class: string;
  file: string;
  doc: string;
  methods: MethodSymbol[];
  /** Sınıf dosyasının içe aktardığı locator export'larının girişleri; anahtar `export.key[.key]`. */
  locators: Record<string, LocatorSymbol>;
}

export interface ExtractError {
  file: string;
  line?: number;
  message: string;
}

export interface SymbolTable {
  schema_version: number;
  root: string;
  page_objects: PageObjectSymbol[];
  locator_files: { file: string; exports: string[] }[];
  errors: ExtractError[];
}

/** Ayrıştırılan dizinler dışında kalanlar (git'te zaten izlenmez). */
const IGNORED_DIRS = new Set(["node_modules", ".git", "dist", "results", "test-results", "playwright-report"]);
const EXPECT_NAME = /^expect(?:$|[A-Z0-9_])/;
const LOCATOR_FILE = "locators.ts";

function toPosix(p: string): string {
  return p.split(sep).join(posix.sep);
}

/** `dir` altındaki .ts dosyaları (symlink'ler izlenmez), sıralı. */
function listTsFiles(dir: string): string[] {
  const out: string[] = [];
  const walk = (abs: string): void => {
    for (const name of readdirSync(abs).sort()) {
      const child = join(abs, name);
      const st = lstatSync(child);
      if (st.isSymbolicLink()) continue;
      if (st.isDirectory()) {
        if (!IGNORED_DIRS.has(name)) walk(child);
      } else if (st.isFile() && name.endsWith(".ts") && !name.endsWith(".d.ts")) {
        out.push(child);
      }
    }
  };
  walk(dir);
  return out;
}

function stringValue(node: Node | undefined): string | undefined {
  if (!node) return undefined;
  if (Node.isStringLiteral(node) || Node.isNoSubstitutionTemplateLiteral(node)) {
    return node.getLiteralValue();
  }
  return undefined;
}

function propertyName(prop: Node): string | undefined {
  if (!Node.isPropertyAssignment(prop)) return undefined;
  const nameNode = prop.getNameNode();
  if (Node.isIdentifier(nameNode)) return nameNode.getText();
  if (Node.isStringLiteral(nameNode) || Node.isNoSubstitutionTemplateLiteral(nameNode)) {
    return nameNode.getLiteralValue();
  }
  return undefined;
}

function unwrapAsConst(node: Node | undefined): Node | undefined {
  let cur = node;
  while (cur && (Node.isAsExpression(cur) || Node.isParenthesizedExpression(cur) || Node.isSatisfiesExpression(cur))) {
    cur = cur.getExpression();
  }
  return cur;
}

interface LocatorFile {
  file: string;
  exports: Map<string, Map<string, LocatorSymbol>>;
}

function parseLocatorFile(sf: SourceFile, rel: string, errors: ExtractError[]): LocatorFile {
  const exports = new Map<string, Map<string, LocatorSymbol>>();
  for (const stmt of sf.getVariableStatements()) {
    if (!stmt.isExported()) continue;
    for (const decl of stmt.getDeclarations()) {
      const exportName = decl.getName();
      const init = unwrapAsConst(decl.getInitializer());
      if (!init || !Node.isObjectLiteralExpression(init)) {
        errors.push({ file: rel, line: decl.getStartLineNumber(), message: `'${exportName}' nesne literal'i değil` });
        continue;
      }
      const entries = new Map<string, LocatorSymbol>();
      walkLocatorObject(init, [], rel, entries, errors, exportName);
      exports.set(exportName, entries);
    }
  }
  return { file: rel, exports };
}

function walkLocatorObject(
  obj: ObjectLiteralExpression,
  path: string[],
  rel: string,
  entries: Map<string, LocatorSymbol>,
  errors: ExtractError[],
  exportName: string,
): void {
  const props = obj.getProperties();
  const isEntry = props.some((p) => propertyName(p) === "testId");
  if (isEntry) {
    const fields: Record<string, string> = {};
    for (const p of props) {
      const key = propertyName(p);
      const value = Node.isPropertyAssignment(p) ? stringValue(p.getInitializer()) : undefined;
      if (key === undefined || value === undefined) {
        errors.push({
          file: rel,
          line: p.getStartLineNumber(),
          message: `${[exportName, ...path].join(".")}: giriş alanları yalnızca string literal olabilir`,
        });
        return;
      }
      fields[key] = value;
    }
    const testId = fields["testId"] ?? "";
    const entry: LocatorSymbol = {
      testId,
      role: fields["role"] ?? "",
      name: fields["name"] ?? "",
      intent: fields["intent"] ?? "",
      prefix: testId.endsWith("-"),
      file: rel,
      line: obj.getStartLineNumber(),
    };
    if (fields["within"] !== undefined) entry.within = fields["within"];
    entries.set(path.join("."), entry);
    return;
  }
  for (const p of props) {
    const key = propertyName(p);
    const value = Node.isPropertyAssignment(p) ? unwrapAsConst(p.getInitializer()) : undefined;
    if (key === undefined || !value || !Node.isObjectLiteralExpression(value)) {
      errors.push({
        file: rel,
        line: p.getStartLineNumber(),
        message: `${[exportName, ...path].join(".")}: beklenmeyen öğe (yalnızca iç içe nesne veya giriş)`,
      });
      continue;
    }
    walkLocatorObject(value, [...path, key], rel, entries, errors, exportName);
  }
}

function docOf(node: { getJsDocs(): { getDescription(): string }[] }): string {
  return node
    .getJsDocs()
    .map((d) => d.getDescription().trim())
    .filter((d) => d !== "")
    .join("\n");
}

function methodSymbol(m: MethodDeclaration): MethodSymbol {
  const params: ParamSymbol[] = m.getParameters().map((p) => {
    const out: ParamSymbol = {
      name: p.getName(),
      type: p.getTypeNode()?.getText() ?? p.getType().getText(p, ts.TypeFormatFlags.NoTruncation),
      optional: p.isOptional(),
    };
    const init = p.getInitializer();
    if (init) out.default = init.getText();
    return out;
  });
  const name = m.getName();
  return {
    name,
    params,
    returns: m.getReturnTypeNode()?.getText() ?? m.getReturnType().getText(m, ts.TypeFormatFlags.NoTruncation),
    kind: EXPECT_NAME.test(name) ? "expect" : "action",
    async: m.isAsync(),
    doc: docOf(m),
    line: m.getStartLineNumber(),
  };
}

function isPublicMethod(m: MethodDeclaration): boolean {
  if (m.getScope() !== Scope.Public) return false;
  if (m.isStatic()) return false;
  const nameNode = m.getNameNode();
  if (Node.isPrivateIdentifier(nameNode) || Node.isComputedPropertyName(nameNode)) return false;
  return !m.getName().startsWith("_");
}

/** Sınıf dosyasının içe aktardığı locator export'ları: [yerel ad → (locator dosyası, export adı)]. */
function importedLocatorExports(
  sf: SourceFile,
  absFile: string,
  locatorFilesByAbs: Map<string, LocatorFile>,
): { file: LocatorFile; exportName: string }[] {
  const out: { file: LocatorFile; exportName: string }[] = [];
  for (const imp of sf.getImportDeclarations()) {
    const spec = imp.getModuleSpecifierValue();
    if (!spec.startsWith(".")) continue;
    const target = resolve(dirname(absFile), spec.replace(/\.(js|ts)$/, "") + ".ts");
    const lf = locatorFilesByAbs.get(target);
    if (!lf) continue;
    for (const named of imp.getNamedImports()) {
      out.push({ file: lf, exportName: named.getName() });
    }
  }
  return out;
}

export function extractSymbols(e2eRoot: string, pagesDir = "pages"): SymbolTable {
  const root = resolve(e2eRoot);
  const pagesAbs = resolve(root, pagesDir);
  if (!pagesAbs.startsWith(root + sep) && pagesAbs !== root) {
    throw new Error(`pages dizini kök dışında: ${pagesDir}`);
  }
  let files: string[];
  try {
    files = listTsFiles(pagesAbs);
  } catch (err) {
    throw new Error(`pages dizini okunamadı: ${pagesDir} (${(err as Error).message})`);
  }
  const project = new Project({
    skipAddingFilesFromTsConfig: true,
    skipFileDependencyResolution: true,
    compilerOptions: { target: ts.ScriptTarget.ES2022, strict: true, noEmit: true, skipLibCheck: true },
  });
  const errors: ExtractError[] = [];
  const rel = (abs: string): string => toPosix(relative(root, abs));

  const sources = files.map((f) => ({ abs: f, sf: project.addSourceFileAtPath(f) }));
  const program = project.getProgram();
  for (const { abs, sf } of sources) {
    // Yalnızca sözdizimi hataları (tür denetimi burada yapılmaz; tsc /check'te koşar).
    for (const d of program.getSyntacticDiagnostics(sf)) {
      const err: ExtractError = {
        file: rel(abs),
        message: `sözdizimi: ${ts.flattenDiagnosticMessageText(d.compilerObject.messageText, "\n")}`,
      };
      const line = d.getLineNumber();
      if (line !== undefined) err.line = line;
      errors.push(err);
    }
  }

  const locatorFilesByAbs = new Map<string, LocatorFile>();
  for (const { abs, sf } of sources) {
    if (abs.endsWith(sep + LOCATOR_FILE)) locatorFilesByAbs.set(abs, parseLocatorFile(sf, rel(abs), errors));
  }

  const pageObjects: PageObjectSymbol[] = [];
  for (const { abs, sf } of sources) {
    if (locatorFilesByAbs.has(abs)) continue;
    const classes: ClassDeclaration[] = sf.getClasses().filter((c) => c.isExported() && c.getName());
    if (classes.length === 0) continue;
    const locators: Record<string, LocatorSymbol> = {};
    for (const { file, exportName } of importedLocatorExports(sf, abs, locatorFilesByAbs)) {
      const entries = file.exports.get(exportName);
      if (!entries) {
        errors.push({ file: rel(abs), message: `${file.file} içinde '${exportName}' export'u yok` });
        continue;
      }
      for (const [key, entry] of entries) locators[`${exportName}.${key}`] = entry;
    }
    for (const cls of classes) {
      pageObjects.push({
        class: cls.getName() ?? "",
        file: rel(abs),
        doc: docOf(cls),
        methods: cls.getMethods().filter(isPublicMethod).map(methodSymbol),
        locators,
      });
    }
  }

  const locatorFiles = [...locatorFilesByAbs.values()]
    .map((lf) => ({ file: lf.file, exports: [...lf.exports.keys()] }))
    .sort((a, b) => a.file.localeCompare(b.file));
  pageObjects.sort((a, b) => a.file.localeCompare(b.file) || a.class.localeCompare(b.class));
  return {
    schema_version: SCHEMA_VERSION,
    root: toPosix(pagesDir),
    page_objects: pageObjects,
    locator_files: locatorFiles,
    errors,
  };
}
