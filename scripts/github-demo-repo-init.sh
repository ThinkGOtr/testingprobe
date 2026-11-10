#!/usr/bin/env bash
# github-demo-repo-init — GitHub kipinin demo deposunu (ör. ThinkGOtr/testingprobe-demo-app) hazırlar.
#
#   scripts/github-demo-repo-init.sh                       # KURU ÇALIŞMA: ağacı geçici dizinde kurar,
#                                                          # ne gönderileceğini yazdırır; ağ yok
#   scripts/github-demo-repo-init.sh --out /tmp/demo-repo  # aynı, ağaç bu (boş/yok) dizine
#   scripts/github-demo-repo-init.sh --push                # BOŞ depoya main + demo-baseline etiketi
#   scripts/github-demo-repo-init.sh --push --update       # dolu depo: yeni içerik ayrı dalda (PR ile)
#
# Seçenekler: --repo OWNER/REPO (varsayılan $GITHUB_REPO, yoksa ThinkGOtr/testingprobe-demo-app),
#             --codeowner LOGIN (CODEOWNERS sahibi; varsayılan gokhansipahi).
#
# Depo düzeni (ürünün GitHub kipinin beklediği; core TP_FORGE_APP_ROOT varsayılanı 'demo-app',
# toolchain TP_E2E_ROOT=demo-app/e2e, TP_APP_PATHS=demo-app/web,demo-app/api):
#   demo-app/                  test edilen uygulama (api/, web/, e2e/, ci/, .sauce/) — git'te izlenen
#                              dosyalar, çalışma ağacındaki içerikleriyle
#   .github/workflows/ci.yml   zorunlu check'ler test-local, ast-guard, semgrep (GitHub-hosted
#                              ubuntu-24.04 runner'ları); ürün deposundaki ci.yml'den, golden-drift
#                              job'u çıkarılarak (golden kayıtlar ürün deposunda kalır: rules/, docs/)
#   .github/workflows/break-verify.yml  elle "kırarak doğrula" kanıtı (zorunlu değil)
#   .github/workflows/{mobil-android,mobil-ios,masaustu-windows}.yml  uygulama e2e (009; Java +
#                              Appium; platform etkinse mobil-android / masaustu-windows zorunlu check)
#   tools/appium/package{,-lock}.json   Appium 3 + sürücüler (uygulama iş akışları npm ci ile kurar)
#   .github/CODEOWNERS         /demo-app/e2e/pages/, tests/generated/, kalite kapısı yapılandırması,
#                              /.github/, /toolchain/ast-guard/, /scripts/github-*.sh → @<codeowner>
#   .github/dependabot.yml     Action SHA'ları + ast-guard bağımlılıkları (PR açar, merge etmez)
#   scripts/github-{ast-guard-mode,ci-results,demo-serve,sauce-summary,break-verify-result}.sh
#   toolchain/ast-guard/       AST koruması (CI'da taban daldan çalışır); monorepo ci.yml'yi sınayan
#                              test/ci-workflow.test.ts hariç
#   toolchain/security/no-mcp-in-image.sh   (toolchain imajı yolu; Constitution II)
#   .playwright-version, .gitignore, README.md
# Sır İÇERMEZ: .env*, anahtar/token kalıpları (PEM, ghp_, github_pat_, sk-ant-, AKIA) bulunursa
# durur. Model anahtarı/MCP/ajan bağımlılığı yoktur (Constitution II: CI'da AI yok).
#
# İlk commit tek ve deterministiktir (sabit tarih; yazar: TP_BOOTSTRAP_AUTHOR_NAME/EMAIL, yoksa
# git yapılandırmanız okunur — değiştirilmez) ve `demo-baseline` etiketi ona konur: GitHub kipinde
# demo sıfırlaması main'in AĞACINI bu etiketin ağacına döndüren bir PR açar.
#
# --push: kimlik sizin git kimlik bilgilerinizdir (ör. `gh auth setup-git`; workflow dosyaları için
# token'da `workflow` izni gerekir). Betik token okumaz/yazmaz. Uzak depoda main varsa --update
# olmadan durur: --update yeni ağacı uzak main'in üstüne tek commit olarak `altyapi/bootstrap-<zaman>`
# dalına gönderir; PR'ı siz açar ve insan olarak merge edersiniz (ruleset). Etiketin taşınması
# ayrı ve bilinçli bir yönetici adımıdır (yazdırılır).
set -euo pipefail
CALLER_PWD="$PWD"  # lib.sh depo köküne geçer; göreli --out çağıranın dizinine göredir
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"

usage() { sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; }

