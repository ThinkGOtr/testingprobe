#!/usr/bin/env bash
# demo-app Windows masaüstü e2e kontrolleri — C# / .NET 10 (Appium .NET + NUnit, NovaWindows).
# run-app-checks.sh'in (Java) C# karşılığı (014 test dilleri §3.2). GitHub CI ve yerel AYNI betik; AI yok.
#   bağımlılık kilidi → üretilen test koruması (cs-araclar guard) → dotnet build -warnaserror
#   → birim testleri (cihazsız) → cihaz koşusu (Category!=birim)
#
# Kullanım: ci/run-app-csharp-checks.sh windows
#   ör. TEST_FILTER='Category=duman' ci/run-app-csharp-checks.sh windows
#
# Sonuçlar (demo-app/e2e-app-csharp/results/):
#   junit.xml               cihaz koşusu JUnit XML (JunitXml.TestLogger; ci/parse.py JUnit yolu)
#   birim/junit.xml         birim testlerinin JUnit XML'i
#   allure-results/         Allure sonuçları (Allure.NUnit)
#   kanit/<Sınıf>.<Metot>/  başarısız testin ekran görüntüsü + sayfa kaynağı (triage)
#   guard.json              cs-araclar guard raporu
#
# Ortam (Altyapi/Ayarlar.cs): APPIUM_URL (http://127.0.0.1:4723) · APP_PATH ya da APP_ID · APP_ARGS ·
#   APP_WORKDIR · DEMO_API_URL + DEMOAPP_TEST_TOKEN (ya da TP_E2E_NO_RESET=1) · BREAK_CAMPAIGN=1 ·
#   TP_FAULT=<kod> · BEKLEME_MS · BAYI_KILIT_MS
#   TEST_FILTER        cihaz koşusuna ek NUnit süzgeci (ör. Category=kampanya)
#   SKIP_GUARD=1       kilit + guard adımlarını atla (break-verify-app-csharp.sh tekrar koşuları)
#   SKIP_BIRIM=1       birim adımını atla
#   TP_E2E_CSHARP_DEPS güvenilir kopyaların dizini (varsayılan: <repo>/toolchain/e2e-csharp-deps/windows)
# Token yalnızca ortamdan okunur; komut satırına yazmayın.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="$(cd "$root/.." && pwd)"
step() { printf '\n==> %s\n' "$*"; }

platform="${1:-}"
case "$platform" in
  windows) shift ;;
  *) echo "kullanım: $0 windows   (e2e-app-csharp yalnız Windows masaüstü uygulamasını test eder)" >&2; exit 2 ;;
esac
[[ $# -eq 0 ]] || { echo "HATA: ek argüman desteklenmez; süzgeç için TEST_FILTER kullanın" >&2; exit 2; }

app="$root/e2e-app-csharp"
proje="Antreklabs.Bayi.E2eApp.csproj"
cd "$app"
sonuc="$app/results"
rm -rf "$sonuc"
mkdir -p "$sonuc"
export PLATFORM=windows
export KANIT_DIZINI="$sonuc/kanit"
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1

# MSBuild'in proje dizininden okuduğu (kod çalıştırabilen) dosyalar: yalnız güvenilir kopyalar.
KILITLI=("$proje" Directory.Packages.props packages.lock.json nuget.config)

if [[ "${SKIP_GUARD:-0}" != "1" ]]; then
  step "bağımlılık kilidi: proje dosyaları ↔ güvenilir kopyalar"
  for f in "${KILITLI[@]}"; do
    [[ -L "$f" ]] && { echo "HATA: $f sembolik bağ olamaz" >&2; exit 1; }
  done
  yabanci="$(find . -path ./bin -prune -o -path ./obj -prune -o -path ./results -prune -o -type f \
    \( -name '*.props' -o -name '*.targets' -o -name '*.rsp' -o -name '*.csproj' -o -name 'global.json' \
       -o -name 'Directory.Build.*' -o -name '*.dll' \) -print | sed 's|^\./||' | sort)"
  for f in $yabanci; do
    case " ${KILITLI[*]} " in *" $f "*) ;; *)
      echo "HATA: $f: MSBuild/NuGet yapılandırması yalnız güvenilir dosyalarla olur (kod çalıştırabilir)." >&2
      exit 1 ;;
    esac
  done
  guvenilir="${TP_E2E_CSHARP_DEPS:-$repo/toolchain/e2e-csharp-deps/windows}"
  if [[ -d "$guvenilir" ]]; then
    for f in "${KILITLI[@]}"; do
      cmp -s "$f" "$guvenilir/$f" || {
        echo "HATA: demo-app/e2e-app-csharp/$f güvenilir kopyayla bayt eşit değil ($guvenilir/$f)." >&2
        echo "      Bağımlılık değişikliği önce toolchain/e2e-csharp-deps/windows/'a (ve imaja) girer." >&2
        exit 1
      }
    done
    echo "kilitli dosyalar = $guvenilir ✓"
  elif [[ "${CI:-}" == "true" ]]; then
    echo "HATA: güvenilir kopyalar yok ($guvenilir); CI'da bağımlılık kilidi zorunludur." >&2
    exit 1
  else
    echo "UYARI: güvenilir kopyalar yok ($guvenilir); kilit denetimi atlandı (yerel; CI=true iken hata)"
  fi

  step "üretilen test koruması: cs-araclar guard --kimlikler"
  dosyalar=()
  if [[ -d Tests/Generated ]]; then
    while IFS= read -r f; do dosyalar+=("$f"); done < <(find Tests/Generated -maxdepth 1 -name '*.cs' -type f | sort)
  fi
  araclar="${TP_CS_ARACLAR:-}"
  if [[ -n "$araclar" ]]; then
    "$araclar" guard --root . --kimlikler --quiet --out "$sonuc/guard.json" -- "${dosyalar[@]}"
  else
    dotnet run --project "$repo/toolchain/cs-araclar/src/CsAraclar" -c Release -- \
      guard --root . --kimlikler --quiet --out "$sonuc/guard.json" -- "${dosyalar[@]}"
  fi
fi

step "bağımlılıklar: dotnet restore --locked-mode"
dotnet restore "$proje" --locked-mode

step "derleme: dotnet build -warnaserror"
dotnet build "$proje" --no-restore -c Debug -warnaserror -nologo

if [[ "${SKIP_BIRIM:-0}" != "1" ]]; then
  step "birim testleri (cihazsız): Category=birim"
  dotnet test "$proje" --no-build --filter "Category=birim" \
    --logger "junit;LogFilePath=$sonuc/birim/junit.xml" --results-directory "$sonuc/birim"
fi

suzgec="Category!=birim"
[[ -n "${TEST_FILTER:-}" ]] && suzgec="($suzgec)&(${TEST_FILTER})"
step "cihaz koşusu: platform=windows süzgeç=$suzgec"
rc=0
dotnet test "$proje" --no-build --filter "$suzgec" \
  --logger "junit;LogFilePath=$sonuc/junit.xml" --results-directory "$sonuc/trx" || rc=$?

allure="$(find bin -type d -name allure-results 2>/dev/null | head -1 || true)"
[[ -n "$allure" ]] && cp -R "$allure" "$sonuc/allure-results"

printf '\nSONUÇLAR: %s\n' "$sonuc/junit.xml"
[[ -d "$sonuc/kanit" ]] && printf 'KANIT:    %s\n' "$sonuc/kanit"
exit "$rc"
