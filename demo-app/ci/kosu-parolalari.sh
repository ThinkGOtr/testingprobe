#!/usr/bin/env bash
# Koşu hesabı parolaları (Java hedefleri için; `source` edilir): üretilen Java testleri seed parolasıyla
# girişte parolayı System.getenv("TP_TESTVERI_KOSU_<KULLANICI>")'dan okur ve JVM ortamı süreç içinde
# yazamaz. Toolchain runner bunu koşu ortamına verir; bu betik TP dışı koşularda (CI/yerel) eksik
# adları altyapi/Bayiler.java seed listesindeki parolayla doldurur (var olan değere dokunmaz; değer
# yazdırılmaz). Ad kuralı core `render.kosu_parola_adi` ile aynı.
# Kullanım: source ci/kosu-parolalari.sh <Bayiler.java yolu>
kosu_parolalari_yukle() {
  local bayiler="$1" k p ad
  [[ -f "$bayiler" ]] || return 0
  while IFS=$'\t' read -r k p; do
    ad="TP_TESTVERI_KOSU_$(printf '%s' "$k" | tr '[:lower:]' '[:upper:]' | sed 's/[^A-Z0-9]/_/g')"
    [[ "$ad" =~ ^TP_TESTVERI_[A-Z0-9_]{1,64}$ ]] || continue
    [[ -n "${!ad:-}" ]] || export "$ad=$p"
  done < <(sed -nE 's/.*new BayiBilgisi\("([^"]+)", "([^"\\]*)".*/\1\t\2/p' "$bayiler")
}
kosu_parolalari_yukle "${1:-}"
