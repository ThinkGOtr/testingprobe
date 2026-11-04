#!/usr/bin/env bash
# demo-web-sync — çalışan demo-app-web'i core'un istediği forge commit'inden yeniden derler.
#
#   scripts/demo-web-sync.sh                 # bekleyen istek varsa bir kez uygular
#   scripts/demo-web-sync.sh --wait break    # 'break' isteği gelene kadar (≤ TP_DEMO_SYNC_WAIT_S) bekler
#   scripts/demo-web-sync.sh --watch         # sürekli izler (sunum boyunca ayrı terminalde)
#   scripts/demo-web-sync.sh --main          # forge main'in güncel head'i için istek yazar ve uygular
#                                            # (ör. GitHub kipinde make up sonrası GitHub main'i)
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
# GitHub kipi (TP_FORGE=github): yerel forge arşivi yerine web ağacı toolchain-worker'ın salt
# okunur forge aynasından alınır — `python -m toolchain_common.mirror_export archive|tree --ref
# <sha> --path <web yolu>` (commit aynada yoksa TP_FORGE_REMOTE_URL'den salt okunur belirteçle
# çekilir; belirteç yalnızca toolchain-worker'dadır, bu betik görmez). Web yolu core-worker'dan
# (`forge_demo web-path`; GitHub'da varsayılan demo-app/web). TP_FORGE_REMOTE_URL boşsa açık
# hatayla durur. Derlenen imaj, istek ve .done akışı yerel kiple aynıdır.
#
# Kilit: aynı anda birden çok kopya çalışabilir (sunum boyunca açık --watch + make demo-break /
# demo-reset'in kendi --wait'i). Derleme + yeniden oluşturma forge volume'ünde atomik
# `mkdir /forge/demo-web-sync.lock` kilidi altında yapılır; kilidi tutan kopya isteği uygular,
# diğeri bekler. --wait, isteği başka bir kopya uyguladıysa (.done) başarıyla çıkar. Kilit
# TP_DEMO_SYNC_LOCK_STALE_S (600) sn'den eskiyse (çöken kopya) devralınır.
#
# Ortam: TP_FORGE_EXEC (varsayılan "docker compose exec -T core-worker"),
#        TP_TOOLCHAIN_EXEC (GitHub kipi; varsayılan "docker compose exec -T toolchain-worker"),
#        TP_DEMO_WEB_IMAGE (varsayılan ${TP_IMAGE_PREFIX:-testingprobe}-demo-app-web:local),
#        TP_DEMO_SYNC_WAIT_S (--wait / tek sefer kilit beklemesi, varsayılan 120),
#        TP_DEMO_SYNC_POLL_S (3), TP_DEMO_SYNC_LOCK_STALE_S (600).
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
    --main) MODE="main" ;;
    -h|--help) sed -n '2,36p' "$SELF" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "bilinmeyen argüman: $1" ;;
  esac
  shift
done

command -v docker >/dev/null 2>&1 || die "docker bulunamadı"
demo_exec_init
# shellcheck disable=SC2206  # komut öneki bilerek kelimelere bölünür
TOOLCHAIN_EXEC=(${TP_TOOLCHAIN_EXEC:-docker compose exec -T toolchain-worker})
WEB_IMAGE="${TP_DEMO_WEB_IMAGE:-${TP_IMAGE_PREFIX}-demo-app-web:local}"
POLL="${TP_DEMO_SYNC_POLL_S:-3}"
WAIT_LIMIT="${TP_DEMO_SYNC_WAIT_S:-120}"
KILIT_STALE="${TP_DEMO_SYNC_LOCK_STALE_S:-600}"
case "$KILIT_STALE" in ""|*[!0-9]*) die "TP_DEMO_SYNC_LOCK_STALE_S sayı olmalı" ;; esac

# sync_once / sync_kilitli dönüş kodları (1 = die: hata).
RC_ISTEK_YOK=10
RC_KILIT_MESGUL=11
# core-worker'a ulaşılamadı (exec başarısız: konteyner yeniden oluşturuluyor / yeniden başlıyor,
# Docker kısa süre yanıt vermiyor). --watch bunu loglayıp yeniden dener; tek sefer / --wait hata verir.
RC_GECICI=12

istek_oku() {
  "${DEMO_EXEC[@]}" sh -c 'cat /forge/demo-web-refresh.json 2>/dev/null || true'
}

done_oku() {
  "${DEMO_EXEC[@]}" sh -c 'cat /forge/demo-web-refresh.done 2>/dev/null || true' | tr -d '[:space:]'
}

