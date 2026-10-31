#!/usr/bin/env bash
# ast-guard modunu seçer (Constitution VI; .github/workflows/ci.yml "ast-guard" job'u).
#
#   repair : en sıkı kontrol — yalnızca pages/**/locators.ts içindeki testId değerleri değişebilir.
#   pr     : değişen locators.ts dosyaları saf veri kalmalı; değişen testId'ler özette listelenir.
#
# repair modu şu koşullardan BİRİ yeterliyse seçilir:
#   1. PR dalı REPAIR_BRANCH_PREFIX (varsayılan `tp/repair-`) ile başlar;
#   2. PR'da `tp-repair` etiketi vardır;
#   3. PR'ı bot açmıştır (GitHub kullanıcı türü `Bot` — GitHub App PR'ları — veya giriş adı
#      TP_BOT_LOGINS listesinde) ve dal CASE_BRANCH_PREFIX (varsayılan `tp/case-`) ile başlamaz.
#      Bot'un tek "test ekleme" yolu tp/case-* dalıdır; diğer her bot PR'ı onarım sayılır.
#      Böylece dal adı farklı bir onarım PR'ı veya etiketi kaldırılan bot PR'ı zayıf kontrole düşmez.
#
# Kontrol koşar mı (run): PR'da ve (mod repair VEYA demo-app/e2e/pages/** ya da
# demo-app/e2e/tsconfig.json değişti — ci.yml `pages` filtresi → PAGES_CHANGED) ise.
#
# Girdi (ortam): IS_PR, HEAD_REF, HAS_REPAIR_LABEL, PAGES_CHANGED, PR_AUTHOR, PR_AUTHOR_TYPE,
#                TP_BOT_LOGINS (virgülle ayrılmış, büyük/küçük harf duyarsız), REPAIR_BRANCH_PREFIX,
#                CASE_BRANCH_PREFIX.
# Çıktı: stdout'a ve (tanımlıysa) $GITHUB_OUTPUT'a `mode=`, `run=`, `reason=` satırları.
set -euo pipefail

IS_PR="${IS_PR:-false}"
HEAD_REF="${HEAD_REF:-}"
HAS_REPAIR_LABEL="${HAS_REPAIR_LABEL:-false}"
PAGES_CHANGED="${PAGES_CHANGED:-false}"
PR_AUTHOR="${PR_AUTHOR:-}"
PR_AUTHOR_TYPE="${PR_AUTHOR_TYPE:-}"
TP_BOT_LOGINS="${TP_BOT_LOGINS:-}"
REPAIR_BRANCH_PREFIX="${REPAIR_BRANCH_PREFIX:-tp/repair-}"
CASE_BRANCH_PREFIX="${CASE_BRANCH_PREFIX:-tp/case-}"

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

has_prefix() { # $1 = değer, $2 = önek (boş önek hiçbir şeyle eşleşmez)
  [ -n "$2" ] && [ "${1#"$2"}" != "$1" ]
}

is_bot() {
  [ "$PR_AUTHOR_TYPE" = "Bot" ] && return 0
  [ -n "$PR_AUTHOR" ] || return 1
  local author login
  author="$(lower "$PR_AUTHOR")"
  local IFS=','
  for login in $TP_BOT_LOGINS; do
    login="$(lower "$(printf '%s' "$login" | tr -d '[:space:]')")"
    [ -n "$login" ] || continue
    # "tp-bot" listede ise App'in "tp-bot[bot]" girişi de eşleşir.
    if [ "$author" = "$login" ] || [ "$author" = "${login}[bot]" ]; then
      return 0
    fi
  done
  return 1
}

mode="pr"
reason=""
run=false

if [ "$IS_PR" = "true" ]; then
  if has_prefix "$HEAD_REF" "$REPAIR_BRANCH_PREFIX"; then
    mode=repair
    reason="dal ${REPAIR_BRANCH_PREFIX}* önekli"
  elif [ "$HAS_REPAIR_LABEL" = "true" ]; then
    mode=repair
    reason="tp-repair etiketi"
  elif is_bot; then
    if has_prefix "$HEAD_REF" "$CASE_BRANCH_PREFIX"; then
      reason="bot PR'ı, test dalı (${CASE_BRANCH_PREFIX}*)"
    else
      mode=repair
      reason="bot PR'ı (${PR_AUTHOR:-?}), ${CASE_BRANCH_PREFIX}* dalı değil"
    fi
  else
    reason="insan PR'ı"
  fi
  if [ "$mode" = "repair" ] || [ "$PAGES_CHANGED" = "true" ]; then
    run=true
  else
    reason="$reason; pages/** ve tsconfig.json değişmedi"
  fi
else
  reason="PR değil"
fi

out="mode=$mode
run=$run
reason=$reason"
printf '%s\n' "$out"
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  printf '%s\n' "$out" >> "$GITHUB_OUTPUT"
fi
