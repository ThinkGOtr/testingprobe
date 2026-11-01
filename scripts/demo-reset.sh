#!/usr/bin/env bash
# demo-reset — demo durumunu sunumun başına döndürür (verileri silmeden).
#
#   scripts/demo-reset.sh          # API yolu: POST /api/demo/reset (main → demo-baseline,
#                                  # açık tp/* ve kırılma PR'ları kapatılır, bağlı script'ler
#                                  # closed), demo-app-web baseline'dan derlenir; jira-sim'de
#                                  # yalnızca sistemin açtığı Bug'lar (AI-generated + tp-<uuid>)
#                                  # silinir — jira-sim SIFIRLANMAZ
#   scripts/demo-reset.sh --full   # tam sıfırlama: make reset (denetim dışa aktarılır, çekirdek
#                                  # veri ve artefaktlar silinir, forge/jira-sim/seed yeniden)
#
# API yolu çekirdek veritabanına dokunmaz (denetim append-only); geçmiş koşular, hata analizleri ve
# bug taslakları kalır. Bu yüzden jira-sim de sıfırlanmaz: /sim/reset anahtar sayacını geri sarar,
# veritabanındaki Test issue anahtarları (external_ref) yok olur ve yeni Bug'lar eski anahtarları
# yeniden alır (çakışma). Temiz prova için --full kullanın (TEKNIK-TASARIM §13).
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
# shellcheck source=scripts/demo-common.sh
. "$(dirname "$SELF")/demo-common.sh"

case "${1:-}" in
  --full) exec "$TP_REPO_ROOT/scripts/reset.sh" ;;
  -h|--help) sed -n '2,13p' "$SELF" | sed 's/^# \{0,1\}//'; exit 0 ;;
  "") ;;
  *) die "bilinmeyen argüman: $1 (kullanım: demo-reset.sh [--full])" ;;
esac

demo_api_login
echo "Demo sıfırlaması isteniyor (POST /api/demo/reset)..."
demo_api_post /demo/reset
yanit="$DEMO_BODY"
case "$DEMO_HTTP" in
  200|202) ;;
  *) die "sıfırlama reddedildi (HTTP $DEMO_HTTP): $(printf '%s' "$yanit" | json_get detail)" ;;
esac
printf '%s' "$yanit" | python3 -c '
import json, sys
d = json.load(sys.stdin)
s = d.get("sonuc") or {}
f = s.get("forge") or {}
print("  iş: %s · main → %s (değişti: %s)" % (
    d.get("job_id"), str(f.get("main_sonra"))[:12], f.get("degisti")))
for k in s.get("kapanan_prlar") or []:
    hata = k.get("hata")
    print("  PR #%s (%s) kapatıldı%s" % (k.get("pr"), k.get("dal"), " — hata: %s" % hata if hata else ""))
j = s.get("jira") or {}
if j.get("silinen") is not None:
    print("  jira-sim: %d AI Bug silindi (%s); sıfırlanmadı" % (
        len(j["silinen"]), ", ".join(j["silinen"]) or "-"))
for h in j.get("hatalar") or []:
    print("  UYARI: %s silinemedi: %s" % (h.get("key"), h.get("hata")))
if j.get("durum") in ("hata", "atlandi") and j.get("neden"):
    print("  jira: %s — %s" % (j.get("durum"), j.get("neden")))
'
"$TP_REPO_ROOT/scripts/demo-web-sync.sh" --wait baseline

echo "Tamam: demo başlangıç durumunda (veritabanı korunur; tam sıfırlama: scripts/demo-reset.sh --full)."