REPO="${GITHUB_REPO:-ThinkGOtr/testingprobe-demo-app}"
OUT=""
PUSH=0
UPDATE=0
CODEOWNER="gokhansipahi"
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2:?--repo değer ister}"; shift 2 ;;
    --repo=*) REPO="${1#*=}"; shift ;;
    --out) OUT="${2:?--out değer ister}"; shift 2 ;;
    --out=*) OUT="${1#*=}"; shift ;;
    --codeowner) CODEOWNER="${2:?--codeowner değer ister}"; shift 2 ;;
    --codeowner=*) CODEOWNER="${1#*=}"; shift ;;
    --push) PUSH=1; shift ;;
    --update) UPDATE=1; shift ;;
    --dry-run) PUSH=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) err "bilinmeyen argüman: $1"; usage >&2; exit 2 ;;
  esac
done

printf '%s' "$REPO" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$' \
  || die "geçersiz --repo: '$REPO' (OWNER/REPO)"
printf '%s' "$CODEOWNER" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9-]{0,38}(/[A-Za-z0-9._-]+)?$' \
  || die "geçersiz --codeowner: '$CODEOWNER'"
[ "$UPDATE" = 0 ] || [ "$PUSH" = 1 ] || die "--update yalnızca --push ile anlamlıdır"
command -v git >/dev/null 2>&1 || die "git gerekli"
command -v python3 >/dev/null 2>&1 || die "python3 gerekli"
git -C "$TP_REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1 \
  || die "ürün deposu bir git çalışma ağacı değil (izlenen dosya listesi gerekli)"

if [ -n "$OUT" ]; then
  case "$OUT" in /*) ;; *) OUT="$CALLER_PWD/$OUT" ;; esac
  if [ -e "$OUT" ] && [ -n "$(ls -A "$OUT" 2>/dev/null)" ]; then
    die "--out dizini boş değil: $OUT"
  fi
  mkdir -p "$OUT"
  DEST="$(cd "$OUT" && pwd)"
else
  DEST="$(mktemp -d "${TMPDIR:-/tmp}/tp-demo-repo.XXXXXX")"
fi

# ------------------------------------------------------------------ ağaç
copy_tracked() {
  # git'te izlenen dosyalar (çalışma ağacındaki içerikleriyle); silinmiş olanlar atlanır.
  local f
  while IFS= read -r f; do
    [ -f "$TP_REPO_ROOT/$f" ] || continue
    case "$f" in
      toolchain/ast-guard/test/ci-workflow.test.ts) continue ;;  # monorepo ci.yml'yi sınar
    esac
    mkdir -p "$DEST/$(dirname "$f")"
    cp -p "$TP_REPO_ROOT/$f" "$DEST/$f"
  done < <(git -C "$TP_REPO_ROOT" ls-files -c -- "$@")
}

copy_tracked demo-app toolchain/ast-guard toolchain/security/no-mcp-in-image.sh \
  .playwright-version .github/workflows/break-verify.yml .github/dependabot.yml .github/actionlint.yaml \
  .github/workflows/mobil-android.yml .github/workflows/mobil-ios.yml \
  .github/workflows/masaustu-windows.yml tools/appium/package.json tools/appium/package-lock.json \
  scripts/github-ast-guard-mode.sh scripts/github-ci-results.sh scripts/github-demo-serve.sh \
  scripts/github-sauce-summary.sh scripts/github-break-verify-result.sh
[ -f "$DEST/demo-app/web/Dockerfile" ] || die "demo-app/web/Dockerfile kopyalanmadı"
[ -f "$DEST/demo-app/e2e/pages/catalog/locators.ts" ] || die "demo-app/e2e/pages/catalog/locators.ts yok"

SOURCE_SHA="$(git -C "$TP_REPO_ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo bilinmiyor)"
DIRTY=""
git -C "$TP_REPO_ROOT" diff --quiet -- demo-app .github toolchain/ast-guard scripts/github-*.sh \
  2>/dev/null || DIRTY=" (+ commit edilmemiş değişiklikler)"

# ci.yml: golden-drift job'u çıkarılır; başlığa kaynak notu eklenir. CODEOWNERS sahibi değiştirilir.
python3 - "$TP_REPO_ROOT" "$DEST" "$CODEOWNER" "$SOURCE_SHA$DIRTY" <<'PY'
import re, sys
from pathlib import Path

src, dest, owner, kaynak = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
lines = (src / ".github/workflows/ci.yml").read_text(encoding="utf-8").splitlines(keepends=True)
out, skip = [], False
job = re.compile(r"^  [A-Za-z0-9_-]+:\s*$")
for line in lines:
    if line.rstrip("\n") == "  golden-drift:":
        skip = True
        continue
    if skip and job.match(line):
        skip = False
    if not skip:
        out.append(line)
text = "".join(out)
if "golden-drift:" in text.replace("golden-drift/", ""):
    sys.exit("ci.yml: golden-drift job'u çıkarılamadı")
for need in ("  test-local:", "  ast-guard:", "  semgrep:", "  changes:"):
    if need + "\n" not in text:
        sys.exit(f"ci.yml: zorunlu job eksik: {need.strip()}")
not_ = (
    "# Bu kopya testing-probe deposundan scripts/github-demo-repo-init.sh ile üretildi "
    f"(kaynak {kaynak}).\n"
    "# Fark: golden-drift job'u yok (golden kayıtlar ve rules/ ürün deposunda kalır). Elle\n"
    "# düzenlemeyin; ürün deposunda değiştirip betiği --push --update ile yeniden çalıştırın.\n"
)
first, rest = text.split("\n", 1)
(dest / ".github/workflows").mkdir(parents=True, exist_ok=True)
(dest / ".github/workflows/ci.yml").write_text(first + "\n" + not_ + rest, encoding="utf-8")

co = (src / ".github/CODEOWNERS").read_text(encoding="utf-8")
co = co.replace("@gokhansipahi", "@" + owner)
(dest / ".github/CODEOWNERS").write_text(co, encoding="utf-8")
PY

cat >"$DEST/.gitignore" <<'EOF'
.DS_Store
.env
.env.*
node_modules/
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
dist/
test-results/
playwright-report/
blob-report/
results/
demo-app/results/
demo-app/e2e/results/
*.db
*.sqlite
EOF

cat >"$DEST/README.md" <<EOF
# ${REPO#*/}

