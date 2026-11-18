#!/usr/bin/env bash
# demo-app web e2e kontrolleri — C# hattı (Playwright .NET + NUnit; specs 014 test dilleri §3.2).
# run-checks.sh (TypeScript) ve run-java-checks.sh (Java) karşılığı. GitHub CI (web-csharp.yml) ve
# yerel geliştirici AYNI betiği kullanır (AI yok):
#   bağımlılık kilidi → üretilen test koruması (cs-araclar guard) → dotnet build -warnaserror
#   → birim testleri (tarayıcısız) → tarayıcı koşusu
#
# Kullanım: ci/run-csharp-checks.sh [dotnet test argümanları...]
#   TEST_FILTER   tarayıcı koşusunun NUnit süzgeci (varsayılan: Category!=birim), ör. Category=kampanya
#
# Sonuçlar (demo-app/e2e-csharp/results/):
#   junit.xml                 tarayıcı koşusu JUnit XML (JunitXml.TestLogger; ci/parse.py JUnit yolu)
#   allure-results/           Allure sonuçları (ALLURE_CONFIG ile yönlendirilir)
#   kanit/<Sınıf>.<Metot>/    başarısız testin ekran.png + trace.zip + sayfa.html (triage)
#   birim/junit.xml           birim testlerinin JUnit XML'i
#   guard.json                cs-araclar guard raporu
#
# Ortam (Altyapi/Ayarlar.cs):
#   BASE_URL (http://127.0.0.1:8081) · DEMO_API_URL ya da API_URL (/test/* kökü; yoksa <BASE_URL>/api)
#   DEMOAPP_TEST_TOKEN — ya da yalnızca sepet yalıtımı: TP_E2E_NO_RESET=1
#   BREAK_CAMPAIGN=1 (bayi kapsamlı kırılma; bkz. break-verify-csharp.sh) · TP_FAULT=<kod>
#   PLAYWRIGHT_BROWSERS_PATH  Chromium önbelleği (test sırasında indirme yok)
#   TP_CS_ARACLAR_DLL   derlenmiş cs-araclar (cs-araclar.dll); yoksa toolchain/cs-araclar'dan `dotnet run`
#   TP_E2E_CSHARP_DEPS  güvenilir kopyalar dizini (varsayılan: <repo>/toolchain/e2e-csharp-deps/web);
#                       proje dosyaları bayt eşit olmalı. CI=true iken dizin yoksa betik HATA ile durur.
#   SKIP_BIRIM=1     birim adımını atla (break-verify-csharp.sh tekrar koşularında)
#   SKIP_GUARD=1     kilit + koruma adımlarını atla (break-verify-csharp.sh tekrar koşularında)
#   SKIP_BUILD=1     derlemeyi atla (önceki adımda derlendi; break-verify-csharp.sh)
# Token yalnızca ortamdan okunur; komut satırına yazmayın, süreç listesinde görünür.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="$(cd "$root/.." && pwd)"
proje="$root/e2e-csharp"
csproj="Antreklabs.Bayi.E2e.csproj"
step() { printf '\n==> %s\n' "$*"; }

export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1
cd "$proje"
sonuc="$proje/results"
# Önceki koşunun raporu / kanıtı yeni sonuçla karışmasın.
rm -rf "$sonuc/junit.xml" "$sonuc/allure-results" "$sonuc/kanit" "$sonuc/birim" "$sonuc/guard.json"
mkdir -p "$sonuc"

