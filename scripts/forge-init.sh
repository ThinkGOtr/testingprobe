#!/usr/bin/env bash
# forge-init — yerel forge'u (LocalForge) hazırlar: tp_forge volume'ünde bare git deposu.
#
#   scripts/forge-init.sh            # depo yoksa oluşturur; varsa yalnızca izinleri düzeltir
#   scripts/forge-init.sh --force    # depoyu ve PR kaydını (tp-prs.json) silip yeniden oluşturur
#   scripts/forge-init.sh break      # demo locator kırılması (make break): aşağıya bakın
#   scripts/forge-init.sh baseline   # main → demo-baseline + demo-app-web yeniden derleme
#   scripts/forge-init.sh status     # forge main sha'sı ve "Sepete ekle" testid durumu
#   scripts/forge-init.sh sync-web   # forge main ≠ demo-baseline ise demo-app-web'i forge main'den
#                                    # yeniden derler (make up, kırık demoyu çalışma ağacıyla ezmesin)
#   scripts/forge-init.sh sync-dizin <dizin> [--baseline] [--koru <alt-yol>[,<alt-yol>...]]
#                                    # MEVCUT depoya demo-app/<dizin>'i main'e TEK commit ile ekler /
#                                    # eşitler (ör. e2e-java); PR kaydı ve diğer dallar korunur
#
# GitHub kipi (TP_FORGE=github): break/baseline core-worker'da insan kimliğiyle (GITHUB_MERGE_TOKEN,
#   demo-admin bypass) PR olarak yapılır (bot kullanılmaz); demo-app-web ardından
#   `scripts/demo-web-sync.sh --main` ile GitHub main'inden (toolchain-worker aynası) derlenir.
#
# break: core-worker içinde `python -m tp_core.integrations.forge_demo break` çalışır:
#   demo/break-locator → main PR'ı açılır, demo-admin kural bypass'ıyla (PR head sha'sına bağlı)
#   merge edilir, denetim kaydına "demo kırılması" yazılır. Ardından demo-app-web imajı forge
#   main HEAD'inin web/ arşivinden (çalışma ağacından değil) derlenir ve servis yeniden
#   oluşturulur. İkisi de idempotenttir (zaten kırıksa/baseline'daysa forge'a dokunulmaz).
#   Derleme de idempotenttir: `forge_demo web-state` çalışan uygulamanın /build.json'u main'i
#   (commit ya da web/ ağacı) yansıtıyor derse "demo-app-web zaten <sha>" yazılır, derleme ve
#   yeniden oluşturma atlanır (yalnızca /forge/demo-app-web.sha gerekirse düzeltilir) — süren
#   push CI'ı öldürülmez. Yeniden oluşturma gerekiyorsa ve ci.run/repair.fix işi koşuyorsa
#   betik durur (--force ya da TP_DEMO_WEB_FORCE=1 zorlar; bitince `sync-web`).
#   Ortam: TP_FORGE_EXEC (varsayılan "docker compose exec -T core-worker"),
#          TP_DEMO_WEB_IMAGE (varsayılan ${TP_IMAGE_PREFIX:-testingprobe}-demo-app-web:local),
#          TP_DEMO_WEB_DEPLOY=0 → yalnızca imajı derler, servisi yeniden oluşturmaz,
#          TP_DEMO_WEB_FORCE=1 (ya da --force) → güncel olsa / iş koşsa da derler + oluşturur.
#
# sync-dizin <dizin>: --force'un aksine depoyu silmez. demo-app/<dizin>'in çalışma ağacındaki içeriği
#   (init ile aynı dışlamalar + target/results/kanit + alt .gitignore'lar) main'in üstüne tek commit
#   olarak yazılır ve hızlı ileri (fast-forward) eklenir; değişiklik yoksa hiçbir şey yazılmaz
#   (idempotent). Tüm ref'ler yerelde hazırlanıp depoya tek atomik `git fetch` ile yazılır (depo
#   receive.denyNonFastforwards=true; bir adım düşerse hiçbir ref değişmez). Commit yalnızca
#   <dizin>/ altına dokunur; tp-prs.json, açık PR dalları ve demo-app-web.sha değişmez. Uygulama
#   dizinleri (web, api) kabul edilmez (çalışan uygulama eşleşmesi: make reset).
#   --baseline: main demo-baseline'dayken etiketi de yeni commit'e taşır ve demo/break-locator'ı
#   (tek commit) onun üstüne yeniden kurar; böylece make demo-reset/make break eklenen dizini
#   silmez. --baseline olmadan sıfırlama (main → demo-baseline) eklenen dizini geri alır.
#   --koru <alt-yol>: <dizin> altındaki bu yollar forge main'deki hâliyle KALIR (çalışma ağacındaki
#   içerik yok sayılır; forge'da yoksa eklenmez). Tek ad (ör. `uretilen`) her derinlikteki o adlı
#   dizini (ör. src/test/java/**/uretilen/**: merge edilmiş üretilen Java testleri), `/` içeren
#   yol (ör. `tests/generated`) <dizin>/'e göre o yolu korur. Virgülle ya da tekrarla birden çok.
#   Kaynak deposunun hook'ları çalışmaz (tüm git çağrıları core.hooksPath=/dev/null; GÜV-Y2).
#   Volume yoksa oluşturulmaz, hata verilir (yanlış COMPOSE_PROJECT_NAME'de boş volume kalmasın).
#   Örnek (011, mevcut LocalForge'a web + Java projesi): make forge-sync-dizin D=e2e-java B=--baseline
#   Örnek (011 dağıtımı, K-T14: güvenilir pom değişti, merge edilmiş testler korunur):
#     make forge-sync-dizin D=e2e-app K=uretilen   ve   make forge-sync-dizin D=e2e-java K=uretilen

