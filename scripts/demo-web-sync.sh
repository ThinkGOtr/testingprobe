#!/usr/bin/env bash
# demo-web-sync — çalışan demo-app-web'i core'un istediği forge commit'inden yeniden derler.
#
#   scripts/demo-web-sync.sh                 # bekleyen istek varsa bir kez uygular
#   scripts/demo-web-sync.sh --wait break    # 'break' isteği gelene kadar (≤ TP_DEMO_SYNC_WAIT_S) bekler
#   scripts/demo-web-sync.sh --watch         # sürekli izler (sunum boyunca ayrı terminalde)
#
# Neden: toolchain /check testleri compose'da ÇALIŞAN demo-app-web'e karşı koşar; uygulama main'in
# web/ ağacını yansıtmazsa koşu yapılmaz (ortam). core-worker imaj derleyemez; `POST
# /demo/break-locator` ve `POST /demo/reset` forge volume'üne istek yazar:
#   /forge/demo-web-refresh.json  {istek_id, eylem, sha, zaman, isteyen}
# Bu betik isteği okur, `forge_demo archive --ref <sha> --path web` arşivinden imajı derler
# (DEMO_APP_BUILD_SHA / DEMO_APP_WEB_TREE → /build.json), servisi yeniden oluşturur ve
# /forge/demo-app-web.sha'yı yazar. core'daki `demo.await_web` işi bunu görünce push CI'ını
# kuyruğa alır. Uygulanan istek /forge/demo-web-refresh.done'a yazılır (idempotent).
#
# Ortam: TP_FORGE_EXEC (varsayılan "docker compose exec -T core-worker"),
#        TP_DEMO_WEB_IMAGE (varsayılan testingprobe-demo-app-web:local),
#        TP_DEMO_SYNC_WAIT_S (--wait için, varsayılan 120), TP_DEMO_SYNC_POLL_S (3).
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
# shellcheck source=scripts/demo-common.sh
. "$(dirname "$SELF")/demo-common.sh"

MODE=once
WAIT_EYLEM=""
while [ $# -gt 0 ]; do
  case "$1" in
    --watch) MODE="watch" ;;
    --wait)
      if [ $# -lt 2 ] || [ -z "$2" ] || [ "${2#-}" != "$2" ]; then
        die "--wait bir eylem ister (break|baseline). Kullanım: demo-web-sync.sh --wait <eylem>"
      fi
      MODE="wait"; WAIT_EYLEM="$2"; shift ;;
    -h|--help) sed -n '2,22p' "$SELF" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "bilinmeyen argüman: $1" ;;
  esac
  shift
done

command -v docker >/dev/null 2>&1 || die "docker bulunamadı"
demo_exec_init
WEB_IMAGE="${TP_DEMO_WEB_IMAGE:-testingprobe-demo-app-web:local}"
POLL="${TP_DEMO_SYNC_POLL_S:-3}"

istek_oku() {
  "${DEMO_EXEC[@]}" sh -c 'cat /forge/demo-web-refresh.json 2>/dev/null || true'
}

# İsteği uygular. 0: uygulandı/zaten güncel · 1: bekleyen istek yok.
sync_once() {
  local req sha eylem istek_id done_id current calisan web_tree tmp eski_imaj yeni_imaj
  req="$(istek_oku)"
  [ -n "$req" ] || return 1
  sha="$(printf '%s' "$req" | python3 -c '
import json, re, sys
d = json.load(sys.stdin)
s = str(d.get("sha") or "")
print(s if re.fullmatch(r"[0-9a-f]{40}", s) else "")')"
  [ -n "$sha" ] || die "geçersiz yenileme isteği: $req"
  eylem="$(printf '%s' "$req" | json_get eylem)"
  istek_id="$(printf '%s' "$req" | json_get istek_id)"
  case "$istek_id" in *[!0-9a-f]*|"") die "geçersiz istek kimliği" ;; esac
  done_id="$("${DEMO_EXEC[@]}" sh -c 'cat /forge/demo-web-refresh.done 2>/dev/null || true' | tr -d '[:space:]')"
  [ "$done_id" != "$istek_id" ] || return 1
  current="$("${DEMO_EXEC[@]}" sh -c 'head -n 1 /forge/demo-app-web.sha 2>/dev/null || true' | tr -d '[:space:]')"
  # Çalışan uygulamanın kendi beyanı (/build.json) esas: sha dosyası tek başına yetmez (eski imaj
  # çalışırken dosya güncel kalmış olabilir). web-state okunamazsa sha dosyasına düşülür.
  calisan="$("${DEMO_EXEC[@]}" python -m tp_core.integrations.forge_demo web-state 2>/dev/null \
    | python3 -c 'import json,sys
