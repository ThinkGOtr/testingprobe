#!/usr/bin/env bash
# make up — önkoşul kontrolü → docker compose up --wait → durum tablosu.
# İdempotent: çalışan ortamda yalnızca eksik/değişen servisleri başlatır.
# Sağlık süresi aşılırsa sağlıksız servislerin adını ve son 20 log satırını yazar (≠0).
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"

WAIT_TIMEOUT="${TP_WAIT_TIMEOUT:-300}"

"$TP_REPO_ROOT/scripts/preflight.sh"

# Beklenen her servis için: migrate 0 ile tamamlanmış, diğerleri running+healthy olmalı.
# Uymayanları "servis<TAB>neden" olarak yazar.
failing_services() {
  local services rows svc row state health code
  services="$(compose config --services)"
  rows="$(ps_rows)"
  for svc in $services; do
    row="$(printf '%s\n' "$rows" | awk -F '\t' -v s="$svc" '$1 == s' | head -n 1)"
    if [ -z "$row" ]; then
      printf '%s\tkonteyner yok\n' "$svc"; continue
    fi
    state="$(printf '%s' "$row" | cut -f2)"
    health="$(printf '%s' "$row" | cut -f3)"
    code="$(printf '%s' "$row" | cut -f4)"
    if [ "$svc" = "migrate" ]; then
      [ "$state" = "exited" ] && [ "$code" = "0" ] && continue
      [ "$state" = "running" ] && { printf '%s\thâlâ çalışıyor\n' "$svc"; continue; }
      printf '%s\tdurum=%s çıkış=%s\n' "$svc" "$state" "$code"; continue
    fi
    [ "$state" = "running" ] && [ "$health" = "healthy" ] && continue
    printf '%s\tdurum=%s sağlık=%s\n' "$svc" "$state" "$health"
  done
}

echo "Servisler başlatılıyor (en çok ${WAIT_TIMEOUT} sn sağlık beklenir)..."
rc=0
compose up -d --build --wait --wait-timeout "$WAIT_TIMEOUT" || rc=$?

bad="$(failing_services || true)"
if [ -n "$bad" ]; then
  echo >&2
  echo "HATA: ortam sağlıklı başlatılamadı (docker compose çıkış kodu: $rc). Sağlıksız servisler:" >&2
  printf '%s\n' "$bad" | while IFS="$(printf '\t')" read -r svc why; do
    echo >&2
    echo "=== $svc ($why) — son 20 log satırı ===" >&2
    compose logs --no-color --tail 20 "$svc" >&2 2>&1 || true
  done
  exit 1
fi
if [ "$rc" -ne 0 ]; then
  # compose hata verdi ama tüm servisler sağlıklı (ör. --wait'in tek seferlik migrate'i
  # hata sayması) → kabul et, uyar.
  echo "Uyarı: docker compose $rc ile döndü, ancak tüm servisler sağlıklı." >&2
fi

echo
"$TP_REPO_ROOT/scripts/status.sh"
