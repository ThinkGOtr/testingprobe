#!/usr/bin/env bash
# make export-audit — audit_event tablosunu salt okuma ile dışa aktarır:
#   exports/audit-<UTC yyyymmddTHHMMSSZ>.jsonl   (satır başına bir row_to_json, id sırasıyla)
#   exports/audit-<...>.jsonl.sha256            (`shasum -a 256 -c` ile exports/ içinde doğrulanır)
# Postgres çalışmıyor/sağlıksızsa veya sorgu hata verirse ≠0 döner ve yarım dosya bırakmaz.
#
# TP_EXPORT_ALLOW_NO_TABLE=1 (yalnızca reset kullanır): audit_event tablosu hiç yoksa
# (migrasyon hiç çalışmamış) dışa aktarılacak kayıt yoktur → dosya üretmeden 0 döner.
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"

[ -f .env ] || die ".env bulunamadı — 'make env' çalıştırın"
svc_healthy postgres || die "postgres çalışmıyor veya sağlıklı değil — önce 'make up'"

has_table="$(psql_app -v ON_ERROR_STOP=1 -At -c "select to_regclass('public.audit_event') is not null")" \
  || die "Postgres'e tp_app olarak bağlanılamadı"
if [ "$has_table" != "t" ]; then
  if [ "${TP_EXPORT_ALLOW_NO_TABLE:-0}" = "1" ]; then
    echo "audit_event tablosu yok (migrasyon hiç çalışmamış); dışa aktarılacak kayıt yok."
    exit 0
  fi
  die "audit_event tablosu bulunamadı"
fi

umask 077
mkdir -p exports
ts="$(date -u +%Y%m%dT%H%M%SZ)"
while [ -e "exports/audit-$ts.jsonl" ]; do
  sleep 1
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
done
name="audit-$ts.jsonl"
tmp="exports/.$name.part"
trap 'rm -f "$tmp"' EXIT

if ! psql_app -v ON_ERROR_STOP=1 -At \
     -c "select row_to_json(a) from audit_event a order by a.id" > "$tmp"; then
  die "audit_event dışa aktarılamadı"
fi
mv "$tmp" "exports/$name"
trap - EXIT

if command -v shasum >/dev/null 2>&1; then
  (cd exports && shasum -a 256 "$name" > "$name.sha256")
else
  (cd exports && sha256sum "$name" > "$name.sha256")
fi
hash="$(cut -d ' ' -f1 "exports/$name.sha256")"
count="$(wc -l < "exports/$name" | tr -d ' ')"

echo "Denetim kaydı dışa aktarıldı: exports/$name ($count kayıt)"
echo "sha256: $hash  (exports/$name.sha256)"
