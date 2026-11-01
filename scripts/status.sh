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

# Giriş bilgilerinin yeri (değerler yazdırılmaz).
if printf '%s\n' "$rows" | awk -F '\t' '$1 == "jira-sim" && $2 == "running" { f = 1 } END { exit !f }'; then
  echo
  echo "jira-sim PO girişi: po@sim.local — parola .env'de JIRA_SIM_PO_PASSWORD"
fi

# Demo-A kazanç ölçümü: manuel baz değer yoksa portal kazanç oranı göstermez.
if [ -z "$(env_get TP_MANUAL_BASELINE_S)" ]; then
  echo
  echo "Varsayılan manuel baz değer yok (TP_MANUAL_BASELINE_S); story başına ölçüm portaldan / PUT /requirements/{id}/baseline ile girilir (ölçülmeyen story'de kazanç gösterilmez)."
fi

# Etkin model kipi: core-worker'ın gerçekten gördüğü TP_MODEL_MODE (compose: .env yoksa auto).
# Anahtar değerleri ASLA yazdırılmaz; yalnızca tanımlı olup olmadığı.
if printf '%s\n' "$rows" | awk -F '\t' '$1 == "core-worker" && $2 == "running" { f = 1 } END { exit !f }'; then
  mod="$(docker compose exec -T core-worker printenv TP_MODEL_MODE 2>/dev/null | tr -d '\r' || true)"
  anahtar="yok"
  if docker compose exec -T core-worker sh -c 'test -n "${ANTHROPIC_API_KEY:-}"' >/dev/null 2>&1; then
    anahtar="tanımlı"
    if docker compose exec -T core-worker sh -c 'test -n "${ANTHROPIC_WORKSPACE_ID:-}"' >/dev/null 2>&1; then
      anahtar="tanımlı (çalışma alanı kimliği var)"
    fi
  fi
  echo
  case "${mod:-auto}" in
    replay) echo "Model kipi: REPLAY (kayıtlı golden yanıtlar; canlı model çağrısı yok) — model anahtarı: $anahtar" ;;
    live) echo "Model kipi: CANLI (live) — model anahtarı: $anahtar. Demo provası (make demo-prova) yalnızca REPLAY'de koşar." ;;
    *) echo "Model kipi: ${mod:-auto} (anahtar varsa canlı, yoksa REPLAY) — model anahtarı: $anahtar. Sunum için .env'de TP_MODEL_MODE=replay önerilir." ;;
  esac
fi
