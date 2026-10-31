#!/usr/bin/env bash
# demo-app'i CI runner'ında QA ortamı olarak ayağa kaldırır (Sauce Labs job'u; TEKNIK-TASARIM §8.5).
#
#   API : uv sync --frozen --no-dev → uvicorn, SQLite (her başlatmada sıfır), DEMOAPP_TEST_MODE=1
#   Web : npm ci → vite build → vite preview (/api → API proxy'si demo-app/web/vite.config.ts'ten)
#
# Sauce VM'indeki tarayıcı uygulamaya Sauce Connect tüneliyle `http://<TP_ALLOWED_HOSTS>:<PORT>`
# adresinden ulaşır. vite preview tanımadığı Host başlığını reddeder (DNS rebinding koruması); izinli
# adlar TP_ALLOWED_HOSTS'tan Vite'ın __VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS değişkenine geçer
# (preview.allowedHosts tanımsızken server.allowedHosts kullanılır; vite.config.ts değişmez).
#
# Hazırlık: API /health ve web üzerinden /api/health yanıt verince "hazır" yazılır. Sağlık ucu
# web portunda `/api/health`'tir (`/health` SPA geri dönüşüyle her zaman 200 döner, kanıt değildir).
#
# Kullanım:
#   scripts/github-demo-serve.sh            # ön planda çalışır; süreçlerden biri ölürse ≠0 ile çıkar
#   scripts/github-demo-serve.sh --smoke    # başlat → doğrula → durdur (CI duman testi / yerel)
#
# Ortam:
#   PORT (8081)  DEMO_API_PORT (18000)  TP_BIND_HOST (127.0.0.1)  TP_ALLOWED_HOSTS (virgülle; boş olabilir)
#   TP_APP_ROOT (<repo>/demo-app)  DEMOAPP_TEST_TOKEN (test uçlarının paylaşılan sırrı; e2e'ye de verilir)
#   BREAK_CAMPAIGN (API'ye geçer)  SKIP_INSTALL=1 (bağımlılıklar hazırsa uv sync / npm ci / build atlanır)
#   TP_SERVE_READY_TIMEOUT (sn, 180)
set -euo pipefail

SMOKE=0
for arg in "$@"; do
  case "$arg" in
    --smoke) SMOKE=1 ;;
    -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "bilinmeyen argüman: $arg" >&2; exit 2 ;;
  esac
done

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="${TP_APP_ROOT:-$here/../demo-app}"
APP_ROOT="$(cd "$APP_ROOT" && pwd)"
PORT="${PORT:-8081}"
API_PORT="${DEMO_API_PORT:-18000}"
BIND_HOST="${TP_BIND_HOST:-127.0.0.1}"
ALLOWED_HOSTS="${TP_ALLOWED_HOSTS:-}"
READY_TIMEOUT="${TP_SERVE_READY_TIMEOUT:-180}"

for v in PORT API_PORT; do
  case "${!v}" in ''|*[!0-9]*) echo "::error::$v sayı olmalı: ${!v}" >&2; exit 2 ;; esac
done
if [ "$PORT" = "$API_PORT" ]; then
  echo "::error::PORT ve DEMO_API_PORT farklı olmalı ($PORT)" >&2; exit 2
fi
# Vite, ayrılmış karakter içeren listeyi sessizce yok sayar; burada açık hata verilir.
case "$ALLOWED_HOSTS" in
  *[!A-Za-z0-9.,_-]*) echo "::error::TP_ALLOWED_HOSTS yalnızca ad listesi olmalı (virgülle): $ALLOWED_HOSTS" >&2; exit 2 ;;
esac
for d in api web; do
  [ -d "$APP_ROOT/$d" ] || { echo "::error::$APP_ROOT/$d bulunamadı" >&2; exit 2; }
done

log() { printf '[demo-serve] %s\n' "$*" >&2; }

run_dir="$(mktemp -d "${TMPDIR:-/tmp}/tp-demo-serve.XXXXXX")"
api_pid=""
web_pid=""
# shellcheck disable=SC2317,SC2329  # trap ile çağrılır
cleanup() {
  local code=$?
  trap - EXIT INT TERM
  for pid in $web_pid $api_pid; do
    # Süreç grubunu değil, alt ağacı durdur: npx → node, uv → python.
    pkill -TERM -P "$pid" 2>/dev/null || true
    kill -TERM "$pid" 2>/dev/null || true
  done
  for pid in $web_pid $api_pid; do wait "$pid" 2>/dev/null || true; done
  rm -rf "$run_dir"
  exit "$code"
}
trap cleanup EXIT
trap 'exit 143' INT TERM

