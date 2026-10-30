#!/usr/bin/env bash
# make env — .env'i .env.example'dan üretir ve boş F0 parolalarını rastgele doldurur.
# Var olan .env'deki dolu değerlere asla dokunmaz; yalnızca hâlâ boş olan F0 anahtarlarını doldurur.
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"

umask 077

gen_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 24
  else
    python3 -c 'import secrets; print(secrets.token_hex(24))'
  fi
}

if [ ! -f .env ]; then
  [ -f .env.example ] || die ".env.example bulunamadı"
  cp .env.example .env
  echo ".env, .env.example'dan oluşturuldu"
fi

filled=""
for key in $TP_F0_KEYS; do
  if [ -n "$(env_get "$key")" ]; then
    continue
  fi
  secret="$(gen_secret)"
  tmp="$(mktemp .env.tmp.XXXXXX)"
  if grep -Eq "^[[:space:]]*${key}[[:space:]]*=" .env; then
    # Yalnızca boş değerli satırı değiştir (KEY=, KEY="", KEY='')
    awk -v k="$key" -v v="$secret" '
      match($0, "^[ \t]*" k "[ \t]*=") {
        val = substr($0, RLENGTH + 1); gsub(/[ \t"\047]/, "", val)
        if (val == "") { print k "=" v; next }
      }
      { print }
    ' .env > "$tmp"
  else
    cat .env > "$tmp"
    # Dosya yeni satırla bitmiyorsa ekle
    if [ -s "$tmp" ] && [ "$(tail -c 1 "$tmp" | od -An -c | tr -d ' ')" != '\n' ]; then
      printf '\n' >> "$tmp"
    fi
    printf '%s=%s\n' "$key" "$secret" >> "$tmp"
  fi
  mv "$tmp" .env
  filled="$filled $key"
done

chmod 600 .env

if [ -n "$filled" ]; then
  echo "Rastgele dolduruldu:$filled"
fi
echo ".env hazır"
