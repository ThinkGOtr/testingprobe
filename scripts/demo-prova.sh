#!/usr/bin/env bash
# demo-prova — tam demo provası: sıfırla → 14 adım + locator kırma/onarım, N kez; özet.
#
#   scripts/demo-prova.sh                 # 1 koşu: make reset + make demo-reset → API provası
#   scripts/demo-prova.sh --runs 3        # TEKNIK-TASARIM §13: 3 ardışık sorunsuz prova
#   scripts/demo-prova.sh --sifirlama-yok # ilk koşudan önce sıfırlama yapma (yığın zaten temizse)
#   scripts/demo-prova.sh --ui            # API yerine portal + jira-sim arayüzüyle (Playwright,
#                                         # video + adım ekran görüntüleri; rehearsal/ui/)
#   scripts/demo-prova.sh --ui-tur        # her API provasından sonra salt okuma arayüz turu
#                                         # (yedek video: tamamlanmış akışın ekranları)
#   scripts/demo-prova.sh --devam         # adım başarısız olsa da provayı sürdür (tanı için)
#   scripts/demo-prova.sh --kirma-yayinla # API provasında isteğe bağlı C6: kırma taslağı → yeni Bug
#                                         # (story + Test issue bağlı; sahnede taslak karara kalır)
#   scripts/demo-prova.sh --sakla 10      # bitince yalnızca son 10 koşu rapor dizinini tut (0: silme)
#   scripts/demo-prova.sh --temizle [N]   # prova koşmadan eski rapor dizinlerini temizle (son N, 10)
#   scripts/demo-prova.sh --temizle N --video-dahil  # video içeren arayüz raporlarını da sil
#
# Video (.webm/.mp4) içeren rapor dizinleri (-ui-canli-, -ui-tur-: yedek video) otomatik temizlikte
# ne sayılır ne silinir; yalnızca açık `--video-dahil` ile silinir (her biri için uyarı yazılır).
#
# Sıfırlama sunucunun sunum öncesi sırasıdır (DEMO-AKISI §1.2): `make reset` (scripts/reset.sh:
# denetim kaydı exports/ altına dışa aktarılır, çekirdek veri + artefaktlar silinir, forge ve
# jira-sim demo başlangıcına döner, seed yüklenir) ardından `make demo-reset` (main → demo-baseline,
# baseline push CI kuyruğa girer); P0 bu temel koşunun yeşil bitmesini bekler. Demo-A (TPD-1 ön
# inceleme) ancak temiz veritabanında yeniden oynatılabildiği için tek başına `make demo-reset`
# yetmez. Model kipi core-worker'dan okunur: TP_MODEL_MODE=replay değilse prova koşmaz (çıkış 2).
# Prova `TP_REPLAY_STRICT=1` ile koşar: betik değişkeni dışa aktarır, compose core-worker'ı
# bu değerle yeniden oluşturur (golden'a düşmez; REPLAY-MISS provayı düşürür). Betik bitince
# core-worker önceki değerine döndürülür (`--strict-birak` ile 1'de kalır).
#
# Çıkış: 0 = tüm koşular başarılı; 1 = en az bir koşu başarısız; 2 = kullanım/ön koşul hatası.
# Raporlar: rehearsal/reports/<zaman>-k<n>/ (API) · <zaman>-ui-canli-k<n>/ (--ui) ·
# <zaman>-ui-tur-k<n>/ (--ui-tur) + rehearsal/reports/prova-ozeti-<zaman>.md. <zaman> yerel saattir ve
# dizin adını bu betik verir: özet yalnızca BU koşunun yazdığı raporu gösterir (yoksa "rapor yok").
# Rapor dizini yalnızca sahibine açıktır (700). Her koşudan sonra dizin .env sırlarına karşı taranır
# (trace.zip silinir); sır bulunursa koşu başarısız sayılır (yedek video paketi paylaşılmamalı).
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
# shellcheck source=scripts/lib.sh
. "$(dirname "$SELF")/lib.sh"

RUNS=1
SIFIRLA=1
UI=0
UI_TUR=0
DEVAM=()
STRICT_BIRAK=0
KIRMA=()
SAKLA=10
TEMIZLE=0
VIDEO_DAHIL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --runs) [ $# -ge 2 ] || die "--runs bir sayı ister"; RUNS="$2"; shift ;;
    --runs=*) RUNS="${1#--runs=}" ;;
    --sifirlama-yok) SIFIRLA=0 ;;
    --ui) UI=1 ;;
    --ui-tur) UI_TUR=1 ;;
    --devam) DEVAM=(--devam) ;;
    --strict-birak) STRICT_BIRAK=1 ;;
    --kirma-yayinla) KIRMA=(--kirma-yayinla) ;;
    --video-dahil) VIDEO_DAHIL=1 ;;
    --sakla) [ $# -ge 2 ] || die "--sakla bir sayı ister"; SAKLA="$2"; shift ;;
    --temizle)
      TEMIZLE=1
      if [ $# -ge 2 ] && [ -n "$2" ] && [ "${2#-}" = "$2" ]; then SAKLA="$2"; shift; fi ;;
    -h|--help) sed -n '2,36p' "$SELF" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) err "bilinmeyen argüman: $1 (yardım: --help)"; exit 2 ;;
  esac
  shift
