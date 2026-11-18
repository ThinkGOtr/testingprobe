#!/usr/bin/env python3
""""Kırarak doğrula" kırmızı adımının denetimi — C# hattı (ci/break-verify-csharp.sh; AI yok).

Java karşılığı: ../e2e-java/araclar/KirmiziDenetimi.java. Yalnız standart kütüphane:
`python3 araclar/kirmizi_denetimi.py <junit-dizini>` (dizindeki *.xml; JunitXml.TestLogger çıktısı).

JunitXml.TestLogger her hatayı `<failure type="failure" message="…">` yazar; tür ayrımı NUnit
iletisinin önekindedir:
  - NUnit doğrulama hatası (`NUnit.Framework.AssertionException`; page object beklentileri
    Playwright doğrulama hatasını buna çevirir): ileti ÖNEKSİZDİR ("Locator expected to have text …").
  - Diğer istisnalar: "<Tam.Tür.Adı> : <ileti>" (ör. "System.TimeoutException : Timeout 5000ms
    exceeded."); hazırlık/kapanış hatası "SetUp : <Tür> : …" / "TearDown : …".
Kırmızıların HEPSİ doğrulama hatası olmalı ve en az bir kırmızı olmalı. Kurulum kaynaklı doğrulama
iletileri (/test/*, giriş, token, eleman hiç bulunamadı) ve atlanan test kırmızı sayılmaz.

Çıkış kodu: 0 geçti, 1 denetim başarısız, 2 kullanım / rapor yok.
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# "<Tür> : " öneki (isteğe bağlı SetUp/TearDown önekiyle): doğrulama DIŞI istisna.
TUR_ONEKI = re.compile(r"^(?:(?:One[Tt]ime)?(?:SetUp|TearDown) : )?[A-Za-z_][\w.`]*(?:Exception|Error) : ")
HAZIRLIK_ONEKI = re.compile(r"^(?:One[Tt]ime)?(?:SetUp|TearDown) : ")
# Doğrulama türünde olsa da kurulum kaynaklı sayılan iletiler (Java KirmiziDenetimi.KURULUM ile aynı).
KURULUM = re.compile(r"/test/|giriş başarısız|DEMOAPP_TEST_TOKEN|element\(s\) not found|Chromium açılamadı", re.S)


def denetle(dizin: Path) -> int:
    dosyalar = sorted(dizin.glob("*.xml"))
    if not dosyalar:
        print(f"HATA: JUnit XML yok: {dizin}", file=sys.stderr)
        return 2
    kirmizi: list[str] = []
    yesil: list[str] = []
    kotu: list[str] = []
    for dosya in dosyalar:
        veri = dosya.read_bytes()
        if b"<!DOCTYPE" in veri or b"<!ENTITY" in veri:
            print(f"HATA: DTD/varlık bildirimi içeren rapor reddedildi: {dosya}", file=sys.stderr)
            return 2
        for tc in ET.fromstring(veri).iter("testcase"):
            ad = f"{tc.get('classname', '').rsplit('.', 1)[-1]}.{tc.get('name', '')}"
            sonuc = next((c for c in tc if c.tag in ("failure", "error", "skipped")), None)
            if sonuc is None:
                yesil.append(ad)
                continue
            mesaj = sonuc.get("message") or ""
            dogrulama = (
                sonuc.tag == "failure"
                and not TUR_ONEKI.match(mesaj)
                and not HAZIRLIK_ONEKI.match(mesaj)
                and not KURULUM.search(mesaj)
            )
            if dogrulama:
                kirmizi.append(ad)
            else:
                ilk = mesaj.splitlines()[0] if mesaj else ""
                kotu.append(f"{ad} [{sonuc.tag}] {ilk[:200]}")
    print("kırmızı: " + " | ".join(kirmizi))
    print("yeşil kalan: " + " | ".join(yesil))
    if kotu:
        for k in kotu:
            print(f"  ✗ {k}", file=sys.stderr)
        print(
            f"HATA: {len(kotu)} sonuç doğrulama (assertion) hatası değil (kurulum/locator hatası ya da atlandı)",
            file=sys.stderr,
        )
        return 1
    if not kirmizi:
        print("HATA: hiç kırmızı test yok", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("kullanım: python3 kirmizi_denetimi.py <junit-dizini>", file=sys.stderr)
        sys.exit(2)
    sys.exit(denetle(Path(sys.argv[1])))
