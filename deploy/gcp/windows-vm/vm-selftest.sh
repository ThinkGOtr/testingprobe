#!/usr/bin/env bash
# vm.sh öz testi — GCP gerekmez; PATH'e sahte `gcloud` konur, gerçek gcloud hiç çağrılmaz.
#
#   deploy/gcp/windows-vm/vm-selftest.sh
#
# Doğrular:
#   1. olustur (DRY_RUN=1, EVET=1) sözleşmedeki bayrakları içerir: windows-2022, e2-medium,
#      europe-west1-b, 50GB pd-standard, --enable-display-device, shielded bayrakları, dört tp-*
#      metadata anahtarı + windows-startup-script-ps1; --tags / --no-address YOK; yazan çağrı yok.
#   2. tp-demo iç IP'si otomatik bulunur; bulunamazsa 10.156.0.2'ye düşer; TP_WINDOWS_VM_IZINLI önceliklidir.
#   3. olustur ve sil etkileşimsiz kipte EVET=1 olmadan reddeder (gcloud yazma çağrısı yok).
#   4. kurulum.ps1 yoksa olustur açık mesajla düşer.
#   5. ac/kapat/sil DRY_RUN'da yalnızca yazdırır; bekle HAZIR'da 0, HATA'da ≠0; ip yalnızca IP yazar.
set -euo pipefail
BURASI="$(cd "$(dirname "$0")" && pwd)"
VMSH="$BURASI/vm.sh"

TMP="$(mktemp -d "${TMPDIR:-/tmp}/tp-windows-vm-selftest.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"
CAGRI="$TMP/cagri.log"
KURULUM="$TMP/kurulum.ps1"
echo '# sahte kurulum' >"$KURULUM"

# Sahte gcloud: her çağrıyı kaydeder; salt okuma çağrılarına sabit yanıt verir; yazan çağrıda iz bırakır.
cat >"$TMP/bin/gcloud" <<'S'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$SAHTE_CAGRI"
case "$*" in
  *"instances describe tp-demo "*)
    [ "${SAHTE_TPDEMO_YOK:-0}" = "1" ] && exit 1
    echo 10.156.0.77 ;;
  *"instances describe"*"value(status)"*) echo RUNNING ;;
  *"instances describe"*"networkIP"*) echo 10.132.0.5 ;;
  *"get-serial-port-output"*)
    printf 'önyükleme...\r\n%s\r\n' "${SAHTE_SERI:-}" ;;
  *"instances create"*|*"instances start"*|*"instances stop"*|*"instances delete"*|*"firewall-rules"*|*"add-metadata"*)
    echo "YAZMA $*" >>"$SAHTE_CAGRI.yazma" ;;
esac
exit 0
S
chmod +x "$TMP/bin/gcloud"

export PATH="$TMP/bin:$PATH" SAHTE_CAGRI="$CAGRI" TP_WINDOWS_VM_KURULUM="$KURULUM"
unset TP_GCP_PROJECT TP_WINDOWS_VM_NAME TP_WINDOWS_VM_ZONE TP_WINDOWS_VM_MACHINE TP_WINDOWS_VM_REF \
  TP_WINDOWS_VM_IZINLI TP_WINDOWS_VM_API_URL EVET DRY_RUN 2>/dev/null || true

HATA=0
gec() { printf '  ✓ %s\n' "$1"; }
kal() { printf '  ✗ %s\n' "$1" >&2; HATA=1; }
icerir() { case "$1" in *"$2"*) gec "$3" ;; *) kal "$3 — '$2' yok" ;; esac; }
icermez() { case "$1" in *"$2"*) kal "$3 — '$2' var" ;; *) gec "$3" ;; esac; }
yazma_yok() { if [ -s "$CAGRI.yazma" ]; then kal "$1 — gerçek yazma çağrısı yapıldı"; else gec "$1"; fi; }

echo "1. olustur DRY_RUN"
cikti="$(DRY_RUN=1 EVET=1 "$VMSH" olustur </dev/null 2>/dev/null)"
for b in "DRY_RUN: gcloud --project testingprobe compute instances create tp-windows" \
  "--zone europe-west1-b" "--machine-type e2-medium" "--image-project windows-cloud" \
  "--image-family windows-2022" "--boot-disk-size 50GB" "--boot-disk-type pd-standard" \
  "--enable-display-device" "--shielded-secure-boot" "--shielded-vtpm" \
  "--shielded-integrity-monitoring" "--network default" "tp-repo=ThinkGOtr/testingprobe" \
  "tp-repo-ref=dev" "tp-izinli-kaynak=10.156.0.77" \
  "tp-api-url=https://bayi.testing-probe.antreklabs.com/api" \
  "windows-startup-script-ps1=$KURULUM"; do
  icerir "$cikti" "$b" "bayrak: $b"
done
icermez "$cikti" "--tags" "ağ etiketi yok"
icermez "$cikti" "--no-address" "geçici dış IP korunur"
icermez "$(cat "$CAGRI")" "firewall-rules" "güvenlik duvarı kuralına dokunulmaz"
yazma_yok "DRY_RUN yazmaz"

