#!/usr/bin/env bash
# Sauce Labs koşusunun sonucunu çekirdeğin okuyabileceği tek dosyaya (sauce.json) ve GitHub adım
# özetine yazar (.github/workflows/ci.yml "sauce" job'u). AI yok. Kimlik yoksa da çalışır:
# `--skipped <neden>` ile "atlandi" kaydı yazılır (çekirdek "Sauce koşmadı" ile "Sauce kırmızı"yı ayırır).
#
# Çıktı düzeni (--out; `sauce-results` artefaktının kökü):
#   sauce.json          aşağıdaki kayıt (schema_version 1)
#   junit.xml           Sauce VM'deki Playwright JUnit raporu (bulunursa; yoksa saucectl JUnit'i)
#   results.json        Sauce VM'deki Playwright JSON raporu (bulunursa)
#   saucectl-report.json, saucectl-junit.xml, saucectl.log, serve.log   (varsa, aynen)
#   artifacts/          saucectl'in indirdiği artefaktlar (video, log, …)
#
# sauce.json: {schema_version, kaynak:"sauce", durum: passed|failed|error|atlandi, neden, tetik,
#   istek_id, sha, run_id, run_attempt, run_url, bolge, tunel, saucectl_exit,
#   job_url (ilk Sauce job linki | null), jobs:[{id, url, ad, durum, tarayici, platform}],
#   dosyalar:{junit, junit_turu: playwright|saucectl|null, json, saucectl_report, log}}
#
# Kullanım:
#   scripts/github-sauce-summary.sh --out tp-sauce [--report F] [--junit F] [--log F] [--serve-log F]
#     [--artifacts DIR] [--exit-code N] [--region R] [--tunnel T] [--skipped "neden"]
# Ortam: TP_TRIGGER, TP_ISTEK_ID, GITHUB_REPOSITORY, GITHUB_RUN_ID, GITHUB_RUN_ATTEMPT,
#   GITHUB_SERVER_URL, GITHUB_SHA, GITHUB_STEP_SUMMARY (yoksa özet stdout'a).
# Çıkış: 0 (yazıldı) · 2 (kullanım hatası). Sauce sonucu çıkış koduna yansımaz (job zorunlu değil).
set -euo pipefail

out=""
report=""
junit=""
log=""
serve_log=""
arts=""
exit_code=""
region="${SAUCE_REGION:-}"
tunnel=""
skipped=""
is_skipped=0

while [ $# -gt 0 ]; do
  case "$1" in
    --out) out="${2:?}"; shift 2 ;;
    --report) report="${2:?}"; shift 2 ;;
    --junit) junit="${2:?}"; shift 2 ;;
    --log) log="${2:?}"; shift 2 ;;
    --serve-log) serve_log="${2:?}"; shift 2 ;;
    --artifacts) arts="${2:?}"; shift 2 ;;
    --exit-code) exit_code="${2-}"; shift 2 ;;
    --region) region="${2-}"; shift 2 ;;
    --tunnel) tunnel="${2-}"; shift 2 ;;
    --skipped) skipped="${2:?--skipped neden ister}"; is_skipped=1; shift 2 ;;
    -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "bilinmeyen argüman: $1" >&2; exit 2 ;;
  esac
done
[ -n "$out" ] || { echo "--out gerekli" >&2; exit 2; }
case "$exit_code" in ''|*[!0-9]*) [ -z "$exit_code" ] || { echo "--exit-code sayı olmalı" >&2; exit 2; } ;; esac
command -v jq >/dev/null || { echo "jq gerekli" >&2; exit 2; }
mkdir -p "$out"
out="$(cd "$out" && pwd)"

copy_if() { # $1 kaynak dosya, $2 hedef ad
  if [ -n "$1" ] && [ -f "$1" ] && [ ! -L "$1" ]; then cp "$1" "$out/$2"; fi
}
copy_if "$report" saucectl-report.json
copy_if "$junit" saucectl-junit.xml
copy_if "$log" saucectl.log
copy_if "$serve_log" serve.log

junit_turu=""
if [ -n "$arts" ] && [ -d "$arts" ]; then
  mkdir -p "$out/artifacts"
  (cd "$arts" && find . -type f -print0 | while IFS= read -r -d '' f; do
    mkdir -p "$out/artifacts/$(dirname "$f")"
    cp "$f" "$out/artifacts/$f"
  done)
  # Sauce VM'deki Playwright raporları (playwright.config.ts: results/junit.xml, results/results.json)
  pw_junit="$(cd "$out" && find artifacts -type f -name junit.xml | LC_ALL=C sort | head -n 1)"
  pw_json="$(cd "$out" && find artifacts -type f -name results.json | LC_ALL=C sort | head -n 1)"
  if [ -n "$pw_junit" ]; then cp "$out/$pw_junit" "$out/junit.xml"; junit_turu=playwright; fi
  if [ -n "$pw_json" ]; then cp "$out/$pw_json" "$out/results.json"; fi
fi
if [ -z "$junit_turu" ] && [ -f "$out/saucectl-junit.xml" ]; then
  cp "$out/saucectl-junit.xml" "$out/junit.xml"
  junit_turu=saucectl
fi

