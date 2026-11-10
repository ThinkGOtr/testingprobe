#!/usr/bin/env bash
# Bayi Sipariş Portalı (WPF) yayın betiği — macOS/Linux/Windows (Git Bash) üzerinde çalışır.
# Çıktı: demo-app/desktop/build/<rid>/BayiSiparis.exe (+ bağımlılıklar; tek klasör).
#
# Kullanım:
#   scripts/yayinla.sh                     # win-x64 ve win-arm64, kendi içinde (self-contained)
#   scripts/yayinla.sh win-arm64           # yalnız ARM64 (Windows 11 ARM sanal makinesi)
#   scripts/yayinla.sh --fd win-x64        # çatıya bağımlı (hedefte .NET 8 Desktop Runtime gerekir)
#   scripts/yayinla.sh --test              # önce çekirdek testlerini koşturur
set -euo pipefail

KOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJE="$KOK/src/BayiSiparis.Masaustu/BayiSiparis.Masaustu.csproj"
CIKTI="$KOK/build"
KENDI_ICINDE=true
TEST=false
RIDLER=()

for a in "$@"; do
  case "$a" in
    --fd) KENDI_ICINDE=false ;;
    --test) TEST=true ;;
    win-x64|win-arm64) RIDLER+=("$a") ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "Bilinmeyen argüman: $a (izinli: win-x64, win-arm64, --fd, --test)" >&2; exit 2 ;;
  esac
done
[ ${#RIDLER[@]} -eq 0 ] && RIDLER=(win-x64 win-arm64)

command -v dotnet >/dev/null || { echo "dotnet bulunamadı (.NET SDK 8 veya üstü gerekir)" >&2; exit 1; }
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1

if $TEST; then
  dotnet test "$KOK/BayiSiparis.sln" -c Release
fi

for rid in "${RIDLER[@]}"; do
  hedef="$CIKTI/$rid"
  echo "==> $rid (self-contained=$KENDI_ICINDE) → $hedef"
  rm -rf "$hedef"
  dotnet publish "$PROJE" -c Release -r "$rid" --self-contained "$KENDI_ICINDE" -o "$hedef" -p:DebugType=none
  test -f "$hedef/BayiSiparis.exe" || { echo "BayiSiparis.exe üretilmedi: $hedef" >&2; exit 1; }
done

echo "Tamam:"
for rid in "${RIDLER[@]}"; do echo "  $CIKTI/$rid/BayiSiparis.exe"; done
