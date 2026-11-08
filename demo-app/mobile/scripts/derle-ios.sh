#!/usr/bin/env bash
# iOS simülatörü için .app derlemesi — Release yapılandırması, JS paketi .app içine gömülü;
# test anında Metro GEREKMEZ. Yalnızca simülatör içindir (imzasız, cihaza kurulmaz).
#
# Çıktı: demo-app/mobile/build/BayiSiparis.app
#
# Yöntem: `expo prebuild` (ios/ her seferinde yeniden üretilir, depoda yok) → `pod install` →
# `xcodebuild -sdk iphonesimulator -configuration Release`.
#
# Ortam:
#   EXPO_PUBLIC_API_URL / EXPO_PUBLIC_API_URL_IOS  API adresi (varsayılan http://127.0.0.1:8081/api)
#   IOS_ARCHS     simülatör mimarisi (varsayılan arm64; Intel Mac'te x86_64)
#   POD           pod komutu (varsayılan: PATH'teki çalışan ilk `pod`, olmazsa /opt/homebrew/bin/pod)
#   TEMIZ=1       node_modules'u da sıfırdan kurar (npm ci)
set -euo pipefail

KOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CIKTI="$KOK/build"
TURETILMIS="$CIKTI/ios-derived"
cd "$KOK"

export EXPO_NO_TELEMETRY=1
export LANG="${LANG:-en_US.UTF-8}"   # CocoaPods UTF-8 ister
IOS_ARCHS="${IOS_ARCHS:-arm64}"

pod_bul() {
  if [[ -n "${POD:-}" ]]; then echo "$POD"; return; fi
  if command -v pod >/dev/null 2>&1 && pod --version >/dev/null 2>&1; then command -v pod; return; fi
  if [[ -x /opt/homebrew/bin/pod ]] && /opt/homebrew/bin/pod --version >/dev/null 2>&1; then
    echo /opt/homebrew/bin/pod; return
  fi
  echo "HATA: çalışan CocoaPods bulunamadı (brew install cocoapods ya da POD=…)" >&2
  return 1
}
POD_BIN="$(pod_bul)"

if [[ "${TEMIZ:-0}" == "1" || ! -d node_modules ]]; then
  npm ci --no-audit --no-fund
fi

echo "==> Sözleşme ve tip denetimi"
node scripts/kimlik-kontrol.mjs
npx tsc --noEmit

echo "==> expo prebuild (ios)"
npx expo prebuild --platform ios --clean --no-install

echo "==> pod install ($POD_BIN)"
(cd ios && "$POD_BIN" install)

WS="$(cd ios && ls -d *.xcworkspace | head -n1)"
SEMA="${WS%.xcworkspace}"
echo "==> xcodebuild ($SEMA, Release, iphonesimulator, $IOS_ARCHS)"
xcodebuild \
  -workspace "ios/$WS" \
  -scheme "$SEMA" \
  -configuration Release \
  -sdk iphonesimulator \
  -destination "generic/platform=iOS Simulator" \
  -derivedDataPath "$TURETILMIS" \
  ARCHS="$IOS_ARCHS" ONLY_ACTIVE_ARCH=NO \
  CODE_SIGNING_ALLOWED=NO \
  -quiet \
  build

APP="$(ls -d "$TURETILMIS"/Build/Products/Release-iphonesimulator/*.app | head -n1)"
rm -rf "$CIKTI/BayiSiparis.app"
cp -R "$APP" "$CIKTI/BayiSiparis.app"
[[ -f "$CIKTI/BayiSiparis.app/main.jsbundle" ]] || { echo "HATA: main.jsbundle .app içinde yok" >&2; exit 1; }
echo "==> Hazır: $CIKTI/BayiSiparis.app (bundle id: com.antreklabs.bayisiparis)"