echo "2. izinli kaynak"
cikti="$(SAHTE_TPDEMO_YOK=1 DRY_RUN=1 EVET=1 "$VMSH" olustur </dev/null 2>/dev/null)"
icerir "$cikti" "tp-izinli-kaynak=10.156.0.2" "tp-demo okunamazsa 10.156.0.2"
cikti="$(TP_WINDOWS_VM_IZINLI=10.156.0.9 TP_WINDOWS_VM_MACHINE=e2-standard-2 DRY_RUN=1 EVET=1 "$VMSH" olustur </dev/null 2>/dev/null)"
icerir "$cikti" "tp-izinli-kaynak=10.156.0.9" "TP_WINDOWS_VM_IZINLI önceliklidir"
icerir "$cikti" "--machine-type e2-standard-2" "TP_WINDOWS_VM_MACHINE"
for kotu in "0.0.0.0/0" "10.156.0.2,x" "abc"; do
if TP_WINDOWS_VM_IZINLI="$kotu" DRY_RUN=1 EVET=1 "$VMSH" olustur </dev/null >/dev/null 2>&1; then
  kal "geçersiz izinli kaynak reddedilmeli: $kotu"; else gec "geçersiz izinli kaynak reddedilir: $kotu"; fi
done

echo "3. onaysız reddetme"
: >"$CAGRI"
if DRY_RUN=1 "$VMSH" olustur </dev/null >"$TMP/o.out" 2>"$TMP/o.err"; then
  kal "olustur EVET=1 olmadan reddetmeli"; else gec "olustur EVET=1 olmadan reddeder"; fi
icerir "$(cat "$TMP/o.err")" "EVET=1" "ret mesajı EVET=1'i anar"
icermez "$(cat "$TMP/o.out")" "instances create" "reddedince komut yazdırılmaz"
if "$VMSH" sil </dev/null >/dev/null 2>&1; then
  kal "sil EVET=1 olmadan reddetmeli"; else gec "sil EVET=1 olmadan reddeder"; fi
yazma_yok "reddedince yazma yok"

echo "4. kurulum.ps1 yok"
if TP_WINDOWS_VM_KURULUM="$TMP/yok.ps1" DRY_RUN=1 EVET=1 "$VMSH" olustur </dev/null >/dev/null 2>"$TMP/k.err"; then
  kal "kurulum.ps1 yokken düşmeli"; else gec "kurulum.ps1 yokken düşer"; fi
icerir "$(cat "$TMP/k.err")" "kurulum.ps1" "mesaj betiği anar"

echo "5. diğer komutlar"
icerir "$(DRY_RUN=1 "$VMSH" ac 2>/dev/null)" "DRY_RUN: gcloud --project testingprobe compute instances start tp-windows --zone europe-west1-b" "ac"
icerir "$(DRY_RUN=1 "$VMSH" kapat 2>/dev/null)" "compute instances stop tp-windows" "kapat"
cikti="$(DRY_RUN=1 EVET=1 "$VMSH" sil 2>/dev/null)"
icerir "$cikti" "compute instances delete tp-windows --zone europe-west1-b --delete-disks all --quiet" "sil diski de siler"
yazma_yok "ac/kapat/sil DRY_RUN yazmaz"
if [ "$("$VMSH" ip 2>/dev/null)" = "10.132.0.5" ]; then gec "ip yalnızca IP"; else kal "ip çıktısı"; fi
cikti="$(SAHTE_SERI='TP-WINDOWS-HAZIR appium=4723 uygulama=C:\tp\uygulama\BayiSiparis.exe ref=dev' "$VMSH" durum 2>/dev/null)"
icerir "$cikti" "kurulum : TP-WINDOWS-HAZIR appium=4723" "durum son satırı gösterir"
icermez "$cikti" "önyükleme" "durum seri çıktının geri kalanını yazmaz"
if SAHTE_SERI='TP-WINDOWS-HAZIR appium=4723' TP_WINDOWS_VM_BEKLE_ARALIK=0 "$VMSH" bekle >/dev/null 2>&1; then
  gec "bekle HAZIR'da 0"; else kal "bekle HAZIR'da 0 dönmeli"; fi
if SAHTE_SERI='TP-WINDOWS-HATA node indirme' TP_WINDOWS_VM_BEKLE_ARALIK=0 "$VMSH" bekle >/dev/null 2>&1; then
  kal "bekle HATA'da ≠0 dönmeli"; else gec "bekle HATA'da ≠0"; fi
if SAHTE_SERI='kurulum sürüyor' TP_WINDOWS_VM_BEKLE_DK=0 TP_WINDOWS_VM_BEKLE_ARALIK=0 "$VMSH" bekle >/dev/null 2>&1; then
  kal "bekle zaman aşımında ≠0 dönmeli"; else gec "bekle zaman aşımında ≠0"; fi
yazma_yok "salt okuma komutları yazmaz"

if [ "$HATA" -ne 0 ]; then echo "vm-selftest: BAŞARISIZ" >&2; exit 1; fi
echo "vm-selftest: tamam"
