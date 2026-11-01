#!/usr/bin/env bash
# demo-prova öz testi — yığın gerekmez (docker/uv taklit edilir; sır taraması gerçek koşar).
#
#   scripts/demo-prova-selftest.sh
#
# Doğrular:
#   1. Özet her koşunun KENDİ rapor dizinini gösterir (betik adlandırır, yerel saat); rapor yazmadan
#      düşen koşu eski bir raporla (ör. önceki çağrının -k2'si, ya da -k1/-k10 karışması) eşlenmez.
#   2. Koşu dizininde .env sırrı bulunursa koşu FAIL (çıkış 3) olur; trace.zip silinir; değer yazılmaz.
#   3. Rapor dizini 700; --sakla N yalnızca en yeni N koşu dizinini tutar; --temizle prova koşmaz;
#      video içeren arayüz raporları (yedek video) sayılmaz/silinmez, yalnızca --video-dahil ile.
#   4. Her sıfırlamadan sonra demo-reset (baseline CI) koşar (DEMO-AKISI §1.2).
#   5. Model kipi core-worker'dan okunur: .env/kabuk ya da worker replay değilse çıkış 2, özet
#      gözlenen kipi yazar (sabit "REPLAY" metni yok).
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
REPO="$(cd "$(dirname "$SELF")/.." && pwd)"
GERCEK_UV="$(command -v uv)" || { echo "uv yok" >&2; exit 2; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/tp-demo-prova-selftest.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
KOK="$TMP/reports"
BIN="$TMP/bin"
mkdir -p "$KOK" "$BIN"
SAHTE_SIR="sahte-ozt-sir-$$-degeri"

cat >"$BIN/docker" <<'S'
#!/usr/bin/env bash
case "$*" in
  *"printenv TP_REPLAY_STRICT"*) echo 1 ;;
  *"printenv TP_MODEL_MODE"*) echo "${SAHTE_WORKER_MOD:-replay}" ;;
esac
exit 0
S
cat >"$BIN/uv" <<S
#!/usr/bin/env bash
case "\$*" in
  *tp_rehearsal.sir_tarama*) exec "$GERCEK_UV" "\$@" ;;
esac
kosu="" ; yol=""
while [ \$# -gt 0 ]; do
  case "\$1" in --kosu-no) kosu="\$2"; shift ;; --rapor-yolu) yol="\$2"; shift ;; esac
  shift
done
case "\$kosu" in
  1) mkdir -p "\$yol"; echo "# Demo provası — BAŞARILI" >"\$yol/rapor.md"; exit 0 ;;
  2) exit 1 ;;  # rapor yazmadan düşer
  3) mkdir -p "\$yol/video"; echo "# BAŞARILI" >"\$yol/rapor.md"
     printf 'parola=%s\n' "\$TP_SELFTEST_TOKEN" >"\$yol/video/sizinti.txt"
     printf 'iz\n' >"\$yol/video/trace.zip"; exit 0 ;;
