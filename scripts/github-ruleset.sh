#!/usr/bin/env bash
# main dalı ruleset'i (TEKNIK-TASARIM §8.5, Constitution "Etkili eylemler").
#
#   - main'e doğrudan push yok (her değişiklik PR ile), force-push ve silme yok
#   - merge için: 1 insan onayı + CODEOWNERS onayı + zorunlu check'ler yeşil
#   - "enforce for admins": bypass listesinde yalnızca demo-admin (insan) takımı; bot App yok
#
# Varsayılan KURU ÇALIŞMA: hiçbir API çağrısı yapmaz, gönderilecek JSON'u ve komutları yazdırır.
# Uygulamak için --apply. İdempotent: aynı adlı ruleset varsa günceller (PUT), yoksa oluşturur (POST).
#
# Kullanım:
#   scripts/github-ruleset.sh [--repo OWNER/REPO] [--apply] [--name tp-main] [--branch main]
#                             [--bypass-team demo-admin] [--checks test-local,ast-guard,semgrep]
#                             [--add-checks web-java] [--existing-json ruleset.json]
#
# DİKKAT: --checks listeyi DEĞİŞTİRİR (PUT tüm kuralı yazar): orada olmayan mevcut check'ler (ör.
# mobil-android, masaustu-windows, web-java) silinir. Mevcut kurala yalnız ekleme için --add-checks:
# --apply'da mevcut ruleset'in zorunlu check'leri okunur ve verilenlerle BİRLEŞTİRİLİR (hiçbiri
# silinmez; ruleset yoksa ya da ruleset'te required_status_checks kuralı yok/boşsa --checks +
# --add-checks — taban check'ler düşmez). Kuru çalışmada mevcut liste GitHub'dan okunmaz:
# --existing-json <dosya> (gh api repos/O/R/rulesets/<id> çıktısı) verilirse onunla birleştirilir.
# --apply'da --existing-json YOK SAYILIR (her zaman canlı ruleset okunur); dosyadaki liste canlıdan
# farklıysa uyarı yazılır (kuru çalışma eski bir dosyayla yapılmış olabilir).
# K-T10 (011): demo deposunda .github/workflows/web-java.yml varsa `web-java` her zaman zorunludur.
#
# Bypass aktörü: repo ruleset'lerinde bypass listesi takım/rol/App kabul eder. "demo-admin" insan
# hesabını içeren tek üyeli bir org takımı (slug: demo-admin) oluşturun; bot App'i eklemeyin.
set -euo pipefail

usage() { sed -n '/^set -euo/q;2,$p' "$0" | sed 's/^# \{0,1\}//'; }

REPO="${GITHUB_REPO:-}"
APPLY=0
NAME="tp-main"
BRANCH="main"
BYPASS_TEAM="demo-admin"
CHECKS="test-local,ast-guard,semgrep"
ADD_CHECKS=""
EXISTING_JSON=""
# GitHub Actions uygulamasının kimliği: zorunlu check'in kaynağını Actions'a sabitler
# (başka bir App aynı adla "başarılı" durum yazamaz).
ACTIONS_APP_ID=15368

while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="${2:?--repo değer ister}"; shift 2 ;;
    --repo=*) REPO="${1#*=}"; shift ;;
    --apply) APPLY=1; shift ;;
    --dry-run) APPLY=0; shift ;;
    --name) NAME="${2:?--name değer ister}"; shift 2 ;;
    --branch) BRANCH="${2:?--branch değer ister}"; shift 2 ;;
    --bypass-team) BYPASS_TEAM="${2:?--bypass-team değer ister}"; shift 2 ;;
    --checks) CHECKS="${2:?--checks değer ister}"; shift 2 ;;
    --add-checks) ADD_CHECKS="${2:?--add-checks değer ister}"; shift 2 ;;
    --existing-json) EXISTING_JSON="${2:?--existing-json değer ister}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Bilinmeyen argüman: $1" >&2; usage >&2; exit 2 ;;
  esac
done

command -v jq >/dev/null || { echo "jq gerekli" >&2; exit 2; }

if [ -z "$REPO" ]; then
  url="$(git remote get-url origin 2>/dev/null || true)"
  REPO="$(printf '%s' "$url" | sed -E 's#^(git@github\.com:|https://github\.com/)##; s#\.git$##')"
fi
if ! printf '%s' "$REPO" | grep -Eq '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'; then
  echo "Repo belirlenemedi; --repo OWNER/REPO verin (bulunan: '${REPO}')" >&2
  exit 2
fi
OWNER="${REPO%%/*}"

if [ "$APPLY" -eq 1 ]; then
  command -v gh >/dev/null || { echo "gh gerekli" >&2; exit 2; }
  TEAM_ID="$(gh api "orgs/$OWNER/teams/$BYPASS_TEAM" --jq .id 2>/dev/null || true)"
  if ! printf '%s' "$TEAM_ID" | grep -Eq '^[0-9]+$'; then
    echo "Bypass takımı bulunamadı: $OWNER/$BYPASS_TEAM — önce takımı oluşturun ve demo-admin hesabını ekleyin." >&2
    exit 1
  fi
else
  TEAM_ID=0
fi

