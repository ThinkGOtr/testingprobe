#!/usr/bin/env bash
# Android APK derlemesi — JS paketi APK'ya gömülü; test anında Metro GEREKMEZ.
#
# Çıktı: demo-app/mobile/build/bayi-siparis.apk
#
# Yöntem: `expo prebuild` (android/ her seferinde yeniden üretilir, depoda yok) → Gradle
# `assembleRelease`. Expo şablonunda release varyantı debug anahtarıyla (android/app/debug.keystore)
# imzalanır: kurulabilir, `adb install` ile yüklenir, Hermes bayt kodu + gömülü paket içerir,
# geliştirici menüsü / LogBox katmanı YOKTUR (testte ekrana fazladan eleman çıkmaz). Bu yüzden
# "debug imzalı release" seçildi; mağaza imzası yoktur, dağıtılmaz.
#
# Ortam:
#   EXPO_PUBLIC_API_URL / EXPO_PUBLIC_API_URL_ANDROID  API adresi (varsayılan http://10.0.2.2:8081/api)
#   ANDROID_ABI      derlenecek ABI'ler (varsayılan: arm64-v8a,x86_64 — Apple Silicon emülatörü + CI KVM)
#   TEMIZ=1          node_modules'u da sıfırdan kurar (npm ci)
set -euo pipefail

KOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CIKTI="$KOK/build"
cd "$KOK"

export EXPO_NO_TELEMETRY=1
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
if [[ -z "${JAVA_HOME:-}" ]] && [[ -x /usr/libexec/java_home ]]; then
  JAVA_HOME="$(/usr/libexec/java_home -v 17 2>/dev/null || true)"
  export JAVA_HOME
fi
ANDROID_ABI="${ANDROID_ABI:-arm64-v8a,x86_64}"

[[ -d "$ANDROID_HOME" ]] || { echo "HATA: Android SDK yok: $ANDROID_HOME" >&2; exit 1; }

if [[ "${TEMIZ:-0}" == "1" || ! -d node_modules ]]; then
  npm ci --no-audit --no-fund
fi

echo "==> Sözleşme ve tip denetimi"
node scripts/kimlik-kontrol.mjs
npx tsc --noEmit

echo "==> expo prebuild (android)"
npx expo prebuild --platform android --clean --no-install

echo "==> Gradle assembleRelease (ABI: $ANDROID_ABI)"
(cd android && ./gradlew --no-daemon -q assembleRelease -PreactNativeArchitectures="$ANDROID_ABI")

mkdir -p "$CIKTI"
cp android/app/build/outputs/apk/release/app-release.apk "$CIKTI/bayi-siparis.apk"
echo "==> Hazır: $CIKTI/bayi-siparis.apk (paket: com.antreklabs.bayisiparis)"
