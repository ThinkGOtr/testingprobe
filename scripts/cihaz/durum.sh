#!/usr/bin/env bash
# make cihaz-durum — Appium, kanonik cihazlar ve uygulama derlemelerinin durumu (salt okuma).
source "$(dirname "$0")/ortak.sh"
set +e

satir() { printf '  %-14s %s\n' "$1" "$2"; }

echo "Cihaz altyapısı"
if appium_kurulu; then
  satir "Appium" "$("$APPIUM_BIN" --version 2>/dev/null) (APPIUM_HOME=${APPIUM_HOME#"$KOK"/})"
else
  satir "Appium" "kurulu değil (make cihaz-kur)"
fi
if appium_hazir; then
  # Oturum listesi (/appium/sessions) Appium 3'te güvensiz özellik (session_discovery); açılmaz.
  sahip="harici süreç"
  pid_canli "$APPIUM_PID" && sahip="pid $(cat "$APPIUM_PID")"
  satir "Appium sunucu" "çalışıyor $APPIUM_URL ($sahip)"
else
  satir "Appium sunucu" "kapalı"
fi

if avd_var; then
  seri="$(android_seri)"
  if [[ -n "$seri" ]]; then
    acik="açılıyor"
    android_acildi "$seri" && acik="hazır"
    satir "Android" "$TP_AVD çalışıyor ($seri, $acik)"
    if "$ADB" -s "$seri" shell pm path "$TP_APP_PAKETI" >/dev/null 2>&1; then
      satir "  uygulama" "$TP_APP_PAKETI kurulu"
    else
      satir "  uygulama" "$TP_APP_PAKETI kurulu değil"
    fi
  else
    satir "Android" "$TP_AVD kapalı"
  fi
else
  satir "Android" "AVD $TP_AVD yok (make cihaz-kur)"
fi

sim="$(ios_sim)"
if [[ -n "$sim" ]]; then
  read -r udid durum rt <<<"$sim"
  satir "iOS" "$TP_SIM $durum ($udid, $rt)"
else
  satir "iOS" "simülatör '$TP_SIM' yok (make cihaz-kur)"
fi

apk="$(son_derleme '*.apk')"
app="$(son_derleme '*.app')"
satir "Derleme apk" "${apk:+${apk#"$KOK"/}}${apk:-yok}"
satir "Derleme app" "${app:+${app#"$KOK"/}}${app:-yok}"
exit 0
