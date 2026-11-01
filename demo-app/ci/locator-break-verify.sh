#!/usr/bin/env bash
# Locator kırılmasının prova doğrulaması (AI yok): `make break`'in getirdiği değişiklik gerçekten
# locator hatası üretir mi ve yalnızca testId onarımıyla yeşile döner mi?
#   1) web kopyasında "Sepete ekle" butonunun data-testid'si add-to-cart → cart-add
#      (scripts/forge-init.sh'in demo/break-locator dalında yaptığı değişikliğin aynısı)
#   2) e2e → kırmızı beklenir; HER kırmızı test `getByTestId(... 'add-to-cart')` locator hatasıyla
#      (locator.click zaman aşımı ya da "element(s) not found") kalmalı, assertion/kurulum hatası değil
#   3) e2e kopyasında yalnızca pages/catalog/locators.ts testId'si → cart-add (onarım PR'ının aynısı)
#   4) e2e → tamamı yeşil beklenir
# Çalışma ağacına dokunmaz: web/ ve e2e/ geçici bir dizine kopyalanır (node_modules bağlanır),
# uygulama Playwright webServer ile kopyadan başlar. Ortam: run-checks.sh ile aynı
# (DEMO_API_COMMAND, DEMO_API_PORT, DEMO_WEB_PREVIEW_PORT). BASE_URL ile kullanılmaz.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -z "${BASE_URL:-}" ]] || { echo "HATA: locator-break-verify çalışan uygulamaya karşı koşmaz (BASE_URL boş olmalı)" >&2; exit 2; }
for d in "$root/web/node_modules" "$root/e2e/node_modules"; do
  [[ -d "$d" ]] || { echo "HATA: $d yok (önce npm ci)" >&2; exit 2; }
done

OLD="add-to-cart"
NEW="cart-add"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/demoapp-locator-break.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
step() { printf '\n==> %s\n' "$*"; }

copy() {  # $1 = alt dizin
  mkdir -p "$tmp/$1"
  (cd "$root/$1" && tar --exclude=./node_modules --exclude=./dist --exclude=./results -cf - .) | tar -C "$tmp/$1" -xf -
  ln -s "$root/$1/node_modules" "$tmp/$1/node_modules"
}
copy web
copy e2e
ln -s "$root/api" "$tmp/api"

step "1/4 web: data-testid $OLD → $NEW (yalnızca web/src)"
files="$(cd "$tmp/web" && grep -rlE --exclude='*.test.*' --exclude='*.spec.*' "[\"'\`]${OLD}[\"'\`]" src || true)"
[[ "$(printf '%s\n' "$files" | grep -c .)" == 1 ]] \
  || { echo "HATA: '$OLD' tam olarak bir web/src dosyasında beklenir: ${files:-yok}" >&2; exit 1; }
sed -i.bak -E "s/([\"'\`])$OLD([\"'\`])/\\1$NEW\\2/g" "$tmp/web/$files" && rm -f "$tmp/web/$files.bak"
echo "değişti: web/$files"

# $1 = beklenen: kirmizi | yesil
run_and_check() {
  local rc=0
  (cd "$tmp/e2e" && npx --no-install playwright test --project=chromium --retries=0) \
    >"$tmp/out.log" 2>&1 || rc=$?
  tail -n 3 "$tmp/out.log"
  node --input-type=module - "$tmp/e2e/results/results.json" "$1" "$OLD" <<'JS'
import { readFileSync } from "node:fs";
const [file, want, oldId] = process.argv.slice(2);
const report = JSON.parse(readFileSync(file, "utf8"));
const rows = [];
const walk = (s) => {
  for (const sp of s.specs ?? [])
    for (const t of sp.tests)
      for (const r of t.results)
        rows.push({ title: sp.title, status: r.status, msg: (r.errors ?? []).map((e) => e.message ?? "").join("\n") });
  (s.suites ?? []).forEach(walk);
};
report.suites.forEach(walk);
const strip = (m) => m.replace(/\u001b\[[0-9;]*m/g, "");
const failed = rows.filter((r) => r.status !== "passed" && r.status !== "skipped");
if (want === "yesil") {
  if (failed.length > 0) {
    console.error(`HATA: onarımdan sonra kırmızı: ${JSON.stringify(failed.map((r) => r.title))}`);
    process.exit(1);
  }
  console.log(`yeşil: ${rows.length} test`);
  process.exit(0);
}
const locatorRe = new RegExp(`getByTestId\\([^\\n]*'${oldId}'\\)`);
const isLocatorError = (m) =>
  locatorRe.test(m) && (/locator\.\w+: Timeout \d+ms exceeded/.test(m) || /element\(s\) not found/.test(m));
const bad = failed.filter((r) => !isLocatorError(strip(r.msg)));
console.log(`kırmızı (${failed.length}): ${failed.map((r) => r.title).join(" | ")}`);
if (failed.length === 0) {
  console.error("HATA: kırık testId ile testler yeşil — kırılma yakalanmıyor");
  process.exit(1);
}
if (bad.length > 0) {
  for (const r of bad) console.error(`  ✗ ${r.title}: ${strip(r.msg).split("\n")[0]}`);
  console.error(`HATA: ${bad.length} kırmızı test '${oldId}' locator hatası değil (triage bunu test bakımı sayamaz)`);
  process.exit(1);
}
JS
  if [[ "$1" == yesil && "$rc" != 0 ]]; then echo "HATA: playwright çıkış kodu $rc" >&2; exit 1; fi
}

step "2/4 e2e kırık uygulamaya karşı (kırmızı, yalnızca '$OLD' locator hatası beklenir)"
run_and_check kirmizi

step "3/4 onarım: yalnızca pages/catalog/locators.ts testId $OLD → $NEW"
loc="$tmp/e2e/pages/catalog/locators.ts"
grep -q "testId: \"$OLD\"" "$loc" || { echo "HATA: locators.ts'te testId '$OLD' yok" >&2; exit 1; }
sed -i.bak "s/testId: \"$OLD\"/testId: \"$NEW\"/" "$loc" && rm -f "$loc.bak"
diff <(sed "s/testId: \"$NEW\"/testId: \"$OLD\"/" "$loc") "$root/e2e/pages/catalog/locators.ts" >/dev/null \
  || { echo "HATA: onarım testId dışında değişiklik içeriyor" >&2; exit 1; }

step "4/4 e2e onarılmış locator'la (tamamı yeşil beklenir)"
run_and_check yesil

printf '\nLocator kırılması: kırmızı (yalnızca locator hatası) → testId onarımı → yeşil ✓\n'
