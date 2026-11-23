#!/usr/bin/env bash
# tp-vm deploy paketi girişi (aiprobe-platform vm-product: /opt/tp/current/bin/up.sh).
# Sırlar /run/tp/tp.env (tmpfs) -> paket kökünde .env (yalnız root okur), sonra `make up`.
set -euo pipefail
cd "$(dirname "$0")/.."
# startup-script ortamında HOME tanımsız; git config --global için gerekli.
export HOME="${HOME:-/root}"
command -v git >/dev/null 2>&1 || { apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git; }
# Paket başka bir uid ile arşivlenmiş olabilir; root git "dubious ownership" demesin.
chown -R root:root .
git config --global --add safe.directory "$(pwd -P)"
install -m 600 /run/tp/tp.env .env
# Config R1: .env'de CONFIG_SOURCE=home ise aiprobe-home etkin config'i (TP_HOME_PROJECT) .env'e
# işlenir (sırlar Secret Manager'dan; Home yoksa LKG). Yalnız standart kütüphane (python3 >= 3.9):
# çekirdek imajı gerekmez. LKG veri diskinde (sır değeri değil, yalnız referans tutar).
# home kipinde Home da LKG de yoksa (ya da python3 yok/eski) açılış DURUR: env'e sessizce düşmek
# Home'da kapatılmış özellikleri ve değiştirilmiş hedefleri yok sayardı. Geri dönüş: tp-env'de
# CONFIG_SOURCE=env. env kipinde yükleyici yalnız uyarır (bugünkü davranış).
if grep -Eiq "^[[:space:]]*(export[[:space:]]+)?CONFIG_SOURCE=['\"]?home" .env; then
  tp_config_home=1
else
  tp_config_home=0
fi
if command -v python3 >/dev/null 2>&1 \
  && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  if ! PYTHONPATH="$(pwd -P)/core/src" python3 -m tp_core.home_config \
    --env-dosyasi .env --lkg "${TP_CONFIG_LKG:-/mnt/tp-data/tp-config/lkg-boot.json}"; then
    if [ "$tp_config_home" = 1 ]; then
      echo "HATA: CONFIG_SOURCE=home ama Home config'i uygulanamadı (Home ve LKG yok); açılış durduruldu" >&2
      exit 1
    fi
    echo "UYARI: home config uygulanamadı; .env (tp-env) ile devam" >&2
  fi
elif [ "$tp_config_home" = 1 ]; then
  echo "HATA: CONFIG_SOURCE=home ama python3 (>= 3.9) yok; açılış durduruldu" >&2
  exit 1
fi
export TP_WAIT_TIMEOUT="${TP_WAIT_TIMEOUT:-900}"
# Disk koruması (2026-11-18: 30G diskte derleme önbelleği 19.5G'a çıkıp C# katmanı açılırken
# "no space left on device"). Derlemeden önce önbellek üst sınırlı tutulur; askıda imajlar silinir.
# Çalışan/etiketli imajlara dokunulmaz. Hata açılışı durdurmaz.
if command -v docker >/dev/null 2>&1; then
  docker builder prune -f --keep-storage "${TP_BUILD_CACHE_KEEP:-6gb}" >/dev/null 2>&1 \
    || echo "UYARI: docker derleme önbelleği temizlenemedi" >&2
  docker image prune -f >/dev/null 2>&1 || true
  # 2026-11-18 (2.): sınırlı önbellek yetmedi — yeni kaynakla tam yeniden derleme ~15-18G ister.
  # Kökte TP_BUILD_MIN_FREE_GB'den az yer varsa önbellek ve kullanılmayan imajlar tamamen silinir.
  bos_gb=$(df -BG --output=avail / 2>/dev/null | tail -1 | tr -dc '0-9')
  if [ -n "$bos_gb" ] && [ "$bos_gb" -lt "${TP_BUILD_MIN_FREE_GB:-20}" ]; then
    echo "UYARI: kökte ${bos_gb}G boş; derleme önbelleği ve kullanılmayan imajlar tamamen siliniyor" >&2
    docker builder prune -af >/dev/null 2>&1 || true
    docker image prune -af >/dev/null 2>&1 || true
  fi
fi
make up
# Demo kipi: çalışan demo-app-web'i main'e eşitleyen host izleyicisi (systemd). Kırma/sıfırlama
# sonrası yenileme isteğini bu uygular; yoksa triage locator kuralı ve onarım yolu çalışan
# uygulamada eşleşme bulamaz. Hata açılışı durdurmaz (izleyici "Demoya hazır" listesinde görünür).
if grep -Eiq '^[[:space:]]*(export[[:space:]]+)?TP_DEMO_MODE=['"'"'"]?(1|true|yes|on)['"'"'"]?[[:space:]]*$' .env \
  && command -v systemctl >/dev/null 2>&1; then
  kok="$(pwd -L)"
  if sed "s#__KOK__#${kok}#" deploy/aiprobe/tp-demo-web-sync.service \
      > /etc/systemd/system/tp-demo-web-sync.service.tmp \
    && mv -f /etc/systemd/system/tp-demo-web-sync.service.tmp /etc/systemd/system/tp-demo-web-sync.service \
    && systemctl daemon-reload && systemctl enable tp-demo-web-sync.service >/dev/null 2>&1 \
    && systemctl restart tp-demo-web-sync.service; then
    echo "demo-web-sync izleyicisi çalışıyor (tp-demo-web-sync.service)"
  else
    echo "UYARI: demo-web-sync izleyicisi kurulamadı (systemctl status tp-demo-web-sync)" >&2
  fi
elif command -v systemctl >/dev/null 2>&1 && [ -f /etc/systemd/system/tp-demo-web-sync.service ]; then
  # Demo kipi kapatıldı: izleyici durdurulur (demo yazmaları yapılmaz).
  systemctl disable --now tp-demo-web-sync.service >/dev/null 2>&1 || true
fi
