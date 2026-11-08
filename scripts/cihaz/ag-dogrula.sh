#!/usr/bin/env bash
# make cihaz-ag — konteynerlerin hosttaki Appium'a ulaştığını ve LAN'ın ulaşamadığını doğrular.
#   1. Geçici konteynerden http://host.docker.internal:4723/status (app-mcp'nin kullandığı yol)
#   2. Appium yalnızca loopback'te mi dinliyor (LAN arayüzünden erişilemez olmalı)
# Docker Desktop (macOS): host.docker.internal bağlantıları Docker Desktop sürecince host'un
# 127.0.0.1'ine vekillenir; bu yüzden Appium 127.0.0.1'e bağlı kalır, 0.0.0.0 gerekmez.
source "$(dirname "$0")/ortak.sh"

appium_hazir || hata "Appium çalışmıyor ($APPIUM_URL): önce make cihaz-baslat"
docker info >/dev/null 2>&1 || hata "Docker çalışmıyor"

# Var olan küçük bir imaj (indirme yoksa curlimages/curl çekilir).
imaj="${TP_AG_IMAJ:-curlimages/curl:8.11.1}"
bilgi "Konteynerden: http://host.docker.internal:$TP_APPIUM_PORT/status ($imaj)"
cikti="$(docker run --rm "$imaj" -sS -m 5 "http://host.docker.internal:$TP_APPIUM_PORT/status" 2>&1)" \
  || hata "Konteyner hosttaki Appium'a ulaşamadı: $cikti"
grep -q '"ready":true' <<<"$cikti" || hata "Beklenmeyen yanıt: $cikti"
tamam "Konteyner → host.docker.internal:$TP_APPIUM_PORT erişilebilir"

dinleme="$(lsof -nP -iTCP:"$TP_APPIUM_PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $9}' | sort -u | tr '\n' ' ')"
bilgi "Appium dinleme adresleri: ${dinleme:-?}"
lan="$(ipconfig getifaddr en0 2>/dev/null || true)"
if [[ -n "$lan" ]]; then
  if curl -sf -m 2 "http://$lan:$TP_APPIUM_PORT/status" >/dev/null 2>&1; then
    uyari "Appium LAN adresinden ($lan) erişilebilir: TP_APPIUM_ADRES=127.0.0.1 kullanın"
    exit 1
  fi
  tamam "LAN adresinden ($lan:$TP_APPIUM_PORT) erişilemez"
fi
