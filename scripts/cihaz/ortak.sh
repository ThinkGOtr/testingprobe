# shellcheck shell=bash
# Cihaz altyapısı ortak tanımları (docs/CIHAZ-ALTYAPISI.md). Diğer betikler `source` eder.
#
# Kanonik cihazlar (yalnızca bunlara dokunulur; başka şeridin `tp-mobil-gelistirme` cihazına ve
# kullanıcının diğer AVD/simülatörlerine dokunulmaz):
#   Android : AVD `tp-android`  (android-36, arm64; google_apis tercih, yoksa google_apis_playstore)
#   iOS     : simülatör `TP iPhone` (kurulu iOS çalışma zamanlarından biri; 18.x tercih)
# Appium 3 + sürücüler proje içinde: tools/appium (APPIUM_HOME; global npm kurulumu yok).

set -euo pipefail

KOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VAR="$KOK/var/cihaz"
mkdir -p "$VAR"

export APPIUM_HOME="$KOK/tools/appium"
APPIUM_BIN="$APPIUM_HOME/node_modules/.bin/appium"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$ANDROID_HOME}"
ADB="$ANDROID_HOME/platform-tools/adb"
EMULATOR="$ANDROID_HOME/emulator/emulator"
AVDMANAGER="$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager"

TP_AVD="${TP_AVD:-tp-android}"
TP_SIM="${TP_SIM:-TP iPhone}"
TP_SIM_TIPI="${TP_SIM_TIPI:-com.apple.CoreSimulator.SimDeviceType.iPhone-16}"

# Appium dinleme adresi. Varsayılan 127.0.0.1: Docker Desktop (macOS) host.docker.internal
# bağlantılarını host'un loopback'ine vekiller; konteynerler bu adrese ulaşır, LAN ulaşamaz.
# (Doğrulama: scripts/cihaz/ag-dogrula.sh; karar ve gerekçe docs/CIHAZ-ALTYAPISI.md §Ağ.)
TP_APPIUM_ADRES="${TP_APPIUM_ADRES:-127.0.0.1}"
TP_APPIUM_PORT="${TP_APPIUM_PORT:-4723}"
APPIUM_URL="http://$TP_APPIUM_ADRES:$TP_APPIUM_PORT"

APPIUM_PID="$VAR/appium.pid"
APPIUM_LOG="$VAR/appium.log"
EMULATOR_PID="$VAR/emulator.pid"
EMULATOR_LOG="$VAR/emulator.log"

# Uygulama derlemeleri (Ş1 üretir; yoksa kurulum atlanır).
MOBIL_BUILD="$KOK/demo-app/mobile/build"
TP_APP_PAKETI="${TP_APP_PAKETI:-com.antreklabs.bayi}"

bilgi() { printf '\033[36m•\033[0m %s\n' "$*"; }
uyari() { printf '\033[33m!\033[0m %s\n' "$*" >&2; }
hata() { printf '\033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }
tamam() { printf '\033[32m✓\033[0m %s\n' "$*"; }

pid_canli() { [[ -f "$1" ]] && kill -0 "$(cat "$1")" 2>/dev/null; }

appium_hazir() { curl -sf -m 2 "$APPIUM_URL/status" >/dev/null 2>&1; }

appium_kurulu() { [[ -x "$APPIUM_BIN" ]]; }

# --------------------------------------------------------------------------------- Android

# tp-android emülatörünün seri numarası (çalışmıyorsa boş). Her emülatöre adı sorulur;
# başka AVD'lerin (ör. tp-mobil-gelistirme) emülatörleri atlanır.
android_seri() {
  [[ -x "$ADB" ]] || return 0
  local s ad
  for s in $("$ADB" devices 2>/dev/null | awk '/^emulator-[0-9]+\t/{print $1}'); do
    ad="$("$ADB" -s "$s" emu avd name 2>/dev/null | head -n1 | tr -d '\r')"
    if [[ "$ad" == "$TP_AVD" ]]; then
      echo "$s"
      return 0
    fi
  done
}

avd_var() { [[ -x "$EMULATOR" ]] && "$EMULATOR" -list-avds 2>/dev/null | grep -qx "$TP_AVD"; }

android_acildi() { [[ "$("$ADB" -s "$1" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]]; }

# ------------------------------------------------------------------------------------- iOS

# `TP iPhone` simülatörünün UDID'i ve durumu: "<udid> <Booted|Shutdown|…>" (yoksa boş).
ios_sim() {
  command -v xcrun >/dev/null 2>&1 || return 0
  xcrun simctl list devices available -j 2>/dev/null | TP_SIM="$TP_SIM" python3 -c '
import json, os, sys
ad = os.environ["TP_SIM"]
d = json.load(sys.stdin)["devices"]
for runtime, cihazlar in sorted(d.items()):
    for c in cihazlar:
        if c.get("name") == ad and c.get("isAvailable", True):
            print(c["udid"], c["state"], runtime.rsplit(".", 1)[-1])
            sys.exit(0)
'
}

# Tercih edilen kurulu iOS çalışma zamanı: TP_IOS_RUNTIME ya da 18.x içinden en yenisi, yoksa
# en yeni iOS.
ios_runtime() {
  if [[ -n "${TP_IOS_RUNTIME:-}" ]]; then
    echo "$TP_IOS_RUNTIME"
    return 0
  fi
  xcrun simctl list runtimes available -j | python3 -c '
import json, sys
rt = [r for r in json.load(sys.stdin)["runtimes"] if r.get("platform") == "iOS" and r.get("isAvailable")]
anahtar = lambda r: tuple(int(x) for x in r["version"].split("."))
rt.sort(key=anahtar)
on8 = [r for r in rt if r["version"].startswith("18.")]
sec = (on8 or rt)[-1:]
print(sec[0]["identifier"] if sec else "")
'
}

# En yeni derleme (ör. demo-app/mobile/build/*.apk); yoksa boş.
son_derleme() {
  local desen="$1"
  [[ -d "$MOBIL_BUILD" ]] || return 0
  # shellcheck disable=SC2012
  ls -td "$MOBIL_BUILD"/$desen 2>/dev/null | head -n1
}
