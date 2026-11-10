#!/usr/bin/env bash
# make cihaz-baslat PLATFORM=android|ios — cihazı açar, derleme varsa uygulamayı kurar, Appium'u
# başlatır (127.0.0.1:4723). İdempotent: çalışan cihaz/Appium yeniden başlatılmaz.
#   GORUNMEZ=1 : Android emülatörü penceresiz (-no-window); iOS simülatörü zaten Simulator.app
#                açılmadan (başsız) başlar, GORUNMEZ=0 iken Simulator.app de açılır.
source "$(dirname "$0")/ortak.sh"

PLATFORM="${1:-${PLATFORM:-}}"
GORUNMEZ="${GORUNMEZ:-0}"
case "$PLATFORM" in
  android | ios) ;;
  *) hata "PLATFORM=android|ios gerekli (ör. make cihaz-baslat PLATFORM=android)" ;;
esac
appium_kurulu || hata "Appium kurulu değil: önce make cihaz-kur"

# ------------------------------------------------------------------------------------ Android
android_baslat() {
  [[ -x "$EMULATOR" ]] || hata "Android emülatörü yok ($ANDROID_HOME)"
  avd_var || hata "AVD $TP_AVD yok: önce make cihaz-kur"
  local seri
  seri="$(android_seri)"
  if [[ -z "$seri" ]]; then
    local ek=(-no-boot-anim -no-audio -no-snapshot-save)
    [[ "$GORUNMEZ" == "1" ]] && ek+=(-no-window -gpu swiftshader_indirect)
    bilgi "Emülatör başlatılıyor: $TP_AVD ${ek[*]}"
    nohup "$EMULATOR" -avd "$TP_AVD" "${ek[@]}" >>"$EMULATOR_LOG" 2>&1 &
    echo $! >"$EMULATOR_PID"
    for _ in $(seq 1 90); do
      seri="$(android_seri)"
      [[ -n "$seri" ]] && break
      pid_canli "$EMULATOR_PID" || hata "Emülatör kapandı; günlük: $EMULATOR_LOG"
      sleep 2
    done
    [[ -n "$seri" ]] || hata "Emülatör adb'de görünmedi (180 sn); günlük: $EMULATOR_LOG"
  else
    bilgi "Emülatör zaten çalışıyor: $TP_AVD ($seri)"
  fi
  for _ in $(seq 1 120); do
    android_acildi "$seri" && break
    sleep 2
  done
  android_acildi "$seri" || hata "Emülatör açılışı bitmedi (240 sn): $seri"
  # Animasyonlar kapalı: deterministik bekleme ve daha hızlı otomasyon.
  for a in window_animation_scale transition_animation_scale animator_duration_scale; do
    "$ADB" -s "$seri" shell settings put global "$a" 0 >/dev/null 2>&1 || true
  done
  echo "$seri" >"$VAR/android.seri"
  tamam "Android hazır: $TP_AVD ($seri)"

  local apk
  apk="$(son_derleme '*.apk')"
  if [[ -n "$apk" ]]; then
    bilgi "Uygulama kuruluyor: ${apk#"$KOK"/}"
    "$ADB" -s "$seri" install -r -g "$apk" >/dev/null && tamam "Uygulama kuruldu"
  else
    uyari "Derleme yok (demo-app/mobile/build/*.apk); uygulama kurulumu atlandı"
  fi
}

# ---------------------------------------------------------------------------------------- iOS
ios_baslat() {
  command -v xcrun >/dev/null || hata "Xcode yok"
  local satir udid durum
  satir="$(ios_sim)"
  [[ -n "$satir" ]] || hata "Simülatör '$TP_SIM' yok: önce make cihaz-kur"
  read -r udid durum _ <<<"$satir"
  if [[ "$durum" != "Booted" ]]; then
    bilgi "Simülatör başlatılıyor: $TP_SIM ($udid)"
    xcrun simctl boot "$udid"
  else
    bilgi "Simülatör zaten açık: $TP_SIM ($udid)"
  fi
  xcrun simctl bootstatus "$udid" -b >/dev/null
  if [[ "$GORUNMEZ" != "1" ]]; then
    open -g -a Simulator --args -CurrentDeviceUDID "$udid" >/dev/null 2>&1 || true
  fi
  echo "$udid" >"$VAR/ios.udid"
  tamam "iOS hazır: $TP_SIM ($udid)"

  local app
  app="$(son_derleme '*.app')"
  if [[ -n "$app" ]]; then
    bilgi "Uygulama kuruluyor: ${app#"$KOK"/}"
    xcrun simctl install "$udid" "$app" && tamam "Uygulama kuruldu"
  else
    uyari "Derleme yok (demo-app/mobile/build/*.app); uygulama kurulumu atlandı"
  fi
}

# ------------------------------------------------------------------------------------- Appium
appium_baslat() {
  if appium_hazir; then
    tamam "Appium zaten çalışıyor: $APPIUM_URL"
    return 0
  fi
  if pid_canli "$APPIUM_PID"; then
    hata "Appium süreci var ($(cat "$APPIUM_PID")) ama $APPIUM_URL/status yanıt vermiyor; make cihaz-durdur"
  fi
  bilgi "Appium başlatılıyor: $APPIUM_URL (günlük: ${APPIUM_LOG#"$KOK"/})"
  # --relaxed-security YOK: adb shell / sürücü komutları kapalı kalır (app-mcp de kullanmaz).
  nohup "$APPIUM_BIN" --address "$TP_APPIUM_ADRES" --port "$TP_APPIUM_PORT" \
    --log-no-colors --log-timestamp --local-timezone >>"$APPIUM_LOG" 2>&1 &
  echo $! >"$APPIUM_PID"
  for _ in $(seq 1 30); do
    appium_hazir && break
    pid_canli "$APPIUM_PID" || hata "Appium kapandı; günlük: $APPIUM_LOG"
    sleep 1
  done
  appium_hazir || hata "Appium 30 sn içinde hazır olmadı; günlük: $APPIUM_LOG"
  tamam "Appium hazır: $APPIUM_URL"
}

"${PLATFORM}_baslat"
appium_baslat