try: print(((json.load(sys.stdin) or {}).get("calisan") or {}).get("sha") or "")
except ValueError: print("?")' 2>/dev/null || echo "?")"
  if [ "$calisan" = "$sha" ] || { [ "$calisan" = "?" ] && [ "$current" = "$sha" ]; }; then
    echo "demo-app-web zaten $sha ($eylem)."
    if [ "$current" != "$sha" ]; then
      # shellcheck disable=SC2016  # $1 iç kabukta genişler
      "${DEMO_EXEC[@]}" sh -c 'umask 022; printf "%s\n" "$1" > /forge/demo-app-web.sha.tmp && mv -f /forge/demo-app-web.sha.tmp /forge/demo-app-web.sha' _ "$sha" \
        || die "/forge/demo-app-web.sha yazılamadı"
    fi
  else
    # shellcheck disable=SC2016  # TP_FORGE konteynerde (iç kabukta) genişler
    forge_kind="$("${DEMO_EXEC[@]}" sh -c 'printf %s "${TP_FORGE:-local}"')"
    [ "$forge_kind" = local ] || die "TP_FORGE=$forge_kind: demo-app-web yerel forge'dan derlenmez"
    tmp="$(mktemp "${TMPDIR:-/tmp}/tp-demo-web.XXXXXX")"
    "${DEMO_EXEC[@]}" python -m tp_core.integrations.forge_demo archive --ref "$sha" --path web >"$tmp" \
      || { rm -f "$tmp"; die "forge arşivi alınamadı ($sha)"; }
    tar -tf "$tmp" | grep -qx 'Dockerfile' || { rm -f "$tmp"; die "arşivde web/Dockerfile yok"; }
    web_tree="$("${DEMO_EXEC[@]}" git -c safe.directory='*' --git-dir=/forge/demo-app.git \
      rev-parse "$sha:web" | tr -d '[:space:]')"
    echo "demo-app-web derleniyor: $eylem @ ${sha:0:12} (web ağacı ${web_tree:0:12})"
    eski_imaj="$(docker image inspect -f '{{.Id}}' "$WEB_IMAGE" 2>/dev/null || true)"
    docker build -q --build-arg "DEMO_APP_BUILD_SHA=$sha" --build-arg "DEMO_APP_WEB_TREE=$web_tree" \
      -t "$WEB_IMAGE" - <"$tmp" >/dev/null || { rm -f "$tmp"; die "demo-app-web derlenemedi"; }
    rm -f "$tmp"
    compose up -d --no-build --no-deps --force-recreate --wait demo-app-web \
      || die "demo-app-web yeniden başlatılamadı"
    # shellcheck disable=SC2016  # $1 iç kabukta genişler
    "${DEMO_EXEC[@]}" sh -c 'umask 022; printf "%s\n" "$1" > /forge/demo-app-web.sha.tmp && mv -f /forge/demo-app-web.sha.tmp /forge/demo-app-web.sha' _ "$sha" \
      || die "/forge/demo-app-web.sha yazılamadı"
    yeni_imaj="$(docker image inspect -f '{{.Id}}' "$WEB_IMAGE" 2>/dev/null || true)"
    if [ -n "$eski_imaj" ] && [ "$eski_imaj" != "$yeni_imaj" ]; then
      docker image rm "$eski_imaj" >/dev/null 2>&1 || true  # kullanımdaysa sessizce kalır
    fi
    echo "demo-app-web = forge $sha"
  fi
  # shellcheck disable=SC2016
  "${DEMO_EXEC[@]}" sh -c 'umask 022; printf "%s\n" "$1" > /forge/demo-web-refresh.done' _ "$istek_id" \
    || die "/forge/demo-web-refresh.done yazılamadı"
  return 0
}

case "$MODE" in
  once)
    sync_once || echo "Bekleyen demo uygulaması yenileme isteği yok."
    ;;
  wait)
    limit="${TP_DEMO_SYNC_WAIT_S:-120}"
    start="$(date +%s)"
    while :; do
      req="$(istek_oku)"
      if [ -n "$req" ] && { [ -z "$WAIT_EYLEM" ] || [ "$(printf '%s' "$req" | json_get eylem)" = "$WAIT_EYLEM" ]; }; then
        sync_once && exit 0
      fi
      [ $(( $(date +%s) - start )) -lt "$limit" ] || die "${limit} sn içinde '${WAIT_EYLEM:-herhangi}' isteği gelmedi"
      sleep "$POLL"
    done
    ;;
  watch)
    echo "demo-app-web yenileme istekleri izleniyor (Ctrl-C ile çıkış)..."
    while :; do
      # sync_once hatada `die` (exit 1) çağırır: alt kabukta koşar ki tek bir geçici hata
      # (docker build, arşiv, yeniden oluşturma) sunum boyunca açık izleyiciyi öldürmesin.
      # Çıkış 1 hem "istek yok" hem hata olabilir; hata mesajı zaten stderr'e yazılır.
      rc=0
      ( sync_once ) || rc=$?
      [ "$rc" -le 1 ] || err "eşitleme başarısız (çıkış $rc); ${POLL} sn sonra yeniden denenecek"
      sleep "$POLL"
    done
    ;;
esac
