#!/usr/bin/env bash
# make asistan-paket — asistanın ürün bilgi paketini üretir: var/tp-bilgi/ (AI-ASISTAN-PLANI §5.1).
#
# Paket imaja kopyalanamaz (core derleme bağlamı ./core); dosya seçimi (izin/hariç listesi), sha256,
# MANIFEST ve sır taraması core imajında koşar: repo /repo'ya salt okunur bağlanır, çıktı /out'a
# yazılır. İmaj USER 10001 ile çalışır; çıktı host kullanıcısına ait olsun diye konteyner host
# uid:gid ile koşturulur. Host'ta yalnız docker ve git önkoşuldur. core-worker paketi
# /opt/tp-bilgi olarak salt okunur görür (docker-compose.yml).
#
# Sır taraması bulgu verirse paket YAZILMAZ ve çıkış kodu ≠ 0'dır (değerler gösterilmez); önceki
# paket yerinde kalır. `make up` bu adımı önce çalıştırır (atlamak için TP_SKIP_ASISTAN_PAKET=1).
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"

command -v docker >/dev/null 2>&1 || die "docker bulunamadı"
command -v git >/dev/null 2>&1 || die "git bulunamadı"
[ -f .env ] || die ".env bulunamadı — 'make env' çalıştırın"

commit="$(git rev-parse HEAD 2>/dev/null)" || die "git commit'i okunamadı (repo kökünde mi?)"
mkdir -p var/tp-bilgi

echo "Asistan bilgi paketi üretiliyor (commit ${commit:0:12})..."
# Önce core imajı derlenir: imajı yalnız `migrate` servisi derler (core-worker'da build bölümü yok,
# pull_policy: never — docker-compose.yml x-core-image). `run --build core-worker` bu yüzden hiçbir
# şey derlemezdi: temiz kurulumda imaj yok, `git pull && make up` akışında eski imajda paket.py yok.
# İdempotent: kaynak değişmediyse önbellekten döner; up.sh'teki `up --build` aynı imajı yeniden kullanır.
compose build migrate
compose run --rm --no-deps --user "$(id -u):$(id -g)" \
  -v "$PWD":/repo:ro \
  -v "$PWD/var/tp-bilgi":/out \
  core-worker python -m tp_core.features.assistant.paket \
  --kaynak /repo --cikti /out --commit "$commit"
