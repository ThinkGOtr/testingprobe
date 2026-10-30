#!/usr/bin/env bash
# make up önkoşulları (research R9): Docker, disk, bellek, .env sırları, port çakışması.
# Her kontrol OK/HATA yazar; biri bile HATA ise ≠0 ile çıkar ve hiçbir servis başlatılmaz.
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"

# Eşikler (ortam değişkeniyle geçersiz kılınabilir)
MIN_DISK_GB="${TP_MIN_DISK_GB:-30}"
# Docker Desktop'ta "8 GB" ayarı, çekirdek payı yüzünden MemTotal'da ~7,7 GiB görünür;
# bu yüzden eşik 7,5 GiB (8 GB ayarını kabul eder, 6 GB'ı reddeder).
MIN_MEM_BYTES="${TP_MIN_MEM_BYTES:-8053063680}"

fails=0
ok()   { printf '  OK    %s\n' "$*"; }
fail() { printf '  HATA  %s\n' "$*"; fails=$((fails + 1)); }

echo "Önkoşul kontrolü:"

# 1) Docker çalışıyor mu
docker_ok=0
if ! command -v docker >/dev/null 2>&1; then
  fail "docker komutu bulunamadı — Docker Desktop (veya Colima) kurun"
elif ! docker info >/dev/null 2>&1; then
  fail "Docker çalışmıyor — Docker Desktop'ı (veya 'colima start') başlatın"
elif ! docker compose version >/dev/null 2>&1; then
  fail "'docker compose' (v2) bulunamadı"
else
  docker_ok=1
  ok "Docker çalışıyor ($(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?'))"
fi

# 2) Boş disk. Docker Desktop/Colima verisini $HOME altındaki bir disk imajında tutar;
#    imaj dinamik büyüdüğü için gerçek sınır host'taki boş alandır → $HOME'un bulunduğu
#    birimde `df` ile ölçülür (yaklaşık değer; VM disk imajı üst sınırı ayrıca dolabilir).
avail_kb="$(df -Pk "$HOME" | awk 'NR == 2 { print $4 }')"
avail_gb=$((avail_kb / 1024 / 1024))
if [ "$avail_gb" -ge "$MIN_DISK_GB" ]; then
  ok "Boş disk: ${avail_gb} GB (en az ${MIN_DISK_GB} GB)"
else
  fail "Boş disk yetersiz: ${avail_gb} GB, en az ${MIN_DISK_GB} GB gerekli — 'make prune' veya disk temizliği yapın"
fi

# 3) Docker'a ayrılan bellek
if [ "$docker_ok" -eq 1 ]; then
  mem="$(docker info --format '{{.MemTotal}}' 2>/dev/null || echo 0)"
  mem_gb="$(awk -v b="$mem" 'BEGIN { printf "%.1f", b / 1073741824 }')"
  if [ "$mem" -ge "$MIN_MEM_BYTES" ] 2>/dev/null; then
    ok "Docker belleği: ${mem_gb} GiB (en az 8 GB)"
  else
    fail "Docker belleği yetersiz: ${mem_gb} GiB — Docker Desktop > Settings > Resources'tan en az 8 GB ayırın"
  fi
else
  fail "Docker belleği kontrol edilemedi (Docker çalışmıyor)"
fi

# 4) Playwright sürüm dosyası
if [ -n "$PLAYWRIGHT_VERSION" ]; then
  ok "Playwright sürümü: $PLAYWRIGHT_VERSION (.playwright-version)"
else
  fail ".playwright-version yok veya boş"
fi

# 5) .env ve zorunlu sırlar
if [ ! -f .env ]; then
  fail ".env bulunamadı — 'make env' çalıştırın"
else
  missing=""
  for key in $TP_F0_KEYS; do
    [ -n "$(env_get "$key")" ] || missing="$missing $key"
  done
  if [ -z "$missing" ]; then
    ok ".env: F0 zorunlu anahtarları dolu"
  else
    fail ".env'de boş/eksik zorunlu anahtar(lar):$missing — 'make env' ile doldurun"
  fi
fi

# 6) Port çakışması. Bizim yığınımızın zaten yayınladığı portlar (idempotent `make up`) sorun değildir.
ours=""
if [ "$docker_ok" -eq 1 ]; then
  ours=" $(stack_published_ports | tr '\n' ' ')"
fi
seen=" "
for spec in PG_PORT:55432 TP_API_PORT:8000 TP_PORTAL_PORT:8080 DEMO_WEB_PORT:8081 JIRA_SIM_PORT:8090; do
  key="${spec%%:*}"
  port="$(env_get "$key")"
  [ -n "$port" ] || port="${spec#*:}"
  case "$port" in
    '' | *[!0-9]*) fail "$key geçersiz port: '$port'"; continue ;;
  esac
  case "$seen" in
    *" $port "*) fail "$key=$port başka bir anahtarla aynı port"; continue ;;
  esac
  seen="$seen$port "
  case "$ours" in
    *" $port "*) ok "Port $port ($key) testingprobe yığınında zaten kullanılıyor"; continue ;;
  esac
  procs="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -Fc 2>/dev/null | sed -n 's/^c//p' | sort -u | tr '\n' ' ' || true)"
  procs="${procs% }"
  if [ -n "$procs" ]; then
    fail "Port $port ($key) kullanımda: $procs — süreci durdurun veya .env'de $key'i değiştirin"
  elif (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    # lsof başka kullanıcının sürecini göremeyebilir; bağlantı kabul ediliyorsa port doludur
    fail "Port $port ($key) kullanımda (süreç adı okunamadı, örn. 'sudo lsof -iTCP:$port')"
  else
    ok "Port $port ($key) boş"
  fi
done

if [ "$fails" -gt 0 ]; then
  echo "Önkoşullar sağlanmadı ($fails hata); hiçbir servis başlatılmadı." >&2
  exit 1
fi
echo "Önkoşullar tamam."
