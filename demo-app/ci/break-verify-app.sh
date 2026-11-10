#!/usr/bin/env bash
# "Kırarak doğrula" (yeşil → kırmızı → yeşil) — uygulama sürümü; break-verify.sh'in Java + Appium
# karşılığı. Kampanya testlerinin kuralı gerçekten yakaladığını kanıtlar. AI yok.
#   1) normal koşu           → kampanya grubu geçmeli
#   2) BREAK_CAMPAIGN=1 koşu → yalnızca kampanya hesabına bağlı testler, ASSERTION ile kalmalı
#                              (kurulum / locator hatası, atlanan test kırmızı sayılmaz — Surefire
#                              JUnit XML'i araclar/KirmiziDenetimi.java ile denetlenir); kampanyasız
#                              testler geçmeli
#   3) normal koşu           → yine geçmeli (kırılma geri alındı, kalıcı iz yok)
# Kırılma bayi kapsamlıdır (POST /test/break) ve yalnızca test süresince açıktır; tek cihaz tek
# iş parçacığıyla koşar: yalnızca bayi1 (ve @Bayi ile sabitlenmiş testin bayisi, o test süresince)
# etkilenir; doğrulama ajanının bayisi (bayi3) hiçbir zaman.
#
# Kullanım: ci/break-verify-app.sh <android|ios|windows> [mvn argümanları...]
# Ortam: run-app-checks.sh ile aynı; DEMOAPP_TEST_TOKEN + DEMO_API_URL ZORUNLU (kırılma /test/break ister).
#        BREAK_VERIFY_GROUPS (varsayılan: kampanya) — TestNG grubu.
# Her adımın JUnit XML'i: demo-app/e2e-app/target/kirarak-dogrula/<adım>/
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
platform="${1:-}"
case "$platform" in
  android|ios|windows) shift ;;
  *) echo "kullanım: $0 <android|ios|windows> [mvn argümanları...]" >&2; exit 2 ;;
esac
[[ -n "${DEMOAPP_TEST_TOKEN:-}" ]] || { echo "HATA: DEMOAPP_TEST_TOKEN gerekli (kırılma POST /test/break ile açılır)" >&2; exit 2; }

grup="${BREAK_VERIFY_GROUPS:-kampanya}"
app="$root/e2e-app"
cikti="$app/target/kirarak-dogrula"
step() { printf '\n==> %s\n' "$*"; }

run() {  # $1 = BREAK_CAMPAIGN değeri, $2 = adım adı; çıkış kodunu döndürür
  local rc=0
  BREAK_CAMPAIGN="$1" SKIP_BIRIM=1 "$root/ci/run-app-checks.sh" "$platform" -Dgroups="$grup" "${@:3}" || rc=$?
  rm -rf "${cikti:?}/$2"
  mkdir -p "$cikti/$2"
  cp "$app"/target/surefire-reports/TEST-*.xml "$cikti/$2/" 2>/dev/null || true
  return "$rc"
}

rm -rf "$cikti"

step "1/3 normal (yeşil beklenir)"
run "" 1-yesil "$@" || { echo "HATA: kırılma olmadan '$grup' testleri kırmızı" >&2; exit 1; }

step "2/3 BREAK_CAMPAIGN=1 (kırmızı beklenir)"
if run 1 2-kirmizi "$@"; then
  echo "HATA: kampanya kuralı bozukken testler yeşil — testler kuralı yakalamıyor" >&2
  exit 1
fi
java "$app/araclar/KirmiziDenetimi.java" "$cikti/2-kirmizi"

step "3/3 normal (yine yeşil beklenir)"
run "" 3-yesil "$@" || { echo "HATA: kırılma geri alındıktan sonra '$grup' testleri kırmızı" >&2; exit 1; }

printf '\nKırarak doğrulama (%s): yeşil → kırmızı → yeşil ✓\n' "$platform"
