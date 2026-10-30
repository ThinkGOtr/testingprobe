# shellcheck shell=bash
# shellcheck disable=SC2034  # değişkenler source eden script'lerde kullanılır
# Ortak yardımcılar — diğer script'ler `source` eder; doğrudan çalıştırılmaz.
# macOS bash 3.2 ve GNU/BSD araçlarıyla uyumludur.

TP_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TP_REPO_ROOT" || exit 1

# Compose proje adı ve Postgres volume'ü (docker-compose.yml: name: testingprobe)
TP_PROJECT="testingprobe"
TP_PG_VOLUME="${TP_PROJECT}_tp_pgdata"

# F0'da zorunlu .env anahtarları (contracts/env.md)
TP_F0_KEYS="POSTGRES_PASSWORD TP_OWNER_PASSWORD TP_APP_PASSWORD DEMOAPP_OWNER_PASSWORD DEMOAPP_PASSWORD SEED_USER_PASSWORD"

# Tek sürüm kaynağı: compose `${PLAYWRIGHT_VERSION:?}` ister
if [ -z "${PLAYWRIGHT_VERSION:-}" ] && [ -f .playwright-version ]; then
  PLAYWRIGHT_VERSION="$(tr -d '[:space:]' < .playwright-version)"
fi
export PLAYWRIGHT_VERSION="${PLAYWRIGHT_VERSION:-}"
export PYTHONIOENCODING=utf-8

err() { printf '%s\n' "$*" >&2; }
die() { err "HATA: $*"; exit 1; }

# .env'den bir anahtarın değerini okur (yoksa boş). Çevreleyen tırnakları atar.
env_get() {
  local key="$1" file="${2:-.env}" line val
  [ -f "$file" ] || return 0
  line="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$file" | tail -n 1 || true)"
  val="${line#*=}"
  # baştaki/sondaki boşluklar
  val="$(printf '%s' "$val" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  case "$val" in
    \"*\") val="${val#\"}"; val="${val%\"}" ;;
    \'*\') val="${val#\'}"; val="${val%\'}" ;;
  esac
  printf '%s' "$val"
}

# Docker compose (proje dosyası + .env ile). Etkileşimli olmayan komutlar için.
compose() { docker compose "$@"; }

# Proje konteynerlerini dosya/.env yüklemeden listeler (`-p` ile; .env eksikken de çalışır).
# Çıktı: her konteyner için sekmeyle ayrılmış satır
#   servis  durum  sağlık  çıkış_kodu  portlar  konteyner_adı
# Boş alanlar "-" olur (bash `read` ardışık sekmeleri birleştirdiği için).
# portlar: "ip:host_port->konteyner_port" virgülle ayrılmış, yoksa "-".
_TP_PS_PY='
import json, sys
raw = sys.stdin.read().strip()
items = []
if raw:
    try:
        data = json.loads(raw)
        items = data if isinstance(data, list) else [data]
    except ValueError:
        for line in raw.splitlines():
            line = line.strip()
            if line:
                items.append(json.loads(line))
for it in sorted(items, key=lambda x: x.get("Service", "")):
    ports = []
    for p in it.get("Publishers") or []:
        pub = p.get("PublishedPort") or 0
        if not pub:
            continue
        s = "%s:%s->%s" % (p.get("URL") or "?", pub, p.get("TargetPort"))
        if s not in ports:
            ports.append(s)
    row = [it.get("Service") or "-", it.get("State") or "-", it.get("Health") or "-",
           str(it.get("ExitCode", "-")), ",".join(ports) or "-", it.get("Name") or "-"]
    print("\t".join(row))
'
ps_rows() {
  local json
  json="$(docker compose -p "$TP_PROJECT" ps -a --format json 2>/dev/null)" || return 1
  printf '%s' "$json" | python3 -c "$_TP_PS_PY"
}

# Servisin konteyner durumu satırı (yoksa boş)
svc_row() { ps_rows | awk -F '\t' -v s="$1" '$1 == s' | head -n 1; }

svc_healthy() {
  local row; row="$(svc_row "$1")"
  [ -n "$row" ] || return 1
  [ "$(printf '%s' "$row" | cut -f2)" = "running" ] && [ "$(printf '%s' "$row" | cut -f3)" = "healthy" ]
}

svc_running() {
  local row; row="$(svc_row "$1")"
  [ -n "$row" ] && [ "$(printf '%s' "$row" | cut -f2)" = "running" ]
}

# Yığının yayınladığı host portları (her satırda bir port)
stack_published_ports() {
  ps_rows | cut -f5 | tr ',' '\n' | sed -n 's/^.*:\([0-9][0-9]*\)->.*$/\1/p' | sort -u
}

# Postgres'te tp_app olarak psql (yerel soket: trust)
psql_app() { compose exec -T postgres psql -X -U tp_app -d tp "$@"; }
