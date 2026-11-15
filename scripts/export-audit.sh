#!/usr/bin/env bash
# make export-audit — audit_event tablosunu salt okuma ile dışa aktarır. Zincir proje başına olduğundan
# (TP-COK-PROJE-PLANI §1.3, migrasyon 0045) her proje ayrı dosyadır:
#   exports/audit-<pid>-<UTC yyyymmddTHHMMSSZ>.jsonl   (o projenin satırları, id sırasıyla; tek başına
#                                                     `verify_chain` ile aynı zinciri verir)
#   exports/audit-<pid>-<...>.jsonl.sha256            (`shasum -a 256 -c` ile exports/ içinde doğrulanır)
# `_kurulum` kurulum geneli olayların zinciridir. 0045 öncesi şemada (proje sütunu yok) tek dosya:
# exports/audit-<ts>.jsonl. Dosya adında pid'in yalnız [A-Za-z0-9._-] karakterleri kalır.
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

projeli="$(psql_app -v ON_ERROR_STOP=1 -At -c "select exists (select 1 from information_schema.columns \
  where table_name = 'audit_event' and column_name = 'project_id')")" \
  || die "audit_event şeması okunamadı"

umask 077
mkdir -p exports
ts="$(date -u +%Y%m%dT%H%M%SZ)"
while compgen -G "exports/audit-*$ts.jsonl" >/dev/null; do
  sleep 1
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
done
tmp=""
trap '[ -n "$tmp" ] && rm -f "$tmp"' EXIT

# disa_aktar <dosya adı> <sorgu> [pid] — sorgu stdin'den gider: `:'pid'` psql değişkeni güvenle
# tırnaklanır (-c ile değişken açılmaz).
disa_aktar() {
  local name="$1" sorgu="$2" pid="${3:-}" hash count
  tmp="exports/.$name.part"
  if ! printf '%s\n' "$sorgu" | psql_app -v ON_ERROR_STOP=1 -v pid="$pid" -At > "$tmp"; then
    die "audit_event dışa aktarılamadı ($name)"
  fi
  mv "$tmp" "exports/$name"
  tmp=""
  if command -v shasum >/dev/null 2>&1; then
    (cd exports && shasum -a 256 "$name" > "$name.sha256")
  else
    (cd exports && sha256sum "$name" > "$name.sha256")
  fi
  hash="$(cut -d ' ' -f1 "exports/$name.sha256")"
  count="$(wc -l < "exports/$name" | tr -d ' ')"
  echo "Denetim kaydı dışa aktarıldı: exports/$name ($count kayıt)"
  echo "sha256: $hash  (exports/$name.sha256)"
}

if [ "$projeli" != "t" ]; then
  disa_aktar "audit-$ts.jsonl" "select row_to_json(a) from audit_event a order by a.id"
  exit 0
fi

pidler="$(psql_app -v ON_ERROR_STOP=1 -At \
  -c "select distinct project_id from audit_event order by 1")" \
  || die "audit_event projeleri okunamadı"
if [ -z "$pidler" ]; then
  echo "audit_event boş; dışa aktarılacak kayıt yok."
  exit 0
fi
while IFS= read -r pid; do
  guvenli="$(printf '%s' "$pid" | tr -c 'A-Za-z0-9._-' '_')"
  disa_aktar "audit-$guvenli-$ts.jsonl" \
    "select row_to_json(a) from audit_event a where a.project_id = :'pid' order by a.id" "$pid"
done <<< "$pidler"
