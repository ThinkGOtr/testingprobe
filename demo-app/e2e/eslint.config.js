// ESLint düz yapılandırması. Komut satırında --no-inline-config ile koşar (yorumla kural kapatılamaz).
import js from "@eslint/js";
import playwright from "eslint-plugin-playwright";
import tseslint from "typescript-eslint";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

// Üretilen testlerin (tests/generated/**) sözleşmesi — İZİN LİSTESİ (aşağıda kullanılır).
// Bu dosyada kalmalı: toolchain-worker eslint.config.js'i güvenilir kopyasıyla (toolchain/e2e-deps)
// hash ile karşılaştırır; sözleşme ayrı bir modülden içe aktarılsaydı PR o modülü değiştirerek
// kuralları devre dışı bırakabilirdi.
//
// Dosyanın taşıyabileceği tek biçim (core codegen şablonu `playwright_test.ts.j2` ile aynı):
//   import { test } | { signedInTest as test } from "../fixtures";
//   test.use({ dealerUsername: "bayi1" });                       // isteğe bağlı
//   test.describe("…", () => {
//     test("…", { tag: ["…"] }, async ({ cartPage, catalogPage }) => {   // seçenek nesnesi isteğe bağlı
//       await catalogPage.addToCart("P-001", 7);                 // adım başına bir çağrı
//       await loginPage.login("bayi1", process.env.TP_TESTVERI_DEMO_PAROLA);  // gizli test verisi (K19)
//     });
//   });
// Fikstür adları ve izinli metotlar page object kaynaklarından (pages/**/*.page.ts) okunur:
// `export class CartPage` → fikstür `cartPage`; sınıf gövdesindeki `async <ad>(` (private/protected
// olmayan) → izinli metot. Her seçici bir İHLALİ tanımlar (no-restricted-syntax).
// Tek literal dışı argüman istisnası (K19, 013 ANALIZ §9): gizli test verisi ortamdan okunur —
// argüman TAM OLARAK `process.env.TP_TESTVERI_<AD>` (AD: [A-Z0-9_]{1,64}; hesaplanmamış, `?.` yok)
// olabilir ve yalnızca `<fikstür>.<metot>(…)` çağrısının DOĞRUDAN argümanı olarak. Dizi içinde,
// test.use'da, `??`/`!`/`.trim()` ile ya da başka yerde `process` kullanımı reddedilir. Tip:
// tests/testveri-env.d.ts (yeni ad oraya eklenir); runner yalnızca TP_TESTVERI_* ortamını geçirir.
function pageSources(dir = join(import.meta.dirname, "pages")) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = join(dir, e.name);
    if (e.isDirectory()) return pageSources(p);
    return e.name.endsWith(".page.ts") ? [readFileSync(p, "utf8")] : [];
  });
}

