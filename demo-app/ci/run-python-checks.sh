#!/usr/bin/env bash
# demo-app e2e kontrolleri — Python hattı (TASARIM §3.1, Ş1): web (pytest + Playwright) ya da
# uygulama (pytest + Appium; android | ios | windows). run-java-checks.sh / run-app-checks.sh
# karşılığı. GitHub CI (web-python.yml, mobil-*-python.yml, masaustu-windows-python.yml) ve yerel
# geliştirici AYNI betiği kullanır (AI yok):
#   bağımlılık kilidi (requirements.lock ↔ güvenilir kopya) → venv (--require-hashes)
#   → derleme (compile) → birim testleri (tarayıcısız / cihazsız) → e2e koşusu
#
# Kullanım: ci/run-python-checks.sh <web|android|ios|windows> [pytest argümanları...]
#   ör. ci/run-python-checks.sh web -m kampanya      ci/run-python-checks.sh android -m duman
#
# Sonuçlar (demo-app/e2e-python/results/ | demo-app/e2e-app-python/results/):
#   junit.xml              e2e koşusu JUnit XML (xunit2; ci/parse.py JUnit yolu)
#   birim-junit.xml        birim testlerinin JUnit XML'i
#   allure-results/        Allure sonuçları (allure-pytest)
#   artifacts/             (web) Playwright izleri (trace.zip) + ekran görüntüleri — yalnız kırmızıda
#   kanit/<test>/          başarısız testin ekran.png + sayfa.html (web) | sayfa-kaynagi.xml (uygulama)
#
# Ortam:
#   web: BASE_URL (http://127.0.0.1:8081) · DEMO_API_URL (/test/* kökü; yoksa <BASE_URL>/api)
#   uygulama: APPIUM_URL · APP_PATH ya da APP_ID · APP_ACTIVITY · APP_ARGS · APP_WORKDIR ·
#             DEVICE_NAME · DEVICE_UDID · PLATFORM_VERSION · DEMO_API_URL
#   DEMOAPP_TEST_TOKEN — ya da yalnızca sepet yalıtımı: TP_E2E_NO_RESET=1
#   BREAK_CAMPAIGN=1 / TP_FAULT=<kod> (bayi kapsamlı kırılma; bkz. break-verify-python-checks.sh)
#   PLAYWRIGHT_BROWSERS_PATH  Chromium önbelleği (web; test sırasında indirme yok)
#   PYTHON           venv'i kuran yorumlayıcı (varsayılan: python3; Windows'ta python)
#   TP_E2E_PYTHON_LOCK  güvenilir kilit (varsayılan: <repo>/toolchain/e2e-python-deps/requirements.lock);
#                    bayt eşit olmalı. CI=true iken dosya yoksa betik HATA ile durur; yerelde yalnız uyarı.
#   SKIP_INSTALL=1   venv (.venv) hazır: kurulum atlanır
#   SKIP_BIRIM=1     birim adımını atla (break-verify-python-checks.sh tekrar koşularında)
#   SKIP_GUARD=1     kilit + derleme adımlarını atla (tekrar koşularında)
#   TP_REPEAT        web tekrar sayısı (pytest-repeat --count; varsayılan 3, kırarak doğrulamada 1)
# Token yalnızca ortamdan okunur; komut satırına yazmayın, süreç listesinde görünür.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="$(cd "$root/.." && pwd)"
step() { printf '\n==> %s\n' "$*"; }

platform="${1:-}"
case "$platform" in
  web) proje="$root/e2e-python"; shift ;;
  android|ios|windows) proje="$root/e2e-app-python"; shift ;;
  *) echo "kullanım: $0 <web|android|ios|windows> [pytest argümanları...]" >&2; exit 2 ;;
esac

cd "$proje"
# Önceki koşunun raporu / kanıtı yeni sonuçla karışmasın.
rm -rf results/junit.xml results/birim-junit.xml results/allure-results results/artifacts results/kanit
mkdir -p results

