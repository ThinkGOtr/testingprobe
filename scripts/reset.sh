#!/usr/bin/env bash
# make reset — (1) denetim kaydını dışa aktar (başarısızsa hiçbir şey silinmez)
#              (2) docker compose down + yalnızca Postgres volume'ünü sil
#              (3) make up  → "ortam temiz"
# Yarıda kesilirse tekrar çalıştırmak güvenlidir: dışa aktarım her zaman silmeden önce yapılır.
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"

[ -f .env ] || die ".env bulunamadı — 'make env' çalıştırın"
docker info >/dev/null 2>&1 || die "Docker çalışmıyor"

if docker volume inspect "$TP_PG_VOLUME" >/dev/null 2>&1; then
  started_pg=0
  if ! svc_healthy postgres; then
    # Ortam kapalı ama veri var: dışa aktarım için yalnızca Postgres'i başlat
    echo "Dışa aktarım için yalnızca postgres başlatılıyor..."
    if ! compose up -d --no-deps --wait --wait-timeout 120 postgres; then
      die "postgres başlatılamadı; dışa aktarım yapılamadı, hiçbir şey silinmedi"
    fi
    started_pg=1
  fi
  if ! TP_EXPORT_ALLOW_NO_TABLE=1 "$TP_REPO_ROOT/scripts/export-audit.sh"; then
    [ "$started_pg" -eq 0 ] || compose stop postgres >/dev/null 2>&1 || true
    die "dışa aktarım başarısız; sıfırlama iptal edildi, hiçbir şey silinmedi"
  fi
else
  echo "Postgres volume'ü ($TP_PG_VOLUME) yok; dışa aktarılacak denetim kaydı yok."
fi

echo "Servisler durduruluyor..."
compose down
if docker volume inspect "$TP_PG_VOLUME" >/dev/null 2>&1; then
  docker volume rm "$TP_PG_VOLUME" >/dev/null
  echo "Çekirdek veri silindi ($TP_PG_VOLUME)."
fi

"$TP_REPO_ROOT/scripts/up.sh"
echo "ortam temiz"
