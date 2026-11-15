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
# Config R1: .env'de CONFIG_SOURCE=home ise aiprobe-home etkin config'i (TP_HOME_PROJECT) .env'e
# işlenir (sırlar Secret Manager'dan; Home yoksa LKG, o da yoksa .env olduğu gibi). Yalnız standart
# kütüphane: çekirdek imajı gerekmez. LKG veri diskinde (sır değeri değil, yalnız referans tutar).
if command -v python3 >/dev/null 2>&1; then
  PYTHONPATH="$(pwd -P)/core/src" python3 -m tp_core.home_config \
    --env-dosyasi .env --lkg "${TP_CONFIG_LKG:-/mnt/tp-data/tp-config/lkg-boot.json}" \
    || echo "UYARI: home config uygulanamadı; .env (tp-env) ile devam" >&2
elif grep -Eq "^CONFIG_SOURCE=['\"]?home" .env; then
  echo "UYARI: python3 yok; CONFIG_SOURCE=home uygulanamadı, .env (tp-env) ile devam" >&2
fi
export TP_WAIT_TIMEOUT="${TP_WAIT_TIMEOUT:-900}"
make up