esac
exit 9
S
cat >"$BIN/sifirla" <<'S'
#!/usr/bin/env bash
echo reset >>"$TP_SELFTEST_CAGRI"
exit 0
S
cat >"$BIN/demo-sifirla" <<'S'
#!/usr/bin/env bash
echo demo-reset >>"$TP_SELFTEST_CAGRI"
exit 0
S
chmod +x "$BIN"/*

hata=0
ok() { printf 'PASS  %s\n' "$*"; }
kotu() { printf 'FAIL  %s\n' "$*"; hata=1; }

# Önceki bir çağrıdan kalan, başarılı görünen raporlar (yanlışlıkla bağlanmamalı).
mkdir -p "$KOK/20200101-000000-k2" "$KOK/20200101-000001-k10"
echo "# eski BAŞARILI" >"$KOK/20200101-000000-k2/rapor.md"
echo "# eski BAŞARILI" >"$KOK/20200101-000001-k10/rapor.md"
# En eski: tek yedek video kaydı (arayüz provası) — otomatik temizlikte silinmemeli.
VIDEO="$KOK/19990101-000000-ui-canli-k1"
mkdir -p "$VIDEO/video/abc"
printf 'webm\n' >"$VIDEO/video/abc/kayit.webm"

CAGRI="$TMP/cagrilar.log"
: >"$CAGRI"
kos() {
  PATH="$BIN:$PATH" TP_PROVA_RAPOR_KOK="$KOK" TP_PROVA_RESET="$BIN/sifirla" \
    TP_PROVA_DEMO_RESET="$BIN/demo-sifirla" TP_SELFTEST_CAGRI="$CAGRI" \
    TP_SELFTEST_TOKEN="$SAHTE_SIR" "$REPO/scripts/demo-prova.sh" "$@"
}

# 5a. .env/kabuk kipi replay değil → sıfırlamaya başlamadan çıkış 2, özet yazılmaz.
rc=0
TP_MODEL_MODE=auto kos --runs 1 >"$TMP/auto.log" 2>&1 || rc=$?
[ "$rc" = 2 ] && ok "TP_MODEL_MODE=auto → çıkış 2" || kotu "auto: çıkış $rc (beklenen 2)"
[ ! -s "$CAGRI" ] && ok "auto: sıfırlama başlamadı" || kotu "auto: sıfırlama çağrıldı"
ls "$KOK"/prova-ozeti-*.md >/dev/null 2>&1 && kotu "auto: özet yazıldı" || ok "auto: özet yazılmadı"
# 5b. Kabuk replay ama core-worker live (ör. eski konteyner) → çıkış 2, prova koşmaz.
rc=0
TP_MODEL_MODE=replay SAHTE_WORKER_MOD=live kos --runs 1 >"$TMP/live.log" 2>&1 || rc=$?
[ "$rc" = 2 ] && ok "core-worker live → çıkış 2" || kotu "worker live: çıkış $rc (beklenen 2)"
grep -q "TP_MODEL_MODE=live" "$TMP/live.log" && ok "worker kipi hata mesajında" || kotu "worker kipi mesajı yok"
ls "$KOK"/prova-ozeti-*.md >/dev/null 2>&1 && kotu "worker live: özet yazıldı" || ok "worker live: özet yazılmadı"
find "$KOK" -mindepth 1 -maxdepth 1 -type d -name '2*-k1' | grep -q . && kotu "worker live: prova koştu" || ok "worker live: prova koşmadı"
: >"$CAGRI"

rc=0
TP_MODEL_MODE=replay kos --runs 3 --sifirlama-yok --sakla 3 >"$TMP/cikti.log" 2>&1 || rc=$?
OZET="$(ls "$KOK"/prova-ozeti-*.md)"

[ "$rc" = 1 ] && ok "çıkış 1 (en az bir koşu başarısız)" || kotu "çıkış $rc (beklenen 1)"
satir() { grep -E "^\| $1 \|" "$OZET" || true; }
s1="$(satir 1)"; s2="$(satir 2)"; s3="$(satir 3)"
case "$s1" in *"PASS"*-k1/rapor.md*) ok "koşu 1 kendi raporunu gösterir" ;; *) kotu "koşu 1: $s1" ;; esac
case "$s2" in *"FAIL"*"rapor yazılmadı"*) ok "koşu 2 rapor yazmadı → eski rapor bağlanmadı" ;; *) kotu "koşu 2: $s2" ;; esac
case "$s2" in *20200101*) kotu "koşu 2 eski raporu gösteriyor" ;; esac
case "$s3" in *"FAIL (çıkış 3)"*"sırrı bulundu"*) ok "koşu 3: sır bulundu → FAIL" ;; *) kotu "koşu 3: $s3" ;; esac
if grep -rqF -- "$SAHTE_SIR" "$TMP/cikti.log" "$OZET"; then kotu "sır değeri çıktıya yazıldı"; else ok "sır değeri yazdırılmadı"; fi
if find "$KOK" -name trace.zip | grep -q .; then kotu "trace.zip silinmedi"; else ok "trace.zip silindi"; fi
zaman="$(basename "$OZET" .md)"; zaman="${zaman#prova-ozeti-}"
case "$s1" in *"/${zaman:0:8}-"*) ok "rapor dizini yerel tarihle adlandırıldı" ;; *) kotu "rapor adı: $s1" ;; esac
izin="$(ls -ld "$KOK" | cut -c1-10)"
[ "$izin" = "drwx------" ] && ok "rapor kökü 700" || kotu "rapor kökü izni $izin"
# 4. --sifirlama-yok + 3 koşu: koşu 2 ve 3'ten önce reset + demo-reset (sırasıyla).
[ "$(tr '\n' ' ' <"$CAGRI")" = "reset demo-reset reset demo-reset " ] \
  && ok "her sıfırlamadan sonra demo-reset" || kotu "sıfırlama sırası: $(tr '\n' ' ' <"$CAGRI")"
# 5c. Özet gözlenen kipi yazar.
grep -q "Model kipi (core-worker'dan okundu): REPLAY" "$OZET" && ok "özet gözlenen kipi yazar" \
  || kotu "özet model kipi satırı: $(grep -i 'model kipi' "$OZET")"
# --sakla 3: video dizini sayılmaz; 2 eski + koşu 1 ve 3 → en yeni 3 kalır, 20200101-000000-k2 silinir.
kalan="$(find "$KOK" -mindepth 1 -maxdepth 1 -type d ! -name '*-ui-*' | wc -l | tr -d ' ')"
[ "$kalan" = 3 ] && ok "--sakla 3: 3 koşu dizini kaldı" || kotu "--sakla 3: $kalan dizin kaldı"
[ ! -d "$KOK/20200101-000000-k2" ] && ok "en eski dizin silindi" || kotu "en eski dizin kaldı"
[ -f "$VIDEO/video/abc/kayit.webm" ] && ok "--sakla: video içeren rapor korundu" || kotu "--sakla videoyu sildi"
grep -q "video içeren 1 prova raporu korundu" "$TMP/cikti.log" && ok "korunan video bildirildi" \
  || kotu "korunan video bildirilmedi"

PATH="$BIN:$PATH" TP_PROVA_RAPOR_KOK="$KOK" "$REPO/scripts/demo-prova.sh" --temizle 1 >/dev/null
kalan="$(find "$KOK" -mindepth 1 -maxdepth 1 -type d ! -name '*-ui-*' | wc -l | tr -d ' ')"
[ "$kalan" = 1 ] && ok "--temizle 1: 1 dizin kaldı, prova koşmadı" || kotu "--temizle 1: $kalan dizin"
[ -d "$VIDEO" ] && ok "--temizle: video içeren rapor korundu" || kotu "--temizle videoyu sildi"
[ "$(ls "$KOK"/prova-ozeti-*.md | wc -l | tr -d ' ')" = 1 ] && ok "özetler korunur" || kotu "özet sayısı"

PATH="$BIN:$PATH" TP_PROVA_RAPOR_KOK="$KOK" "$REPO/scripts/demo-prova.sh" --temizle 1 --video-dahil \
  >"$TMP/video.log"
[ ! -d "$VIDEO" ] && ok "--video-dahil: video raporu silindi" || kotu "--video-dahil silmedi"
grep -q "UYARI: video içeren prova raporu siliniyor" "$TMP/video.log" && ok "video silinirken uyarı" \
  || kotu "video silinirken uyarı yok"

if [ "$hata" != 0 ]; then
  echo "--- demo-prova çıktısı (son 30) ---"; tail -30 "$TMP/cikti.log"; cat "$OZET"
  exit 1
fi
echo "demo-prova öz testi: tümü PASS"
