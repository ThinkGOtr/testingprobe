#!/usr/bin/env bash
# make status — servis, durum, sağlık ve yerel adres tablosu.
# Hiçbir servis çalışmıyorsa "ortam çalışmıyor" yazar ve ≠0 döner.
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"

docker info >/dev/null 2>&1 || { echo "ortam çalışmıyor (Docker çalışmıyor)" >&2; exit 1; }

rows="$(ps_rows)" || { echo "ortam çalışmıyor (docker compose ps başarısız)" >&2; exit 1; }

if ! printf '%s\n' "$rows" | awk -F '\t' '$2 == "running" { f = 1 } END { exit !f }'; then
  echo "ortam çalışmıyor — 'make up' ile başlatın" >&2
  exit 1
fi

# Tabloyu Python ile çiz (Türkçe karakterlerde sütun hizası bayt değil karakterle hesaplanır)
printf '%s\n' "$rows" | python3 -c '
import sys
out = [("SERVİS", "DURUM", "SAĞLIK", "YEREL ADRES")]
bad = False
for line in sys.stdin:
    f = line.rstrip("\n").split("\t")
    if len(f) < 5 or not f[0]:
        continue
    svc, state, health, code, ports = f[:5]
    if svc == "migrate" and state == "exited" and code == "0":
        state = "tamamlandı"
    elif state == "exited":
        state = "çıktı(%s)" % code
        bad = True
    elif health != "healthy":
        bad = True
    addr = "-"
    if ports != "-":
        hosts = [p.split("->")[0] for p in ports.split(",")]
        addr = " ".join(h if svc == "postgres" else "http://" + h for h in hosts)
    out.append((svc, state, health, addr))
w = [max(len(r[i]) for r in out) for i in range(3)]
for r in out:
    print("  ".join(r[i].ljust(w[i]) for i in range(3)) + "  " + r[3])
if bad:
    sys.stderr.write("Uyarı: sağlıklı olmayan servis(ler) var — make logs S=<servis>\n")
'