AI Testing Probe'un **GitHub kipinde** test ettiği demo uygulaması (Bayi Sipariş Portalı;
tüm veri sentetiktir). Bu depo \`testing-probe\` ürün deposundan
\`scripts/github-demo-repo-init.sh\` ile üretilmiştir (kaynak ${SOURCE_SHA}).

| Yol | İçerik |
|---|---|
| \`demo-app/\` | Uygulama (\`api/\`, \`web/\`, \`e2e/\` page object kütüphanesi + testler, \`ci/run-checks.sh\`) |
| \`.github/workflows/ci.yml\` | Zorunlu check'ler: \`test-local\`, \`ast-guard\`, \`semgrep\` (CI'da AI yok) |
| \`toolchain/ast-guard/\` | Locator onarımı yalnızca \`testId\` değiştirebilir (AST koruması) |

Kurallar (ruleset \`tp-main\`): \`main\`'e yalnızca PR ile; 1 insan onayı + CODEOWNERS; bot (GitHub
App) PR açar ama **merge etmez**; ruleset bypass yalnızca \`demo-admin\` takımındadır.
\`demo-baseline\` etiketi demo sıfırlamasının hedef ağacıdır. Kurulum: ürün deposunda
\`docs/GERCEK-SISTEMLER.md\` §5.
EOF

# ------------------------------------------------------------------ sır taraması
python3 - "$DEST" <<'PY'
import re, sys
from pathlib import Path

root = Path(sys.argv[1])
kalip = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bghp_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"
    r"|\bghs_[A-Za-z0-9]{20,}|\bsk-ant-[A-Za-z0-9_-]{10,}|\bAKIA[0-9A-Z]{16}\b"
)
bulgu = []
for p in root.rglob("*"):
    if ".git" in p.relative_to(root).parts or not p.is_file():
        continue
    rel = p.relative_to(root).as_posix()
    if p.name == ".env" or p.name.startswith(".env."):
        bulgu.append(f"{rel}: .env dosyası")
        continue
    try:
        metin = p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    if kalip.search(metin):
        bulgu.append(f"{rel}: anahtar/token kalıbı")
if bulgu:
    sys.exit("HATA: sır şüphesi, gönderilmez:\n  " + "\n  ".join(bulgu))
PY

# ------------------------------------------------------------------ git (deterministik ilk commit)
AUTHOR_NAME="${TP_BOOTSTRAP_AUTHOR_NAME:-$(git -C "$TP_REPO_ROOT" config user.name 2>/dev/null || true)}"
AUTHOR_EMAIL="${TP_BOOTSTRAP_AUTHOR_EMAIL:-$(git -C "$TP_REPO_ROOT" config user.email 2>/dev/null || true)}"
[ -n "$AUTHOR_NAME" ] || AUTHOR_NAME="testing-probe-bootstrap"
[ -n "$AUTHOR_EMAIL" ] || AUTHOR_EMAIL="bootstrap@testingprobe.invalid"
g() {
  GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \
    GIT_AUTHOR_NAME="$AUTHOR_NAME" GIT_AUTHOR_EMAIL="$AUTHOR_EMAIL" \
    GIT_COMMITTER_NAME="$AUTHOR_NAME" GIT_COMMITTER_EMAIL="$AUTHOR_EMAIL" \
    GIT_AUTHOR_DATE="2026-01-01T00:00:00+0000" GIT_COMMITTER_DATE="2026-01-01T00:00:00+0000" \
    git -C "$DEST" "$@"
}
g init -q -b main .
g add -A
g commit -q -m "Demo uygulaması: başlangıç durumu (testing-probe $SOURCE_SHA)"
g tag demo-baseline
# Ağ işlemleri (ls-remote/fetch/push) sizin git yapılandırmanızla (kimlik bilgisi yardımcısı).
gnet() { git -C "$DEST" "$@"; }
HEAD_SHA="$(g rev-parse HEAD)"
TREE_SHA="$(g rev-parse 'HEAD^{tree}')"
WEB_TREE="$(g rev-parse HEAD:demo-app/web)"
N_FILES="$(g ls-files | wc -l | tr -d ' ')"
URL="https://github.com/$REPO.git"

echo "Demo deposu ağacı: $DEST"
echo "  depo: $REPO · dosya: $N_FILES · commit: ${HEAD_SHA:0:12} · ağaç: ${TREE_SHA:0:12} · demo-app/web: ${WEB_TREE:0:12}"
echo "  kaynak: testing-probe $SOURCE_SHA$DIRTY · CODEOWNERS: @$CODEOWNER"
g ls-files | awk -F/ '{ k = (NF > 1) ? $1 "/" : $1; n[k]++ } END { for (k in n) printf "    %-28s %d\n", k, n[k] }' | sort

if [ "$PUSH" != 1 ]; then
  cat <<EOF

# KURU ÇALIŞMA: hiçbir şey gönderilmedi (ağ çağrısı yok). Göndermek için:
#   $0 --repo $REPO --push
# Bu, boş depoya şunu yapar:
#   git -C $DEST push $URL main refs/tags/demo-baseline
# Ardından (docs/GERCEK-SISTEMLER.md §5): ruleset (scripts/github-ruleset.sh --repo $REPO --apply),
# App kurulumu, demo-admin takımı ve .env (TP_FORGE=github, GITHUB_REPO=$REPO, ...).
EOF
  exit 0
fi

# ------------------------------------------------------------------ gönderim (yalnızca --push)
remote_main="$(git ls-remote --heads "$URL" main 2>/dev/null | awk '{print $1}')" \
  || die "uzak depoya erişilemedi: $URL (depo var mı, git kimliğiniz yetkili mi?)"
if [ -z "$remote_main" ]; then
  [ "$UPDATE" = 0 ] || die "--update: uzak depoda main yok; ilk gönderim için --update olmadan çalıştırın"
  echo "Uzak depo boş: main + demo-baseline gönderiliyor → $URL"
  gnet push "$URL" main refs/tags/demo-baseline
  echo "Tamam. Sonraki adımlar: docs/GERCEK-SISTEMLER.md §5 (ruleset, App, demo-admin, .env)."
  exit 0
fi

[ "$UPDATE" = 1 ] || die "uzak depoda main zaten var (${remote_main:0:12}); güncellemek için --push --update (PR dalı)"
BRANCH="altyapi/bootstrap-$(date -u +%Y%m%d%H%M%S)"
gnet fetch -q "$URL" "+refs/heads/main:refs/remotes/uzak/main"
PARENT="$(g rev-parse refs/remotes/uzak/main)"
if [ "$(g rev-parse "$PARENT^{tree}")" = "$TREE_SHA" ]; then
  echo "Uzak main zaten bu ağaçta (${PARENT:0:12}); gönderilecek değişiklik yok."
  exit 0
fi
NEW="$(printf 'testing-probe %s içeriğiyle güncelleme\n' "$SOURCE_SHA" | g commit-tree "$TREE_SHA" -p "$PARENT")"
gnet push "$URL" "$NEW:refs/heads/$BRANCH"
cat <<EOF
Gönderildi: $BRANCH (${NEW:0:12}, ebeveyn uzak main ${PARENT:0:12}).
Sonraki adımlar (insan):
  gh pr create --repo $REPO --head $BRANCH --base main --title "testing-probe içerik güncellemesi"
  # CI yeşil + CODEOWNERS onayı → GitHub arayüzünden merge (bot merge etmez).
  # demo-baseline etiketini YENİ içeriğe taşımak bilinçli bir yönetici adımıdır (demo sıfırlaması
  # main'in ağacını bu etikete döndürür):
  #   git push --force $URL <merge_commit_sha>:refs/tags/demo-baseline
EOF
