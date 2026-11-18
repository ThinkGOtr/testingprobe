#!/usr/bin/env bash
# "Kırarak doğrula" (yeşil → kırmızı → yeşil) — Python hattı (web ya da uygulama); break-verify-
# java.sh / break-verify-app.sh karşılığı. Kampanya testlerinin kuralı gerçekten yakaladığını
# kanıtlar. AI yok.
#   1) normal koşu           → kampanya testleri geçmeli
#   2) BREAK_CAMPAIGN=1 koşu → kırmızı testlerin HEPSİ doğrulama (AssertionError) ile kalmalı:
#                              kurulum hatası (/test/*, giriş, token; `<error>`), locator zaman
#                              aşımı (TimeoutError / TimeoutException) ve atlanan test kırmızı
#                              SAYILMAZ (JUnit XML aşağıdaki denetimle okunur; KirmiziDenetimi.java
#                              ile aynı kural); en az bir kırmızı olmalı
#   3) normal koşu           → yine geçmeli (kırılma geri alındı, kalıcı iz yok)
# Kırılma bayi kapsamlıdır (POST /test/break) ve yalnızca test süresince açıktır; koşu tek
# süreçtir (bayi1 ve dealer ile sabitlenmiş testin bayisi etkilenir; doğrulama ajanının bayisi
# bayi3 hiçbir zaman).
#
# Kullanım: ci/break-verify-python-checks.sh <web|android|ios|windows> [pytest argümanları...]
# Ortam: run-python-checks.sh ile aynı; DEMOAPP_TEST_TOKEN ZORUNLU (kırılma /test/break ister).
#        BREAK_VERIFY_MARK (varsayılan: kampanya) — pytest işareti.
# Her adımın JUnit XML'i ve (kırmızıda) kanıtı: <proje>/results/kirarak-dogrula/<adım>/
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
platform="${1:-}"
case "$platform" in
  web) proje="$root/e2e-python"; shift ;;
  android|ios|windows) proje="$root/e2e-app-python"; shift ;;
  *) echo "kullanım: $0 <web|android|ios|windows> [pytest argümanları...]" >&2; exit 2 ;;
esac
[[ -n "${DEMOAPP_TEST_TOKEN:-}" ]] || { echo "HATA: DEMOAPP_TEST_TOKEN gerekli (kırılma POST /test/break ile açılır)" >&2; exit 2; }

isaret="${BREAK_VERIFY_MARK:-kampanya}"
cikti="$proje/results/kirarak-dogrula"
step() { printf '\n==> %s\n' "$*"; }

# İlk koşu venv'i kurar ve kilidi denetler; sonrakiler hazır venv'i kullanır.
kurulum=(SKIP_BIRIM=1)
run() {  # $1 = BREAK_CAMPAIGN değeri, $2 = adım adı; çıkış kodunu döndürür
  local rc=0
  env "${kurulum[@]}" BREAK_CAMPAIGN="$1" TP_REPEAT=1 \
    "$root/ci/run-python-checks.sh" "$platform" -m "$isaret" "${@:3}" || rc=$?
  kurulum=(SKIP_BIRIM=1 SKIP_INSTALL=1 SKIP_GUARD=1)
  rm -rf "${cikti:?}/$2"
  mkdir -p "$cikti/$2"
  cp "$proje/results/junit.xml" "$cikti/$2/" 2>/dev/null || true
  [[ -d "$proje/results/kanit" ]] && cp -R "$proje/results/kanit" "$cikti/$2/kanit"
  return "$rc"
}

rm -rf "$cikti"

step "1/3 normal (yeşil beklenir)"
run "" 1-yesil "$@" || { echo "HATA: kırılma olmadan '$isaret' testleri kırmızı" >&2; exit 1; }

step "2/3 BREAK_CAMPAIGN=1 (kırmızı beklenir)"
if run 1 2-kirmizi "$@"; then
  echo "HATA: kampanya kuralı bozukken testler yeşil — testler kuralı yakalamıyor" >&2
  exit 1
fi
py="$proje/.venv/bin/python"
[[ -x "$py" ]] || py="$proje/.venv/Scripts/python.exe"
"$py" - "$cikti/2-kirmizi/junit.xml" <<'EOF'
# Kırmızı denetimi (KirmiziDenetimi.java karşılığı; yalnız stdlib). pytest JUnit XML'inde
# `<failure>` test gövdesinin hatasıdır (mesaj "AssertionError: …" ile başlar), `<error>` hazırlık /
# fikstür hatasıdır. Rapor test kodunun çıktısıdır: DTD/varlık bildirimi reddedilir.
import re
import sys
import xml.etree.ElementTree as ET

KURULUM = re.compile(r"/test/|giriş başarısız|DEMOAPP_TEST_TOKEN|KurulumHatasi")
veri = open(sys.argv[1], "rb").read()
if b"<!DOCTYPE" in veri or b"<!ENTITY" in veri:
    sys.exit("HATA: JUnit XML'de DTD/varlık bildirimi")
kirmizi, kotu = [], []
for tc in ET.fromstring(veri).iter("testcase"):
    ad = f"{tc.get('classname', '')}.{tc.get('name', '')}"
    sonuc = next((c for c in tc if c.tag in ("failure", "error", "skipped")), None)
    if sonuc is None:
        continue
    mesaj = sonuc.get("message") or ""
    if sonuc.tag == "failure" and mesaj.startswith("AssertionError") and not KURULUM.search(mesaj):
        kirmizi.append(ad)
    else:
        kotu.append(f"{ad} [{sonuc.tag}: {mesaj[:120]}]")
print("kırmızı (assertion): " + (" | ".join(kirmizi) or "-"))
if kotu:
    print(f"HATA: {len(kotu)} sonuç doğrulama (assertion) hatası değil (kurulum/locator hatası ya da atlandı):",
          file=sys.stderr)
    for k in kotu:
        print("  " + k, file=sys.stderr)
    sys.exit(1)
if not kirmizi:
    sys.exit("HATA: kırmızı test yok")
EOF

step "3/3 normal (yine yeşil beklenir)"
run "" 3-yesil "$@" || { echo "HATA: kırılma geri alındıktan sonra '$isaret' testleri kırmızı" >&2; exit 1; }

printf '\nKırarak doğrulama (%s, Python): yeşil → kırmızı → yeşil ✓\n' "$platform"