# --- Kilit (forge volume'ünde; tüm kopyalar aynı core-worker volume'ünü görür) -------------------
# /forge/demo-web-sync.lock/owner: "<epoch> <sahip>". Zaman konteyner saatinden okunur (host ile
# saat kayması eskime hesabını bozmasın). Sahip yoksa dizinin mtime'ı kullanılır.
# Dönüş: 0 alındı · 1 meşgul (KILIT_MESAJ) · 2 exec başarısız (KILIT_MESAJ; geçici, çağıran karar verir).
KILIT_SAHIBI=""
KILIT_MESAJ=""

kilit_al() {
  local token out rc=0
  token="$(hostname 2>/dev/null || echo host):$$:$(date +%s):${RANDOM}"
  # shellcheck disable=SC2016  # $1/$2 iç kabukta genişler
  out="$("${DEMO_EXEC[@]}" sh -c '
L=/forge/demo-web-sync.lock
now=$(date +%s)
if mkdir "$L" 2>/dev/null; then printf "%s %s\n" "$now" "$1" > "$L/owner"; exit 0; fi
o=$(cat "$L/owner" 2>/dev/null || true)
t=${o%% *}
case "$t" in ""|*[!0-9]*) t=$(stat -c %Y "$L" 2>/dev/null || stat -f %m "$L" 2>/dev/null || echo "$now") ;; esac
yas=$((now - t))
if [ "$yas" -ge "$2" ]; then
  rm -rf "$L"
  if mkdir "$L" 2>/dev/null; then printf "%s %s\n" "$now" "$1" > "$L/owner"; echo "eski kilit devralındı (${yas} sn, ${o#* })"; exit 0; fi
  exit 3
fi
echo "sahip: ${o#* } · ${yas} sn"
exit 3' _ "$token" "$KILIT_STALE")" || rc=$?
  case "$rc" in
    0) KILIT_SAHIBI="$token"; [ -z "$out" ] || err "UYARI: $out"; return 0 ;;
    3) KILIT_MESAJ="$out"; return 1 ;;
    *) KILIT_MESAJ="eşitleme kilidi alınamadı (/forge/demo-web-sync.lock, çıkış $rc)"; return 2 ;;
  esac
}

kilit_birak() {
  [ -n "$KILIT_SAHIBI" ] || return 0
  # Yalnızca kendi kilidimizi siler (devralınmışsa dokunmaz).
  # shellcheck disable=SC2016  # $1 iç kabukta genişler
  "${DEMO_EXEC[@]}" sh -c '
L=/forge/demo-web-sync.lock
o=$(cat "$L/owner" 2>/dev/null || true)
[ "${o#* }" = "$1" ] && rm -rf "$L"
exit 0' _ "$KILIT_SAHIBI" >/dev/null 2>&1 || true
  KILIT_SAHIBI=""
}

trap 'kilit_birak' EXIT
trap 'exit 130' INT TERM

# Kilit altında sync_once. 0 · RC_ISTEK_YOK · RC_KILIT_MESGUL · RC_GECICI · 1 (hata).
sync_kilitli() {
  local rc=0
  kilit_al || rc=$?
  case "$rc" in
    0) ;;
    1) return "$RC_KILIT_MESGUL" ;;
    *) return "$RC_GECICI" ;;
  esac
  # sync_once hatada `die` (exit 1) çağırır: alt kabukta koşar ki kilit her durumda bırakılsın.
  ( sync_once ) || rc=$?
  kilit_birak
  return "$rc"
}

kilit_mesgul_bildir() {
  err "Başka bir demo-web-sync kopyası demo-app-web'i derliyor (${KILIT_MESAJ:-?}); bitmesi bekleniyor..."
  err "  (takılı kaldıysa: docker compose exec core-worker rm -rf /forge/demo-web-sync.lock)"
}

