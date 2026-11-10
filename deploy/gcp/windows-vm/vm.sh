#!/usr/bin/env bash
# Windows masaüstü testi için GCP Windows VM'inin (tp-windows) yaşam döngüsü — Mac tarafı.
# Sözleşme: specs/009-mobil-masaustu/windows-gcp.md · Kılavuz: deploy/gcp/windows-vm/README.md
#
#   deploy/gcp/windows-vm/vm.sh <komut>
#
# Komutlar:
#   olustur  VM'i oluşturur (onay ister; EVET=1 ile atlanır). kurulum.ps1 her açılışta koşar.
#   ac       VM'i başlatır.            kapat  VM'i durdurur (disk ücreti sürer).
#   durum    Durum + iç IP + seri porttaki son TP-WINDOWS-HAZIR/HATA satırı.
#   bekle    Seri portta HAZIR görünene dek bekler; HATA ya da zaman aşımında ≠0.
#   ekran    Ekran görüntüsünü var/windows-vm/ altına kaydeder, yolu yazar.
#   sil      VM'i ve önyükleme diskini siler (onay ister; EVET=1 ile atlanır).
#   ip       Yalnızca iç IP'yi yazar (TP_WINDOWS_VM_APPIUM=<ip>:4723 için).
#
# Ortam: TP_GCP_PROJECT, TP_WINDOWS_VM_NAME, TP_WINDOWS_VM_ZONE, TP_WINDOWS_VM_MACHINE,
#   TP_WINDOWS_VM_REPO, TP_WINDOWS_VM_REF, TP_WINDOWS_VM_IZINLI, TP_WINDOWS_VM_API_URL,
#   TP_WINDOWS_VM_BEKLE_DK (45), TP_WINDOWS_VM_BEKLE_ARALIK (sn, 20), TP_WINDOWS_VM_KURULUM (betik yolu).
#   DRY_RUN=1: yazan gcloud komutları çalıştırılmaz, yalnızca yazdırılır. EVET=1: onay sorulmaz.
#
# Güvenlik: bu betik GCP güvenlik duvarı kuralı OLUŞTURMAZ ve VM'e ağ etiketi VERMEZ; yalnızca
# default-allow-internal / default-allow-icmp geçerlidir. Seri port çıktısının yalnızca durum satırı
# yazdırılır.
set -euo pipefail

KOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

PROJE="${TP_GCP_PROJECT:-testingprobe}"
VM="${TP_WINDOWS_VM_NAME:-tp-windows}"
BOLGE="${TP_WINDOWS_VM_ZONE:-europe-west1-b}"
MAKINE="${TP_WINDOWS_VM_MACHINE:-e2-medium}"
DEPO="${TP_WINDOWS_VM_REPO:-ThinkGOtr/testingprobe}"
REF="${TP_WINDOWS_VM_REF:-dev}"
API_URL="${TP_WINDOWS_VM_API_URL:-https://bayi.testing-probe.antreklabs.com/api}"
KURULUM="${TP_WINDOWS_VM_KURULUM:-$KOK/deploy/gcp/windows-vm/kurulum.ps1}"
BEKLE_DK="${TP_WINDOWS_VM_BEKLE_DK:-45}"
BEKLE_ARALIK="${TP_WINDOWS_VM_BEKLE_ARALIK:-20}"
EKRAN_DIZIN="$KOK/var/windows-vm"   # var/ .gitignore'da

# tp-demo (izinli kaynak) — iç IP'si otomatik bulunamazsa sözleşmedeki varsayılan
TP_DEMO_VM="tp-demo"
TP_DEMO_BOLGE="europe-west3-a"
TP_DEMO_IP_YEDEK="10.156.0.2"

DURUM_DESENI='TP-WINDOWS-(HAZIR|HATA)'

