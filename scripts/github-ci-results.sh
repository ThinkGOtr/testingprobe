#!/usr/bin/env bash
# CI koşusunun sonuçlarını yerel koşuyla AYNI ad ve biçimde tek bir artefakt dizininde toplar
# (.github/workflows/ci.yml "test-local"; çekirdeğin ci-runs alımı bu düzeni okur). AI yok.
#
# Çıktı düzeni (--out; artefakt kökü = bu dizin):
#   ci-meta.json        koşu bilgisi (aşağıda; schema_version 1)
#   junit.xml           Playwright JUnit raporu          (yerel: src/e2e/results/junit.xml)
#   results.json        Playwright JSON raporu           (yerel: src/e2e/results/results.json)
#   allure-results/     allure-playwright çıktısı        (yerel: src/e2e/results/allure-results/)
#   playwright-report/  Playwright HTML raporu           (yerel: src/e2e/results/html/)
#   artifacts/          iz/ekran görüntüsü (başarısızlar) (yerel: src/e2e/results/artifacts/)
#   run-checks.log      run-checks.sh çıktısı (--log verilirse)
#
# ci-meta.json alanları: schema_version, kaynak ("github"), job, tetik, istek_id, sha (gerçekten
# test edilen commit: checkout HEAD; repository_dispatch'te GITHUB_SHA varsayılan dalın ucu olabilir),
# github_sha, ref, event, repo, run_id, run_attempt, run_url, playwright, toolchain_image,
# exit_code, durum (passed|failed|error — toolchain/runner/results.py decide_status ile aynı kural),
# hata, stats {expected, unexpected, flaky, skipped, duration_ms} | null, results_kok (results.json
# içindeki ek yollarının kökü; alım bunu `artifacts/` altına eşler), dosyalar {ad: göreli yol | null},
# generated_tests (e2e/tests/generated/** altındaki spec dosyaları, uygulama köküne göreli).
#
# Kullanım:
#   scripts/github-ci-results.sh --out tp-results --src demo-app/e2e/results [--src results] \
#     [--app-root demo-app] [--exit-code N] [--log run-checks.log] [--job test-local]
# --src birden çok verilebilir; results.json veya junit.xml içeren İLK dizin kullanılır.
# Ortam (GitHub): TP_TRIGGER, TP_ISTEK_ID, PLAYWRIGHT_VERSION, TOOLCHAIN_IMAGE, GITHUB_SHA, GITHUB_REF,
#   GITHUB_EVENT_NAME, GITHUB_REPOSITORY, GITHUB_RUN_ID, GITHUB_RUN_ATTEMPT, GITHUB_SERVER_URL.
# Gereken: bash, jq, git (sha için; yoksa GITHUB_SHA). Çıkış: 0 (yazıldı) · 2 (kullanım hatası).
set -euo pipefail

out=""
app_root="demo-app"
exit_code=""
log_file=""
job="test-local"
srcs=()

while [ $# -gt 0 ]; do
  case "$1" in
    --out) out="${2:?--out değer ister}"; shift 2 ;;
    --src) srcs+=("${2:?--src değer ister}"); shift 2 ;;
    --app-root) app_root="${2:?--app-root değer ister}"; shift 2 ;;
    --exit-code) exit_code="${2:?--exit-code değer ister}"; shift 2 ;;
    --log) log_file="${2:?--log değer ister}"; shift 2 ;;
    --job) job="${2:?--job değer ister}"; shift 2 ;;
    -h|--help) sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "bilinmeyen argüman: $1" >&2; exit 2 ;;
  esac
done
[ -n "$out" ] || { echo "--out gerekli" >&2; exit 2; }
[ "${#srcs[@]}" -gt 0 ] || { echo "en az bir --src gerekli" >&2; exit 2; }
case "$exit_code" in ''|*[!0-9]*) [ -z "$exit_code" ] || { echo "--exit-code sayı olmalı" >&2; exit 2; } ;; esac
command -v jq >/dev/null || { echo "jq gerekli" >&2; exit 2; }

mkdir -p "$out"
out="$(cd "$out" && pwd)"

src=""
for s in "${srcs[@]}"; do
  if [ -f "$s/results.json" ] || [ -f "$s/junit.xml" ]; then
    src="$(cd "$s" && pwd)"
    break
  fi
done

# Kopyalama: sembolik bağlar izlenmez (artefakt yalnızca koşunun ürettiği dosyaları taşır).
copy_file() { # $1 kaynak, $2 hedef ad
  if [ -n "$src" ] && [ -f "$src/$1" ] && [ ! -L "$src/$1" ]; then
    cp "$src/$1" "$out/$2"
  fi
}
copy_dir() { # $1 kaynak dizin, $2 hedef dizin
  if [ -n "$src" ] && [ -d "$src/$1" ] && [ ! -L "$src/$1" ]; then
    rm -rf "${out:?}/$2"
    mkdir -p "$out/$2"
    (cd "$src/$1" && find . -type f -print0 | while IFS= read -r -d '' f; do
      mkdir -p "$out/$2/$(dirname "$f")"
      cp "$f" "$out/$2/$f"
    done)
  fi
}

