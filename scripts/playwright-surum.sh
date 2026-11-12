#!/usr/bin/env bash
# playwright-surum — Playwright sürümünün depodaki tüm kopyalarını denetler / listeler (ağ yok).
#
#   scripts/playwright-surum.sh            # = denetle
#   scripts/playwright-surum.sh denetle    # .playwright-version'a göre tüm sabitler; uyuşmazlıkta çıkış 1
#   scripts/playwright-surum.sh liste      # yükseltmede değişmesi gereken dosyaların listesi
#   make playwright-surum-denetle
#
# Tek sürüm kaynağı depo kökündeki `.playwright-version`'dır (npm `@playwright/test` / `playwright-core`
# sürümü, ör. 1.64.1). Yükseltme kontrol listesi: docs/PLAYWRIGHT-YUKSELTME.md.
#
# Java hattı (011, demo-app/e2e-java) farklıdır: Playwright for Java'nın Maven sürümü (pom
# `<playwright.version>`, ör. 1.64.0) npm sürümüyle AYNI OLMAK ZORUNDA DEĞİLDİR. Önemli olan Java
# sürücüsünün paketlediği çekirdektir: `com.microsoft.playwright:driver` jar'ındaki
# `driver/package/package.json` "version" alanı (ör. 1.64.1) `.playwright-version`'a eşit olmalı —
# böylece iki hat aynı tarayıcı derlemelerini (browsers.json) ve tek PLAYWRIGHT_BROWSERS_PATH'i
# kullanır. Bunu derlemede SurumBirimTesti (e2e-java birim testi) denetler; bu betik yerel Maven
# deposunda (~/.m2 ya da TP_M2_REPO) jar varsa aynı denetimi çevrimdışı yapar, yoksa "denetlenemedi"
# der (hata değil). İki pom (demo-app/e2e-java/pom.xml ↔ toolchain/e2e-java-deps/pom.xml) bayt eşit
# olmalıdır (pom kilidi).
#
# Bilgi amaçlı (hata saymaz): demo-app/.sauce/config.yml (Sauce'un desteklediği sürüme sabit; bkz.
# .github/CI.md "Sauce"), review-portal ve rehearsal/ui (bağımsız UI test projeleri), Dockerfile FROM
# digest'i (çevrimdışı doğrulanamaz; etiket ve yorum denetlenir).
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "$0")/lib.sh"

MOD="${1:-denetle}"
case "$MOD" in
  denetle|liste) ;;
  -h|--help) sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) die "bilinmeyen argüman: $MOD (kullanım: playwright-surum.sh [denetle|liste])" ;;
esac
command -v python3 >/dev/null 2>&1 || die "python3 gerekli"

if [ "$MOD" = liste ]; then
  cat <<'EOF'