/** Page object sınıflarından fikstür adlarını ve herkese açık async metotları çıkarır. */
function pageObjectApi(sources = pageSources()) {
  const fixtures = new Set();
  const methods = new Set();
  for (const src of sources) {
    for (const m of src.matchAll(/^export class ([A-Z][A-Za-z0-9]*)/gm)) {
      fixtures.add(m[1].charAt(0).toLowerCase() + m[1].slice(1));
    }
    for (const m of src.matchAll(/^ {2}async ([a-z][A-Za-z0-9]*)\(/gm)) methods.add(m[1]);
  }
  methods.delete("constructor");
  if (!fixtures.size || !methods.size) throw new Error("page object API okunamadı (pages/**/*.page.ts)");
  return { fixtures: [...fixtures].sort(), methods: [...methods].sort() };
}

const alt = (names) => `/^(${names.join("|")})$/`;

function generatedTestSyntax(api = pageObjectApi()) {
  const FX = alt(api.fixtures);
  const METHOD = alt(api.methods);
  const TEST = "/^(test|signedInTest)$/";
  const ALLOWED_IDS = alt(["test", "signedInTest", "describe", "use", "dealerUsername", "tag", ...api.fixtures, ...api.methods]);
  const fx = "Üretilen test yalnızca page object fikstür metotlarını literal argümanlarla çağırır.";
  // `process.env.TP_TESTVERI_<AD>` biçimi ve onun fikstür çağrısının doğrudan argümanı olarak konumu.
  const PENV =
    "MemberExpression[computed=false][optional=false][property.type='Identifier'][property.name=/^TP_TESTVERI_[A-Z0-9_]{1,64}$/]" +
    "[object.type='MemberExpression'][object.computed=false][object.optional=false]" +
    "[object.object.type='Identifier'][object.object.name='process'][object.property.type='Identifier'][object.property.name='env']";
  const SECRET = `CallExpression[callee.object.name=${FX}] > ${PENV}.arguments`;
  const SECRET_ENV = `${SECRET} > MemberExpression.object`; // iç `process.env`
  return [
    // --- içe aktarma -------------------------------------------------------------------------
    {
      selector: "ImportSpecifier[imported.name!=/^(test|signedInTest)$/], ImportSpecifier[local.name!='test']",
      message: "Üretilen test '../fixtures'tan yalnızca test ya da `signedInTest as test` alır.",
    },
    {
      selector: "ImportDefaultSpecifier, ImportNamespaceSpecifier, ImportExpression, ExportNamedDeclaration, ExportDefaultDeclaration, ExportAllDeclaration",
      message: "Üretilen testte bu içe/dışa aktarma biçimi yasak.",
    },
    // --- tanımlayıcı izin listesi -------------------------------------------------------------
    {
      selector: `Identifier:not([name=${ALLOWED_IDS}]):not(${SECRET} > Identifier.property, ${SECRET_ENV} > Identifier)`,
      message: "Üretilen test ham Playwright/Node nesnelerine erişemez (page, globalThis, fetch…); yalnızca test ve page object fikstürleri.",
    },
    { selector: "MemberExpression[computed=true], Property[computed=true], MethodDefinition, SpreadElement, RestElement, AssignmentPattern, ArrayPattern", message: fx },
    { selector: "ThisExpression, Super, MetaProperty, TaggedTemplateExpression, ChainExpression, SequenceExpression", message: fx },
    // --- üye erişimi: yalnızca test.describe / test.use ve <fikstür>.<metot>(…) çağrısı ---------
    {
      selector: `MemberExpression:not([object.name=${TEST}][property.name=/^(describe|use)$/]):not([object.name=${FX}][property.name=${METHOD}]):not(${SECRET}, ${SECRET_ENV})`,
      message: "Üretilen testte yalnızca test.describe, test.use ve <fikstür>.<page object metodu> kullanılabilir.",
    },
    {
      selector: `:not(CallExpression) > MemberExpression:not(${SECRET_ENV}), CallExpression > MemberExpression.arguments:not(${SECRET})`,
      message: fx,
    },
    // --- çağrılar --------------------------------------------------------------------------------
    { selector: `CallExpression:not([callee.type='MemberExpression']):not([callee.name=${TEST}])`, message: fx },
    { selector: "NewExpression, ImportExpression", message: fx },
    {
      selector: `CallExpression[callee.object.name=${FX}] > .arguments:not(Literal, ArrayExpression, UnaryExpression[operator='-'][argument.type='Literal'], ${PENV})`,
      message: fx,
    },
    { selector: "ArrayExpression > .elements:not(Literal, UnaryExpression[operator='-'][argument.type='Literal'])", message: fx },
    // Fikstür çağrısı beklenmeli ve tek başına deyim olmalı.
    { selector: `:not(AwaitExpression) > CallExpression[callee.object.name=${FX}]`, message: "Page object çağrısı `await` ile tek deyim olmalı." },
    { selector: `:not(ExpressionStatement) > AwaitExpression, AwaitExpression > :not(CallExpression[callee.object.name=${FX}]).argument`, message: fx },
    // --- deyim biçimi ----------------------------------------------------------------------------
    { selector: "Program > :not(ImportDeclaration, ExpressionStatement)", message: "Üretilen testin üst düzeyinde yalnızca import, test.use ve test.describe/test bulunur." },
    { selector: `Program > ExpressionStatement > :not(CallExpression[callee.name=${TEST}], CallExpression[callee.object.name=${TEST}]).expression`, message: fx },
    { selector: "BlockStatement > :not(ExpressionStatement)", message: "Üretilen test doğrusal olmalı (şablon: adım başına bir page object çağrısı)." },
    { selector: "ExpressionStatement > :not(AwaitExpression, CallExpression).expression", message: fx },
    // İşlevler yalnızca test / test.describe gövdesi olarak, ok işleviyle.
    { selector: "FunctionExpression, FunctionDeclaration, ClassDeclaration, ClassExpression", message: fx },
    {
      selector: `ArrowFunctionExpression:not(CallExpression[callee.name=${TEST}] > .arguments, CallExpression[callee.object.name=${TEST}][callee.property.name='describe'] > .arguments)`,
      message: fx,
    },
    { selector: "ArrowFunctionExpression > :not(BlockStatement).body, ArrowFunctionExpression > :not(ObjectPattern).params", message: fx },
    { selector: `ObjectPattern > Property > :not(Identifier[name=${FX}]).value`, message: "Test gövdesi yalnızca page object fikstürlerini alır." },
    // Nesneler yalnızca test.use({ dealerUsername }) ve test seçenekleri ({ tag: [...] }).
    {
      selector: "CallExpression[callee.property.name='use'] Property[key.name!='dealerUsername']",
      message: "Üretilen testte test.use yalnızca dealerUsername alır.",
    },
    { selector: "ObjectExpression > Property > :not(Literal, ArrayExpression).value", message: fx },
    {
      selector: "IfStatement, ConditionalExpression, LogicalExpression, BinaryExpression, AssignmentExpression, UpdateExpression, SwitchStatement, ForStatement, ForInStatement, ForOfStatement, WhileStatement, DoWhileStatement, TryStatement, ThrowStatement, ReturnStatement, TemplateLiteral, YieldExpression",
      message: "Üretilen test doğrusal olmalı (şablon: adım başına bir page object çağrısı).",
    },
    { selector: "TSAsExpression, TSNonNullExpression, TSTypeAssertion, TSSatisfiesExpression, TSAnyKeyword, TSTypeReference", message: fx },
  ];
}

export default tseslint.config(
  { ignores: ["node_modules/", "results/", "playwright-report/", "test-results/"] },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  {
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    rules: {
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/await-thenable": "error",
      "@typescript-eslint/restrict-template-expressions": ["error", { allowNumber: true }],
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },
  {
    ...playwright.configs["flat/recommended"],
    files: ["tests/**/*.ts", "pages/**/*.ts"],
    rules: {
      ...playwright.configs["flat/recommended"].rules,
      // Doğrulamalar page object'lerin expect* metotlarındadır.
      "playwright/expect-expect": ["error", { assertFunctionPatterns: ["^expect", "^audit$"] }],
      "playwright/no-skipped-test": "error",
      "playwright/no-focused-test": "error",
      "playwright/no-wait-for-timeout": "error",
      "playwright/no-force-option": "error",
      "playwright/no-page-pause": "error",
      "playwright/no-networkidle": "error",
      "playwright/no-standalone-expect": "off",
    },
  },
  {
    // Kod üretiminin şablonla yazdığı testler (README "Üretilen testler için sözleşme"). Kurallar
    // İZİN LİSTESİDİR (yasak listesi değil): dosya yalnızca şu biçimi taşıyabilir —
    //   import { test | signedInTest [as test] } from "../fixtures";
    //   test.use({ dealerUsername: "<literal>" });
    //   test.describe("<literal>", () => { test("<literal>", [{ tag: [<literal>…] },] async ({ <fikstür>… }) => {
    //     await <fikstür>.<page object metodu>(<literal | literal dizisi | process.env.TP_TESTVERI_<AD>>…);   // adım başına
    //   }); });
    // Fikstür ve metot adları pages/**/*.page.ts'ten okunur. Başka her tanımlayıcı (page, globalThis,
    // fetch…), hesaplanmış üye erişimi (x["page"]), zincirli üye (a.b.c) ve literal olmayan argüman
    // reddedilir; tek istisna fikstür çağrısının doğrudan argümanı olarak `process.env.TP_TESTVERI_<AD>`
    // (K19). AI'sız CI kapısı; şablon birincil denetimdir, bu kural elle düzenlemeye karşıdır.
    files: ["tests/generated/**/*.ts"],
    rules: {
      "no-restricted-imports": [
        "error",
        { patterns: [{ regex: "^(?!\\.\\./fixtures$)", message: "Üretilen test yalnızca '../fixtures'tan içe aktarır." }] },
      ],
      "no-restricted-syntax": ["error", ...generatedTestSyntax()],
    },
  },
  {
    files: ["**/*.js"],
    ...tseslint.configs.disableTypeChecked,
  },
);