done
case "$RUNS" in ''|*[!0-9]*|0) err "--runs pozitif tam sayı olmalı: $RUNS"; exit 2 ;; esac
case "$SAKLA" in ''|*[!0-9]*) err "--sakla/--temizle sıfır ya da pozitif tam sayı olmalı: $SAKLA"; exit 2 ;; esac

# TP_PROVA_RAPOR_KOK / TP_PROVA_RESET yalnızca öz testi içindir (scripts/demo-prova-selftest.sh).
RAPOR_KOK="${TP_PROVA_RAPOR_KOK:-$TP_REPO_ROOT/rehearsal/reports}"
SIFIRLA_KOMUTU="${TP_PROVA_RESET:-$TP_REPO_ROOT/scripts/reset.sh}"
DEMO_SIFIRLA_KOMUTU="${TP_PROVA_DEMO_RESET:-$TP_REPO_ROOT/scripts/demo-reset.sh}"
mkdir -p "$RAPOR_KOK"
chmod 700 "$RAPOR_KOK"

video_var() {
  [ -n "$(find "$1" -type f \( -name '*.webm' -o -name '*.mp4' \) -print 2>/dev/null | head -n 1)" ]
}

# Koşu rapor dizinlerinden (adı <YYYYMMDD-HHMMSS>[-...]) en yeni N'i tutar; özetler ve .reset logları
# küçük olduğundan kalır. Video içeren dizinler (yedek video; bir UI koşusu 200–450 MB) sayılmaz ve
# silinmez — yalnızca VIDEO_DAHIL=1 (--video-dahil) ile, her biri için uyarıyla.
eskileri_temizle() {
  local n="$1" d sayac=0 korunan=0
  [ "$n" -gt 0 ] || return 0
  while IFS= read -r d; do
    [ -n "$d" ] || continue
    if video_var "$RAPOR_KOK/$d"; then
      if [ "$VIDEO_DAHIL" != 1 ]; then
        korunan=$((korunan + 1))
        continue
      fi
    fi
    sayac=$((sayac + 1))
    [ "$sayac" -gt "$n" ] || continue
    if video_var "$RAPOR_KOK/$d"; then
      echo "UYARI: video içeren prova raporu siliniyor (--video-dahil): rehearsal/reports/$d"
    fi
    rm -rf -- "${RAPOR_KOK:?}/$d"
    echo "eski prova raporu silindi: rehearsal/reports/$d"
  done <<EOF_DIZIN
$(find "$RAPOR_KOK" -mindepth 1 -maxdepth 1 -type d -name '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]*' \
    -exec basename {} \; | sort -r)
EOF_DIZIN
  if [ "$korunan" -gt 0 ]; then
    echo "video içeren $korunan prova raporu korundu (yedek video; silmek için: scripts/demo-prova.sh --temizle N --video-dahil)"
  fi
}

if [ "$TEMIZLE" = 1 ]; then
  eskileri_temizle "$SAKLA"
  exit 0
fi

command -v uv >/dev/null 2>&1 || { err "uv bulunamadı (rehearsal/ bir uv projesidir)"; exit 2; }
if [ "$UI" = 1 ] || [ "$UI_TUR" = 1 ]; then
  command -v npx >/dev/null 2>&1 || { err "npx bulunamadı (rehearsal/ui Playwright ister)"; exit 2; }
  [ -d rehearsal/ui/node_modules/@playwright/test ] \
    || { err "rehearsal/ui bağımlılıkları yok: (cd rehearsal/ui && npm ci)"; exit 2; }
fi
[ -n "$(env_get SEED_USER_PASSWORD)" ] || { err ".env SEED_USER_PASSWORD yok"; exit 2; }
# 013 K19: test verisi parola sırrı tanımsızsa kod üretimi `test_verisi` engeliyle durur; farklı
# değer REPLAY kayıtlarındaki demo parolasıyla uyuşmaz (render taraması PR'ı durdurur).
# Değer yazdırılmaz. Eksikse: `make env` (.env.example'daki demo değeri eklenir).
ornek_parola="$(env_get TP_TESTVERI_DEMO_PAROLA .env.example)"
if [ -z "$(env_get TP_TESTVERI_DEMO_PAROLA)" ]; then
  err ".env TP_TESTVERI_DEMO_PAROLA boş ya da yok (013 K19): 'make env' çalıştırın ya da .env.example'daki değeri yazın"
  exit 2
