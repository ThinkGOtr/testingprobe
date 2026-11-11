# shellcheck shell=bash
# DEMO_EXEC / DEMO_HTTP / DEMO_BODY bu dosyayı source eden betiklerde kullanılır (SC2034 yanlış alarm).
# shellcheck disable=SC2034
# Demo betiklerinin ortak yardımcıları (demo-break.sh, demo-reset.sh, demo-web-sync.sh source eder).
# Doğrudan çalıştırılmaz. macOS bash 3.2 uyumlu.
#
# API çağrıları portal üzerinden yapılır (core-api host'a port açmaz):
#   TP_API_URL          varsayılan http://127.0.0.1:${TP_PORTAL_PORT:-8080}/api
#   TP_DEMO_USER        Sistem Yöneticisi (admin) kullanıcısı, varsayılan "yonetici" (seed)
#   TP_DEMO_PASSWORD    yoksa .env SEED_USER_PASSWORD
# İstemci tarayıcı değildir (Origin / Sec-Fetch-Site göndermez): OriginGuard geçirir.

# shellcheck source=scripts/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

demo_exec_init() {
  # shellcheck disable=SC2206  # komut öneki bilerek kelimelere bölünür
  DEMO_EXEC=(${TP_FORGE_EXEC:-docker compose exec -T core-worker})
}

demo_api_url() {
  local port
  port="${TP_PORTAL_PORT:-$(env_get TP_PORTAL_PORT)}"
  printf '%s' "${TP_API_URL:-http://127.0.0.1:${port:-8080}/api}"
}

# Oturum çerezi geçici dosyada; betik çıkarken silinir.
demo_api_login() {
  command -v curl >/dev/null 2>&1 || die "curl bulunamadı"
  DEMO_COOKIES="$(mktemp "${TMPDIR:-/tmp}/tp-demo-cookie.XXXXXX")"
  trap 'rm -f "$DEMO_COOKIES"' EXIT
  local user pass body code
  user="${TP_DEMO_USER:-yonetici}"
  pass="${TP_DEMO_PASSWORD:-$(env_get SEED_USER_PASSWORD)}"
  [ -n "$pass" ] || die "sunucu parolası yok (TP_DEMO_PASSWORD ya da .env SEED_USER_PASSWORD)"
  body="$(TP_U="$user" TP_P="$pass" python3 -c \
    'import json,os; print(json.dumps({"kullanici_adi": os.environ["TP_U"], "parola": os.environ["TP_P"]}))')"
  code="$(curl -sS -o /dev/null -w '%{http_code}' -c "$DEMO_COOKIES" \
    -H 'Content-Type: application/json' --data "$body" "$(demo_api_url)/auth/login")" \
    || die "API'ye ulaşılamadı: $(demo_api_url) (make up?)"
  [ "$code" = 200 ] || die "sunucu girişi başarısız (HTTP $code; kullanıcı: $user)"
}

# demo_api_post <yol> → gövde DEMO_BODY'de, HTTP kodu DEMO_HTTP'de. Alt kabukta (`$(...)`)
# çağrılmaz: değişkenler çağırana geçmez.
demo_api_post() {
  local out
  out="$(mktemp "${TMPDIR:-/tmp}/tp-demo-out.XXXXXX")"
  DEMO_HTTP="$(curl -sS -o "$out" -w '%{http_code}' -b "$DEMO_COOKIES" -X POST \
    --max-time 60 "$(demo_api_url)$1")" || { rm -f "$out"; die "API isteği başarısız: $1"; }
  DEMO_BODY="$(cat "$out")"
  rm -f "$out"
}

demo_api_get() {
  curl -sS -b "$DEMO_COOKIES" --max-time 30 "$(demo_api_url)$1"
}

# JSON alanı (nokta yolu) — yoksa boş.
json_get() {
  python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except ValueError:
    sys.exit(0)
for k in sys.argv[1].split("."):
    d = d.get(k) if isinstance(d, dict) else None
print("" if d is None else (json.dumps(d, ensure_ascii=False) if isinstance(d, (dict, list)) else d))
' "$1"
}