copy_file junit.xml junit.xml
copy_file results.json results.json
copy_dir allure-results allure-results
copy_dir html playwright-report
copy_dir artifacts artifacts
if [ -n "$log_file" ] && [ -f "$log_file" ]; then
  cp "$log_file" "$out/run-checks.log"
fi

# Gerçekten test edilen commit (checkout HEAD); git yoksa GITHUB_SHA.
sha="$(git rev-parse HEAD 2>/dev/null || true)"
[ -n "$sha" ] || sha="${GITHUB_SHA:-}"

generated="[]"
if [ -d "$app_root/e2e/tests/generated" ]; then
  generated="$(cd "$app_root" && find e2e/tests/generated -type f -name '*.spec.ts' | LC_ALL=C sort | jq -R . | jq -s .)"
fi

present() { [ -e "$out/$1" ] && printf '%s' "$1" || printf ''; }

stats="null"
report_errors=0
if [ -f "$out/results.json" ] && jq -e 'type == "object"' "$out/results.json" >/dev/null 2>&1; then
  stats="$(jq -c '(.stats // {}) as $s | {
      expected: ($s.expected // 0), unexpected: ($s.unexpected // 0), flaky: ($s.flaky // 0),
      skipped: ($s.skipped // 0), duration_ms: (($s.duration // 0) | floor)}' "$out/results.json")"
  report_errors="$(jq '(.errors // []) | length' "$out/results.json")"
fi

# durum: toolchain/runner/results.py decide_status ile aynı kural.
hata=""
if [ "$stats" = "null" ]; then
  durum=error
  hata="Playwright JSON raporu üretilmedi (tsc/eslint/kurulum adımı başarısız olmuş olabilir; run-checks.log)"
elif [ "$report_errors" -gt 0 ]; then
  durum=error
  hata="$(jq -r '.errors[0].message // .errors[0] // "rapor düzeyinde hata" | tostring | .[0:500]' "$out/results.json")"
elif [ "$(jq '.unexpected' <<< "$stats")" -gt 0 ]; then
  durum=failed
elif [ "$(jq '.expected + .flaky' <<< "$stats")" -eq 0 ]; then
  durum=error
  hata="Hiç test koşmadı (filtre eşleşmedi ya da yapılandırma hatası)."
elif [ "${exit_code:-0}" = "0" ]; then
  durum=passed
else
  durum=error
  hata="Playwright çıkış kodu $exit_code"
fi

server="${GITHUB_SERVER_URL:-https://github.com}"
run_url=""
if [ -n "${GITHUB_REPOSITORY:-}" ] && [ -n "${GITHUB_RUN_ID:-}" ]; then
  run_url="$server/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID"
fi

jq -n \
  --arg job "$job" --arg tetik "${TP_TRIGGER:-}" --arg istek "${TP_ISTEK_ID:-}" \
  --arg sha "$sha" --arg github_sha "${GITHUB_SHA:-}" --arg ref "${GITHUB_REF:-}" \
  --arg event "${GITHUB_EVENT_NAME:-}" --arg repo "${GITHUB_REPOSITORY:-}" \
  --arg run_id "${GITHUB_RUN_ID:-}" --arg attempt "${GITHUB_RUN_ATTEMPT:-}" --arg run_url "$run_url" \
  --arg pw "${PLAYWRIGHT_VERSION:-}" --arg image "${TOOLCHAIN_IMAGE:-}" \
  --arg exit_code "$exit_code" --arg durum "$durum" --arg hata "$hata" \
  --argjson stats "$stats" --arg kok "$src" --argjson generated "$generated" \
  --arg junit "$(present junit.xml)" --arg json "$(present results.json)" \
  --arg allure "$(present allure-results)" --arg html "$(present playwright-report)" \
  --arg arts "$(present artifacts)" --arg log "$(present run-checks.log)" \
  'def nz: if . == "" then null else . end;
   {schema_version: 1, kaynak: "github", job: $job, tetik: ($tetik | nz), istek_id: ($istek | nz),
    sha: ($sha | nz), github_sha: ($github_sha | nz), ref: ($ref | nz), event: ($event | nz),
    repo: ($repo | nz), run_id: ($run_id | nz), run_attempt: ($attempt | nz), run_url: ($run_url | nz),
    playwright: ($pw | nz), toolchain_image: ($image | nz),
    exit_code: (if $exit_code == "" then null else ($exit_code | tonumber) end),
    durum: $durum, hata: ($hata | nz), stats: $stats, results_kok: ($kok | nz),
    dosyalar: {junit: ($junit | nz), json: ($json | nz), allure: ($allure | nz),
               html: ($html | nz), artifacts: ($arts | nz), log: ($log | nz)},
    generated_tests: $generated}' > "$out/ci-meta.json"

printf 'ci-meta: durum=%s sha=%s kaynak_dizin=%s\n' "$durum" "${sha:0:12}" "${src:-yok}"
