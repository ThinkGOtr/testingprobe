#!/usr/bin/env bash
# make e2e-smoke — demo-app e2e testlerini test-runner konteynerinin İÇİNDEN, compose'daki demo
# uygulamasına karşı koşturur (test-runner'ın gerçek yolu: demo-net, BASE_URL=demo-app-web,
# bayi kapsamlı sıfırlama DEMO_API_URL + DEMOAPP_TEST_TOKEN ile). AI yok.
#
#   scripts/e2e-smoke.sh            # forge main'deki e2e kodu, tüm testler
#   scripts/e2e-smoke.sh --grep X   # ek argümanlar `playwright test`'e geçer
#   E2E_REF=demo-baseline scripts/e2e-smoke.sh
#   E2E_BREAK_VERIFY=1 scripts/e2e-smoke.sh   # ayrıca kampanya kırılması: yeşil → kırmızı → yeşil
#
# Kod forge'dan (git archive) alınır; çalışma ağacı değil. Bağımlılıklar toolchain imajındadır
# (/opt/toolchain/node_modules: @playwright/test, @axe-core/playwright, allure-playwright); ağ yok.
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"

REF="${E2E_REF:-main}"
svc_running test-runner || die "test-runner çalışmıyor (make up)"

# shellcheck disable=SC2016  # $… konteyner içindeki kabukta açılır
# tp-run-lock: test-runner /run ile aynı süreçler arası kilit; smoke koşusu boyunca /run sırada bekler.
compose exec -T -e E2E_REF="$REF" -e E2E_BREAK_VERIFY="${E2E_BREAK_VERIFY:-0}" test-runner \
  /opt/toolchain/bin/tp-run-lock --wait 600 -- bash -euo pipefail -c '
  W="$(mktemp -d /tmp/tp-e2e-smoke.XXXXXX)"
  trap "rm -rf \"$W\"" EXIT
  git -c safe.directory="*" --git-dir="$TP_FORGE_PATH" archive "$E2E_REF" e2e | tar -C "$W" -xf -
  cd "$W/e2e"
  ln -s /opt/toolchain/node_modules node_modules
  echo "==> forge $E2E_REF @ $(git -c safe.directory="*" --git-dir="$TP_FORGE_PATH" rev-parse --short "$E2E_REF") → $BASE_URL"
  npx --no-install playwright test --reporter=list "$@"
  if [ "$E2E_BREAK_VERIFY" = 1 ]; then
    echo "==> kırılma (BREAK_CAMPAIGN=1, yalnızca koşunun bayisi): kırmızı beklenir"
    if BREAK_CAMPAIGN=1 npx --no-install playwright test tests/cart.spec.ts tests/order.spec.ts \
         --workers=1 --reporter=list >"$W/break.log" 2>&1; then
      cat "$W/break.log"; echo "HATA: kırık kampanyada testler yeşil (test kuralı yakalamıyor)" >&2; exit 1
    fi
    grep -E "failed|passed" "$W/break.log" | tail -n 2
    echo "==> kırılma kapalı: yeşil beklenir"
    npx --no-install playwright test tests/cart.spec.ts tests/order.spec.ts --reporter=line
    echo "Kırarak doğrulama (test-runner): yeşil → kırmızı → yeşil ✓"
  fi
' _ "$@"
