// locators.ts "saf veri" ayrıştırıcısı.
//
// İzin verilen tek biçim (TEKNIK-TASARIM §8.7):
//   export const cart = {
//     addToCart: { testId: "add-to-cart", role: "button", name: "Sepete ekle", intent: "..." },
//   } as const;
//
// Kurallar: yalnızca `export const <ad> = { ... } as const;` deyimleri (yorumlar serbest);
// nesne değerleri yalnızca iç içe nesne veya string literal; hesaplanan anahtar, spread,
// shorthand, metot, şablon ifadesi, çağrı, tanımlayıcı başvurusu vb. yasak. `testId` taşıyan
// nesne bir "giriş"tir ve tüm alanları string olmalıdır.
import { Node, Project, SyntaxKind, ts, type ObjectLiteralExpression } from "ts-morph";

export interface Violation {
  code: string;
  file: string;
  message: string;
  line?: number;
  entry?: string;
  field?: string;
  before?: string;
  after?: string;
}

export interface LocatorEntry {
  /** `export.key[.key...]` */
  id: string;
  fields: Record<string, string>;
  /** testId string literal düğümünün kaynak metindeki konumu ve ham metni */
  testIdSpan: { start: number; end: number; text: string } | undefined;
  line: number;
}

export interface ParsedLocators {
  file: string;
  exports: string[];
  entries: Map<string, LocatorEntry>;
  violations: Violation[];
}

/** testId değeri: harf/rakamla başlar; harf, rakam, `-`, `_`, `.`, `:` içerir. */
export const TESTID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/;

const project = new Project({
  useInMemoryFileSystem: true,
  compilerOptions: { target: ts.ScriptTarget.ES2022, noLib: true },
});
let counter = 0;

function kindName(node: Node): string {
  return node.getKindName();
}

