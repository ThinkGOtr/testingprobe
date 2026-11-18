#!/usr/bin/env bash
# "Kırarak doğrula" (yeşil → kırmızı → yeşil) — Windows masaüstü, C# (e2e-app-csharp);
# break-verify-app.sh'in C# karşılığı. Kampanya testlerinin kuralı gerçekten yakaladığını kanıtlar. AI yok.
#   1) normal koşu           → kampanya kategorisi geçmeli
#   2) BREAK_CAMPAIGN=1 koşu → kırmızılar YALNIZCA doğrulama (NUnit AssertionException) olmalı; kurulum
#                              (/test/, giriş başarısız, DEMOAPP_TEST_TOKEN), locator (WebDriverTimeoutException)
#                              ve atlanan test kırmızı sayılmaz; en az bir kırmızı olmalı
#   3) normal koşu           → yine geçmeli (kırılma geri alındı)
#
# Kullanım: ci/break-verify-app-csharp.sh windows
# Ortam: run-app-csharp-checks.sh ile aynı; DEMOAPP_TEST_TOKEN + DEMO_API_URL ZORUNLU.
#        BREAK_VERIFY_GROUPS (varsayılan: kampanya) — NUnit kategorisi.
# Her adımın JUnit XML'i: demo-app/e2e-app-csharp/kirarak-dogrula/<adım>/junit.xml
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ "${1:-}" == "windows" ]] || { echo "kullanım: $0 windows" >&2; exit 2; }
[[ -n "${DEMOAPP_TEST_TOKEN:-}" ]] || { echo "HATA: DEMOAPP_TEST_TOKEN gerekli (kırılma POST /test/break ile açılır)" >&2; exit 2; }

grup="${BREAK_VERIFY_GROUPS:-kampanya}"
[[ "$grup" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo "HATA: BREAK_VERIFY_GROUPS geçersiz: $grup" >&2; exit 2; }
app="$root/e2e-app-csharp"
cikti="$app/kirarak-dogrula"
py="$(command -v python3 || command -v python || true)"
[[ -n "$py" ]] || { echo "HATA: kırmızı denetimi için python3 gerekli" >&2; exit 2; }
step() { printf '\n==> %s\n' "$*"; }

run() {  # $1 = BREAK_CAMPAIGN değeri, $2 = adım adı, $3 = ilk koşu mu (kilit + guard + birim)
  local rc=0 skip=1
  [[ "$3" == "1" ]] && skip=0
  BREAK_CAMPAIGN="$1" SKIP_GUARD="$skip" SKIP_BIRIM=1 TEST_FILTER="Category=$grup" \
    "$root/ci/run-app-csharp-checks.sh" windows || rc=$?
  rm -rf "${cikti:?}/$2"
  mkdir -p "$cikti/$2"
  cp "$app/results/junit.xml" "$cikti/$2/" 2>/dev/null || true
  return "$rc"
}

# Kırmızı adım denetimi (Java araclar/KirmiziDenetimi.java karşılığı). JunitXml.TestLogger hata
# türünü `type` özniteliğine yazmaz; NUnit ileti biçimi ayırt eder: beklenmeyen istisna
# "<Tam.Tür.Adı> : <ileti>" ile başlar, AssertionException iletisi düz metindir; [SetUp]'taki
# (TestTabani hazırlığı) hata "SetUp : …" önekini taşır ve her zaman kurulum sayılır.
kirmizi_denetimi() {
  "$py" - "$1" <<'PY'
import re, sys, xml.etree.ElementTree as ET
from pathlib import Path
KURULUM = re.compile(r"^\s*(SetUp|TearDown) : |/test/|giriş başarısız|DEMOAPP_TEST_TOKEN")
ISTISNA = re.compile(r"^\s*[A-Za-z_][\w.]*(Exception|Error)\s:\s")
yol = Path(sys.argv[1]) / "junit.xml"
if not yol.is_file():
    sys.exit(f"HATA: {yol} yok")
kirmizi, kotu = [], []
for tc in ET.parse(yol).getroot().iter("testcase"):
    ad = f"{tc.get('classname')}.{tc.get('name')}"
    if tc.find("skipped") is not None:
        kotu.append(f"{ad} [atlandı]")
        continue
    hata = tc.find("failure") if tc.find("failure") is not None else tc.find("error")
    if hata is None:
        continue
    ileti = (hata.get("message") or "") + "\n" + (hata.text or "")
    if KURULUM.search(ileti):
        kotu.append(f"{ad} [kurulum]")
    elif ISTISNA.match(hata.get("message") or ""):
        kotu.append(f"{ad} [istisna: {(hata.get('message') or '').split(':')[0].strip()}]")
    else:
        kirmizi.append(ad)
print("kırmızı (assertion):", *kirmizi, sep="\n  ")
if kotu:
    print("kabul edilmeyen:", *kotu, sep="\n  ")
if not kirmizi or kotu:
    sys.exit("HATA: kırmızı adım yalnız assertion kırmızılarından oluşmalı (en az bir)")
PY
}

rm -rf "$cikti"

step "1/3 normal (yeşil beklenir)"
run "" 1-yesil 1 || { echo "HATA: kırılma olmadan '$grup' testleri kırmızı" >&2; exit 1; }

step "2/3 BREAK_CAMPAIGN=1 (kırmızı beklenir)"
if run 1 2-kirmizi 0; then
  echo "HATA: kampanya kuralı bozukken testler yeşil — testler kuralı yakalamıyor" >&2
  exit 1
fi
kirmizi_denetimi "$cikti/2-kirmizi"

step "3/3 normal (yine yeşil beklenir)"
run "" 3-yesil 0 || { echo "HATA: kırılma geri alındıktan sonra '$grup' testleri kırmızı" >&2; exit 1; }

printf '\nKırarak doğrulama (windows, C#): yeşil → kırmızı → yeşil ✓\n'