elif [ -n "$ornek_parola" ] && [ "$(env_get TP_TESTVERI_DEMO_PAROLA)" != "$ornek_parola" ]; then
  err ".env TP_TESTVERI_DEMO_PAROLA demo değerinden farklı: REPLAY kayıtları demo parolasıyla; prova kod üretiminde durur"
  exit 2
fi

# §13 provası strict REPLAY'dir. compose core-worker'a TP_MODEL_MODE'u kabuk ortamından, yoksa .env'den
# verir (varsayılan auto). auto/live'da prova gerçek, değerlendirilmemiş model çağrısı yapar ve özet
# yalan söylerdi: sıfırlamaya hiç başlamadan durulur.
BEKLENEN_MOD="${TP_MODEL_MODE:-$(env_get TP_MODEL_MODE)}"
BEKLENEN_MOD="${BEKLENEN_MOD:-auto}"
if [ "$BEKLENEN_MOD" != replay ]; then
  err "HATA: TP_MODEL_MODE=$BEKLENEN_MOD — demo provası yalnızca REPLAY'de koşar (TEKNIK-TASARIM §13)."
  err "      .env'de TP_MODEL_MODE=replay yapın (kabukta export edilmişse kaldırın), sonra yeniden deneyin."
  exit 2
fi

worker_strict() {
  docker compose exec -T core-worker printenv TP_REPLAY_STRICT 2>/dev/null | tr -d '[:space:]' || true
}
ONCEKI_STRICT="$(worker_strict)"
export TP_REPLAY_STRICT=1

strict_geri_al() {
  [ "$STRICT_BIRAK" = 1 ] && return 0
  [ "${ONCEKI_STRICT:-0}" = 1 ] && return 0
  echo "core-worker TP_REPLAY_STRICT önceki değerine (${ONCEKI_STRICT:-0}) döndürülüyor..."
  TP_REPLAY_STRICT="${ONCEKI_STRICT:-0}" docker compose up -d --no-deps --wait --wait-timeout 180 core-worker \
    >/dev/null 2>&1 || err "UYARI: core-worker geri döndürülemedi (make up)"
}
trap strict_geri_al EXIT

worker_mod() {
  docker compose exec -T core-worker printenv TP_MODEL_MODE 2>/dev/null | tr -d '[:space:]' || true
}

# Koşudan önce core-worker'ın gerçekten replay'de olduğunu doğrular (özet gözlenen kipi yazar).
mod_dogrula() {
  local m
  m="$(worker_mod)"
  if [ "$m" != replay ]; then
    err "HATA: core-worker TP_MODEL_MODE=${m:-okunamadı} — prova yalnızca REPLAY'de koşar (çıkış 2)."
    err "      .env'de TP_MODEL_MODE=replay yapıp 'make up' çalıştırın."
    exit 2
  fi
  GOZLENEN_MOD="$m"
}
GOZLENEN_MOD=""

strict_ac() {
  if [ "$(worker_strict)" != 1 ]; then
    echo "core-worker TP_REPLAY_STRICT=1 ile yeniden oluşturuluyor..."
    docker compose up -d --no-deps --wait --wait-timeout 180 core-worker >/dev/null \
      || die "core-worker TP_REPLAY_STRICT=1 ile başlatılamadı"
  fi
  [ "$(worker_strict)" = 1 ] || die "core-worker TP_REPLAY_STRICT=1 değil"
}

ZAMAN="$(date +%Y%m%d-%H%M%S)"
OZET="$RAPOR_KOK/prova-ozeti-$ZAMAN.md"
satirlar=()
basarili=0
ardisik=0
en_iyi_ardisik=0

