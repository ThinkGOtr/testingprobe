#!/usr/bin/env bash
# "Kırarak doğrula" (demo-app/ci/break-verify.sh) sonucunu makine okunur break-verify.json'a yazar
# (.github/workflows/break-verify.yml). AI yok. Sınıflandırma betiğin çıkış kodu ve kendi HATA
# satırlarına dayanır (demo-app/ci/break-verify.sh; metin değişirse toolchain/ast-guard testi kırılır):
#   kanitlandi  çıkış 0: yeşil → kırmızı (assertion) → yeşil
#   zayif_test  "testler kuralı yakalamıyor": kırılma açıkken testler yeşil (PR "zayıf test")
#   hata        diğer her şey (adım 1/3 kırmızı, kırmızı assertion değil, kurulum hatası …)
#
# Çıktı (--out): break-verify.json {schema_version, kaynak:"github", sonuc, adim (1|2|3|null),
#   neden, exit_code, grep, istek_id, sha, ref, run_id, run_url}, break-verify.log, results.json
#   (son koşunun Playwright JSON raporu, varsa).
# Kullanım: scripts/github-break-verify-result.sh --out DIR --log F [--results F] [--exit-code N] [--grep G]
set -euo pipefail

out=""
log=""
results=""
exit_code=""
grep_expr=""
while [ $# -gt 0 ]; do
  case "$1" in
    --out) out="${2:?}"; shift 2 ;;
    --log) log="${2:?}"; shift 2 ;;
    --results) results="${2:?}"; shift 2 ;;
    --exit-code) exit_code="${2-}"; shift 2 ;;
    --grep) grep_expr="${2-}"; shift 2 ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "bilinmeyen argüman: $1" >&2; exit 2 ;;
  esac
done
[ -n "$out" ] || { echo "--out gerekli" >&2; exit 2; }
case "$exit_code" in ''|*[!0-9]*) [ -z "$exit_code" ] || { echo "--exit-code sayı olmalı" >&2; exit 2; } ;; esac
command -v jq >/dev/null || { echo "jq gerekli" >&2; exit 2; }
mkdir -p "$out"

text=""
if [ -n "$log" ] && [ -f "$log" ] && [ ! -L "$log" ]; then
  cp "$log" "$out/break-verify.log"
  text="$(cat "$log")"
fi
if [ -n "$results" ] && [ -f "$results" ] && [ ! -L "$results" ]; then
  cp "$results" "$out/results.json"
fi

# Son başlayan adım (==> 1/3, 2/3, 3/3)
adim="$(grep -Eo '^==> [123]/3' <<< "$text" | tail -n 1 | cut -c5 || true)"
neden="$(grep -E '^HATA: ' <<< "$text" | tail -n 1 | cut -c7- || true)"

if [ "$exit_code" = "0" ]; then
  sonuc=kanitlandi
  neden=""
elif grep -q 'testler kuralı yakalamıyor' <<< "$text"; then
  sonuc=zayif_test
else
  sonuc=hata
  [ -n "$neden" ] || neden="break-verify.sh tamamlanmadı (çıkış: ${exit_code:-yok}; break-verify.log)"
fi

sha="$(git rev-parse HEAD 2>/dev/null || true)"
[ -n "$sha" ] || sha="${GITHUB_SHA:-}"
run_url=""
if [ -n "${GITHUB_REPOSITORY:-}" ] && [ -n "${GITHUB_RUN_ID:-}" ]; then
  run_url="${GITHUB_SERVER_URL:-https://github.com}/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID"
fi

jq -n --arg sonuc "$sonuc" --arg adim "$adim" --arg neden "$neden" --arg exit_code "$exit_code" \
  --arg grep "$grep_expr" --arg istek "${TP_ISTEK_ID:-}" --arg sha "$sha" --arg ref "${GITHUB_REF:-}" \
  --arg run_id "${GITHUB_RUN_ID:-}" --arg run_url "$run_url" \
  'def nz: if . == "" then null else . end;
   {schema_version: 1, kaynak: "github", sonuc: $sonuc,
    adim: (if $adim == "" then null else ($adim | tonumber) end), neden: ($neden | nz),
    exit_code: (if $exit_code == "" then null else ($exit_code | tonumber) end),
    grep: ($grep | nz), istek_id: ($istek | nz), sha: ($sha | nz), ref: ($ref | nz),
    run_id: ($run_id | nz), run_url: ($run_url | nz)}' > "$out/break-verify.json"

{
  echo "### Kırarak doğrula"
  case "$sonuc" in
    kanitlandi) echo "yeşil → kırmızı → yeşil ✓ — test hata yakalıyor" ;;
    zayif_test) echo "**Zayıf test:** kırılma açıkken testler yeşil kaldı — $neden" ;;
    *) echo "**Hata** (adım ${adim:-?}/3): $neden" ;;
  esac
} >> "${GITHUB_STEP_SUMMARY:-/dev/stdout}"
printf 'break-verify.json: sonuc=%s\n' "$sonuc"
