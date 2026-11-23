#!/usr/bin/env bash
# Sauce Labs hesabının dakika/eşzamanlılık durumu — YALNIZ seçilmiş sayısal alanlar, tek satır JSON
# (stdout). Kimlik (SAUCE_USERNAME / SAUCE_ACCESS_KEY) ortamdan okunur, komut satırına ya da çıktıya
# yazılmaz (curl'e netrc ile stdin'den verilir). Sauce oturumu AÇMAZ, dakika harcamaz.
#
#   scripts/github-sauce-kota.sh [--region eu-central-1]
#
# Çıktı alanları (okunamayan null): kalan_dk (hesabın kalan VM dakikası, Sauce'un bildirdiği),
#   kalan_mac_dk, kullanilan_dk (tüm geçmiş, usage ucu), es_vm (izinli eşzamanlı VM),
#   es_mac (izinli eşzamanlı Mac VM), es_vm_simdi (şu an süren).
# Hata çıkışı yok: erişilemezse alanlar null (iş akışını düşürmez).
set -uo pipefail
region="${SAUCE_REGION:-eu-central-1}"
while [ $# -gt 0 ]; do
  case "$1" in
    --region) region="${2:?}"; shift 2 ;;
    *) echo "bilinmeyen argüman: $1" >&2; exit 2 ;;
  esac
done
case "$region" in us-west-1|eu-central-1|us-east-4) ;; *) echo '{}'; exit 0 ;; esac
if [ -z "${SAUCE_USERNAME:-}" ] || [ -z "${SAUCE_ACCESS_KEY:-}" ]; then
  echo '{}'
  exit 0
fi
case "$SAUCE_USERNAME" in *[!A-Za-z0-9._@+-]*) echo '{}'; exit 0 ;; esac
host="api.$region.saucelabs.com"
al() { # $1 = yol; gövde stdout'a (hata → boş)
  printf 'machine %s login %s password %s\n' "$host" "$SAUCE_USERNAME" "$SAUCE_ACCESS_KEY" \
    | curl -fsS -m 20 --netrc-file /dev/stdin "https://$host$1" 2>/dev/null || true
}
d="$(mktemp -d)"
trap 'rm -rf "$d"' EXIT
al "/rest/v1/users/$SAUCE_USERNAME" > "$d/kul"
al "/rest/v1.2/users/$SAUCE_USERNAME/concurrency" > "$d/esz"
al "/rest/v1/users/$SAUCE_USERNAME/usage" > "$d/kullanim"
for f in kul esz kullanim; do jq -e . "$d/$f" >/dev/null 2>&1 || echo null > "$d/$f"; done
jq -cn --slurpfile kul "$d/kul" --slurpfile esz "$d/esz" --slurpfile kullanim "$d/kullanim" '
  def n: if type == "number" then . elif type == "string" and test("^-?[0-9]+(\\.[0-9]+)?$") then tonumber else null end;
  ($kul[0] // {}) as $k | ($esz[0] // {}) as $e | ($kullanim[0] // {}) as $u
  | {
      kalan_dk: (($k | objects | .minutes) // null | n),
      kalan_mac_dk: (($k | objects | .mac_minutes) // null | n),
      kullanilan_dk: (try (([($u.usage // [])[] | (.[1][1] // 0) | n // 0] | add // 0) / 60 * 10 | round / 10) catch null),
      es_vm: (try ($e.concurrency.organization.allowed.vms | n) catch null),
      es_mac: (try ($e.concurrency.organization.allowed.mac_vms | n) catch null),
      es_vm_simdi: (try ($e.concurrency.organization.current.vms | n) catch null)
    }' 2>/dev/null || echo '{}'
