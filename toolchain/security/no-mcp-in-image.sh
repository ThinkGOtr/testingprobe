#!/usr/bin/env bash
# Anayasa II denetimi: CI / test-runner imajında MCP sunucusu ve ajan bağımlılığı YOKTUR.
#
#   toolchain/security/no-mcp-in-image.sh image <imaj-ref>     # docker run (GitHub CI Yol A, build)
#   toolchain/security/no-mcp-in-image.sh compose <servis>     # çalışan konteyner (make security-check)
#
# Toolchain imajının `ci` hedefi (varsayılan; toolchain-worker, test-runner, ci.yml test-local)
# @playwright/mcp içermez; yalnızca `mcp` hedefi (playwright-mcp servisi) /opt/mcp'ye kurar.
# Denetimler (imajın içinde):
#   1. `require.resolve('@playwright/mcp')` imajdaki hiçbir node kökünden (/opt/toolchain, /opt/e2e,
#      /opt/allure, /opt/mcp, genel npm kökü) çözülemez.
#   2. Dosya sisteminde `node_modules/@playwright/mcp` dizini yoktur (/opt, /usr, /home).
#   3. Python'da `mcp`, `anthropic`, `claude_agent_sdk` içe aktarılamaz.
# Çıkış: 0 = geçti, 1 = ihlal, 2 = kullanım. Ortam: TP_COMPOSE (varsayılan "docker compose").
set -euo pipefail

usage() { echo "kullanım: $0 image <imaj-ref> | compose <servis>" >&2; exit 2; }
[ $# -eq 2 ] || usage
mode="$1" target="$2"

# İmaj içinde koşan denetim (sh; node ve python imajda var).
# shellcheck disable=SC2016  # $… konteyner içindeki kabukta açılır
inner='
set -u
bad=0
for root in /opt/toolchain /opt/e2e /opt/allure /opt/mcp "$(npm root -g 2>/dev/null || true)"; do
  [ -n "$root" ] && [ -d "$root" ] || continue
  if node -e "require.resolve(\"@playwright/mcp\", {paths: [process.argv[1]]})" "$root" >/dev/null 2>&1; then
    echo "İHLAL: @playwright/mcp $root kökünden çözülüyor" >&2; bad=1
  fi
done
found="$(find /opt /usr /home -type d -path "*/node_modules/@playwright/mcp" 2>/dev/null | head -n 5)"
if [ -n "$found" ]; then
  echo "İHLAL: imajda @playwright/mcp paketi var:" >&2; echo "$found" >&2; bad=1
fi
for py in /opt/toolchain/.venv/bin/python python3; do
  command -v "$py" >/dev/null 2>&1 || [ -x "$py" ] || continue
  if ! "$py" -c "
import importlib.util, sys
found = [m for m in (\"mcp\", \"anthropic\", \"claude_agent_sdk\") if importlib.util.find_spec(m)]
sys.exit(1 if found else 0)
" 2>/dev/null; then
    echo "İHLAL: $py ile ajan/MCP Python paketi içe aktarılabiliyor" >&2; bad=1
  fi
done
exit "$bad"
'

# shellcheck disable=SC2206  # komut öneki bilerek kelimelere bölünür
COMPOSE=(${TP_COMPOSE:-docker compose})
case "$mode" in
  image) runner=(docker run --rm --entrypoint sh "$target" -c "$inner") ;;
  compose) runner=("${COMPOSE[@]}" exec -T "$target" sh -c "$inner") ;;
  *) usage ;;
esac

if ! "${runner[@]}"; then
  echo "GÜVENLİK İHLALİ (anayasa II): '$target' içinde MCP sunucusu / ajan bağımlılığı var." \
       "CI ve test-runner toolchain imajının 'ci' hedefini kullanmalı (MCP yalnızca 'mcp' hedefinde)." >&2
  exit 1
fi
echo "Tamam: '$target' içinde MCP sunucusu ve ajan bağımlılığı yok (anayasa II)."