for i in $(seq 1 "$RUNS"); do
  echo
  echo "================ Prova $i/$RUNS ================"
  t0=$(date +%s)
  if [ "$SIFIRLA" = 1 ] || [ "$i" -gt 1 ]; then
    echo "Sıfırlama: make reset (denetim dışa aktarılır, çekirdek veri silinir)..."
    if ! "$SIFIRLA_KOMUTU" > "$RAPOR_KOK/.reset-$ZAMAN-k$i.log" 2>&1; then
      tail -20 "$RAPOR_KOK/.reset-$ZAMAN-k$i.log" >&2
      satirlar+=("| $i | sıfırlama | ❌ FAIL | $(( $(date +%s) - t0 )) sn | make reset başarısız |")
      ardisik=0
      continue
    fi
  fi
  strict_ac
  mod_dogrula
  if [ "$SIFIRLA" = 1 ] || [ "$i" -gt 1 ]; then
    echo "Demo sıfırlaması: make demo-reset (main → demo-baseline + baseline push CI; DEMO-AKISI §1.2)..."
    if ! "$DEMO_SIFIRLA_KOMUTU" >> "$RAPOR_KOK/.reset-$ZAMAN-k$i.log" 2>&1; then
      tail -20 "$RAPOR_KOK/.reset-$ZAMAN-k$i.log" >&2
      satirlar+=("| $i | sıfırlama | ❌ FAIL | $(( $(date +%s) - t0 )) sn | make demo-reset başarısız |")
      ardisik=0
      continue
    fi
  fi
  rc=0
  # Koşunun rapor dizini burada, yerel saatle adlandırılır ve koşuya verilir: özet yalnızca bu
  # koşunun yazdığı raporu gösterir (eski koşunun raporu yanlışlıkla bağlanmaz).
  kz="$(date +%Y%m%d-%H%M%S)"
  tur_dizin=""
  if [ "$UI" = 1 ]; then
    rapor_dizin="$RAPOR_KOK/$kz-ui-canli-k$i"
    (cd rehearsal/ui && UI_KIP=canli PROVA_KOSU="$i" UI_RAPOR_DIZINI="$rapor_dizin" npx playwright test) || rc=$?
    kip="arayüz"
  else
    rapor_dizin="$RAPOR_KOK/$kz-k$i"
    uv run --quiet --project rehearsal python -m tp_rehearsal --kosu-no "$i" --rapor-yolu "$rapor_dizin" \
      ${DEVAM[@]+"${DEVAM[@]}"} ${KIRMA[@]+"${KIRMA[@]}"} || rc=$?
    kip="API"
    if [ "$UI_TUR" = 1 ]; then
      tur_dizin="$RAPOR_KOK/$kz-ui-tur-k$i"
      (cd rehearsal/ui && UI_KIP=tur PROVA_KOSU="$i" UI_RAPOR_DIZINI="$tur_dizin" npx playwright test) \
        || echo "UYARI: arayüz turu başarısız (prova sonucu değişmez)"
    fi
  fi
  sure=$(( $(date +%s) - t0 ))
  # Sır taraması: trace.zip silinir, kalan her dosya .env sır değerlerine karşı taranır (değer yazılmaz).
  sir_notu=""
  if ! uv run --quiet --project rehearsal python -m tp_rehearsal.sir_tarama --iz-sil \
       "$rapor_dizin" ${tur_dizin:+"$tur_dizin"}; then
    sir_notu=" · ⚠️ rapor dizininde .env sırrı bulundu (paylaşmayın)"
    [ "$rc" = 0 ] && rc=3
  fi
  if [ -f "$rapor_dizin/rapor.md" ]; then
    rapor="${rapor_dizin#"$TP_REPO_ROOT"/}/rapor.md"
  else
    rapor="— (rapor yazılmadı)"
  fi
  [ -n "$tur_dizin" ] && [ -f "$tur_dizin/rapor.md" ] && rapor="$rapor · tur: ${tur_dizin#"$TP_REPO_ROOT"/}/rapor.md"
  if [ "$rc" = 0 ]; then
    basarili=$((basarili + 1)); ardisik=$((ardisik + 1))
    [ "$ardisik" -gt "$en_iyi_ardisik" ] && en_iyi_ardisik=$ardisik
    satirlar+=("| $i | $kip | ✅ PASS | $sure sn | $rapor |")
  else
    ardisik=0
    satirlar+=("| $i | $kip | ❌ FAIL (çıkış $rc) | $sure sn | $rapor$sir_notu |")
  fi
done

{
  echo "# Demo provası özeti — $ZAMAN"
  echo
  echo "- Koşu: $RUNS · başarılı: $basarili · en uzun ardışık sorunsuz seri: $en_iyi_ardisik"
  echo "- TEKNIK-TASARIM §13 hedefi: 3 ardışık sorunsuz prova (temiz \`make reset\` + \`make demo-reset\` sonrası)."
  if [ "$GOZLENEN_MOD" = replay ]; then
    echo "- Model kipi (core-worker'dan okundu): REPLAY — TP_MODEL_MODE=replay, TP_REPLAY_STRICT=1."
  else
    echo "- Model kipi (core-worker'dan okundu): ${GOZLENEN_MOD:-okunamadı} — REPLAY doğrulanmadı."
  fi
  echo "- Gerçek CI değil, yerel CI (LocalForge + test-runner)."
  echo
  echo "| Koşu | Kip | Sonuç | Süre (sıfırlama dahil) | Rapor |"
  echo "|---|---|---|---|---|"
  for s in "${satirlar[@]}"; do echo "$s"; done
} > "$OZET"
echo
cat "$OZET"
echo "Özet: ${OZET#"$TP_REPO_ROOT"/}"
eskileri_temizle "$SAKLA"
[ "$basarili" = "$RUNS" ]
