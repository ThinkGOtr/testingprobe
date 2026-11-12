#!/usr/bin/env bash
# "Kırarak doğrula" (yeşil → kırmızı → yeşil) — web Java hattı; break-verify.sh (TypeScript) ve
# break-verify-app.sh (Appium) karşılığı. Kampanya testlerinin kuralı gerçekten yakaladığını kanıtlar. AI yok.
#   1) normal koşu           → kampanya grubu geçmeli
#   2) BREAK_CAMPAIGN=1 koşu → yalnızca kampanya hesabına bağlı testler, ASSERTION ile kalmalı
#                              (kurulum / locator hatası, atlanan test kırmızı sayılmaz — Surefire
#                              JUnit XML'i araclar/KirmiziDenetimi.java ile denetlenir); kampanyasız
#                              testler geçmeli
#   3) normal koşu           → yine geçmeli (kırılma geri alındı, kalıcı iz yok)
# Kırılma bayi kapsamlıdır (POST /test/break) ve yalnızca test süresince açıktır. -Dgroups koşusu tek
# iş parçacığıdır: yalnızca bayi1 (ve @Bayi ile sabitlenmiş testin bayisi, o test süresince)
# etkilenir; doğrulama ajanının bayisi (bayi3) hiçbir zaman.
#
# Kullanım: ci/break-verify-java.sh [mvn argümanları...]
# Ortam: run-java-checks.sh ile aynı; DEMOAPP_TEST_TOKEN ZORUNLU (kırılma /test/break ister).
#        BREAK_VERIFY_GROUPS (varsayılan: kampanya) — TestNG grubu.
# Her adımın JUnit XML'i, Extent raporu (extent-report/index.html) ve (kırmızıda) kanıtı:
#   demo-app/e2e-java/target/kirarak-dogrula/<adım>/
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -n "${DEMOAPP_TEST_TOKEN:-}" ]] || { echo "HATA: DEMOAPP_TEST_TOKEN gerekli (kırılma POST /test/break ile açılır)" >&2; exit 2; }

grup="${BREAK_VERIFY_GROUPS:-kampanya}"
proje="$root/e2e-java"
cikti="$proje/target/kirarak-dogrula"
step() { printf '\n==> %s\n' "$*"; }

run() {  # $1 = BREAK_CAMPAIGN değeri, $2 = adım adı; çıkış kodunu döndürür
  local rc=0
  BREAK_CAMPAIGN="$1" SKIP_BIRIM=1 SKIP_GUARD=1 "$root/ci/run-java-checks.sh" -Dgroups="$grup" "${@:3}" || rc=$?
  rm -rf "${cikti:?}/$2"
  mkdir -p "$cikti/$2"
  cp "$proje"/target/surefire-reports/TEST-*.xml "$cikti/$2/" 2>/dev/null || true
  [[ -d "$proje/target/kanit" ]] && cp -R "$proje/target/kanit" "$cikti/$2/kanit"
  # Extent raporu sonraki adımda silinir (run-java-checks.sh): adımın raporu kanıtla birlikte
  # saklanır. Gömülmeyen ekranların bağlantısı ../kanit/… olduğundan dizin düzeni aynı kalır.
  [[ -d "$proje/target/extent-report" ]] && cp -R "$proje/target/extent-report" "$cikti/$2/extent-report"
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
java "$proje/araclar/KirmiziDenetimi.java" "$cikti/2-kirmizi"

step "3/3 normal (yine yeşil beklenir)"
run "" 3-yesil "$@" || { echo "HATA: kırılma geri alındıktan sonra '$grup' testleri kırmızı" >&2; exit 1; }

printf '\nKırarak doğrulama (web, Java): yeşil → kırmızı → yeşil ✓\n'
