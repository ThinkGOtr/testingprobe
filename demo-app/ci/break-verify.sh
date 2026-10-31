#!/usr/bin/env bash
# "Kırarak doğrula" (yeşil → kırmızı → yeşil) — kampanya testlerinin kuralı gerçekten yakaladığını
# kanıtlar. AI yok; test-runner ve yerel geliştirici aynı betiği kullanır.
#   1) normal koşu           → kampanya testleri geçmeli
#   2) BREAK_CAMPAIGN=1 koşu → yalnızca kampanya hesabına bağlı testler, ASSERTION ile kalmalı
#                              (fixture/kurulum hatası kırmızı sayılmaz); kampanyasız testler geçmeli
#   3) normal koşu           → yine geçmeli (kırılma geri alındı, kalıcı iz yok)
# Kırılma bayi kapsamlıdır (POST /test/break) ve yalnızca test süresince açıktır; paylaşılan
# uygulama örneği bozulmaz. Kırmızı adım tek işçiyle koşar: yalnızca bayi1 (ve test.use ile
# başka bir e2e bayisine sabitlenmiş testlerin bayisi, yalnızca o test süresince) etkilenir;
# doğrulama ajanının bayisi (bayi3) hiçbir zaman.
# Ortam: BASE_URL + DEMO_API_URL + DEMOAPP_TEST_TOKEN (çalışan ortam) ya da hiçbiri (webServer).
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root/e2e"
grep_expr="${BREAK_VERIFY_GREP:-kampanya}"
results="results/results.json"

run() {  # $1 = BREAK_CAMPAIGN değeri; çıkış kodunu döndürür
  local rc=0
  BREAK_CAMPAIGN="$1" npx --no-install playwright test --project=chromium --retries=0 \
    --grep "$grep_expr" "${@:2}" || rc=$?
  return "$rc"
}

step() { printf '\n==> %s\n' "$*"; }

step "1/3 normal (yeşil beklenir)"
run "" || { echo "HATA: kırılma olmadan kampanya testleri kırmızı" >&2; exit 1; }

step "2/3 BREAK_CAMPAIGN=1 (kırmızı beklenir)"
# Tek işçi → yalnızca bayi1 kırılır (sabitlenmiş testler hariç); bayi3 (MCP doğrulaması) hiç etkilenmez.
if run 1 --workers=1; then
  echo "HATA: kampanya kuralı bozukken testler yeşil — testler kuralı yakalamıyor" >&2
  exit 1
fi
node --input-type=module - "$results" <<'JS'
import { readFileSync } from "node:fs";
const report = JSON.parse(readFileSync(process.argv[2], "utf8"));
const rows = [];
const walk = (s) => {
  for (const sp of s.specs ?? [])
    for (const t of sp.tests)
      for (const r of t.results) rows.push({ title: sp.title, status: r.status, msg: r.error?.message ?? "" });
  (s.suites ?? []).forEach(walk);
};
report.suites.forEach(walk);
const failed = rows.filter((r) => r.status !== "passed");
const strip = (m) => m.replace(/\u001b\[[0-9;]*m/g, "");
const bad = failed.filter((r) => !/expect\(.*\)\..*failed/.test(strip(r.msg)) || /\/test\/|giriş başarısız/.test(strip(r.msg)));
const passed = rows.filter((r) => r.status === "passed").map((r) => r.title);
console.log(`kırmızı: ${failed.map((r) => r.title).join(" | ")}`);
console.log(`yeşil kalan: ${passed.join(" | ")}`);
if (failed.length === 0 || bad.length > 0) {
  console.error(`HATA: kırmızı sonuç doğrulama (assertion) hatası değil: ${JSON.stringify(bad.map((r) => r.title))}`);
  process.exit(1);
}
JS

step "3/3 normal (yine yeşil beklenir)"
run "" || { echo "HATA: kırılma geri alındıktan sonra kampanya testleri kırmızı" >&2; exit 1; }

printf '\nKırarak doğrulama: yeşil → kırmızı → yeşil ✓\n'
