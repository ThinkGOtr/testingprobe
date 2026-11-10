#!/usr/bin/env bash
# Mac → GCP Windows VM (tp-windows) Appium tüneli — docs/WINDOWS-GCP.md §7.
#
# tp-windows'un Appium'u (<iç-IP>:4723) yalnızca tp-demo'nun iç IP'sinden (10.156.0.2) kabul eder;
# internete açık değildir. Bu betik tp-demo'ya IAP üzerinden SSH açar ve Mac'teki
# 127.0.0.1:<yerel-port>'u tp-demo üzerinden VM'in Appium'una iletir (bağlantı VM'e tp-demo'nun
# kaynak adresiyle ulaşır, Windows güvenlik duvarı kuralı değişmez):
#
#   gcloud compute ssh tp-demo --zone europe-west3-a --tunnel-through-iap -- \
#     -N -L 127.0.0.1:14723:<winIP>:4723
#
# Sonra Mac'te: APPIUM_URL=http://127.0.0.1:14723 (run-app-checks.sh windows, duman*.mjs windows).
# Tünel ön planda kalır; Ctrl+C ile kapanır. Yalnızca 127.0.0.1'e bağlanır (LAN'a açılmaz).
#
# VERİ: bu kipte Windows uygulaması tp-demo'nun arka ucuna (https://bayi.../api) konuşur. Mac'teki
# testlerin sıfırlaması da tp-demo'ya gitmelidir; tp-demo'nun demo-app-api'si hosta port açmaz ve
# dış kapı /api/test/*'i kapatır. Bu yüzden Mac'ten yalnızca sepet yalıtımıyla koşun
# (TP_E2E_NO_RESET=1, DEMO_API_URL=https://bayi.../api — herkese açık API ile sepet boşaltılır;
# `sifir-veri` grubu atlanır, BREAK_CAMPAIGN olmaz). Tam kontrol (sıfırlama + kırarak doğrula)
# tp-demo'daki test-runner'dan koşar (docs/WINDOWS-GCP.md §6).
#
# Ortam:
#   TP_WINDOWS_VM_IP        tp-windows iç IP'si (verilmezse deploy/gcp/windows-vm/vm.sh ip)
#   TP_WINDOWS_TUNEL_PORT   Mac'teki yerel port (14723)
#   TP_DEMO_VM              atlama makinesi (tp-demo)
#   TP_DEMO_ZONE            atlama makinesinin bölgesi (europe-west3-a)
#   TP_GCP_PROJECT          GCP projesi (testingprobe)
#   DRY_RUN=1               yalnızca komutu yazdırır, çalıştırmaz
set -euo pipefail

KOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

bilgi() { printf '\033[36m•\033[0m %s\n' "$*"; }
hata() { printf '\033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

TP_DEMO_VM="${TP_DEMO_VM:-tp-demo}"
TP_DEMO_ZONE="${TP_DEMO_ZONE:-europe-west3-a}"
TP_GCP_PROJECT="${TP_GCP_PROJECT:-testingprobe}"
TP_WINDOWS_TUNEL_PORT="${TP_WINDOWS_TUNEL_PORT:-14723}"

ip="${TP_WINDOWS_VM_IP:-}"
if [[ -z "$ip" ]]; then
  vm_sh="$KOK/deploy/gcp/windows-vm/vm.sh"
  [[ -x "$vm_sh" ]] || hata "TP_WINDOWS_VM_IP verilmedi ve $vm_sh yok: TP_WINDOWS_VM_IP=<tp-windows iç IP'si> verin"
  # vm.sh ip çıktısındaki ilk IPv4 (betik açıklama satırı yazsa da yalnız adres alınır).
  ip="$("$vm_sh" ip 2>/dev/null | grep -Eo '([0-9]{1,3}\.){3}[0-9]{1,3}' | head -n 1 || true)"
  [[ -n "$ip" ]] || hata "tp-windows iç IP'si alınamadı (VM açık mı? make windows-vm-durum); ya da TP_WINDOWS_VM_IP verin"
fi

# Yalnızca VPC iç adresi (10.0.0.0/8): tünel internete ya da başka bir ağa yönlendirilmez.
if ! [[ "$ip" =~ ^10\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]] \
  || (( BASH_REMATCH[1] > 255 || BASH_REMATCH[2] > 255 || BASH_REMATCH[3] > 255 )); then
  hata "tp-windows iç IP'si 10.x.x.x biçiminde olmalı: '$ip'"
fi
if ! [[ "$TP_WINDOWS_TUNEL_PORT" =~ ^[0-9]{1,5}$ ]] || (( TP_WINDOWS_TUNEL_PORT < 1024 || TP_WINDOWS_TUNEL_PORT > 65535 )); then
  hata "TP_WINDOWS_TUNEL_PORT 1024..65535 olmalı: '$TP_WINDOWS_TUNEL_PORT'"
fi

komut=(gcloud compute ssh "$TP_DEMO_VM" --project "$TP_GCP_PROJECT" --zone "$TP_DEMO_ZONE"
  --tunnel-through-iap -- -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30
  -L "127.0.0.1:$TP_WINDOWS_TUNEL_PORT:$ip:4723")

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  printf '%q ' "${komut[@]}"
  printf '\n'
  exit 0
fi

command -v gcloud >/dev/null 2>&1 || hata "gcloud yok (brew install --cask google-cloud-sdk)"
bilgi "Tünel: 127.0.0.1:$TP_WINDOWS_TUNEL_PORT → $TP_DEMO_VM → $ip:4723 (Ctrl+C ile kapanır)"
bilgi "Mac'te: APPIUM_URL=http://127.0.0.1:$TP_WINDOWS_TUNEL_PORT ; deneme: curl -s http://127.0.0.1:$TP_WINDOWS_TUNEL_PORT/status"
exec "${komut[@]}"