# Oluşan içerik (/forge/demo-app.git):
#   main                 ← demo-app/ dizininin ŞU ANKİ içeriği (api/, web/, e2e/, ci/, README) kök olarak
#   demo-baseline (tag)  ← main'in ilk commit'i (make reset buraya döner)
#   demo/break-locator   ← main + tek commit: web kaynağında "Sepete ekle" butonunun
#                          data-testid'si add-to-cart → cart-add (yalnızca bu değer değişir)
# Commit tarihleri sabittir: aynı demo-app içeriği her seferinde aynı commit sha'larını üretir.
#
# Sahiplik/izinler: depo `10001:1001` (core uid : toolchain pwuser gid) sahipliğinde,
# `core.sharedRepository=0666` ile oluşturulur ve `chmod -R a+rwX` uygulanır; /forge 0777'dir
# (LocalForge PR kaydını /forge/tp-prs.json olarak yazar). Böylece core-worker (uid 10001) ve
# toolchain-worker (uid 1001) aynı depoya yazabilir. Sahibi olmayan uid ile çalışan git
# "dubious ownership" verir: istemciler `-c safe.directory=*` (veya depo yolu) kullanmalıdır
# (LocalForge bunu yapar).
#
# Çalıştırma: tek kullanımlık konteyner (core imajı; git içerir), ağ kapalı, demo-app salt okunur.
# Ortam: TP_FORGE_VOLUME (varsayılan ${COMPOSE_PROJECT_NAME:-testingprobe}_tp_forge), TP_FORGE_SRC (varsayılan demo-app),
#        TP_FORGE_IMAGE (varsayılan ${TP_IMAGE_PREFIX:-testingprobe}-core:local; yoksa core/ dizininden build edilir).
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"

FORCE=0
MODE=init
DIZIN=""
BASELINE=0
KORU=""
KULLANIM="forge-init.sh [--force] | break | baseline | status | sync-web | sync-dizin <dizin> [--baseline] [--koru <alt-yol>]"
while [ $# -gt 0 ]; do
  case "$1" in
    --force) FORCE=1 ;;
    --baseline) BASELINE=1 ;;
    --koru)
      [ $# -ge 2 ] || die "--koru bir alt yol ister (ör. uretilen)"
      KORU="${KORU:+$KORU,}$2"
      shift
      ;;
    break|baseline|status|sync-web) MODE="$1" ;;
    sync-dizin)
      MODE=sync-dizin
      [ $# -ge 2 ] || die "sync-dizin bir dizin adı ister (ör. e2e-java)"
      DIZIN="$2"
      shift
      ;;
    -h|--help) sed -n '/^set -euo/q;2,$p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "bilinmeyen argüman: $1 (kullanım: $KULLANIM)" ;;
  esac
  shift
done
[ "$BASELINE" = 0 ] || [ "$MODE" = sync-dizin ] || die "--baseline yalnızca sync-dizin ile anlamlıdır"
[ -z "$KORU" ] || [ "$MODE" = sync-dizin ] || die "--koru yalnızca sync-dizin ile anlamlıdır"
if [ "$MODE" = sync-dizin ]; then
  # Yalnızca demo-app'in tek bir üst düzey dizini; yol geçişi ve uygulama dizinleri reddedilir.
  # bash regex tüm dizeyi eşler (satır tabanlı grep'in aksine yeni satırlı '..\ne2e-java' geçmez).
  [[ "$DIZIN" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] \
    || die "geçersiz dizin adı: '$DIZIN' (demo-app altında tek düzey, ör. e2e-java)"
  case "$DIZIN" in
    web|api) die "sync-dizin $DIZIN: uygulama dizini eşitlenmez (çalışan demo-app-web eşleşmesi); make reset kullanın" ;;
  esac
  [ "$FORCE" = 0 ] || die "sync-dizin --force ile birlikte kullanılamaz (--force depoyu siler)"
  # --koru: <dizin>'e göre alt yollar; her parça harf/rakamla başlar (.., mutlak yol, glob yok).
  # bash regex tüm dizeyi eşler (yeni satır, boş parça, glob, '..' geçmez).
  koru_yol='[A-Za-z0-9][A-Za-z0-9._-]{0,63}(/[A-Za-z0-9][A-Za-z0-9._-]{0,63}){0,15}'
  if [ -n "$KORU" ] && ! [[ "$KORU" =~ ^${koru_yol}(,${koru_yol}){0,15}$ ]]; then
    die "geçersiz --koru yolu: '$KORU' (<dizin>'e göre alt yol(lar), ör. uretilen ya da tests/generated)"
  fi
