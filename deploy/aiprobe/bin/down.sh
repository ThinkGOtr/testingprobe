#!/usr/bin/env bash
# tp-vm deploy paketi kapanışı (aiprobe-platform vm-product: /opt/tp/current/bin/down.sh).
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || install -m 600 /run/tp/tp.env .env
docker compose down
