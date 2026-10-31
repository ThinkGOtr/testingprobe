#!/usr/bin/env bash
# Merge kapısı yalıtımı (make security-check maddesi; çalışan compose yığınına karşı).
#
# LocalForge merge'ü `checks/<sha>.json`'daki `local-ci` sonucuna göre verir; bu dosyanın tek yazarı
# toolchain-worker'dır (MIMARI-SOZLESME §2). test-runner commit'ten gelen kodu (playwright.config,
# fixture, page object, spec) koşturur: kapı dizinine ulaşabilseydi bir commit başka bir PR'ın
# head sha'sı için sahte `success` yazabilirdi. Denetimler:
#   1. toolchain-worker'da kapı dizini (TP_CHECKS_PATH) ayrı bir bağlama noktasıdır (tp_checks).
#   2. test-runner'ın hiçbir bağlaması tp_checks volume'ü değildir ve kapı yoluna bağlı değildir.
#   3. test-runner kapı yoluna bir kanarya yazmayı dener; kanarya toolchain-worker'da GÖRÜNMEZ.
#   4. toolchain-worker belirteci (TP_TOOLCHAIN_TOKEN) toolchain-worker'da tanımlı, test-runner'da YOK.
#   5. test-runner'dan toolchain-worker:8100/check'e (a) kapsamlı + record_check:true ve (b) tam
#      kapsamlı istek atılır (belirteçsiz, var olmayan sha — hiçbir koşu başlamaz). Ya ulaşılamaz
#      (ağ yalıtımı) ya da 401 dönmelidir; (a) için 422 (kapsamlı kayıt reddi) de kabul edilir.
#      Bu madde olmadan test-runner'daki commit kodu /check ile kapıyı yazdırabilirdi.
# Çıkış: 0 = geçti, 1 = ihlal. Ortam: TP_COMPOSE (varsayılan "docker compose").
set -euo pipefail

# shellcheck disable=SC2206  # komut öneki bilerek kelimelere bölünür
COMPOSE=(${TP_COMPOSE:-docker compose})
fail() { echo "GÜVENLİK İHLALİ (merge kapısı): $*" >&2; exit 1; }

gate="$("${COMPOSE[@]}" exec -T toolchain-worker sh -c 'printf %s "${TP_CHECKS_PATH:-/artifacts/checks}"')"
[ -n "$gate" ] || fail "toolchain-worker kapı yolu okunamadı"

# 1
"${COMPOSE[@]}" exec -T toolchain-worker python -c \
  "import os, sys; sys.exit(0 if os.path.ismount(sys.argv[1]) else 1)" "$gate" \
  || fail "toolchain-worker: $gate ayrı bir volume değil (tp_checks bağlanmalı)"

# 2
runner_id="$("${COMPOSE[@]}" ps -q test-runner)"
[ -n "$runner_id" ] || fail "test-runner konteyneri bulunamadı"
mounts="$(docker inspect "$runner_id" --format '{{range .Mounts}}{{.Name}}|{{.Destination}}{{"\n"}}{{end}}')"
if printf '%s\n' "$mounts" | grep -Eq '(^|_)tp_checks\|'; then
  fail "test-runner tp_checks volume'ünü bağlıyor"
fi
if printf '%s\n' "$mounts" | awk -F'|' -v g="$gate" '$2 == g { found = 1 } END { exit !found }'; then
  fail "test-runner'da $gate bir bağlama noktası"
fi

# 3
canary=".tp-isolation-$(date +%s)-$$"
"${COMPOSE[@]}" exec -T test-runner sh -c \
  "mkdir -p '$gate' 2>/dev/null; touch '$gate/$canary' 2>/dev/null" || true
if "${COMPOSE[@]}" exec -T toolchain-worker test -e "$gate/$canary"; then
  "${COMPOSE[@]}" exec -T test-runner rm -f "$gate/$canary" || true
  fail "test-runner'ın yazdığı dosya toolchain-worker'ın kapı dizininde görünüyor"
fi
"${COMPOSE[@]}" exec -T test-runner rm -f "$gate/$canary" >/dev/null 2>&1 || true

# 4
# shellcheck disable=SC2016  # $… konteyner içindeki kabukta açılır
"${COMPOSE[@]}" exec -T toolchain-worker sh -c '[ -n "${TP_TOOLCHAIN_TOKEN:-}" ]' \
  || fail "toolchain-worker'da TP_TOOLCHAIN_TOKEN tanımlı değil: /check kimlik doğrulamasız"
# shellcheck disable=SC2016
if "${COMPOSE[@]}" exec -T test-runner sh -c '[ -n "${TP_TOOLCHAIN_TOKEN:-}" ]'; then
  fail "test-runner'da TP_TOOLCHAIN_TOKEN var: commit kodu belirteci okuyup /check çağırabilir"
fi

# 5
zero_sha="0000000000000000000000000000000000000000"
probe_check() {  # $1 = JSON gövde → HTTP durum kodu ya da "ULASILAMADI"
  "${COMPOSE[@]}" exec -T test-runner node -e '
    fetch("http://toolchain-worker:8100/check", {
      method: "POST", headers: {"content-type": "application/json"}, body: process.argv[1],
      signal: AbortSignal.timeout(10000),
    }).then((r) => console.log(r.status)).catch(() => console.log("ULASILAMADI"));
  ' "$1"
}
scoped="$(probe_check '{"sha":"'"$zero_sha"'","test_files":["tests/cart.spec.ts"],"repeat_each":1,"record_check":true}')"
case "$scoped" in
  ULASILAMADI|401|422) ;;
  *) fail "test-runner kapsamlı record_check:true /check isteği reddedilmedi (HTTP $scoped)" ;;
esac
full="$(probe_check '{"sha":"'"$zero_sha"'","repeat_each":1}')"
case "$full" in
  ULASILAMADI|401) ;;
  *) fail "test-runner belirteçsiz /check çağırabiliyor (HTTP $full; 401 beklenirdi)" ;;
esac

echo "Tamam: merge kapısı ($gate) yalnızca toolchain-worker'da; test-runner ulaşamıyor" \
     "(/check: kapsamlı=$scoped, tam=$full)."