bilgi() { printf '\033[36m•\033[0m %s\n' "$*" >&2; }
uyari() { printf '\033[33m!\033[0m %s\n' "$*" >&2; }
hata() { printf '\033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }
tamam() { printf '\033[32m✓\033[0m %s\n' "$*" >&2; }

command -v gcloud >/dev/null 2>&1 || hata "gcloud bulunamadı (docs/GCP-KURULUM.md §Önkoşullar)."

# Salt okuyan gcloud çağrısı — DRY_RUN'da da çalışır.
gc() { gcloud --project "$PROJE" "$@"; }

# Yazan gcloud çağrısı — DRY_RUN=1 ise yalnızca komutu yazdırır.
gc_yaz() {
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    printf 'DRY_RUN:'
    printf ' %q' gcloud --project "$PROJE" "$@"
    printf '\n'
    return 0
  fi
  gc "$@"
}

# Tehlikeli işlem onayı: EVET=1 ya da etkileşimli olarak VM adının yazılması.
onayla() {
  local islem="$1" cevap
  [[ "${EVET:-0}" == "1" ]] && return 0
  if [[ ! -t 0 ]]; then
    hata "$islem onay ister; etkileşimsiz kipte EVET=1 verin."
  fi
  printf '%s: proje=%s vm=%s bölge=%s\nOnaylamak için VM adını yazın (%s): ' \
    "$islem" "$PROJE" "$VM" "$BOLGE" "$VM" >&2
  read -r cevap || cevap=""
  [[ "$cevap" == "$VM" ]] || hata "Onaylanmadı; işlem yapılmadı."
}

ic_ip() {
  gc compute instances describe "$VM" --zone "$BOLGE" \
    --format='value(networkInterfaces[0].networkIP)'
}

vm_durumu() {
  gc compute instances describe "$VM" --zone "$BOLGE" --format='value(status)' 2>/dev/null || true
}

# Seri port 1'deki son HAZIR/HATA satırı (yoksa boş). Yalnızca bu satır yazdırılır.
son_durum_satiri() {
  gc compute instances get-serial-port-output "$VM" --zone "$BOLGE" --port 1 2>/dev/null \
    | tr -d '\r' | grep -Eo "${DURUM_DESENI}.*" | tail -n 1 || true
}

izinli_kaynak() {
  if [[ -n "${TP_WINDOWS_VM_IZINLI:-}" ]]; then
    printf '%s' "$TP_WINDOWS_VM_IZINLI"; return 0
  fi
  local ip
  ip="$(gc compute instances describe "$TP_DEMO_VM" --zone "$TP_DEMO_BOLGE" \
        --format='value(networkInterfaces[0].networkIP)' 2>/dev/null || true)"
  if [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    printf '%s' "$ip"
  else
    uyari "$TP_DEMO_VM iç IP'si okunamadı; varsayılan $TP_DEMO_IP_YEDEK kullanılıyor (TP_WINDOWS_VM_IZINLI ile değiştirin)."
    printf '%s' "$TP_DEMO_IP_YEDEK"
  fi
}

# --metadata değerleri virgül içeremez (gcloud ayracı).
metadata_degeri() {
  case "$2" in *,*) hata "$1 değeri virgül içeremez: $2" ;; esac
  printf '%s' "$2"
}

k_olustur() {
  [[ -f "$KURULUM" ]] || hata "Kurulum betiği yok: $KURULUM (deploy/gcp/windows-vm/kurulum.ps1 gerekli)."
  local izinli
  izinli="$(izinli_kaynak)"
  # Tek adres (CIDR yok): 4723'e yalnızca tp-demo erişsin.
  [[ "$izinli" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && [[ "$izinli" != "0.0.0.0" ]] \
    || hata "TP_WINDOWS_VM_IZINLI tek bir IPv4 adresi olmalı: $izinli"
  local md
  md="tp-repo=$(metadata_degeri tp-repo "$DEPO")"
  md+=",tp-repo-ref=$(metadata_degeri tp-repo-ref "$REF")"
  md+=",tp-izinli-kaynak=$izinli"
  md+=",tp-api-url=$(metadata_degeri tp-api-url "$API_URL")"

  bilgi "Oluşturulacak: $VM ($MAKINE, $BOLGE, windows-2022, 50 GB pd-standard) proje=$PROJE"
  bilgi "Depo: $DEPO@$REF · Appium izinli kaynak: $izinli · Ağ etiketi yok, güvenlik duvarı kuralı yok"
  onayla "OLUŞTUR"
  gc_yaz compute instances create "$VM" \
    --zone "$BOLGE" \
    --machine-type "$MAKINE" \
    --image-project windows-cloud \
    --image-family windows-2022 \
    --boot-disk-size 50GB \
    --boot-disk-type pd-standard \
    --boot-disk-auto-delete \
    --enable-display-device \
    --shielded-secure-boot \
    --shielded-vtpm \
    --shielded-integrity-monitoring \
    --network default \
    --metadata "$md" \
    --metadata-from-file "windows-startup-script-ps1=$KURULUM"
  [[ "${DRY_RUN:-0}" == "1" ]] || tamam "Oluşturuldu. İlk kurulum ~20–40 dk sürer: make windows-vm-bekle"
}

k_ac() {
  gc_yaz compute instances start "$VM" --zone "$BOLGE"
  [[ "${DRY_RUN:-0}" == "1" ]] || tamam "Başlatıldı; hazır olmasını bekleyin: make windows-vm-bekle"
}

k_kapat() {
  gc_yaz compute instances stop "$VM" --zone "$BOLGE"
  [[ "${DRY_RUN:-0}" == "1" ]] || tamam "Durduruldu (disk ücreti sürer; tamamen kaldırmak: make windows-vm-sil)."
}

k_durum() {
  local durum ip satir
  durum="$(vm_durumu)"
  [[ -n "$durum" ]] || hata "$VM bulunamadı (proje=$PROJE bölge=$BOLGE)."
  ip="$(ic_ip 2>/dev/null || true)"
  printf 'vm      : %s (%s, proje=%s)\n' "$VM" "$BOLGE" "$PROJE"
  printf 'durum   : %s\n' "$durum"
  printf 'iç IP   : %s\n' "${ip:--}"
  if [[ "$durum" == "RUNNING" ]]; then
    satir="$(son_durum_satiri)"
    printf 'kurulum : %s\n' "${satir:-henüz satır yok (kurulum sürüyor olabilir)}"
  fi
}

k_bekle() {
  [[ "$BEKLE_DK" =~ ^[0-9]+$ ]] || hata "TP_WINDOWS_VM_BEKLE_DK sayı olmalı: $BEKLE_DK"
  [[ "$BEKLE_ARALIK" =~ ^[0-9]+$ ]] || hata "TP_WINDOWS_VM_BEKLE_ARALIK sayı olmalı: $BEKLE_ARALIK"
  local bitis satir durum
  bitis=$(( $(date +%s) + BEKLE_DK * 60 ))
  bilgi "$VM seri portunda TP-WINDOWS-HAZIR bekleniyor (en çok $BEKLE_DK dk)…"
  while :; do
    durum="$(vm_durumu)"
    if [[ "$durum" == "RUNNING" ]]; then
      satir="$(son_durum_satiri)"
      case "$satir" in
        TP-WINDOWS-HAZIR*) printf '%s\n' "$satir"; tamam "Hazır."; return 0 ;;
        TP-WINDOWS-HATA*) printf '%s\n' "$satir"; hata "Kurulum hata bildirdi (ayrıntı: make windows-vm-ekran)." ;;
      esac
    fi
    if (( $(date +%s) >= bitis )); then
      hata "Zaman aşımı ($BEKLE_DK dk); son durum=${durum:-?}. Ekran: make windows-vm-ekran"
    fi
    sleep "$BEKLE_ARALIK"
  done
}

k_ekran() {
  mkdir -p "$EKRAN_DIZIN"
  local dosya
  dosya="$EKRAN_DIZIN/ekran-$(date +%Y%m%d-%H%M%S).png"
  gc compute instances get-screenshot "$VM" --zone "$BOLGE" --destination "$dosya" >/dev/null
  printf '%s\n' "$dosya"
}

k_sil() {
  bilgi "Silinecek: $VM ve önyükleme diski (proje=$PROJE bölge=$BOLGE). Geri alınamaz."
  onayla "SİL"
  gc_yaz compute instances delete "$VM" --zone "$BOLGE" --delete-disks all --quiet
  [[ "${DRY_RUN:-0}" == "1" ]] || tamam "Silindi."
}

k_ip() {
  local ip
  ip="$(ic_ip)" || hata "$VM okunamadı (proje=$PROJE bölge=$BOLGE)."
  [[ -n "$ip" ]] || hata "$VM iç IP'si yok."
  printf '%s\n' "$ip"
}

kullanim() {
  sed -n '2,23p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

case "${1:-}" in
  olustur) k_olustur ;;
  ac) k_ac ;;
  kapat) k_kapat ;;
  durum) k_durum ;;
  bekle) k_bekle ;;
  ekran) k_ekran ;;
  sil) k_sil ;;
  ip) k_ip ;;
  *) kullanim ;;
esac
