#!/usr/bin/env bash
# make cihaz-wda — WebDriverAgent'ı `TP iPhone` simülatörü için önceden derler.
# xcuitest'in ilk oturumu WDA'yı xcodebuild ile derler (birkaç dakika); bu adım derlemeyi
# Xcode DerivedData önbelleğine alır, sonraki oturumlar artımlı derlemeyle saniyeler içinde açılır.
# Xcode sürümü değişince yeniden çalıştırın.
source "$(dirname "$0")/ortak.sh"

appium_kurulu || hata "Appium kurulu değil: önce make cihaz-kur"
satir="$(ios_sim)"
[[ -n "$satir" ]] || hata "Simülatör '$TP_SIM' yok: önce make cihaz-kur"
read -r udid _ rt <<<"$satir"
# rt: iOS-18-5 → 18.5
sdk="$(sed -E 's/^iOS-([0-9]+)-([0-9]+).*/\1.\2/' <<<"$rt")"
bilgi "WebDriverAgent derleniyor: $TP_SIM ($udid, iOS $sdk) — birkaç dakika sürebilir"
# Not: xcuitest 12.x `build-wda` betiği derleme bittiğinde bekleyen sözü çözmediği için
# "unsettled top-level await" ile 13 kodlu çıkar; başarı ölçütü xcodebuild'in kendi satırıdır.
"$APPIUM_BIN" driver run xcuitest build-wda --name "$TP_SIM" --sdk "$sdk" >"$VAR/wda-derleme.log" 2>&1 || true
grep -q '\*\* TEST BUILD SUCCEEDED \*\*' "$VAR/wda-derleme.log" \
  || hata "WDA derlenemedi; günlük: ${VAR#"$KOK"/}/wda-derleme.log"
tamam "WebDriverAgent derlendi (günlük: ${VAR#"$KOK"/}/wda-derleme.log)"
