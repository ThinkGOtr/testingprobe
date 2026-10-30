#!/usr/bin/env bash
# make seed — deterministik başlangıç verisi (idempotent; tekrar çalıştırmak güvenli).
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"

[ -f .env ] || die ".env bulunamadı — 'make env' çalıştırın"
svc_running core-api || die "core-api çalışmıyor — önce 'make up'"
compose exec -T core-api python -m tp_core.seed
