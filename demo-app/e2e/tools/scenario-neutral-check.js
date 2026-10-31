// El yazımı testlerin demo senaryosundan bağımsız olduğunu denetler (npm run check:scenario-neutral).
//
// Kampanyanın 6. adetteki davranışı demo senaryosuna bağlıdır (DEMO-VERISI, Demo-B): ana yolda
// (F2 `fix_doc`) "6 adet → 1 bedava" doğrudur; `f2-kod-hatasi` senaryosunda "6 adet → bedava yok"
// beklenir ve bugünkü kod (adet // 6) defect adayıdır. El yazımı bir test bu aralıkta kampanya
// sonucunu doğrularsa CI bugünkü davranışı (olası hatayı) "Geçti" diye onaylar ve Kod üretimi
// sayfasındaki defect adayıyla çelişir. Bu yüzden el yazımı testlerde kampanyalı üründen, iki
// yorumun farklı sonuç verdiği adetlerle (⌊n/6⌋ ≠ ⌊n/7⌋) kampanyaya bağlı doğrulama yapılamaz.
// tests/generated/ hariçtir (onaylı case metninden üretilir; senaryoya bağlı olması doğrudur).
//
// `--selftest`: denetimin kendisini örneklerle sınar.
import console from "node:console";
import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";
import process from "node:process";
import { URL, fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const CAMPAIGN_PRODUCTS = new Set(["P-001"]);
const CAMPAIGN_DEPENDENT = /\.(expectFreeQuantity|expectDiscount|expectTotal|expectLineTotal|expectConfirmedTotal)\(/;

const ambiguous = (n) => Math.floor(n / 6) !== Math.floor(n / 7);

/** Kaynaktaki her test bloğu için senaryoya bağlı doğrulamaları döndürür. */
export function findViolations(source) {
  const starts = [...source.matchAll(/\btest\(\s*["'`]([^"'`]*)["'`]/g)];
  const out = [];
  starts.forEach((m, i) => {
    const block = source.slice(m.index, starts[i + 1]?.index ?? source.length);
    const qty = new Map();
    for (const a of block.matchAll(/\.addToCart\(\s*"([^"]+)"\s*,\s*(\d+)\s*\)/g)) {
      qty.set(a[1], (qty.get(a[1]) ?? 0) + Number(a[2]));
    }
    const bad = [...qty].filter(([code, n]) => CAMPAIGN_PRODUCTS.has(code) && ambiguous(n));
    if (bad.length && CAMPAIGN_DEPENDENT.test(block)) {
      out.push({ title: m[1], products: bad.map(([c, n]) => `${c}×${n}`).join(", ") });
    }
  });
  return out;
}

function specFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = join(dir, e.name);
    if (e.isDirectory()) return e.name === "generated" ? [] : specFiles(p);
    return e.name.endsWith(".spec.ts") ? [p] : [];
  });
}

function selftest() {
  const t = (n, assert) =>
    `test("x", async ({ catalogPage, cartPage }) => {\n  await catalogPage.addToCart("P-001", ${n});\n  await cartPage.${assert};\n});\n`;
  const cases = [
    ["6 adet + bedava doğrulaması", t(6, 'expectFreeQuantity("P-001", 1)'), 1],
    ["6 adet + toplam doğrulaması", t(6, 'expectTotal("125,00 TL")'), 1],
    ["14 adet (iki yorumda da 2)", t(14, 'expectFreeQuantity("P-001", 2)'), 0],
    ["7 adet → 1 bedava", t(7, 'expectFreeQuantity("P-001", 1)'), 0],
    ["6 adet, kampanyaya bağlı olmayan doğrulama", t(6, "expectLineQuantity(\"P-001\", 6)"), 0],
    ["kampanyasız ürün", t(6, 'expectTotal("90,00 TL")').replace("P-001", "P-002"), 0],
    ["iki ekleme toplamı 12", t(5, 'expectFreeQuantity("P-001", 2)').replace("});", '  await catalogPage.addToCart("P-001", 7);\n});'), 1],
  ];
  let failed = 0;
  for (const [name, src, want] of cases) {
    const got = findViolations(src).length;
    if (got !== want) {
      failed++;
      console.error(`HATA: '${name}' için ${want} ihlal beklenirdi, ${got} bulundu`);
    } else console.log(`ok  ${name}`);
  }
  return failed;
}

if (process.argv.includes("--selftest")) {
  if (selftest()) process.exit(1);
  console.log("Senaryo bağımsızlığı denetimi öz sınaması: tamam");
} else {
  const violations = specFiles(join(root, "tests")).flatMap((f) =>
    findViolations(readFileSync(f, "utf8")).map((v) => ({ ...v, file: relative(root, f) })),
  );
  for (const v of violations) {
    console.error(
      `HATA: ${v.file} › "${v.title}": kampanyalı üründe senaryoya bağlı adet (${v.products}) ile kampanya sonucu doğrulanıyor (⌊n/6⌋ ≠ ⌊n/7⌋).`,
    );
  }
  if (violations.length) process.exit(1);
  console.log("El yazımı testler demo senaryosundan bağımsız: tamam");
}
