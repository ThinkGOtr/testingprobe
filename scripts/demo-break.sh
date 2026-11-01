#!/usr/bin/env bash
# demo-break — demo locator kırılması (TEKNIK-TASARIM §2 adım 12, §10).
#
#   scripts/demo-break.sh          # API yolu (sunucu oturumu): POST /api/demo/break-locator,
#                                  # ardından demo-app-web forge main'den yeniden derlenir
#   scripts/demo-break.sh --make   # host yolu (make break): ön koşul denetimi, sonra
#                                  # scripts/forge-init.sh break
#   scripts/demo-break.sh --zorla  # yeşil temel koşu yoksa da kır (onarım sonra engellenir)
#
# Ön koşul: kırılmadan ÖNCE en az bir yeşil koşu (baseline push CI). Locator onarımı rol + adı
# "son yeşil" kanıta karşı doğrular; `make reset` sonrası veritabanında koşu yoktur → önce
# `make demo-reset` (baseline push CI kuyruğa alınır) ve koşu yeşile dönünce kırın. API yolu bunu
# denetler (409 + yönerge). --make yolu aynı denetimi core-worker'da veritabanından yapar
# (`python -m tp_core.features.demo on-kosul`; ret `demo.break_refused` olarak denetlenir) ve
# denetlenemezse (core-worker yok) KIRMAZ. Locator demosu yalnızca TP_FORGE=local'dır: GitHub
# kipinde iki yol da reddeder (çalışan demo-app-web GitHub main'inden derlenmez).
#
# API yolu: core-worker `demo/break-locator` dalını demo-admin bypass'ıyla merge eder (denetim:
# "demo kırılması" + isteyen sunucu `demo.break`), uygulama yenileme isteği yazar; bu betik isteği
# demo-web-sync.sh ile uygular; core `demo.await_web` uygulama main'i yansıtınca main için push
# CI'ını kuyruğa alır → CI kırmızı → triage test_maintenance/locator → portalda "Onarım PR'ı aç".
# Ortam: TP_DEMO_USER / TP_DEMO_PASSWORD / TP_API_URL (demo-common.sh).
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
# shellcheck source=scripts/demo-common.sh
. "$(dirname "$SELF")/demo-common.sh"

# /demo/status → onarim_on_kosulu: 0 hazır · 1 yeşil temel koşu yok · 2 denetlenemedi.
on_kosul() {
  local durum
  durum="$(demo_api_get /demo/status 2>/dev/null)" || return 2
  printf '%s' "$durum" | python3 -c '
import json, sys
try:
    o = (json.load(sys.stdin) or {}).get("onarim_on_kosulu") or {}
except ValueError:
    sys.exit(2)
if o.get("hazir") is True:
    k = o.get("son_yesil_kosu") or {}
    print("  son yeşil koşu: %s (%s, %s)" % (str(k.get("run_id"))[:8], k.get("tetik"),
          str(k.get("commit"))[:12]))
    sys.exit(0)
if o.get("hazir") is False:
    print("  UYARI: kırılmadan önce yeşil koşu yok. " + str(o.get("yonerge") or ""))
    sys.exit(1)
sys.exit(2)'
}

ZORLA=0
MAKE=0
for arg in "$@"; do
  case "$arg" in
    --make) MAKE=1 ;;
    --zorla) ZORLA=1 ;;
    -h|--help) sed -n '2,20p' "$SELF" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "bilinmeyen argüman: $arg (kullanım: demo-break.sh [--make] [--zorla])" ;;
  esac
done

if [ "$MAKE" = 1 ]; then
  # Host yolu core API'sini atlar: ön koşul core-worker'da veritabanından denetlenir
  # (POST /demo/break-locator ile aynı kurallar). Denetlenemezse kırılma yapılmaz.
  demo_exec_init
  zorla_arg=()
  [ "$ZORLA" != 1 ] || zorla_arg=(--zorla)
  rc=0
  cikti="$("${DEMO_EXEC[@]}" python -m tp_core.features.demo on-kosul --isteyen "make-break:${USER:-host}" ${zorla_arg[@]+"${zorla_arg[@]}"})" || rc=$?
  case "$rc" in
    0)
      uyari="$(printf '%s' "$cikti" | json_get uyari)"
      [ -z "$uyari" ] || err "UYARI: $uyari"
      ;;
    3)
      neden="$(printf '%s' "$cikti" | json_get neden)"
      if printf '%s' "$neden" | grep -q "TP_FORGE=local"; then
        die "$neden"
      fi
      die "${neden:-kırılma yapılmadı (yeşil temel koşu yok).} Bilerek atlamak için: scripts/demo-break.sh --make --zorla"
      ;;
    *)
      die "onarım ön koşulu denetlenemedi (core-worker'a ulaşılamadı, çıkış $rc); kırılma yapılmadı. make up ile servisleri başlatın."
      ;;
  esac
  exec "$TP_REPO_ROOT/scripts/forge-init.sh" break
fi

demo_api_login
on_kosul || true
echo "Demo kırılması isteniyor (POST /api/demo/break-locator)..."
if [ "$ZORLA" = 1 ]; then
  demo_api_post "/demo/break-locator?zorla=true"
else
  demo_api_post /demo/break-locator
fi
yanit="$DEMO_BODY"
case "$DEMO_HTTP" in
  200|202) ;;
  *) die "kırılma reddedildi (HTTP $DEMO_HTTP): $(printf '%s' "$yanit" | json_get detail)" ;;
esac
printf '%s' "$yanit" | python3 -c '
import json, sys
d = json.load(sys.stdin)
s = d.get("sonuc") or {}
print("  iş: %s · durum: %s" % (d.get("job_id"), d.get("durum") or d.get("is_durumu")))
if s:
    print("  değişti: %s · PR #%s · main %s · testid %s" % (
        s.get("degisti"), s.get("pr"), str(s.get("main_sonra"))[:12], s.get("testid")))
'
"$TP_REPO_ROOT/scripts/demo-web-sync.sh" --wait break
echo "Tamam: main kırık, demo-app-web main'den derlendi; push CI kuyruğa alınacak (Kontrol Kulesi)."
