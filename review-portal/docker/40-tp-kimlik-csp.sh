#!/bin/sh
# Portal CSP'si kimlik kipine göre (specs/010-aiprobe-sso T042; PLAN §2.3 değiştirici).
#
# nginx resmi imajı /docker-entrypoint.d/*.sh betiklerini nginx başlamadan çalıştırır. Bu betik
# değişmez şablondan (/etc/nginx/tp/nginx.conf.sablon = repodaki nginx.conf) etkin yapılandırmayı
# yazar:
#   TP_AUTH_MODE=local (varsayılan) → şablon aynen (CSP bugünküyle aynı, dış köken yok).
#   TP_AUTH_MODE=aiprobe|both       → CSP'ye yalnız AI Probe başlangıç kökeni eklenir:
#       connect-src 'self' <home>  (değiştirici: {home}/sdk/products.json, {home}/api/v1/status)
#       img-src 'self' data: <home> (katalogdaki ürün logoları)
#     script-src eklenmez: değiştirici vendor'lanmıştır, paketle aynı kökenden gelir ('self').
# AIPROBE_HOME_ORIGIN varsayılanı https://home.aiprobe.antreklabs.com; yalnız https kökeni kabul
# edilir. Geçersiz kip/köken ya da şablonda CSP bulunamazsa betik hata verir ve kap başlamaz
# (fail-closed). Testte yollar TP_NGINX_SABLON / TP_NGINX_CONF ile değiştirilir (src/api/nginx.test.ts).
set -eu

KIP="${TP_AUTH_MODE:-local}"
SABLON="${TP_NGINX_SABLON:-/etc/nginx/tp/nginx.conf.sablon}"
HEDEF="${TP_NGINX_CONF:-/etc/nginx/nginx.conf}"
HOME_KOKENI="${AIPROBE_HOME_ORIGIN:-https://home.aiprobe.antreklabs.com}"
AD="40-tp-kimlik-csp"

case "$KIP" in
  local)
    # Şablon yoksa (imaj dışı kullanım) mevcut yapılandırma olduğu gibi kalır.
    if [ -f "$SABLON" ]; then cat "$SABLON" > "$HEDEF"; fi
    exit 0
    ;;
  aiprobe | both) ;;
  *)
    echo "$AD: geçersiz TP_AUTH_MODE='$KIP' (local|aiprobe|both)" >&2
    exit 1
    ;;
esac

if ! printf '%s\n' "$HOME_KOKENI" | grep -Eq '^https://[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:[0-9]{1,5})?$'; then
  echo "$AD: geçersiz AIPROBE_HOME_ORIGIN='$HOME_KOKENI' (https://host[:port], yol yok)" >&2
  exit 1
fi
if [ ! -f "$SABLON" ]; then
  echo "$AD: şablon yok: $SABLON" >&2
  exit 1
fi
CSP_SAYISI="$(grep -c "add_header Content-Security-Policy \"default-src 'self'; img-src 'self' data:; .*connect-src 'self';" "$SABLON" || true)"
if [ "$CSP_SAYISI" -lt 1 ]; then
  echo "$AD: şablonda beklenen CSP başlığı bulunamadı" >&2
  exit 1
fi

sed -e "/add_header Content-Security-Policy/ s#connect-src 'self';#connect-src 'self' ${HOME_KOKENI};#" \
    -e "/add_header Content-Security-Policy/ s#img-src 'self' data:;#img-src 'self' data: ${HOME_KOKENI};#" \
    "$SABLON" > "$HEDEF"
echo "$AD: TP_AUTH_MODE=$KIP, CSP'ye $HOME_KOKENI eklendi ($CSP_SAYISI başlık)"
