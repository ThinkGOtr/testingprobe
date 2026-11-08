#!/usr/bin/env bash
# make cihaz-durdur [PLATFORM=android|ios] — Appium'u ve kanonik cihaz(lar)ı durdurur.
# PLATFORM verilmezse Appium + tp-android + TP iPhone. Yalnızca kanonik cihazlara dokunulur.
source "$(dirname "$0")/ortak.sh"

PLATFORM="${1:-${PLATFORM:-}}"

appium_durdur() {
  if pid_canli "$APPIUM_PID"; then
    kill "$(cat "$APPIUM_PID")" 2>/dev/null || true
    for _ in $(seq 1 10); do pid_canli "$APPIUM_PID" || break; sleep 1; done
    pid_canli "$APPIUM_PID" && kill -9 "$(cat "$APPIUM_PID")" 2>/dev/null || true
    tamam "Appium durduruldu"
  else
    bilgi "Appium (bu betikle başlatılmış) çalışmıyor"
  fi
  rm -f "$APPIUM_PID"
}

android_durdur() {
  local seri
  seri="$(android_seri)"
  if [[ -n "$seri" ]]; then
    "$ADB" -s "$seri" emu kill >/dev/null 2>&1 || true
    tamam "Emülatör durduruldu: $TP_AVD ($seri)"
  else
    bilgi "Emülatör $TP_AVD çalışmıyor"
  fi
  rm -f "$EMULATOR_PID" "$VAR/android.seri"
}

ios_durdur() {
  local satir udid durum
  satir="$(ios_sim)"
  if [[ -z "$satir" ]]; then
    bilgi "Simülatör '$TP_SIM' yok"
    return 0
  fi
  read -r udid durum _ <<<"$satir"
  if [[ "$durum" == "Booted" ]]; then
    xcrun simctl shutdown "$udid" && tamam "Simülatör durduruldu: $TP_SIM ($udid)"
  else
    bilgi "Simülatör '$TP_SIM' zaten kapalı"
  fi
  rm -f "$VAR/ios.udid"
}

case "$PLATFORM" in
  android) android_durdur ;;
  ios) ios_durdur ;;
  "")
    appium_durdur
    android_durdur
    ios_durdur
    ;;
  *) hata "PLATFORM=android|ios (boş: hepsi)" ;;
esac
