#!/usr/bin/env python3
"""Masaüstü (WPF) AutomationId'lerini web data-testid'leriyle karşılaştırır (plan §2.2).

Tek başına çalışır: web kimliklerini kendisi toplar (demo-app/web/src/**/*.tsx içindeki data-testid
değerleri + demo-app/e2e/pages/**/locators.ts içindeki testId değerleri). Masaüstü kimliklerini
demo-app/desktop/src/**/*.xaml ve *.cs dosyalarından toplar.

Dinamik kimlikler önek olarak karşılaştırılır (sonu "-"):
  web     data-testid={`product-card-${p.kod}`}               → "product-card-"
  xaml    AutomationId="{Binding Kod, StringFormat=product-card-{0}}" → "product-card-"

Çıkış kodu: 0 = birebir uyum; 1 = eksik ya da izinsiz fazla kimlik var.
Kullanım: python3 demo-app/desktop/scripts/kimlik-kontrol.py [--json]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DESKTOP = Path(__file__).resolve().parent.parent
DEMO_APP = DESKTOP.parent
WEB_SRC = DEMO_APP / "web" / "src"
LOCATORS = DEMO_APP / "e2e" / "pages"

# Yalnız masaüstünde bulunan, bilerek eklenmiş kimlikler (web'de karşılığı yok):
# pencere, ekran kökleri ve meşgul göstergesi — UI Automation testlerinin deterministik beklemesi için.
MASAUSTU_EK = {
    "app-window": "Ana pencere",
    "busy-indicator": "API çağrısı sürerken görünen gösterge (bitince ağaçtan çıkar)",
    "page-login": "Giriş ekranı kökü",
    "page-catalog": "Katalog ekranı kökü",
    "page-cart": "Sepet ekranı kökü",
    "page-order-confirmation": "Sipariş onayı ekranı kökü",
    "page-orders": "Sipariş geçmişi ekranı kökü",
}

# web: data-testid="sabit"  |  data-testid={`onek-${...}`}  |  data-testid={"sabit"}
WEB_SABIT = re.compile(r'data-testid=(?:"([^"]+)"|\{"([^"]+)"\})')
WEB_SABLON = re.compile(r"data-testid=\{`([^`$]*)\$\{")
WEB_SABLON_TAM = re.compile(r"data-testid=\{`([^`$]+)`\}")
LOCATOR_TESTID = re.compile(r'testId:\s*"([^"]+)"')

# xaml: AutomationProperties.AutomationId="sabit" | "{Binding X, StringFormat=onek-{0}}"
XAML_ID = re.compile(r'AutomationProperties\.AutomationId="([^"]*)"')
XAML_FORMAT = re.compile(r"StringFormat=['\"]?([^,'\"}{]*)\{0\}")
CS_ID = re.compile(r'AutomationProperties\.SetAutomationId\([^,]+,\s*(?:\$?"([^"{]*)(\{[^"]*)?")')


def web_kimlikleri() -> dict[str, set[str]]:
    """Kimlik → kaynak dosyalar (göreli yol)."""
    sonuc: dict[str, set[str]] = {}

    def ekle(kimlik: str, dosya: Path) -> None:
        sonuc.setdefault(kimlik, set()).add(str(dosya.relative_to(DEMO_APP)))

    for dosya in sorted(WEB_SRC.rglob("*.tsx")):
        metin = dosya.read_text(encoding="utf-8")
        for m in WEB_SABIT.finditer(metin):
            ekle(m.group(1) or m.group(2), dosya)
        for m in WEB_SABLON.finditer(metin):
            ekle(m.group(1), dosya)
        for m in WEB_SABLON_TAM.finditer(metin):
            ekle(m.group(1), dosya)
    for dosya in sorted(LOCATORS.rglob("locators.ts")):
        for m in LOCATOR_TESTID.finditer(dosya.read_text(encoding="utf-8")):
            ekle(m.group(1), dosya)
    return sonuc


def masaustu_kimlikleri() -> tuple[dict[str, set[str]], list[str]]:
    """Kimlik → kaynak dosyalar; ayrıca çözülemeyen bağlamalar (hata)."""
    sonuc: dict[str, set[str]] = {}
    cozulemeyen: list[str] = []
    kaynaklar = [p for p in sorted((DESKTOP / "src").rglob("*")) if p.suffix in {".xaml", ".cs"}]
    for dosya in kaynaklar:
        if "obj" in dosya.parts or "bin" in dosya.parts:
            continue
        metin = dosya.read_text(encoding="utf-8")
        goreli = str(dosya.relative_to(DEMO_APP))
        if dosya.suffix == ".xaml":
            for m in XAML_ID.finditer(metin):
                deger = m.group(1)
                if deger.startswith("{"):
                    f = XAML_FORMAT.search(deger)
                    if not f or not f.group(1).endswith("-"):
                        cozulemeyen.append(f"{goreli}: {deger}")
                        continue
                    deger = f.group(1)
                sonuc.setdefault(deger, set()).add(goreli)
        else:
            for m in CS_ID.finditer(metin):
                sonuc.setdefault(m.group(1), set()).add(goreli)
    return sonuc, cozulemeyen


def main() -> int:
    web = web_kimlikleri()
    masaustu, cozulemeyen = masaustu_kimlikleri()
    eksik = sorted(set(web) - set(masaustu))
    fazla = sorted(set(masaustu) - set(web) - set(MASAUSTU_EK))
    ortak = sorted(set(web) & set(masaustu))
    rapor = {
        "web_kimlik_sayisi": len(web),
        "masaustu_kimlik_sayisi": len(masaustu),
        "eslesen": ortak,
        "eksik": {k: sorted(web[k]) for k in eksik},
        "izinsiz_fazla": {k: sorted(masaustu[k]) for k in fazla},
        "masaustune_ozgu": sorted(set(masaustu) & set(MASAUSTU_EK)),
        "cozulemeyen": cozulemeyen,
    }
    basarili = not eksik and not fazla and not cozulemeyen

    if "--json" in sys.argv[1:]:
        print(json.dumps(rapor, ensure_ascii=False, indent=2))
    else:
        print(f"Web kimlikleri: {len(web)} · masaüstünde eşleşen: {len(ortak)}")
        for k in eksik:
            print(f"  EKSİK   {k}  (web: {', '.join(sorted(web[k]))})")
        for k in fazla:
            print(f"  FAZLA   {k}  (masaüstü: {', '.join(sorted(masaustu[k]))})")
        for c in cozulemeyen:
            print(f"  ÇÖZÜLEMEDİ  {c}")
        ek = sorted(set(masaustu) & set(MASAUSTU_EK))
        print(f"Masaüstüne özgü (izinli): {', '.join(ek) if ek else '-'}")
        print("SONUÇ: " + ("uyumlu" if basarili else "UYUMSUZ"))
    return 0 if basarili else 1


if __name__ == "__main__":
    sys.exit(main())
