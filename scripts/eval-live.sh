#!/usr/bin/env bash
# make eval-live — prompt paketlerinin değerlendirme setini CANLI modelle koşturur (constitution X).
#
# Yalnızca açıkça çağrıldığında çalışır; demo/CI yolunda hiç çağrılmaz. .env'deki TP_MODEL_MODE
# (replay) bu komutu etkilemez: komutun kendisi canlı çağrı isteğidir. Host'ta (core/.venv, uv)
# koşar; rapor rules/evaluation/results/ altına yazılır (compose'da rules salt okunurdur).
#
#   scripts/eval-live.sh --ping                 tek küçük çağrı: OK ya da API hata türü/iletisi
#   scripts/eval-live.sh --dry-run              API çağrısı yok; set + tahmini maliyet
#   scripts/eval-live.sh [--bundle triage …]    canlı koşu (sert tavan TP_EVAL_BUDGET_USD, vars. 5)
#       --budget-usd N      tavanı bu koşu için değiştirir
#       --record            kayıt adaylarını exports/eval-live/<zaman>/replay-adaylari/'na yazar
#                           (commit'li golden'lar asla değişmez; insan incelemesi)
#       --record-dir DİZİN  aday dizini (rules/replay içinde olamaz)
#       --update-status     set tamamen geçerse rules/evaluations.yaml → evaluated (guardrails:
#                           diğer 7 paket aynı guardrails sürümüyle geçince geçişli olarak)
#       --ledger DOSYA      çağrı defteri (vars. exports/eval-live/ai_call.jsonl; hash zincirli)
#       --via-flow          asistan setini gerçek akıştan (flow.cevapla) koşar; bayraksız atlanır
#                           (tohumlu yığın ister: make up + seed; worker durdurulmalı)
#       --purpose AMAÇ      yalnız bu amacı koşar (tekrarlanabilir; ör. assistant, assistant_deep)
#
# Ajan setleri (consistency-check, verify-and-map) yığını ister (make up): forge, demo-app salt
# okuma veritabanı (DEMOAPP_RO_DATABASE_URL), Playwright MCP (PLAYWRIGHT_MCP_URL). Erişilemezse
# paket atlanır, durumu değişmez. Her canlı çağrı (--ping dahil) deftere yazılır (constitution VIII).
#
# Sırlar (.env: ANTHROPIC_API_KEY, ANTHROPIC_WORKSPACE_ID) yalnızca alt sürecin ortamına verilir;
# hiçbir zaman yazdırılmaz. Ortamda zaten tanımlıysa .env'deki değer kullanılmaz.
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"

case "${1:-}" in
  -h|--help)
    sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
esac

command -v uv >/dev/null 2>&1 || die "uv bulunamadı (core/README.md: host Python ortamı)"

# .env'den yalnızca bu komutun ihtiyaç duyduğu anahtarlar (değerler yazdırılmaz).
for key in ANTHROPIC_API_KEY ANTHROPIC_WORKSPACE_ID TP_EVAL_BUDGET_USD TP_MODEL_PROVIDER TP_PII_MASKING; do
  if [ -z "${!key:-}" ]; then
    val="$(env_get "$key")"
    if [ -n "$val" ]; then
      export "$key=$val"
    fi
  fi
done
unset val

export TP_RULES_DIR="$TP_REPO_ROOT/rules"
# Bu komut TP_MODEL_MODE'u okumaz; yine de alt süreçte yanlış izlenim olmasın.
unset TP_MODEL_MODE TP_REPLAY_STRICT

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  case " $* " in
    *" --dry-run "*) ;;
    *) err "Not: ANTHROPIC_API_KEY tanımlı değil; canlı çağrı yapılamaz (yalnızca --dry-run)." ;;
  esac
fi

cd "$TP_REPO_ROOT/core"
exec uv run --frozen python -m tp_core.gateway.eval_live "$@"