Playwright yükseltmesinde değişen dosyalar (ayrıntı: docs/PLAYWRIGHT-YUKSELTME.md):
  .playwright-version                          tek kaynak (npm sürümü)
  toolchain/Dockerfile                         FROM mcr.microsoft.com/playwright:v<sürüm>-noble@sha256:<digest> + yorum
  toolchain/package.json, package-lock.json    @playwright/test + overrides playwright/playwright-core
  toolchain/e2e-deps/package.json, package-lock.json   demo-app/e2e manifestlerinin birebir kopyası
  toolchain/mcp/package.json, package-lock.json        overrides playwright/playwright-core (@playwright/mcp uyumu)
  demo-app/e2e/package.json, package-lock.json         @playwright/test
  demo-app/e2e-java/pom.xml                    <playwright.version> (Java sürümü; npm'den farklı olabilir)
  toolchain/e2e-java-deps/pom.xml              demo-app/e2e-java/pom.xml ile BAYT EŞİT
  demo-app/.sauce/config.yml                   Sauce destekliyorsa (bilgi)
Sonra: make playwright-surum-denetle · toolchain imajı yeniden derlenir (Java duman testi) ·
       Playwright MCP golden'ları/fikstürleri gerekiyorsa yeniden kaydedilir.
EOF
  exit 0
fi

python3 - "$TP_REPO_ROOT" "${TP_M2_REPO:-$HOME/.m2/repository}" <<'PY'
import json
import re
import sys
import zipfile
from pathlib import Path

kok, m2 = Path(sys.argv[1]), Path(sys.argv[2])
hatalar: list[str] = []
bilgi: list[str] = []
V = (kok / ".playwright-version").read_text(encoding="utf-8").strip()
if not re.fullmatch(r"\d+\.\d+\.\d+", V):
    sys.exit(f"HATA: .playwright-version biçimi geçersiz: {V!r}")
print(f".playwright-version = {V}")


def tamam(ad: str, deger: object) -> None:
    if deger == V:
        print(f"  ✓ {ad} = {deger}")
    else:
        hatalar.append(f"{ad} = {deger} (beklenen {V})")
        print(f"  ✗ {ad} = {deger} (beklenen {V})")


def paket(yol: str) -> dict:
    return json.loads((kok / yol).read_text(encoding="utf-8"))


def bagimlilik(d: dict, ad: str) -> object:
    return (d.get("devDependencies") or {}).get(ad) or (d.get("dependencies") or {}).get(ad)


def kilit(yol: str, ad: str) -> object:
    p = kok / yol
    if not p.is_file():
        return "dosya yok"
    return (json.loads(p.read_text(encoding="utf-8")).get("packages") or {}).get(
        f"node_modules/{ad}", {}
    ).get("version")


# npm manifestleri ve kilitleri
for d, overrides in (
    ("toolchain", True),
    ("toolchain/e2e-deps", False),
    ("toolchain/mcp", True),
    ("demo-app/e2e", False),
):
    pj = paket(f"{d}/package.json")
    if d != "toolchain/mcp":
        tamam(f"{d}/package.json @playwright/test", bagimlilik(pj, "@playwright/test"))
    if overrides:
        for ad in ("playwright", "playwright-core"):
            tamam(f"{d}/package.json overrides.{ad}", (pj.get("overrides") or {}).get(ad))
    tamam(f"{d}/package-lock.json playwright-core", kilit(f"{d}/package-lock.json", "playwright-core"))

# Dockerfile taban imajı (digest çevrimdışı doğrulanamaz; etiket deseni ve yorum)
df = (kok / "toolchain/Dockerfile").read_text(encoding="utf-8")
if "FROM mcr.microsoft.com/playwright:v${PLAYWRIGHT_VERSION}-noble@sha256:" in df:
    print("  ✓ toolchain/Dockerfile FROM playwright:v${PLAYWRIGHT_VERSION}-noble@sha256:… (digest elle)")
else:
    hatalar.append("toolchain/Dockerfile: FROM playwright:v${PLAYWRIGHT_VERSION}-noble@sha256 deseni yok")
m = re.search(r"pins v(\d+\.\d+\.\d+)-noble", df)
tamam("toolchain/Dockerfile digest yorumu (pins v…-noble)", m.group(1) if m else None)

# Java hattı: iki pom bayt eşit; sürücü çekirdeği = .playwright-version
pom_hedef, pom_guv = kok / "demo-app/e2e-java/pom.xml", kok / "toolchain/e2e-java-deps/pom.xml"
if pom_hedef.read_bytes() == pom_guv.read_bytes():
    print("  ✓ demo-app/e2e-java/pom.xml = toolchain/e2e-java-deps/pom.xml (bayt eşit)")
else:
    hatalar.append("demo-app/e2e-java/pom.xml ↔ toolchain/e2e-java-deps/pom.xml bayt eşit değil")
    print("  ✗ demo-app/e2e-java/pom.xml ↔ toolchain/e2e-java-deps/pom.xml bayt eşit değil")
m = re.search(r"<playwright\.version>([^<]+)</playwright\.version>", pom_hedef.read_text("utf-8"))
jv = m.group(1).strip() if m else None
if not jv:
    hatalar.append("demo-app/e2e-java/pom.xml: <playwright.version> yok")
else:
    print(f"  · Playwright for Java (pom <playwright.version>) = {jv}"
          + ("" if jv == V else f" — npm sürümünden farklı olabilir; belirleyici sürücü çekirdeğidir"))
    jar = m2 / f"com/microsoft/playwright/driver/{jv}/driver-{jv}.jar"
    if jar.is_file():
        with zipfile.ZipFile(jar) as z:
            cekirdek = json.loads(z.read("driver/package/package.json")).get("version")
        tamam(f"Java sürücü çekirdeği ({jar.name} driver/package/package.json)", cekirdek)
    else:
        bilgi.append(f"Java sürücü çekirdeği denetlenemedi ({jar} yok); e2e-java SurumBirimTesti denetler")

# Bilgi amaçlı
sc = kok / "demo-app/.sauce/config.yml"
if sc.is_file():
    m = re.search(r"^playwright:\s*\n\s+version:\s*(\S+)", sc.read_text("utf-8"), re.M)
    bilgi.append(f"demo-app/.sauce/config.yml playwright.version = {m.group(1) if m else '?'} "
                 "(Sauce desteğine sabit; .github/CI.md 'Sauce')")
for yol in ("review-portal/package.json", "rehearsal/ui/package.json"):
    if (kok / yol).is_file():
        bilgi.append(f"{yol} @playwright/test = {bagimlilik(paket(yol), '@playwright/test')} (bağımsız)")

for b in bilgi:
    print(f"  i {b}")
if hatalar:
    print(f"\nHATA: {len(hatalar)} uyuşmazlık (kontrol listesi: docs/PLAYWRIGHT-YUKSELTME.md)", file=sys.stderr)
    sys.exit(1)
print("\nTamam: Playwright sürümü tutarlı.")
PY