wait_http() { # $1 = url, $2 = ad, $3 = izlenen pid; 2xx gelene kadar bekler
  local url="$1" name="$2" pid="$3" deadline=$((SECONDS + READY_TIMEOUT))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if curl -fsS -o /dev/null --max-time 5 "$url" 2>/dev/null; then
      log "$name hazır: $url"
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      log "$name süreci erken sonlandı"
      return 1
    fi
    sleep 1
  done
  log "$name ${READY_TIMEOUT} sn içinde hazır olmadı: $url"
  return 1
}

# --- API --------------------------------------------------------------------------------------
if [ "${SKIP_INSTALL:-0}" != "1" ]; then
  log "api: uv sync --frozen --no-dev"
  (cd "$APP_ROOT/api" && uv sync --frozen --no-dev)
fi
db="$run_dir/demoapp-qa.db"
log "api: uvicorn 127.0.0.1:$API_PORT (SQLite, test modu)"
(
  cd "$APP_ROOT/api"
  export DEMOAPP_DATABASE_URL="sqlite:///$db" DEMOAPP_TEST_MODE=1 BREAK_CAMPAIGN="${BREAK_CAMPAIGN:-}"
  exec uv run --frozen --no-dev uvicorn demoapp_api.main:app --host 127.0.0.1 --port "$API_PORT"
) &
api_pid=$!
wait_http "http://127.0.0.1:$API_PORT/health" "API" "$api_pid"

# --- Web --------------------------------------------------------------------------------------
if [ "${SKIP_INSTALL:-0}" != "1" ]; then
  log "web: npm ci --ignore-scripts && npm run build"
  (cd "$APP_ROOT/web" && npm ci --ignore-scripts --no-audit --no-fund && npm run build)
fi
log "web: vite preview $BIND_HOST:$PORT (izinli ek adlar: ${ALLOWED_HOSTS:-yok})"
(
  cd "$APP_ROOT/web"
  export DEMOAPP_API_URL="http://127.0.0.1:$API_PORT" __VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS="$ALLOWED_HOSTS"
  exec npx --no-install vite preview --host "$BIND_HOST" --port "$PORT" --strictPort
) &
web_pid=$!
wait_http "http://127.0.0.1:$PORT/api/health" "Web (/api proxy)" "$web_pid"

first_host="${ALLOWED_HOSTS%%,*}"
log "uygulama hazır: http://${first_host:-127.0.0.1}:$PORT"

# --- Duman testi ------------------------------------------------------------------------------
if [ "$SMOKE" = "1" ]; then
  fail=0
  check() { # $1 = açıklama, $2 = beklenen kod, kalan: curl argümanları
    local what="$1" want="$2" got
    shift 2
    got="$(curl -sS -o "$run_dir/body" -w '%{http_code}' --max-time 10 "$@" || echo 000)"
    if [ "$got" = "$want" ]; then
      log "OK   $what → $got"
    else
      log "FAIL $what → $got (beklenen $want)"
      head -c 300 "$run_dir/body" >&2 2>/dev/null || true
      echo >&2
      fail=1
    fi
  }
  base="http://127.0.0.1:$PORT"
  check "GET /api/health (proxy → API)" 200 "$base/api/health"
  grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' "$run_dir/body" \
    || { log "FAIL /api/health gövdesinde status=ok yok"; fail=1; }
  check "GET / (SPA)" 200 "$base/"
  grep -q 'id="root"' "$run_dir/body" || { log "FAIL / gövdesinde #root yok"; fail=1; }
  if [ -n "$ALLOWED_HOSTS" ]; then
    IFS=',' read -r -a hosts <<< "$ALLOWED_HOSTS"
    for h in "${hosts[@]}"; do
      [ -n "$h" ] || continue
      check "GET / Host: $h:$PORT (izinli)" 200 -H "Host: $h:$PORT" "$base/"
      check "GET /api/health Host: $h:$PORT (izinli)" 200 -H "Host: $h:$PORT" "$base/api/health"
    done
  fi
  check "GET / Host: tp-izinsiz.invalid (reddedilmeli)" 403 -H "Host: tp-izinsiz.invalid:$PORT" "$base/"
  if [ "$fail" != "0" ]; then
    log "duman testi BAŞARISIZ"
    exit 1
  fi
  log "duman testi başarılı"
  exit 0
fi

# --- Ön plan: süreçlerden biri ölürse çık -----------------------------------------------------
while kill -0 "$api_pid" 2>/dev/null && kill -0 "$web_pid" 2>/dev/null; do
  sleep 2
done
log "API veya web süreci sonlandı"
exit 1
