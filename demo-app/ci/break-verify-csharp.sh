#!/usr/bin/env bash
# "Kırarak doğrula" (yeşil → kırmızı → yeşil) — web C# hattı; break-verify.sh (TypeScript) ve
# break-verify-java.sh (Java) karşılığı. Kampanya testlerinin kuralı gerçekten yakaladığını kanıtlar. AI yok.
#   1) normal koşu           → kampanya kategorisi geçmeli
#   2) BREAK_CAMPAIGN=1 koşu → yalnızca kampanya hesabına bağlı testler, ASSERTION ile kalmalı
#                              (kurulum / locator hatası, atlanan test kırmızı sayılmaz — JUnit XML
#                              e2e-csharp/araclar/kirmizi_denetimi.py ile denetlenir); kampanyasız
#                              testler geçmeli
#   3) normal koşu           → yine geçmeli (kırılma geri alındı, kalıcı iz yok)
# Kırılma bayi kapsamlıdır (POST /test/break) ve yalnızca test süresince açıktır.
#
# Kullanım: ci/break-verify-csharp.sh [dotnet test argümanları...]
# Ortam: run-csharp-checks.sh ile aynı; DEMOAPP_TEST_TOKEN ZORUNLU (kırılma /test/break ister).
#        BREAK_VERIFY_CATEGORY (varsayılan: kampanya) — NUnit kategorisi.
# Her adımın JUnit XML'i ve (kırmızıda) kanıtı: demo-app/e2e-csharp/results/kirarak-dogrula/<adım>/
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -n "${DEMOAPP_TEST_TOKEN:-}" ]] || { echo "HATA: DEMOAPP_TEST_TOKEN gerekli (kırılma POST /test/break ile açılır)" >&2; exit 2; }

kategori="${BREAK_VERIFY_CATEGORY:-kampanya}"
[[ "$kategori" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "HATA: BREAK_VERIFY_CATEGORY geçersiz: $kategori" >&2; exit 2; }
proje="$root/e2e-csharp"
cikti="$proje/results/kirarak-dogrula"
step() { printf '\n==> %s\n' "$*"; }

ilk=1
run() {  # $1 = BREAK_CAMPAIGN değeri, $2 = adım adı; çıkış kodunu döndürür
  local rc=0 build=1
  [[ "$ilk" == "1" ]] && build=0
  ilk=0
  BREAK_CAMPAIGN="$1" SKIP_BIRIM=1 SKIP_GUARD=1 SKIP_BUILD="$build" TEST_FILTER="Category=$kategori" \
    "$root/ci/run-csharp-checks.sh" "${@:3}" || rc=$?
  rm -rf "${cikti:?}/$2"
  mkdir -p "$cikti/$2"
  cp "$proje/results/junit.xml" "$cikti/$2/" 2>/dev/null || true
  [[ -d "$proje/results/kanit" ]] && cp -R "$proje/results/kanit" "$cikti/$2/kanit"
  return "$rc"
}

rm -rf "$cikti"

step "1/3 normal (yeşil beklenir)"
run "" 1-yesil "$@" || { echo "HATA: kırılma olmadan '$kategori' testleri kırmızı" >&2; exit 1; }

step "2/3 BREAK_CAMPAIGN=1 (kırmızı beklenir)"
if run 1 2-kirmizi "$@"; then
  echo "HATA: kampanya kuralı bozukken testler yeşil — testler kuralı yakalamıyor" >&2
  exit 1
fi
python3 "$proje/araclar/kirmizi_denetimi.py" "$cikti/2-kirmizi"

step "3/3 normal (yine yeşil beklenir)"
run "" 3-yesil "$@" || { echo "HATA: kırılma geri alındıktan sonra '$kategori' testleri kırmızı" >&2; exit 1; }

printf '\nKırarak doğrulama (web, C#): yeşil → kırmızı → yeşil ✓\n'