# İsteği uygular (kilit altında çağrılmalı: sync_kilitli). 0: uygulandı/zaten güncel ·
# RC_ISTEK_YOK: bekleyen istek yok (ya da başka kopya zaten uyguladı).
sync_once() {
  local req sha eylem istek_id done_id current calisan web_tree tmp eski_imaj yeni_imaj
  req="$(istek_oku)"
  [ -n "$req" ] || return "$RC_ISTEK_YOK"
  sha="$(printf '%s' "$req" | python3 -c '
import json, re, sys
d = json.load(sys.stdin)
s = str(d.get("sha") or "")
print(s if re.fullmatch(r"[0-9a-f]{40}", s) else "")')"
  [ -n "$sha" ] || die "geçersiz yenileme isteği: $req"
  eylem="$(printf '%s' "$req" | json_get eylem)"
  istek_id="$(printf '%s' "$req" | json_get istek_id)"
  case "$istek_id" in *[!0-9a-f]*|"") die "geçersiz istek kimliği" ;; esac
  done_id="$(done_oku)"
  [ "$done_id" != "$istek_id" ] || return "$RC_ISTEK_YOK"
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
    tmp="$(mktemp "${TMPDIR:-/tmp}/tp-demo-web.XXXXXX")"
    case "$forge_kind" in
      local)
        "${DEMO_EXEC[@]}" python -m tp_core.integrations.forge_demo archive --ref "$sha" --path web >"$tmp" \
          || { rm -f "$tmp"; die "forge arşivi alınamadı ($sha)"; }
        tar -tf "$tmp" | grep -qx 'Dockerfile' || { rm -f "$tmp"; die "arşivde web/Dockerfile yok"; }
        web_tree="$("${DEMO_EXEC[@]}" git -c safe.directory='*' --git-dir=/forge/demo-app.git \
          rev-parse "$sha:web" | tr -d '[:space:]')"
        kaynak="yerel forge"
        ;;
      github)
        web_yolu="$("${DEMO_EXEC[@]}" python -m tp_core.integrations.forge_demo web-path | json_get web_yolu)"
        case "$web_yolu" in
          ""|/*|*..*|*[!A-Za-z0-9._/-]*) rm -f "$tmp"; die "geçersiz web yolu: '$web_yolu' (forge_demo web-path)" ;;
        esac
        # shellcheck disable=SC2016  # TP_FORGE_REMOTE_URL konteynerde (iç kabukta) genişler
        uzak="$("${TOOLCHAIN_EXEC[@]}" sh -c 'printf %s "${TP_FORGE_REMOTE_URL:-}"')" \
          || { rm -f "$tmp"; die "toolchain-worker'a erişilemiyor (make up?)"; }
        [ -n "$uzak" ] || { rm -f "$tmp"; die "TP_FORGE=github: toolchain-worker'da TP_FORGE_REMOTE_URL boş; GitHub main aynaya çekilemez (docs/GERCEK-SISTEMLER.md §5)"; }
        "${TOOLCHAIN_EXEC[@]}" python -m toolchain_common.mirror_export archive --ref "$sha" --path "$web_yolu" >"$tmp" \
          || { rm -f "$tmp"; die "GitHub aynasından web arşivi alınamadı ($sha:$web_yolu)"; }
        tar -tf "$tmp" | grep -qx 'Dockerfile' || { rm -f "$tmp"; die "arşivde $web_yolu/Dockerfile yok"; }
        web_tree="$("${TOOLCHAIN_EXEC[@]}" python -m toolchain_common.mirror_export tree --ref "$sha" --path "$web_yolu" | tr -d '[:space:]')"
        kaynak="GitHub aynası"
        ;;
      *) rm -f "$tmp"; die "bilinmeyen TP_FORGE: $forge_kind (local | github)" ;;
    esac
    case "$web_tree" in
      *[!0-9a-f]*|"") rm -f "$tmp"; die "web ağacı kimliği okunamadı ($sha)" ;;
    esac
    echo "demo-app-web derleniyor ($kaynak): $eylem @ ${sha:0:12} (web ağacı ${web_tree:0:12})"
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
    echo "demo-app-web = forge $sha ($kaynak)"
  fi
  # shellcheck disable=SC2016
  "${DEMO_EXEC[@]}" sh -c 'umask 022; printf "%s\n" "$1" > /forge/demo-web-refresh.done' _ "$istek_id" \
    || die "/forge/demo-web-refresh.done yazılamadı"
  return 0
}

if [ "$MODE" = main ]; then
  # Forge main'in güncel head'i için istek (core-worker yazar; GitHub'da main GitHub'dan okunur),
  # sonra tek sefer uygulanır.
  "${DEMO_EXEC[@]}" python -m tp_core.features.demo web-istek --eylem sync \
    --isteyen "demo-web-sync:${USER:-host}" >/dev/null \
    || die "yenileme isteği yazılamadı (core-worker / forge erişimi)"
  MODE=once
fi

case "$MODE" in
  once)
    start="$(date +%s)"; bildirildi=0
    while :; do
      rc=0; sync_kilitli || rc=$?
      case "$rc" in
        0) exit 0 ;;
        "$RC_ISTEK_YOK") echo "Bekleyen demo uygulaması yenileme isteği yok."; exit 0 ;;
        "$RC_KILIT_MESGUL") ;;
        "$RC_GECICI") die "$KILIT_MESAJ" ;;
        *) exit "$rc" ;;
      esac
      [ "$bildirildi" = 1 ] || { kilit_mesgul_bildir; bildirildi=1; }
      [ $(( $(date +%s) - start )) -lt "$WAIT_LIMIT" ] \
        || die "${WAIT_LIMIT} sn içinde eşitleme kilidi boşalmadı (${KILIT_MESAJ:-?})"
      sleep "$POLL"
    done
    ;;
  wait)
    start="$(date +%s)"; bildirildi=0
    # Başlarken zaten uygulanmış istek eski istektir (önceki kırılma/sıfırlama): beklenmez.
    # Bundan sonra gelen istek ya bu kopya tarafından (kilit altında) ya da başka bir kopya
    # (ör. --watch) tarafından uygulanır; ikisi de başarıdır.
    eski_id=""
    req="$(istek_oku)"
    if [ -n "$req" ]; then
      id0="$(printf '%s' "$req" | json_get istek_id)"
      [ -z "$id0" ] || [ "$(done_oku)" != "$id0" ] || eski_id="$id0"
    fi
    while :; do
      req="$(istek_oku)"
      if [ -n "$req" ] && { [ -z "$WAIT_EYLEM" ] || [ "$(printf '%s' "$req" | json_get eylem)" = "$WAIT_EYLEM" ]; }; then
        istek_id="$(printf '%s' "$req" | json_get istek_id)"
        if [ -n "$istek_id" ] && [ "$istek_id" != "$eski_id" ]; then
          if [ "$(done_oku)" = "$istek_id" ]; then
            echo "demo-app-web '${WAIT_EYLEM:-istek}' için başka bir eşitleyici tarafından güncellendi."
            exit 0
          fi
          rc=0; sync_kilitli || rc=$?
          case "$rc" in
            0) exit 0 ;;
            "$RC_ISTEK_YOK") continue ;;  # bu arada başka kopya uyguladı: .done yeniden okunur
            "$RC_KILIT_MESGUL")
              [ "$bildirildi" = 1 ] || { kilit_mesgul_bildir; bildirildi=1; } ;;
            "$RC_GECICI") die "$KILIT_MESAJ" ;;
            *) exit "$rc" ;;
          esac
        fi
      fi
      [ $(( $(date +%s) - start )) -lt "$WAIT_LIMIT" ] || die "${WAIT_LIMIT} sn içinde '${WAIT_EYLEM:-herhangi}' isteği uygulanmadı"
      sleep "$POLL"
    done
    ;;
  watch)
    echo "demo-app-web yenileme istekleri izleniyor (Ctrl-C ile çıkış)..."
    ulasilamadi=0
    while :; do
      # Tek bir geçici hata (docker build, arşiv, yeniden oluşturma) sunum boyunca açık izleyiciyi
      # öldürmesin: sync_once alt kabukta koşar, hata mesajı zaten stderr'e yazılır. Kilit
      # meşgulse (make demo-break/demo-reset'in --wait'i derliyor) bir sonraki turda bakılır.
      # core-worker'a ulaşılamıyorsa (make demo-prova / make reset / make up yeniden oluşturuyor,
      # çökme sonrası yeniden başlıyor) izleyici çıkmaz: bir kez uyarır, gelince bildirir.
      rc=0
      sync_kilitli || rc=$?
      if [ "$rc" = "$RC_GECICI" ]; then
        if [ "$ulasilamadi" = 0 ]; then
          err "UYARI: core-worker'a ulaşılamıyor ($KILIT_MESAJ); her ${POLL} sn yeniden denenecek (izleyici açık kalır)"
          ulasilamadi=1
        fi
      else
        if [ "$ulasilamadi" = 1 ]; then
          err "core-worker yeniden erişilebilir; izleme sürüyor."
          ulasilamadi=0
        fi
        case "$rc" in
          0|"$RC_ISTEK_YOK"|"$RC_KILIT_MESGUL") ;;
          *) err "eşitleme başarısız (çıkış $rc); ${POLL} sn sonra yeniden denenecek" ;;
        esac
      fi
      sleep "$POLL"
    done
    ;;
esac