fi

# --------------------------------------------------------------- demo kırılması / sıfırlama
if [ "$MODE" != init ] && [ "$MODE" != sync-dizin ]; then
  command -v docker >/dev/null 2>&1 || die "docker bulunamadı"
  # shellcheck disable=SC2206  # komut öneki bilerek kelimelere bölünür
  EXEC=(${TP_FORGE_EXEC:-docker compose exec -T core-worker})
  WEB_IMAGE="${TP_DEMO_WEB_IMAGE:-${TP_IMAGE_PREFIX}-demo-app-web:local}"
  "${EXEC[@]}" python -c 'import tp_core.integrations.forge_demo' >/dev/null 2>&1 \
    || die "core-worker'a erişilemiyor veya forge_demo modülü yok (make up ile core imajını yeniden derleyin)"
  if [ "$MODE" = status ]; then
    exec "${EXEC[@]}" python -m tp_core.integrations.forge_demo status
  fi
  # Çalışan demo-app-web'in forge commit'i → /forge/demo-app-web.sha (toolchain /check 'app' adımı
  # ve /locator-probe bunu okur; konteyner yeniden oluşturmadan güncellenir).
  write_web_sha() {
    local sha
    sha="$("${EXEC[@]}" python -m tp_core.integrations.forge_demo status \
      | python3 -c 'import json,sys; print(json.load(sys.stdin)["main"])')" \
      || die "forge main sha okunamadı"
    # shellcheck disable=SC2016  # $1 iç kabukta genişler
    "${EXEC[@]}" sh -c 'umask 022; printf "%s\n" "$1" > /forge/demo-app-web.sha.tmp && mv -f /forge/demo-app-web.sha.tmp /forge/demo-app-web.sha' _ "$sha" \
      || die "/forge/demo-app-web.sha yazılamadı"
    echo "demo-app-web commit'i: $sha"
  }
  # Çalışan demo-app-web forge main'i yansıtıyor mu? (forge_demo web-state; JSON alanını yazdırır)
  ws_get() {
    printf '%s' "$WS" | python3 -c '
import json, sys
d = json.load(sys.stdin)
k = sys.argv[1]
if k == "mesgul":
    m = d.get("mesgul")
    print("?" if m is None else ", ".join("%s %s" % (j.get("tur"), j.get("id")) for j in m))
elif k == "calisan_sha":
    c = d.get("calisan")
    print("-" if c is None else (c.get("sha") or ""))
else:
    v = d.get(k)
    print("true" if v is True else "false" if v is False else ("" if v is None else v))' "$1"
  }
  web_state() {
    WS="$("${EXEC[@]}" python -m tp_core.integrations.forge_demo web-state)" \
      || die "demo-app-web durumu okunamadı (forge_demo web-state)"
  }
  if [ "$MODE" = sync-web ]; then
    web_state
    if "${EXEC[@]}" python -m tp_core.integrations.forge_demo status \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("baseline") is None or d.get("main_baseline_mi") else 1)'; then
      # main = demo-baseline: make up imajı çalışma ağacından derledi (build.json sha'sı boş) → kalır.
      # Çalışan imaj başka bir forge commit'inden derlenmişse (ör. kırık imaj) aşağıda yeniden derlenir.
      if [ "$(ws_get guncel)" = true ] || [ -z "$(ws_get calisan_sha)" ] || [ "$(ws_get calisan_sha)" = - ]; then
        echo "forge main = demo-baseline; demo-app-web çalışma ağacından derlendiği gibi kalır."
        [ "$(ws_get sha_dosyasi_guncel)" = true ] || write_web_sha
        exit 0
      fi
      echo "forge main = demo-baseline ama çalışan demo-app-web başka bir forge commit'inden; yeniden derlenecek."
    else
      echo "forge main demo-baseline'dan farklı (ör. make break sonrası); demo-app-web forge main'den derlenecek."
    fi
  else
    "${EXEC[@]}" python -m tp_core.integrations.forge_demo "$MODE" \
      || die "forge_demo $MODE başarısız"
  fi
  # shellcheck disable=SC2016  # TP_FORGE konteynerde (iç kabukta) genişler
  forge_kind="$("${EXEC[@]}" sh -c 'printf %s "${TP_FORGE:-local}"')"
  if [ "$forge_kind" != local ]; then
    # GitHub kipi: kırılma/sıfırlama yukarıda insan kimliğiyle PR olarak yapıldı (forge_demo);
    # GitHub CI kendi runner'ında koşar. Çalışan demo-app-web (locator onarımının ölçtüğü uygulama)
    # GitHub main'inden, toolchain-worker aynası üzerinden derlenir (TP_FORGE_REMOTE_URL).
    echo "TP_FORGE=$forge_kind: demo-app-web GitHub main'inden (toolchain aynası) eşitleniyor..."
    if [ "$MODE" = sync-web ]; then
      # make up'ı düşürmez (ör. TP_FORGE_REMOTE_URL henüz yok): uyarır, elle yolu yazar.
      "$(dirname "$0")/demo-web-sync.sh" --main \
        || err "UYARI: demo-app-web GitHub main'iyle eşitlenemedi; düzeltip 'scripts/demo-web-sync.sh --main' çalıştırın."
      exit 0
    fi
    exec "$(dirname "$0")/demo-web-sync.sh" --main
  fi
  [ "$MODE" = sync-web ] || web_state
  main_sha="$(ws_get main)"
  [ -n "$main_sha" ] || die "forge main sha okunamadı"
  WEB_FORCE=0
  if [ "$FORCE" = 1 ] || [ "${TP_DEMO_WEB_FORCE:-0}" = 1 ]; then WEB_FORCE=1; fi
  # İdempotentlik: çalışan uygulama zaten main'i (commit ya da web/ ağacı) yansıtıyorsa ne derleme
  # ne yeniden oluşturma — ikinci bir `make break` süren push CI'ının altındaki uygulamayı öldürmez.
  if [ "$WEB_FORCE" != 1 ] && [ "$(ws_get guncel)" = true ]; then
    echo "demo-app-web zaten $main_sha ($(ws_get neden)); derleme ve yeniden oluşturma atlandı."
    [ "$(ws_get sha_dosyasi_guncel)" = true ] || write_web_sha
    echo "Tamam: $MODE (demo-app-web = forge main)."
    exit 0
  fi
  DEPLOY="${TP_DEMO_WEB_DEPLOY:-1}"
  if [ "$DEPLOY" != 0 ] && [ "$WEB_FORCE" != 1 ]; then
    busy="$(ws_get mesgul)"
    if [ "$busy" = "?" ]; then
      err "UYARI: koşan CI/onarım işleri okunamadı; demo-app-web yine de yeniden oluşturuluyor."
    elif [ -n "$busy" ]; then
      die "koşan iş(ler) var ($busy): demo-app-web şimdi yeniden oluşturulursa koşu ortam hatasıyla düşer. Bitince 'scripts/forge-init.sh sync-web' çalıştırın (zorlamak için: --force ya da TP_DEMO_WEB_FORCE=1)."
    fi
  fi
  TMP_TAR="$(mktemp "${TMPDIR:-/tmp}/tp-demo-web.XXXXXX")"
  # Derleme + yeniden oluşturma, scripts/demo-web-sync.sh ile AYNI kilit altında yapılır
  # (/forge/demo-web-sync.lock, owner "<epoch> <sahip>"): --watch kopyası aynı anda force-recreate
  # yaparsa Docker konteyner adı çakışır. Eski (TP_DEMO_SYNC_LOCK_STALE_S, 600 sn) kilit devralınır.
  WEB_KILIT=""
  web_kilit_birak() {
    [ -n "$WEB_KILIT" ] || return 0
    # shellcheck disable=SC2016  # $1 iç kabukta genişler
    "${EXEC[@]}" sh -c 'L=/forge/demo-web-sync.lock; o=$(cat "$L/owner" 2>/dev/null || true); [ "${o#* }" = "$1" ] && rm -rf "$L"; exit 0' _ "$WEB_KILIT" >/dev/null 2>&1 || true
    WEB_KILIT=""
  }
  trap 'rm -f "$TMP_TAR"; web_kilit_birak' EXIT
  kilit_token="forge-init:$(hostname 2>/dev/null || echo host):$$:${RANDOM}"
  kilit_bekle="${TP_DEMO_SYNC_WAIT_S:-120}"
  kilit_stale="${TP_DEMO_SYNC_LOCK_STALE_S:-600}"
  kilit_bas=$SECONDS
  bildirildi=0
  while :; do
    krc=0
    # shellcheck disable=SC2016  # $1/$2 iç kabukta genişler
    kout="$("${EXEC[@]}" sh -c '