# Ruleset JSON'undan (GET repos/O/R/rulesets/<id>) zorunlu check adları, virgüllü.
mevcut_checks() {
  jq -r '[.rules[]? | select(.type == "required_status_checks")
          | .parameters.required_status_checks[]?.context] | join(",")'
}
# Virgüllü listeleri sırayı koruyarak birleştirir (tekrarsız, boşlar atılır).
birlestir() {
  jq -rn --arg a "$1" --arg b "$2" \
    '[($a | split(",")), ($b | split(","))] | add | map(gsub("^\\s+|\\s+$"; "")) | map(select(length > 0))
     | reduce .[] as $c ([]; if index([$c]) then . else . + [$c] end) | join(",")'
}
# Birleştirme tabanı: mevcut ruleset'in zorunlu check'leri; kural yok ya da liste boşsa --checks
# (OPS-D1: boş tabana yalnız --add-checks yazılıp test-local/ast-guard/semgrep düşmesin).
taban() {
  if [ -n "$1" ]; then printf '%s' "$1"; else printf '%s' "$CHECKS"; fi
}
MERGE_NOTE=""
if [ -n "$ADD_CHECKS" ] && [ "$APPLY" -eq 0 ]; then
  if [ -n "$EXISTING_JSON" ]; then
    [ -r "$EXISTING_JSON" ] || { echo "--existing-json okunamadı: $EXISTING_JSON" >&2; exit 2; }
    dosya_checks="$(mevcut_checks <"$EXISTING_JSON")" \
      || { echo "--existing-json ruleset JSON'u değil: $EXISTING_JSON" >&2; exit 2; }
    CHECKS="$(birlestir "$(taban "$dosya_checks")" "$ADD_CHECKS")"
    if [ -n "$dosya_checks" ]; then
      MERGE_NOTE="mevcut ($EXISTING_JSON) + --add-checks"
    else
      MERGE_NOTE="mevcut ($EXISTING_JSON) zorunlu check içermiyor → --checks + --add-checks"
    fi
  else
    CHECKS="$(birlestir "$CHECKS" "$ADD_CHECKS")"
    MERGE_NOTE="--apply'da mevcut ruleset'in check'leriyle BİRLEŞTİRİLİR (aşağıdaki liste yalnız --checks + --add-checks)"
  fi
fi

payload() {
  jq -n \
    --arg name "$NAME" \
    --arg ref "refs/heads/$BRANCH" \
    --argjson team_id "$TEAM_ID" \
    --argjson app_id "$ACTIONS_APP_ID" \
    --arg checks "$CHECKS" \
    '{
      name: $name,
      target: "branch",
      enforcement: "active",
      conditions: { ref_name: { include: [$ref], exclude: [] } },
      bypass_actors: [ { actor_id: $team_id, actor_type: "Team", bypass_mode: "always" } ],
      rules: [
        { type: "deletion" },
        { type: "non_fast_forward" },
        { type: "pull_request",
          parameters: {
            required_approving_review_count: 1,
            require_code_owner_review: true,
            dismiss_stale_reviews_on_push: true,
            require_last_push_approval: true,
            required_review_thread_resolution: false
          } },
        { type: "required_status_checks",
          parameters: {
            strict_required_status_checks_policy: false,
            required_status_checks:
              ($checks | split(",") | map(select(length > 0)) | map({ context: ., integration_id: $app_id }))
          } }
      ]
    }'
}

BODY="$(payload)"

if [ "$APPLY" -eq 0 ]; then
  cat <<EOF
# KURU ÇALIŞMA (değişiklik yapılmadı). Uygulamak için: $0 --repo $REPO --apply
# Repo: $REPO · ruleset: $NAME · dal: $BRANCH · bypass takımı: $OWNER/$BYPASS_TEAM (kimlik --apply'da çözülür)
# Zorunlu check'ler: $CHECKS${MERGE_NOTE:+ — $MERGE_NOTE}
#
# Adımlar:
#   gh api orgs/$OWNER/teams/$BYPASS_TEAM --jq .id
#   gh api repos/$REPO/rulesets --jq '.[] | select(.name == "$NAME") | .id'
#   varsa: gh api -X PUT  repos/$REPO/rulesets/<id> --input -   (aşağıdaki gövde)
#   yoksa: gh api -X POST repos/$REPO/rulesets      --input -
EOF
  printf '%s\n' "$BODY"
  exit 0
fi

EXISTING_ID="$(gh api "repos/$REPO/rulesets" --paginate --jq ".[] | select(.name == \"$NAME\") | .id" | head -n1)"
if [ -n "$EXISTING_JSON" ]; then
  echo "UYARI: --apply'da --existing-json yok sayılır; canlı ruleset okunur." >&2
fi
if [ -n "$ADD_CHECKS" ]; then
  if [ -n "$EXISTING_ID" ]; then
    mevcut="$(gh api "repos/$REPO/rulesets/$EXISTING_ID" | mevcut_checks)"
    if [ -n "$EXISTING_JSON" ] && [ -r "$EXISTING_JSON" ]; then
      dosya_checks="$(mevcut_checks <"$EXISTING_JSON" 2>/dev/null || echo '?')"
      if [ "$dosya_checks" != "$mevcut" ]; then
        echo "UYARI: --existing-json listesi canlı ruleset'ten farklı (dosya: '${dosya_checks}', canlı: '${mevcut}'); canlı liste kullanılıyor." >&2
      fi
    fi
    [ -n "$mevcut" ] || echo "UYARI: canlı ruleset'te zorunlu check yok; --checks ($CHECKS) taban alınıyor." >&2
    CHECKS="$(birlestir "$(taban "$mevcut")" "$ADD_CHECKS")"
  else
    CHECKS="$(birlestir "$CHECKS" "$ADD_CHECKS")"
  fi
  echo "zorunlu check'ler (birleştirildi): $CHECKS"
  BODY="$(payload)"
fi
if [ -n "$EXISTING_ID" ]; then
  printf '%s' "$BODY" | gh api -X PUT "repos/$REPO/rulesets/$EXISTING_ID" --input - --jq '"güncellendi: \(.name) (#\(.id))"'
else
  printf '%s' "$BODY" | gh api -X POST "repos/$REPO/rulesets" --input - --jq '"oluşturuldu: \(.name) (#\(.id))"'
fi
