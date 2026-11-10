#!/usr/bin/env bash
# demo-app uygulama (Android / iOS / Windows) e2e kontrolleri — run-checks.sh'in Java + Appium
# karşılığı. GitHub CI ve yerel test-runner AYNI betiği kullanır (AI yok).
#   ./mvnw test-compile → birim testleri (cihazsız) → cihaz koşusu (testng.xml ya da -Dgroups=…)
#
# Kullanım: ci/run-app-checks.sh <android|ios|windows> [mvn argümanları...]
#   ör. ci/run-app-checks.sh android -Dgroups=duman
#
# Sonuçlar (demo-app/e2e-app/target/):
#   surefire-reports/TEST-*.xml   cihaz koşusu JUnit XML (ci/parse.py JUnit yolu)
#   allure-results/               Allure sonuçları
#   kanit/<Sınıf>.<metot>/        başarısız testin ekran görüntüsü + sayfa kaynağı (triage)
#   birim-raporlari/              birim testlerinin JUnit XML'i
#
# Ortam (sistem özelliği karşılıkları: e2e-app/pom.xml, Ayarlar.java):
#   APPIUM_URL (http://127.0.0.1:4723) · APP_PATH ya da APP_ID · DEVICE_NAME · DEVICE_UDID
#   DEMO_API_URL (/test/* kökü) + DEMOAPP_TEST_TOKEN — ya da yalnızca sepet yalıtımı: TP_E2E_NO_RESET=1
#   BREAK_CAMPAIGN=1 (bayi kapsamlı kırılma; bkz. break-verify-app.sh)
#   SKIP_INSTALL=1   bağımlılıklar ~/.m2'de hazır: Maven çevrimdışı (-o)
#   SKIP_BIRIM=1     birim adımını atla (break-verify-app.sh tekrar koşularında)
# Token yalnızca ortamdan okunur; komut satırına (-D) yazmayın, süreç listesinde görünür.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
step() { printf '\n==> %s\n' "$*"; }

platform="${1:-}"
case "$platform" in
  android|ios|windows) shift ;;
  *) echo "kullanım: $0 <android|ios|windows> [mvn argümanları...]" >&2; exit 2 ;;
esac

cd "$root/e2e-app"
mvn_opts=(-B -ntp)
[[ "${SKIP_INSTALL:-0}" == "1" ]] && mvn_opts+=(-o)

# Önceki koşunun raporu / kanıtı yeni sonuçla karışmasın.
rm -rf target/surefire-reports target/allure-results target/kanit target/birim-raporlari

step "derleme: ./mvnw test-compile"
./mvnw "${mvn_opts[@]}" -q test-compile

if [[ "${SKIP_BIRIM:-0}" != "1" ]]; then
  step "birim testleri (cihazsız): -Dgroups=birim"
  # -q yok: takılırsa hangi testte olduğu günlükte görünsün; surefire.timeout asılı çatalı keser.
  ./mvnw "${mvn_opts[@]}" surefire:test -Dgroups=birim -Draporlar.dizini=target/birim-raporlari \
    -Dsurefire.timeout=600
fi

step "cihaz koşusu: platform=$platform $*"
rc=0
./mvnw "${mvn_opts[@]}" surefire:test -Dplatform="$platform" "$@" || rc=$?

printf '\nSONUÇLAR: %s\n' "$root/e2e-app/target/surefire-reports"
[[ -d target/kanit ]] && printf 'KANIT:    %s\n' "$root/e2e-app/target/kanit"
exit "$rc"