L=/forge/demo-web-sync.lock
now=$(date +%s)
if mkdir "$L" 2>/dev/null; then printf "%s %s\n" "$now" "$1" > "$L/owner"; exit 0; fi
o=$(cat "$L/owner" 2>/dev/null || true); t=${o%% *}
case "$t" in ""|*[!0-9]*) t=$(stat -c %Y "$L" 2>/dev/null || echo "$now") ;; esac
yas=$((now - t))
if [ "$yas" -ge "$2" ]; then rm -rf "$L"; if mkdir "$L" 2>/dev/null; then printf "%s %s\n" "$now" "$1" > "$L/owner"; echo "eski kilit devralındı (${yas} sn)"; exit 0; fi; fi
echo "sahip: ${o#* } · ${yas} sn"; exit 3' _ "$kilit_token" "$kilit_stale")" || krc=$?
    if [ "$krc" = 0 ]; then WEB_KILIT="$kilit_token"; [ -z "$kout" ] || err "UYARI: $kout"; break; fi
    [ "$krc" = 3 ] || die "eşitleme kilidi alınamadı (/forge/demo-web-sync.lock, çıkış $krc)"
    if [ "$bildirildi" = 0 ]; then
      err "demo-app-web başka bir eşitleyici tarafından güncelleniyor ($kout); bekleniyor…"
      bildirildi=1
    fi
    [ $((SECONDS - kilit_bas)) -lt "$kilit_bekle" ] \
      || die "eşitleme kilidi ${kilit_bekle} sn içinde boşalmadı ($kout). Takılı kaldıysa: docker compose exec core-worker rm -rf /forge/demo-web-sync.lock"
    sleep 2
  done
  "${EXEC[@]}" python -m tp_core.integrations.forge_demo archive --ref "$main_sha" --path web >"$TMP_TAR" \
    || die "forge main arşivi alınamadı"
  tar -tf "$TMP_TAR" | grep -qx 'Dockerfile' || die "arşivde web/Dockerfile yok"
  # Derlenen commit ve web/ ağacı GET /build.json'da görünür (demo-app/web/Dockerfile build arg'ları).
  web_tree="$(ws_get main_web_tree)"
  old_image="$(docker image inspect -f '{{.Id}}' "$WEB_IMAGE" 2>/dev/null || true)"
  echo "demo-app-web forge main HEAD'inden derleniyor: $WEB_IMAGE ($main_sha; $(ws_get neden))"
  docker build -q -t "$WEB_IMAGE" \
    --build-arg "DEMO_APP_BUILD_SHA=$main_sha" --build-arg "DEMO_APP_WEB_TREE=$web_tree" \
    - <"$TMP_TAR" >/dev/null || die "demo-app-web derlenemedi"
  if [ "$DEPLOY" != 0 ]; then
    compose up -d --no-build --no-deps --force-recreate --wait demo-app-web \
      || die "demo-app-web yeniden başlatılamadı"
    write_web_sha
  fi
  web_kilit_birak
  # Eski imaj artık etiketsiz (dangling) kalır: kullanılmıyorsa silinir (kullanımdaysa sessizce kalır).
  new_image="$(docker image inspect -f '{{.Id}}' "$WEB_IMAGE" 2>/dev/null || true)"
  if [ -n "$old_image" ] && [ "$old_image" != "$new_image" ]; then
    docker image rm "$old_image" >/dev/null 2>&1 || true
  fi
  echo "Tamam: $MODE (demo-app-web = forge main)."
  exit 0