export function parseLocators(file: string, text: string): ParsedLocators {
  const result: ParsedLocators = { file, exports: [], entries: new Map(), violations: [] };
  const v = (code: string, message: string, node?: Node, extra: Partial<Violation> = {}): void => {
    const viol: Violation = { code, file, message, ...extra };
    if (node) viol.line = node.getStartLineNumber();
    result.violations.push(viol);
  };

  const sf = project.createSourceFile(`/guard_${counter++}.ts`, text, { overwrite: true });
  try {
    // Yalnızca sözdizimi hataları; anlamsal denetim (tip) bu aracın işi değil (tsc --strict ayrı koşar).
    const parseDiags = (sf.compilerNode as unknown as { parseDiagnostics?: ts.Diagnostic[] }).parseDiagnostics ?? [];
    if (parseDiags.length > 0) {
      for (const d of parseDiags) {
        v("parse_error", `Sözdizimi hatası: ${ts.flattenDiagnosticMessageText(d.messageText, "\n")}`);
      }
      return result;
    }

    for (const stmt of sf.getStatements()) {
      if (!Node.isVariableStatement(stmt)) {
        v("forbidden_statement", `Yalnızca 'export const x = {...} as const' izinli; bulundu: ${kindName(stmt)}`, stmt);
        continue;
      }
      if (!stmt.isExported() || stmt.isDefaultExport()) {
        v("forbidden_statement", "Değişken bildirimi 'export const' olmalı", stmt);
        continue;
      }
      if (stmt.getModifiers().some((m) => m.getKind() === SyntaxKind.DeclareKeyword)) {
        v("forbidden_statement", "'declare' kullanılamaz", stmt);
        continue;
      }
      if (stmt.getDeclarationKind() !== "const") {
        v("forbidden_statement", "Bildirim 'const' olmalı", stmt);
        continue;
      }
      const decls = stmt.getDeclarations();
      if (decls.length !== 1) {
        v("forbidden_statement", "Her deyimde tek bildirim olmalı", stmt);
        continue;
      }
      const decl = decls[0]!;
      const nameNode = decl.getNameNode();
      if (!Node.isIdentifier(nameNode)) {
        v("forbidden_statement", "Yapı bozma (destructuring) kullanılamaz", decl);
        continue;
      }
      if (decl.getTypeNode()) {
        v("forbidden_statement", "Tip ek açıklaması kullanılamaz", decl);
        continue;
      }
      const exportName = nameNode.getText();
      if (result.exports.includes(exportName)) {
        v("duplicate_key", `Yinelenen export: ${exportName}`, decl);
        continue;
      }
      result.exports.push(exportName);
      const init = decl.getInitializer();
      if (!init || !Node.isAsExpression(init) || init.getTypeNode()?.getText() !== "const") {
        v("missing_as_const", `'${exportName}' değeri '{...} as const' olmalı`, decl);
        continue;
      }
      const expr = init.getExpression();
      if (!Node.isObjectLiteralExpression(expr)) {
        v("non_literal_value", `'${exportName}' değeri nesne literal olmalı; bulundu: ${kindName(expr)}`, expr);
        continue;
      }
      walkObject(expr, exportName);
    }
  } finally {
    project.removeSourceFile(sf);
  }
  return result;

  function walkObject(obj: ObjectLiteralExpression, path: string): void {
    const seen = new Set<string>();
    const strings: Record<string, string> = {};
    let testIdSpan: LocatorEntry["testIdSpan"];
    let hasObject = false;
    let hasString = false;
    const children: Array<[string, ObjectLiteralExpression]> = [];
    const badKeys = new Set<string>();

    for (const prop of obj.getProperties()) {
      if (Node.isSpreadAssignment(prop)) {
        v("spread", `${path}: spread (...) kullanılamaz`, prop, { entry: path });
        continue;
      }
      if (Node.isShorthandPropertyAssignment(prop)) {
        v("shorthand_property", `${path}: kısa yazım özellik (${prop.getName()}) kullanılamaz`, prop, { entry: path });
        continue;
      }
      if (!Node.isPropertyAssignment(prop)) {
        v("method", `${path}: metot/getter/setter kullanılamaz`, prop, { entry: path });
        continue;
      }
      const nameNode = prop.getNameNode();
      let key: string;
      if (Node.isIdentifier(nameNode)) key = nameNode.getText();
      else if (Node.isStringLiteral(nameNode) || Node.isNoSubstitutionTemplateLiteral(nameNode))
        key = nameNode.getLiteralText();
      else {
        v("computed_key", `${path}: hesaplanan veya literal olmayan anahtar kullanılamaz (${nameNode.getText()})`, prop, {
          entry: path,
        });
        continue;
      }
      if (seen.has(key)) {
        v("duplicate_key", `${path}: yinelenen anahtar '${key}'`, prop, { entry: path });
        continue;
      }
      seen.add(key);
      const init = prop.getInitializerOrThrow();
      if (Node.isStringLiteral(init) || Node.isNoSubstitutionTemplateLiteral(init)) {
        hasString = true;
        strings[key] = init.getLiteralText();
        if (key === "testId") testIdSpan = { start: init.getStart(), end: init.getEnd(), text: init.getText() };
      } else if (Node.isObjectLiteralExpression(init)) {
        hasObject = true;
        children.push([key, init]);
      } else {
        badKeys.add(key);
        v(
          "non_literal_value",
          `${path}.${key}: değer yalnızca string literal veya nesne olabilir; bulundu: ${kindName(init)} (${truncate(init.getText())})`,
          init,
          { entry: path, field: key },
        );
      }
    }

    if (hasString && hasObject) {
      v("mixed_object", `${path}: bir nesne hem giriş alanları hem alt nesneler içeremez`, obj, { entry: path });
      return;
    }
    if (badKeys.has("testId")) return; // testId zaten ihlal olarak raporlandı
    if (hasString) {
      if (!("testId" in strings)) {
        v("entry_missing_testid", `${path}: giriş 'testId' alanı içermeli`, obj, { entry: path });
        return;
      }
      const testId = strings["testId"] ?? "";
      if (!TESTID_PATTERN.test(testId)) {
        v("invalid_testid", `${path}: geçersiz testId değeri '${testId}'`, obj, { entry: path, field: "testId", after: testId });
      }
      result.entries.set(path, { id: path, fields: strings, testIdSpan, line: obj.getStartLineNumber() });
      return;
    }
    for (const [key, child] of children) walkObject(child, `${path}.${key}`);
  }
}

function truncate(s: string, n = 60): string {
  const one = s.replace(/\s+/g, " ");
  return one.length > n ? `${one.slice(0, n)}…` : one;
}