if [[ "${SKIP_GUARD:-0}" != "1" ]]; then
  step "bağımlılık kilidi: proje dosyaları ↔ güvenilir kopyalar"
  # MSBuild proje/props/targets dosyaları ve .rsp yanıt dosyaları kod çalıştırabilir: yalnız
  # güvenilir kopyası olan dört dosya kabul edilir; başka MSBuild girdisi ya da sembolik bağ yok.
  yabanci="$(find . -path ./bin -prune -o -path ./obj -prune -o -path ./results -prune -o \
    \( -name '*.props' -o -name '*.targets' -o -name '*.rsp' -o -name '*.csproj' -o -name '*.sln' \
       -o -name '*.slnx' -o -name 'global.json' -o -name 'nuget.config' -o -name 'NuGet.Config' \
       -o -name 'packages.lock.json' -o -type l \) -print | sort)"
  beklenen="$(printf '%s\n' ./Antreklabs.Bayi.E2e.csproj ./Directory.Packages.props ./nuget.config ./packages.lock.json | sort)"
  if [[ "$yabanci" != "$beklenen" ]]; then
    echo "HATA: beklenmeyen MSBuild/NuGet girdisi ya da sembolik bağ:" >&2
    diff <(echo "$beklenen") <(echo "$yabanci") >&2 || true
    exit 1
  fi
  guvenilir="${TP_E2E_CSHARP_DEPS:-$repo/toolchain/e2e-csharp-deps/web}"
  if [[ -d "$guvenilir" ]]; then
    for f in "$csproj" Directory.Packages.props packages.lock.json nuget.config; do
      cmp -s "$f" "$guvenilir/$f" || {
        echo "HATA: demo-app/e2e-csharp/$f güvenilir kopya ile bayt eşit değil ($guvenilir/$f)." >&2
        echo "      Bağımlılık değişikliği önce toolchain/e2e-csharp-deps/web/'e (ve imaja) girer." >&2
        exit 1
      }
      echo "$f = $guvenilir/$f ✓"
    done
  elif [[ "${CI:-}" == "true" ]]; then
    # CI'da kilit sessizce kapanamaz: güvenilir kopya yoksa bağımlılık değişikliği denetimsiz geçer.
    echo "HATA: güvenilir kopya dizini yok ($guvenilir); CI'da bağımlılık kilidi zorunludur." >&2
    exit 1
  else
    echo "UYARI: güvenilir kopya dizini yok ($guvenilir); kilit denetimi atlandı (yerel; CI=true iken hata)"
  fi

  step "üretilen test koruması: cs-araclar guard --kimlikler"
  dosyalar=()
  # Henüz üretilen test yoksa dizin olmayabilir (demo deposu): guard boş listeyle koşar.
  if [[ -d Tests/Generated ]]; then
    while IFS= read -r f; do dosyalar+=("${f#./}"); done < <(find ./Tests/Generated -maxdepth 1 -name '*.cs' -type f | sort)
  fi
  if [[ -n "${TP_CS_ARACLAR_DLL:-}" ]]; then
    arac=(dotnet "$TP_CS_ARACLAR_DLL")
  else
    arac=(dotnet run --project "$repo/toolchain/cs-araclar/src/CsAraclar" -c Release --)
  fi
  "${arac[@]}" guard --root . --kimlikler --quiet --out "$sonuc/guard.json" -- "${dosyalar[@]+"${dosyalar[@]}"}"
fi

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  step "derleme: dotnet restore --locked-mode + dotnet build -warnaserror"
  dotnet restore "$csproj" --locked-mode
  dotnet build "$csproj" -c Release --no-restore -warnaserror -nologo
fi

if [[ "${SKIP_BIRIM:-0}" != "1" ]]; then
  step "birim testleri (tarayıcısız): Category=birim"
  dotnet test "$csproj" -c Release --no-build --filter "Category=birim" \
    --logger "junit;LogFilePath=$sonuc/birim/junit.xml" --results-directory "$sonuc/birim"
fi

# Allure sonuç dizini: Allure.Net.Commons ALLURE_CONFIG'teki JSON'dan okur (varsayılan bin/…/allure-results).
printf '{"allure":{"directory":"%s"}}\n' "$sonuc/allure-results" > "$sonuc/allureConfig.json"
export ALLURE_CONFIG="$sonuc/allureConfig.json"
export KANIT_DIZINI="${KANIT_DIZINI:-$sonuc/kanit}"

filtre="${TEST_FILTER:-Category!=birim}"
step "tarayıcı koşusu: ${BASE_URL:-http://127.0.0.1:8081} ($filtre) $*"
rc=0
dotnet test "$csproj" -c Release --no-build --filter "$filtre" \
  --logger "junit;LogFilePath=$sonuc/junit.xml" --results-directory "$sonuc" "$@" || rc=$?

printf '\nSONUÇLAR: %s\n' "$sonuc/junit.xml"
[[ -d "$sonuc/kanit" ]] && printf 'KANIT:    %s\n' "$sonuc/kanit"
exit "$rc"