# Sauce job linkleri: önce saucectl JSON raporu, yoksa log.
url_re='^https://app\.([a-z0-9-]+\.)*saucelabs\.com/tests/[A-Za-z0-9]+$'
jobs="[]"
if [ -f "$out/saucectl-report.json" ] && jq -e . "$out/saucectl-report.json" >/dev/null 2>&1; then
  jobs="$(jq -c --arg re "$url_re" '
    [.. | objects | select((.url | type) == "string" and (.url | test($re)))
     | {id: (.url | capture("/tests/(?<id>[A-Za-z0-9]+)$").id), url,
        ad: (.name // .suiteName // null), durum: (.status // null),
        tarayici: (.browser // .browserName // null), platform: (.platform // .platformName // null)}]
    | unique_by(.url)' "$out/saucectl-report.json")"
fi
if [ "$jobs" = "[]" ] && [ -f "$out/saucectl.log" ]; then
  jobs="$(grep -Eo 'https://app\.([a-z0-9-]+\.)*saucelabs\.com/tests/[A-Za-z0-9]+' "$out/saucectl.log" \
    | LC_ALL=C sort -u \
    | jq -R '{id: (capture("/tests/(?<id>[A-Za-z0-9]+)$").id), url: ., ad: null, durum: null,
              tarayici: null, platform: null}' | jq -sc .)" || jobs="[]"
fi

neden=""
if [ "$is_skipped" = 1 ]; then
  durum=atlandi
  neden="$skipped"
elif [ "$(jq '[.[] | select(.durum != null and (.durum | ascii_downcase) != "passed" and (.durum | ascii_downcase) != "complete")] | length' <<< "$jobs")" -gt 0 ]; then
  durum=failed
elif [ -n "$exit_code" ] && [ "$exit_code" != "0" ]; then
  if [ "$jobs" = "[]" ]; then
    durum=error
    if [ -f "$out/saucectl.log" ] && grep -q "concurrent session limit" "$out/saucectl.log"; then
      neden="Sauce hesabının eşzamanlı oturum sınırı dolu (başka bir koşunun Sauce job'u sürüyordu); job başlatılamadı — uygulama ya da test hatası değil"
    else
      neden="saucectl $exit_code koduyla çıktı ve Sauce job'u oluşmadı (tünel/kimlik/kota; saucectl.log)"
    fi
  else
    durum=failed
  fi
elif [ -z "$exit_code" ]; then
  durum=error
  altyapi="$(echo "${TP_SAUCE_ALTYAPI:-}" | xargs)"
  neden="saucectl çalışmadı (${altyapi:+başarısız altyapı adımı: $altyapi; }önceki adım başarısız; serve.log)"
elif [ "$jobs" = "[]" ]; then
  durum=error
  neden="Sauce job linki bulunamadı"
else
  durum=passed
fi

server="${GITHUB_SERVER_URL:-https://github.com}"
run_url=""
if [ -n "${GITHUB_REPOSITORY:-}" ] && [ -n "${GITHUB_RUN_ID:-}" ]; then
  run_url="$server/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID"
fi
sha="$(git rev-parse HEAD 2>/dev/null || true)"
[ -n "$sha" ] || sha="${GITHUB_SHA:-}"
present() { [ -e "$out/$1" ] && printf '%s' "$1" || printf ''; }

jq -n \
  --arg durum "$durum" --arg neden "$neden" --arg tetik "${TP_TRIGGER:-}" --arg istek "${TP_ISTEK_ID:-}" \
  --arg sha "$sha" --arg run_id "${GITHUB_RUN_ID:-}" --arg attempt "${GITHUB_RUN_ATTEMPT:-}" \
  --arg run_url "$run_url" --arg bolge "$region" --arg tunel "$tunnel" --arg exit_code "$exit_code" \
  --argjson jobs "$jobs" --arg junit "$(present junit.xml)" --arg junit_turu "$junit_turu" \
  --arg json "$(present results.json)" --arg rep "$(present saucectl-report.json)" \
  --arg logf "$(present saucectl.log)" \
  'def nz: if . == "" then null else . end;
   {schema_version: 1, kaynak: "sauce", durum: $durum, neden: ($neden | nz), tetik: ($tetik | nz),
    istek_id: ($istek | nz), sha: ($sha | nz), run_id: ($run_id | nz), run_attempt: ($attempt | nz),
    run_url: ($run_url | nz), bolge: ($bolge | nz), tunel: ($tunel | nz),
    saucectl_exit: (if $exit_code == "" then null else ($exit_code | tonumber) end),
    job_url: ($jobs[0].url // null), jobs: $jobs,
    dosyalar: {junit: ($junit | nz), junit_turu: ($junit_turu | nz), json: ($json | nz),
               saucectl_report: ($rep | nz), log: ($logf | nz)}}' > "$out/sauce.json"

summary() {
  echo "### Sauce Labs (tetik: \`${TP_TRIGGER:-?}\`, bölge: \`${region:-?}\`)"
  echo
  case "$durum" in
    atlandi) echo "Atlandı: $neden. Yerel \`test-local\` job'u geçerlidir." ;;
    passed) echo "Sonuç: **geçti**" ;;
    failed) echo "Sonuç: **kırmızı**" ;;
    *) echo "Sonuç: **hata** — $neden" ;;
  esac
  if [ "$jobs" != "[]" ]; then
    echo
    echo "| Sauce job | ad | durum |"
    echo "|---|---|---|"
    jq -r '.[] | "| [\(.id)](\(.url)) | \((.ad // "-") | gsub("\\|"; "\\\\|")) | \(.durum // "-") |"' <<< "$jobs"
  elif [ "$durum" != "atlandi" ]; then
    echo
    echo "Sauce job linki bulunamadı (sauce-results artefaktındaki saucectl.log'a bakın)."
  fi
  echo
  echo "Makine okunur kayıt: \`sauce-results\` artefaktı → \`sauce.json\`"
}
if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  summary >> "$GITHUB_STEP_SUMMARY"
else
  summary
fi
printf 'sauce.json: durum=%s job=%s\n' "$durum" "$(jq -r '.[0].url // "-"' <<< "$jobs")"
