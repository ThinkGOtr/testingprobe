#!/usr/bin/env bash
# tp-vm deploy paketi: HEAD'in sığ klonu (.git dahil; asistan bilgi paketi commit okur) + kökte bin/up.sh, bin/down.sh -> current.tar.gz
# Kullanım: deploy/aiprobe/paketle.sh [çıktı.tar.gz]  ;  yükleme:
#   gcloud storage cp current.tar.gz gs://aiprobe-platform-tp-deploy/current.tar.gz
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
out="${1:-current.tar.gz}"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
git clone -q --depth 1 --no-local "file://$PWD" "$work/src"
rm -rf "$work/src/.git/hooks"
tmp="$work/src"
mkdir -p "$tmp/bin" && cp deploy/aiprobe/bin/up.sh deploy/aiprobe/bin/down.sh "$tmp/bin/" && chmod +x "$tmp/bin/"*.sh
COPYFILE_DISABLE=1 tar --no-xattrs --uid 0 --gid 0 -czf "$out" -C "$tmp" .
echo "paket: $out ($(git rev-parse --short HEAD))"
