#!/usr/bin/env bash
# demo-app e2e kontrolleri — GitHub CI ve yerel test-runner AYNI betiği kullanır (AI yok).
#   npm ci --ignore-scripts → tsc --strict → eslint --no-inline-config → senaryo bağımsızlığı → playwright test
# Ek argümanlar `playwright test`'e aynen geçer (ör. --retries=1 --repeat-each=3 --grep ...).
#
# BASE_URL tanımlı değilse Playwright uygulamayı webServer ile kendisi başlatır; bunun için
# web bağımlılıkları (npm ci) ve API ortamı (uv sync) da hazırlanır.
# Ortam: BREAK_CAMPAIGN (bayi kapsamlı kırılma; fixture /test/break), DEMO_API_COMMAND (uv yoksa API başlatma komutu),
#        SKIP_INSTALL=1 (bağımlılıklar hazırsa kurulum adımlarını atla; çevrimdışı runner),
#        DEMOAPP_TEST_TOKEN + DEMO_API_URL ya da TP_E2E_NO_RESET=1 (BASE_URL modu; bkz. tests/fixtures.ts).
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
step() { printf '\n==> %s\n' "$*"; }

cd "$root/e2e"

if [[ "${SKIP_INSTALL:-0}" != "1" ]]; then
  step "e2e: npm ci --ignore-scripts"
  npm ci --ignore-scripts --no-audit --no-fund
  if [[ -z "${BASE_URL:-}" ]]; then
    step "web: npm ci --ignore-scripts"
    (cd "$root/web" && npm ci --ignore-scripts --no-audit --no-fund)
    if [[ -z "${DEMO_API_COMMAND:-}" ]]; then
      step "api: uv sync --frozen --no-dev"
      (cd "$root/api" && uv sync --frozen --no-dev)
    fi
  fi
fi

step "tsc --strict"
npx --no-install tsc --noEmit

step "eslint --no-inline-config"
npx --no-install eslint --no-inline-config --max-warnings=0 .

step "el yazımı testler senaryodan bağımsız (6. adet kampanya sınırı doğrulanmaz)"
node tools/scenario-neutral-check.js

step "playwright test $*"
exec npx --no-install playwright test "$@"