fi

VOLUME="${TP_FORGE_VOLUME:-${TP_PROJECT}_tp_forge}"
SRC="${TP_FORGE_SRC:-demo-app}"
IMAGE="${TP_FORGE_IMAGE:-${TP_IMAGE_PREFIX}-core:local}"

command -v docker >/dev/null 2>&1 || die "docker bulunamadı"
[ -d "$SRC" ] || die "kaynak dizin yok: $SRC"
SRC_ABS="$(cd "$SRC" && pwd)"

if [ "$MODE" = sync-dizin ] && ! docker volume inspect "$VOLUME" >/dev/null 2>&1; then
  # OPS-D2: yanlış COMPOSE_PROJECT_NAME / TP_FORGE_VOLUME'de boş volume oluşturup bırakmasın.
  die "forge volume'ü yok ($VOLUME); COMPOSE_PROJECT_NAME / TP_FORGE_VOLUME doğru mu? İlk kurulum: make forge-init"
fi

image_has_git() {
  docker run --rm --network none --entrypoint sh "$IMAGE" -c 'command -v git' >/dev/null 2>&1
}
if ! docker image inspect "$IMAGE" >/dev/null 2>&1 || ! image_has_git; then
  # Eski imajlarda git yoktu (core/Dockerfile git'i sonradan ekledi).
  echo "İmaj yok veya git içermiyor, build ediliyor: $IMAGE"
  docker build -q -t "$IMAGE" core >/dev/null
  image_has_git || die "$IMAGE içinde git yok"
fi

if ! docker volume inspect "$VOLUME" >/dev/null 2>&1; then
  # compose etiketleri: `docker compose` volume'ü kendi oluşturmuş gibi sahiplenir (uyarı vermez).
  docker volume create \
    --label com.docker.compose.project="$TP_PROJECT" \
    --label com.docker.compose.volume="${VOLUME#"${TP_PROJECT}"_}" \
    "$VOLUME" >/dev/null
fi

if [ "$MODE" = sync-dizin ]; then
  [ -d "$SRC_ABS/$DIZIN" ] || die "kaynak dizin yok: $SRC/$DIZIN"
  [ ! -L "$SRC_ABS/$DIZIN" ] || die "$SRC/$DIZIN sembolik bağ olamaz"
  docker run --rm -i --network none --user 0:0 \
    -e DIZIN="$DIZIN" -e BASELINE="$BASELINE" -e KORU="$KORU" \
    -v "$VOLUME:/forge" \
    -v "$SRC_ABS:/src:ro" \
    --entrypoint sh "$IMAGE" -eu -s <<'INNER'
