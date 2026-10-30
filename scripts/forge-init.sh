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
#
# break: core-worker içinde `python -m tp_core.integrations.forge_demo break` çalışır:
#   demo/break-locator → main PR'ı açılır, demo-admin kural bypass'ıyla (PR head sha'sına bağlı)
#   merge edilir, denetim kaydına "demo kırılması" yazılır. Ardından demo-app-web imajı forge
#   main HEAD'inin web/ arşivinden (çalışma ağacından değil) derlenir ve servis yeniden
#   oluşturulur. İkisi de idempotenttir (zaten kırıksa/baseline'daysa forge'a dokunulmaz).
#   Ortam: TP_FORGE_EXEC (varsayılan "docker compose exec -T core-worker"),
#          TP_DEMO_WEB_IMAGE (varsayılan testingprobe-demo-app-web:local),
#          TP_DEMO_WEB_DEPLOY=0 → yalnızca imajı derler, servisi yeniden oluşturmaz.
#
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
# Ortam: TP_FORGE_VOLUME (varsayılan testingprobe_tp_forge), TP_FORGE_SRC (varsayılan demo-app),
#        TP_FORGE_IMAGE (varsayılan testingprobe-core:local; yoksa core/ dizininden build edilir).
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"

FORCE=0
MODE=init
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    break|baseline|status|sync-web) MODE="$arg" ;;
    -h|--help) sed -n '2,38p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "bilinmeyen argüman: $arg (kullanım: forge-init.sh [--force] | break | baseline | status | sync-web)" ;;
  esac
done

# --------------------------------------------------------------- demo kırılması / sıfırlama
if [ "$MODE" != init ]; then
  command -v docker >/dev/null 2>&1 || die "docker bulunamadı"
  # shellcheck disable=SC2206  # komut öneki bilerek kelimelere bölünür
  EXEC=(${TP_FORGE_EXEC:-docker compose exec -T core-worker})
  WEB_IMAGE="${TP_DEMO_WEB_IMAGE:-testingprobe-demo-app-web:local}"
  "${EXEC[@]}" python -c 'import tp_core.integrations.forge_demo' >/dev/null 2>&1 \
    || die "core-worker'a erişilemiyor veya forge_demo modülü yok (make up ile core imajını yeniden derleyin)"
  if [ "$MODE" = status ]; then
    exec "${EXEC[@]}" python -m tp_core.integrations.forge_demo status
  fi
  if [ "$MODE" = sync-web ]; then
    st="$("${EXEC[@]}" python -m tp_core.integrations.forge_demo status)" \
      || die "forge durumu okunamadı"
    if printf '%s' "$st" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("baseline") is None or d.get("main_baseline_mi") else 1)'; then
      echo "forge main = demo-baseline; demo-app-web çalışma ağacından derlendiği gibi kalır."
      exit 0
    fi
    echo "forge main demo-baseline'dan farklı (ör. make break sonrası); demo-app-web forge main'den derlenecek."
  else
    "${EXEC[@]}" python -m tp_core.integrations.forge_demo "$MODE" \
      || die "forge_demo $MODE başarısız"
  fi
  forge_kind="$("${EXEC[@]}" sh -c 'printf %s "${TP_FORGE:-local}"')"
  if [ "$forge_kind" != local ]; then
    echo "Not: TP_FORGE=$forge_kind — demo-app-web yerel forge arşivinden derlenmez;"
    echo "     GitHub main HEAD'i CI/Sauce ortamına kendi akışıyla dağıtılır."
    exit 0
  fi
  TMP_TAR="$(mktemp "${TMPDIR:-/tmp}/tp-demo-web.XXXXXX")"
  trap 'rm -f "$TMP_TAR"' EXIT
  "${EXEC[@]}" python -m tp_core.integrations.forge_demo archive --ref main --path web >"$TMP_TAR" \
    || die "forge main arşivi alınamadı"
  tar -tf "$TMP_TAR" | grep -qx 'Dockerfile' || die "arşivde web/Dockerfile yok"
  echo "demo-app-web forge main HEAD'inden derleniyor: $WEB_IMAGE"
  docker build -q -t "$WEB_IMAGE" - <"$TMP_TAR" >/dev/null || die "demo-app-web derlenemedi"
  if [ "${TP_DEMO_WEB_DEPLOY:-1}" != 0 ]; then
    compose up -d --no-build --no-deps --force-recreate --wait demo-app-web \
      || die "demo-app-web yeniden başlatılamadı"
  fi
  echo "Tamam: $MODE (demo-app-web = forge main)."
  exit 0
fi

VOLUME="${TP_FORGE_VOLUME:-${TP_PROJECT}_tp_forge}"
SRC="${TP_FORGE_SRC:-demo-app}"
IMAGE="${TP_FORGE_IMAGE:-testingprobe-core:local}"

command -v docker >/dev/null 2>&1 || die "docker bulunamadı"
[ -d "$SRC" ] || die "kaynak dizin yok: $SRC"
SRC_ABS="$(cd "$SRC" && pwd)"

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
      --exclude='*.db' --exclude='*.sqlite' -cf - . | tar -C "$C" -xf -
    now_tree="$(cd "$C" && git init -q . && git add -A && git write-tree)"
    rm -rf "$C"
    base_tree="$(git -c safe.directory='*' --git-dir="$REPO" rev-parse 'demo-baseline^{tree}')"
    if [ "$now_tree" != "$base_tree" ]; then
      echo "UYARI: forge demo-baseline'ı demo-app/ dizininin bugünkü içeriğinden ESKİ." >&2
      echo "       Ajanlar ve test-runner eski kodu görür; güncellemek için: make reset" >&2
      echo "       (veya make forge-init F=--force; PR kaydı silinir)." >&2
    fi
    summary
    exit 0
  fi
  echo "--force: mevcut forge deposu ve PR kaydı siliniyor."
  rm -rf "$REPO" /forge/tp-prs.json /forge/tp-prs.json.lock
  rm -f /forge/.tp-prs.*.tmp
fi

W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT
# Yerel araç çıktıları depoya girmez (alt dizinlerdeki .gitignore'lar ayrıca uygulanır).
tar -C /src \
  --exclude=node_modules --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache \
  --exclude=.ruff_cache --exclude=dist --exclude=test-results --exclude=playwright-report \
  --exclude=blob-report --exclude=.DS_Store --exclude=.git --exclude='.env' --exclude='.env.*' \
  --exclude='*.db' --exclude='*.sqlite' -cf - . | tar -C "$W" -xf -
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
fix_perms
echo "forge deposu oluşturuldu ($(printf '%s\n' "$FILES" | wc -l | tr -d ' ') dosyada testid değişti)."
summary
INNER
