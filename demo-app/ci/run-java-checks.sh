#!/usr/bin/env bash
# demo-app web e2e kontrolleri — Java hattı (Playwright for Java + TestNG; 011 plan §2.5).
# run-checks.sh (TypeScript) ve run-app-checks.sh (Appium) karşılığı. GitHub CI (web-java.yml) ve
# yerel geliştirici AYNI betiği kullanır (AI yok):
#   pom kilidi → üretilen test koruması (java-araclar guard) → ./mvnw test-compile
#   → birim testleri (tarayıcısız) → tarayıcı koşusu (testng.xml ya da -Dgroups=…)
#
# Kullanım: ci/run-java-checks.sh [mvn argümanları...]     ör. ci/run-java-checks.sh -Dgroups=kampanya
#
# Sonuçlar (demo-app/e2e-java/target/):
#   surefire-reports/TEST-*.xml   tarayıcı koşusu JUnit XML (ci/parse.py JUnit yolu)
#   allure-results/               Allure sonuçları
#   extent-report/index.html      Extent (Spark) HTML raporu — tek dosya, çevrimdışı açılır
#   kanit/<Sınıf>.<metot>/        başarısız testin ekran.png + trace.zip + sayfa.html (triage)
#   birim-raporlari/              birim testlerinin JUnit XML'i (+ extent-report/, allure-results/)
#   guard.json                    java-araclar guard raporu
#
# Ortam (sistem özelliği karşılıkları: e2e-java/pom.xml, Ayarlar.java):
#   BASE_URL (http://127.0.0.1:8081) · DEMO_API_URL ya da API_URL (/test/* kökü; yoksa <BASE_URL>/api)
#   DEMOAPP_TEST_TOKEN — ya da yalnızca sepet yalıtımı: TP_E2E_NO_RESET=1
#   BREAK_CAMPAIGN=1 (bayi kapsamlı kırılma; bkz. break-verify-java.sh)
#   PLAYWRIGHT_BROWSERS_PATH  Chromium önbelleği (test sırasında indirme yok)
#   TP_JAVA_ARACLAR_JAR       java-araclar.jar (varsayılan: <repo>/toolchain/java-araclar/target/java-araclar.jar;
#                             yoksa derlenir)
#   TP_E2E_JAVA_DEPS_POM      güvenilir pom (varsayılan: <repo>/toolchain/e2e-java-deps/pom.xml); bayt eşit olmalı.
#                             CI=true iken dosya yoksa betik HATA ile durur; yerelde yalnız uyarı.
#   SKIP_INSTALL=1   bağımlılıklar ~/.m2'de hazır: Maven çevrimdışı (-o)
#   SKIP_BIRIM=1     birim adımını atla (break-verify-java.sh tekrar koşularında)
#   SKIP_GUARD=1     pom kilidi + koruma adımlarını atla (break-verify-java.sh tekrar koşularında)
# Token yalnızca ortamdan okunur; komut satırına (-D) yazmayın, süreç listesinde görünür.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="$(cd "$root/.." && pwd)"
proje="$root/e2e-java"
step() { printf '\n==> %s\n' "$*"; }

cd "$proje"
mvn_opts=(-B -ntp)
[[ "${SKIP_INSTALL:-0}" == "1" ]] && mvn_opts+=(-o)

# Önceki koşunun raporu / kanıtı yeni sonuçla karışmasın.
rm -rf target/surefire-reports target/allure-results target/extent-report target/kanit target/birim-raporlari target/guard.json

if [[ "${SKIP_GUARD:-0}" != "1" ]]; then
  step "pom kilidi: e2e-java/pom.xml ↔ güvenilir pom"
  [[ -L .mvn || -L pom.xml ]] && { echo "HATA: pom.xml / .mvn sembolik bağ olamaz" >&2; exit 1; }
  guvenilir="${TP_E2E_JAVA_DEPS_POM:-$repo/toolchain/e2e-java-deps/pom.xml}"
  if [[ -f "$guvenilir" ]]; then
    cmp -s pom.xml "$guvenilir" || {
      echo "HATA: demo-app/e2e-java/pom.xml güvenilir pom ile bayt eşit değil ($guvenilir)." >&2
      echo "      Bağımlılık değişikliği önce toolchain/e2e-java-deps/pom.xml'e (ve imaja) girer." >&2
      exit 1
    }
    echo "pom.xml = $guvenilir ✓"
  elif [[ "${CI:-}" == "true" ]]; then
    # CI'da kilit sessizce kapanamaz (OPS-Y1): güvenilir pom yoksa bağımlılık değişikliği denetimsiz geçer.
    echo "HATA: güvenilir pom yok ($guvenilir); CI'da pom kilidi zorunludur." >&2
    echo "      Demo deposunda toolchain/e2e-java-deps/pom.xml bulunmalı (scripts/github-demo-repo-init.sh)." >&2
    exit 1
  else
    echo "UYARI: güvenilir pom yok ($guvenilir); kilit denetimi atlandı (yerel; CI=true iken hata)"
  fi

  step "üretilen test koruması: java-araclar guard --kimlikler"
  jar="${TP_JAVA_ARACLAR_JAR:-$repo/toolchain/java-araclar/target/java-araclar.jar}"
  if [[ ! -f "$jar" ]]; then
    echo "java-araclar.jar yok; derleniyor: $repo/toolchain/java-araclar"
    (cd "$repo/toolchain/java-araclar" && ./mvnw "${mvn_opts[@]}" -q package -DskipTests)
  fi
  mkdir -p target
  dosyalar=()
  uretilen=src/test/java/com/antreklabs/bayi/uretilen
  # Henüz üretilen test yoksa dizin olmayabilir (demo deposu): guard boş listeyle koşar.
  if [[ -d "$uretilen" ]]; then
    while IFS= read -r f; do dosyalar+=("$f"); done < <(find "$uretilen" -maxdepth 1 -name '*.java' -type f | sort)
  fi
  java -jar "$jar" guard --root . --kimlikler --quiet --out target/guard.json -- "${dosyalar[@]}"
fi

step "derleme: ./mvnw test-compile"
./mvnw "${mvn_opts[@]}" -q test-compile

if [[ "${SKIP_BIRIM:-0}" != "1" ]]; then
  step "birim testleri (tarayıcısız): -Dgroups=birim"
  ./mvnw "${mvn_opts[@]}" surefire:test -Dgroups=birim -Draporlar.dizini=target/birim-raporlari \
    -Dextent.rapor.dizini=target/birim-raporlari/extent-report \
    -Dallure.results.directory=target/birim-raporlari/allure-results -Dsurefire.timeout=600
fi

step "tarayıcı koşusu: ${BASE_URL:-http://127.0.0.1:8081} $*"
rc=0
./mvnw "${mvn_opts[@]}" surefire:test "$@" || rc=$?

printf '\nSONUÇLAR: %s\n' "$proje/target/surefire-reports"
[[ -f target/extent-report/index.html ]] && printf 'EXTENT:   %s\n' "$proje/target/extent-report/index.html"
[[ -d target/kanit ]] && printf 'KANIT:    %s\n' "$proje/target/kanit"
exit "$rc"