# FORGE_DIR / SRC_DIR yalnızca testler içindir (konteynerde /forge ve /src).
F="${FORGE_DIR:-/forge}"
S="${SRC_DIR:-/src}"
REPO="$F/demo-app.git"
W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT
# Konteyner kök (0:0), depo 10001'e ait. git 2.39 yerel clone/push'un upload-pack/receive-pack alt
# süreçleri komut satırındaki `-c safe.directory` değerini GÖRMEZ ("dubious ownership", rc=128):
# safe.directory geçici bir global yapılandırmadan verilir (alt süreçler ortamı devralır).
# core.hooksPath=/dev/null (GÜV-Y2): kök konteyner forge deposunun (ve klonun) hook'larını
# çalıştırmaz — hem global yapılandırmada (alt süreçler) hem her komutta (-c).
printf '[safe]\n\tdirectory = *\n[core]\n\thooksPath = /dev/null\n' > "$W/gitconfig"
export HOME="$W" LC_ALL=C GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL="$W/gitconfig"
export GIT_AUTHOR_NAME=tp-bot GIT_AUTHOR_EMAIL=bot@testingprobe.local
export GIT_COMMITTER_NAME=tp-bot GIT_COMMITTER_EMAIL=bot@testingprobe.local
export GIT_AUTHOR_DATE="2026-01-01T00:00:00+0000" GIT_COMMITTER_DATE="2026-01-01T00:00:00+0000"
g() { git -c safe.directory='*' -c core.hooksPath=/dev/null "$@"; }

[ -d "$REPO" ] || { echo "HATA: forge deposu yok ($REPO); önce make forge-init" >&2; exit 2; }
[ -d "$S/$DIZIN" ] || { echo "HATA: kaynak dizin yok: $DIZIN" >&2; exit 2; }
eski_main="$(g --git-dir="$REPO" rev-parse --verify -q refs/heads/main)" \
  || { echo "HATA: forge'da main yok" >&2; exit 2; }
base="$(g --git-dir="$REPO" rev-parse --verify -q 'refs/tags/demo-baseline^{commit}' || true)"
if [ "$BASELINE" = 1 ]; then
  [ -n "$base" ] || { echo "HATA: demo-baseline etiketi yok" >&2; exit 2; }
  if [ "$(g --git-dir="$REPO" rev-parse "$eski_main^{tree}")" != "$(g --git-dir="$REPO" rev-parse "$base^{tree}")" ]; then
    echo "HATA: --baseline: main demo-baseline'da değil (ör. make break sonrası). Önce make demo-baseline." >&2
    exit 2
  fi
fi

g clone -q --no-tags --branch main "$REPO" "$W/r"
cd "$W/r"
rm -rf "./$DIZIN"
mkdir -p "./$DIZIN"
# Java/Maven çıktıları (target, results, kanit) da girmez (alt .gitignore olmasa bile).
tar -C "$S/$DIZIN" \
  --exclude=node_modules --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache \
  --exclude=.ruff_cache --exclude=dist --exclude=test-results --exclude=playwright-report \
  --exclude=blob-report --exclude=.DS_Store --exclude=.git --exclude='.env' --exclude='.env.*' \
  --exclude='*.db' --exclude='*.sqlite' --exclude=target --exclude=results --exclude=kanit \
  -cf - . | tar --no-same-owner -C "./$DIZIN" -xf -
