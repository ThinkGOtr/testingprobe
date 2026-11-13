#!/usr/bin/env bash
# tp-vm deploy paketi girişi (aiprobe-platform vm-product: /opt/tp/current/bin/up.sh).
# Sırlar /run/tp/tp.env (tmpfs) -> paket kökünde .env (yalnız root okur), sonra `make up`.
set -euo pipefail
cd "$(dirname "$0")/.."
# startup-script ortamında HOME tanımsız; git config --global için gerekli.
export HOME="${HOME:-/root}"
command -v git >/dev/null 2>&1 || { apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git; }
# Paket başka bir uid ile arşivlenmiş olabilir; root git "dubious ownership" demesin.
chown -R root:root .
git config --global --add safe.directory "$(pwd -P)"
install -m 600 /run/tp/tp.env .env
export TP_WAIT_TIMEOUT="${TP_WAIT_TIMEOUT:-900}"
make up