# venv yolu: POSIX bin/, Windows (Git Bash) Scripts/.
venv_py() {
  if [[ -x .venv/bin/python ]]; then echo .venv/bin/python; else echo .venv/Scripts/python.exe; fi
}

if [[ "${SKIP_GUARD:-0}" != "1" ]]; then
  step "bağımlılık kilidi: requirements.lock ↔ güvenilir kilit"
  [[ -L requirements.lock ]] && { echo "HATA: requirements.lock sembolik bağ olamaz" >&2; exit 1; }
  guvenilir="${TP_E2E_PYTHON_LOCK:-$repo/toolchain/e2e-python-deps/requirements.lock}"
  if [[ -f "$guvenilir" ]]; then
    cmp -s requirements.lock "$guvenilir" || {
      echo "HATA: $(basename "$proje")/requirements.lock güvenilir kilitle bayt eşit değil ($guvenilir)." >&2
      echo "      Bağımlılık değişikliği önce toolchain/e2e-python-deps/'e (ve imaja) girer." >&2
      exit 1
    }
    echo "requirements.lock = $guvenilir ✓"
  elif [[ "${CI:-}" == "true" ]]; then
    echo "HATA: güvenilir kilit yok ($guvenilir); CI'da bağımlılık kilidi zorunludur." >&2
    exit 1
  else
    echo "UYARI: güvenilir kilit yok ($guvenilir); kilit denetimi atlandı (yerel; CI=true iken hata)"
  fi
fi

if [[ "${SKIP_INSTALL:-0}" != "1" ]]; then
  step "venv: pip install --require-hashes -r requirements.lock"
  py="${PYTHON:-python3}"
  command -v "$py" >/dev/null 2>&1 || py=python
  "$py" -m venv .venv
  "$(venv_py)" -m pip install --disable-pip-version-check -q --require-hashes --no-deps \
    -r requirements.lock
fi
PY="$(venv_py)"

if [[ "${SKIP_GUARD:-0}" != "1" ]]; then
  step "derleme: compile() (kaynak çalıştırılmaz)"
  "$PY" - <<'EOF'
import pathlib, sys
hata = 0
for p in sorted(pathlib.Path(".").rglob("*.py")):
    if any(x in p.parts for x in (".venv", "results")):
        continue
    try:  # yalnız derlenir (bayt kodu yazılmaz, çalıştırılmaz)
        compile(p.read_bytes(), str(p), "exec", dont_inherit=True)
    except (SyntaxError, ValueError) as exc:
        print(f"{p}: {exc}", file=sys.stderr)
        hata += 1
sys.exit(1 if hata else 0)
EOF
fi

if [[ "${SKIP_BIRIM:-0}" != "1" ]]; then
  step "birim testleri ($( [[ $platform == web ]] && echo tarayıcısız || echo cihazsız )): -m birim"
  "$PY" -m pytest tests/birim -m birim -q --junitxml=results/birim-junit.xml -o junit_family=xunit2
fi

ortak=(--junitxml=results/junit.xml -o junit_family=xunit2
       --alluredir=results/allure-results --ignore=tests/birim)
rc=0
if [[ "$platform" == web ]]; then
  step "tarayıcı koşusu: ${BASE_URL:-http://127.0.0.1:8081} $*"
  "$PY" -m pytest "${ortak[@]}" --browser chromium --tracing retain-on-failure \
    --screenshot only-on-failure --output results/artifacts --count "${TP_REPEAT:-3}" \
    --base-url "${BASE_URL:-http://127.0.0.1:8081}" "$@" || rc=$?
else
  step "cihaz koşusu: platform=$platform $*"
  TP_PLATFORM="$platform" "$PY" -m pytest "${ortak[@]}" "$@" || rc=$?
fi

printf '\nSONUÇLAR: %s\n' "$proje/results/junit.xml"
[[ -d results/kanit ]] && printf 'KANIT:    %s\n' "$proje/results/kanit"
exit "$rc"