# --koru: korunan yollar çalışma ağacından SİLİNİR ve forge main'deki (HEAD) hâlleriyle geri yüklenir.
korunan=0
if [ -n "${KORU:-}" ]; then
  eski_ifs="$IFS"; IFS=,
  for k in $KORU; do
    IFS="$eski_ifs"
    case "$k" in
      */*) rm -rf "./$DIZIN/$k"; spec=":(literal)$DIZIN/$k" ;;
      *) find "./$DIZIN" -depth -name "$k" -exec rm -rf {} + ; spec=":(glob)$DIZIN/**/$k/**" ;;
    esac
    if [ -n "$(g ls-files -- "$spec" | head -n 1)" ]; then
      g checkout -q HEAD -- "$spec"
      korunan=$((korunan + $(g ls-files -- "$spec" | wc -l)))
    fi
    IFS=,
  done
  IFS="$eski_ifs"
  echo "korunan ($KORU): forge main'deki $korunan dosya olduğu gibi kaldı."
fi
g add -A -- "./$DIZIN"
if g diff --cached --quiet; then
  echo "forge main zaten demo-app/$DIZIN ile aynı; commit yazılmadı."
  degisti=0
else
  disarida="$(g diff --cached --name-only | grep -v "^$DIZIN/" || true)"
  [ -z "$disarida" ] || { echo "HATA: $DIZIN/ dışında değişiklik: $disarida" >&2; exit 3; }
  n="$(g diff --cached --name-only | wc -l | tr -d ' ')"
  g commit -q -m "forge: $DIZIN/ demo-app çalışma ağacıyla eşitlendi (forge-init sync-dizin; $n dosya)"
  degisti=1
fi
yeni="$(g rev-parse HEAD)"

# Tüm ref güncellemeleri ÖNCE yerelde hazırlanır, sonra depoya TEK atomik fetch ile yazılır: main
# hızlı ileri (arada ilerlediyse reddedilir), demo/break-locator ve demo-baseline zorla. Depo
# `--shared=0666` ile kurulduğundan receive.denyNonFastforwards=true: zorla push reddedilir; fetch
# (receive-pack'ten geçmez) bu yüzden kullanılır. Bir adım düşerse hiçbir ref değişmez (yarım durum yok).
set -- "refs/heads/main:refs/heads/main"
tasindi=0
if [ "$BASELINE" = 1 ] && [ "$base" != "$yeni" ]; then
  # demo/break-locator: demo-baseline üstünde tek commit (forge-init init). Yeni etiketin üstüne aynı
  # değişiklik yeniden uygulanır; break merge'ü eklenen dizini silmez.
  if kir="$(g --git-dir="$REPO" rev-parse --verify -q refs/heads/demo/break-locator)"; then
    if [ "$(g --git-dir="$REPO" rev-parse "$kir^")" != "$base" ]; then
      echo "HATA: demo/break-locator demo-baseline üstünde tek commit değil; hiçbir ref değiştirilmedi" >&2
      exit 3
    fi
    g checkout -q -b tp-kir "$yeni"
    g cherry-pick "$kir" >/dev/null
    g checkout -q main
    set -- "$@" "+refs/heads/tp-kir:refs/heads/demo/break-locator"
  fi
  g tag -f demo-baseline "$yeni" >/dev/null
  set -- "$@" "+refs/tags/demo-baseline:refs/tags/demo-baseline"
  tasindi=1
fi
if [ "$degisti" = 1 ] || [ "$tasindi" = 1 ]; then
  g --git-dir="$REPO" fetch -q --atomic --no-tags --no-write-fetch-head "$W/r" "$@" \
    || { echo "HATA: forge ref'leri güncellenemedi (main arada ilerlemiş olabilir; yeniden çalıştırın). Hiçbir ref değişmedi." >&2; exit 3; }
fi
if [ "$degisti" = 1 ]; then
  echo "forge main: ${eski_main%"${eski_main#????????????}"} → $(g rev-parse --short=12 HEAD) ($DIZIN/, $n dosya)"
fi
if [ "$tasindi" = 1 ]; then
  echo "demo-baseline → $(g rev-parse --short=12 "$yeni") (demo/break-locator yeniden kuruldu)"
elif [ "$degisti" = 1 ] && [ -n "$base" ]; then
  echo "NOT: demo-baseline taşınmadı; make demo-reset/make reset main'i baseline'a döndürünce $DIZIN/ değişikliği geri alınır (kalıcı için --baseline)."
fi
cd /
# İzinler (init ile aynı); kök değilken (testler) sahiplik değiştirilemez.
chown -R 10001:1001 "$REPO" 2>/dev/null || [ "$(id -u)" != 0 ]
chmod -R a+rwX "$REPO"
echo "forge: $REPO"
g --git-dir="$REPO" for-each-ref --format='  %(refname:short)  %(objectname:short)' refs/heads refs/tags
INNER
  exit 0
fi

docker run --rm -i --network none --user 0:0 \
  -e FORCE="$FORCE" \
  -v "$VOLUME:/forge" \
  -v "$SRC_ABS:/src:ro" \
  --entrypoint sh "$IMAGE" -eu -s <<'INNER'
REPO=/forge/demo-app.git
export HOME=/tmp LC_ALL=C GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
export GIT_AUTHOR_NAME=tp-bot GIT_AUTHOR_EMAIL=bot@testingprobe.local
export GIT_COMMITTER_NAME=tp-bot GIT_COMMITTER_EMAIL=bot@testingprobe.local
export GIT_AUTHOR_DATE="2026-01-01T00:00:00+0000" GIT_COMMITTER_DATE="2026-01-01T00:00:00+0000"

fix_perms() {
  chown -R 10001:1001 /forge
  chmod 0777 /forge
  chmod -R a+rwX "$REPO"
  for f in /forge/tp-prs.json /forge/tp-prs.json.lock; do
    if [ -f "$f" ]; then chmod 0666 "$f"; fi
  done
}

summary() {
  echo "forge: $REPO"
  git -c safe.directory='*' --git-dir="$REPO" for-each-ref \
    --format='  %(refname:short)  %(objectname:short)' refs/heads refs/tags
}

if [ -e "$REPO" ]; then
  if [ "$FORCE" != "1" ]; then
    git -c safe.directory='*' --git-dir="$REPO" rev-parse --verify --quiet refs/tags/demo-baseline >/dev/null \
      || { echo "HATA: $REPO var ama demo-baseline etiketi yok; --force ile yeniden oluşturun" >&2; exit 2; }
    fix_perms
    echo "forge deposu zaten var (değiştirilmedi; yeniden oluşturmak için --force)."
    # Bayatlık denetimi: demo-app/'ın bugünkü ağacı demo-baseline'ın ağacıyla aynı mı?
    # (Aynı dışlamalar + alt .gitignore'lar → aynı içerik aynı tree sha'sını verir.)
    C="$(mktemp -d)"
    tar -C /src \
      --exclude=node_modules --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache \
      --exclude=.ruff_cache --exclude=dist --exclude=test-results --exclude=playwright-report \
      --exclude=blob-report --exclude=.DS_Store --exclude=.git --exclude='.env' --exclude='.env.*' \
      --exclude='*.db' --exclude='*.sqlite' -cf - . | tar --no-same-owner -C "$C" -xf -
    now_tree="$(cd "$C" && git init -q . && git add -A && git write-tree)"
    rm -rf "$C"
    base_tree="$(git -c safe.directory='*' --git-dir="$REPO" rev-parse 'demo-baseline^{tree}')"
    if [ "$now_tree" = "$base_tree" ] && [ ! -s /forge/demo-app-web.sha ]; then
      # make up demo-app-web'i çalışma ağacından derler (= demo-baseline); sync-web gerekirse ezer.
      git -c safe.directory='*' --git-dir="$REPO" rev-parse demo-baseline > /forge/demo-app-web.sha
      chmod 0644 /forge/demo-app-web.sha
    fi
    if [ "$now_tree" != "$base_tree" ]; then
      echo "UYARI: forge demo-baseline'ı demo-app/ dizininin bugünkü içeriğinden ESKİ." >&2
      echo "       Ajanlar ve test-runner eski kodu görür; güncellemek için: make reset" >&2
      echo "       (veya make forge-init F=--force; PR kaydı silinir)." >&2
    fi
    summary
    exit 0
  fi
  echo "--force: mevcut forge deposu ve PR kaydı siliniyor."
  rm -rf "$REPO" /forge/tp-prs.json /forge/tp-prs.json.lock /forge/demo-app-web.sha \
    /forge/demo-web-refresh.json /forge/demo-web-refresh.done
  rm -f /forge/.tp-prs.*.tmp
fi

W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT
# Yerel araç çıktıları depoya girmez (alt dizinlerdeki .gitignore'lar ayrıca uygulanır).
tar -C /src \
  --exclude=node_modules --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache \
  --exclude=.ruff_cache --exclude=dist --exclude=test-results --exclude=playwright-report \
  --exclude=blob-report --exclude=.DS_Store --exclude=.git --exclude='.env' --exclude='.env.*' \
  --exclude='*.db' --exclude='*.sqlite' -cf - . | tar --no-same-owner -C "$W" -xf -
cd "$W"

git init -q -b main .
git add -A
git commit -q -m "Demo uygulaması: başlangıç durumu"
git tag demo-baseline

git checkout -q -b demo/break-locator
[ -d web/src ] || { echo "HATA: web/src yok; demo-app web kaynağı bekleniyor" >&2; exit 3; }
FILES="$(grep -rlE --exclude='*.test.*' --exclude='*.spec.*' \
  "[\"'\`]add-to-cart[\"'\`]" web/src || true)"
if [ -z "$FILES" ]; then
  echo "HATA: web/src içinde 'add-to-cart' data-testid değeri bulunamadı." >&2
  echo "      demo-app web kaynağı DEMO-VERISI.md'deki 'Sepete ekle' butonunu henüz içermiyor olabilir." >&2
  exit 3
fi
for f in $FILES; do
  sed -i -E "s/([\"'\`])add-to-cart([\"'\`])/\\1cart-add\\2/g" "$f"
done
# Doğrulama: yalnızca web/src değişti ve her değişen satır yalnızca bu değer kadar farklı.
changed="$(git diff --name-only)"
case "$(printf '%s\n' "$changed" | grep -v '^web/src/' || true)" in
  "") ;;
  *) echo "HATA: web/src dışında değişiklik: $changed" >&2; exit 3 ;;
esac
removed="$(git diff -U0 | grep '^-' | grep -v '^---' || true)"
added="$(git diff -U0 | grep '^+' | grep -v '^+++' | sed 's/^+/-/; s/cart-add/add-to-cart/g' || true)"
[ -n "$removed" ] && [ "$removed" = "$added" ] \
  || { echo "HATA: kırılma değişikliği beklenenden farklı" >&2; git diff >&2; exit 3; }
git commit -q -am "demo: Sepete ekle butonunun data-testid'si değişti (add-to-cart → cart-add)"

git init -q --bare --shared=0666 -b main "$REPO"
git push -q "$REPO" main demo/break-locator refs/tags/demo-baseline
# Çalışan demo-app-web çalışma ağacından (= demo-baseline) derlenir; toolchain /check 'app' adımı okur.
git -c safe.directory='*' --git-dir="$REPO" rev-parse demo-baseline > /forge/demo-app-web.sha
fix_perms
chmod 0644 /forge/demo-app-web.sha
echo "forge deposu oluşturuldu ($(printf '%s\n' "$FILES" | wc -l | tr -d ' ') dosyada testid değişti)."
summary
INNER
