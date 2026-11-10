#!/usr/bin/env bash
# make cihaz-kur — tek seferlik (idempotent) cihaz altyapısı kurulumu:
#   1. Appium 3 + uiautomator2 + xcuitest sürücüleri tools/appium altına (npm ci; global yok)
#   2. Android AVD `tp-android` (yoksa kurulu android-36 arm64 imajından)
#   3. iOS simülatörü `TP iPhone` (yoksa kurulu bir iOS çalışma zamanıyla)
#   4. app-mcp bağımlılıkları (toolchain/app-mcp, npm ci + derleme)
# WebDriverAgent ön derlemesi ayrı ve yavaştır: make cihaz-wda (docs/CIHAZ-ALTYAPISI.md).
source "$(dirname "$0")/ortak.sh"

# ------------------------------------------------------------------------------------ Appium
command -v node >/dev/null || hata "Node bulunamadı (22 LTS gerekir)"
# Kilit dosyası değişmediyse yeniden kurulmaz (çalışan Appium'un altından node_modules silinmez).
guncel() { [[ -f "$1/node_modules/.package-lock.json" && "$1/node_modules/.package-lock.json" -nt "$1/package-lock.json" ]]; }
if guncel "$APPIUM_HOME"; then
  bilgi "Appium bağımlılıkları güncel: $APPIUM_HOME"
else
  pid_canli "$APPIUM_PID" && hata "Appium çalışıyor; önce make cihaz-durdur (bağımlılıklar yeniden kurulacak)"
  bilgi "Appium 3 + sürücüler: $APPIUM_HOME"
  (cd "$APPIUM_HOME" && npm ci --no-audit --no-fund --loglevel=error >/dev/null)
fi
"$APPIUM_BIN" --version >/dev/null 2>&1 || hata "appium çalışmıyor"
suruculer="$("$APPIUM_BIN" driver list --installed 2>&1 || true)"
for s in uiautomator2 xcuitest; do
  grep -q "$s@" <<<"$suruculer" || hata "Appium sürücüsü görünmüyor: $s (APPIUM_HOME=$APPIUM_HOME)"
done
tamam "Appium $("$APPIUM_BIN" --version) — sürücüler: uiautomator2, xcuitest"

# ------------------------------------------------------------------------------------ Android
if [[ ! -x "$EMULATOR" || ! -x "$AVDMANAGER" ]]; then
  uyari "Android SDK eksik ($ANDROID_HOME: emulator, cmdline-tools/latest); Android atlandı"
elif avd_var; then
  tamam "AVD $TP_AVD mevcut"
else
  # Tercih: google_apis arm64 (Play Store'suz, root'lanabilir); yoksa google_apis_playstore.
  imaj=""
  for tur in google_apis google_apis_playstore; do
    for api in 36 35 34; do
      if [[ -d "$ANDROID_HOME/system-images/android-$api/$tur/arm64-v8a" ]]; then
        imaj="system-images;android-$api;$tur;arm64-v8a"
        break 2
      fi
    done
  done
  [[ -n "$imaj" ]] || hata "Kurulu arm64 Android sistem imajı yok (sdkmanager ile android-36 google_apis kurun)"
  bilgi "AVD $TP_AVD oluşturuluyor ($imaj, pixel_7)"
  echo no | "$AVDMANAGER" create avd -n "$TP_AVD" -k "$imaj" -d pixel_7 >/dev/null
  cfg="$HOME/.android/avd/$TP_AVD.avd/config.ini"
  if [[ -f "$cfg" ]]; then
    # Donanım GPU'su ve donanım klavyesi (Appium yazma işlemleri ekran klavyesini beklemez).
    sed -i '' -e 's/^hw.gpu.enabled=no/hw.gpu.enabled=yes/' -e 's/^hw.keyboard=no/hw.keyboard=yes/' "$cfg"
  fi
  tamam "AVD $TP_AVD oluşturuldu"
fi

# ---------------------------------------------------------------------------------------- iOS
if ! command -v xcrun >/dev/null 2>&1 || ! xcrun simctl help >/dev/null 2>&1; then
  uyari "Xcode / simctl yok; iOS atlandı"
elif [[ -n "$(ios_sim)" ]]; then
  tamam "Simülatör '$TP_SIM' mevcut ($(ios_sim))"
else
  rt="$(ios_runtime)"
  [[ -n "$rt" ]] || hata "Kurulu iOS simülatör çalışma zamanı yok (Xcode > Settings > Components)"
  bilgi "Simülatör '$TP_SIM' oluşturuluyor ($TP_SIM_TIPI, $rt)"
  xcrun simctl create "$TP_SIM" "$TP_SIM_TIPI" "$rt" >/dev/null
  tamam "Simülatör '$TP_SIM' oluşturuldu ($(ios_sim))"
fi

# ------------------------------------------------------------------------------------ app-mcp
if [[ -f "$KOK/toolchain/app-mcp/package-lock.json" ]]; then
  bilgi "app-mcp bağımlılıkları + derleme (toolchain/app-mcp)"
  guncel "$KOK/toolchain/app-mcp" || (cd "$KOK/toolchain/app-mcp" && npm ci --no-audit --no-fund --loglevel=error >/dev/null)
  (cd "$KOK/toolchain/app-mcp" && npm run -s build)
  tamam "app-mcp hazır"
fi

tamam "Kurulum tamam. Sonraki: make cihaz-baslat PLATFORM=android|ios  (iOS ilk kez: make cihaz-wda)"
