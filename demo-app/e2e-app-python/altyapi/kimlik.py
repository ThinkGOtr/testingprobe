"""Erişilebilirlik kimliği → Appium seçicisi (Java: altyapi/Kimlik.java). Platform farkı YALNIZ
burada; ekran nesneleri `kimlikler.py` sabitleriyle `bul()` çağırır.

| Platform | Uygulamada | Seçici |
|---|---|---|
| Android | RN testID → resource-id | `id` |
| iOS | RN testID → accessibilityIdentifier | `accessibility id` |
| Windows | AutomationProperties.AutomationId | `accessibility id` |

RN sürümü Android'de testID'yi content-desc'e yazarsa strateji `KIMLIK_ANDROID=erisilebilirlik`
ile kod değişmeden değiştirilir. Seçiciler (strateji dizesi, değer) çiftidir; Appium istemcisinin
`AppiumBy` sabitleriyle aynı dizeler (içe aktarma gerekmez, birim testlenebilir).
"""

from __future__ import annotations

ID = "id"
ERISILEBILIRLIK = "accessibility id"
UIAUTOMATOR = "-android uiautomator"
_STRATEJI = {"id": ID, "erisilebilirlik": ERISILEBILIRLIK, "accessibilityid": ERISILEBILIRLIK,
             "uiautomator": UIAUTOMATOR}  # fmt: skip
_REGEX_OZEL = ".$*+?(){}|"


def strateji(platform: str, gecersiz_kilma: str | None = None) -> str:
    if gecersiz_kilma:
        s = _STRATEJI.get(gecersiz_kilma.strip().lower())
        if s is None:
            raise ValueError(
                f"geçersiz kimlik stratejisi '{gecersiz_kilma}'; izinli: id | erisilebilirlik | "
                "uiautomator"
            )
        if s == UIAUTOMATOR and platform != "android":
            raise ValueError("uiautomator kimlik stratejisi yalnızca Android içindir")
        return s
    return ID if platform == "android" else ERISILEBILIRLIK


def _duz_ifade(kimlik: str) -> str:
    """Kimliği düzenli ifadede birebir eşleşecek biçime getirir (`\\Q…\\E` UiSelector'da sağlam
    değil; Kimlik.duzIfade notu): özel karakter `[c]` sınıfına alınır."""
    return "".join(f"[{c}]" if c in _REGEX_OZEL else c for c in kimlik)


def ui_selector(strat: str, kimlik: str) -> str:
    """Android UiSelector ifadesi (strateji ne olursa olsun aynı öğeyi seçer)."""
    if strat == ERISILEBILIRLIK:
        return f'new UiSelector().description("{_java_dizesi(kimlik)}")'
    return f'new UiSelector().resourceIdMatches("{_java_dizesi("(.+:id/)?" + _duz_ifade(kimlik))}")'


def _java_dizesi(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def bul(strat: str, kimlik: str) -> tuple[str, str]:
    """`driver.find_elements(*bul(...))` için (strateji, değer)."""
    if not kimlik or not kimlik.strip():
        raise ValueError("boş kimlik")
    if strat == UIAUTOMATOR:
        return UIAUTOMATOR, ui_selector(strat, kimlik)
    return strat, kimlik


def ekli(onek: str, sonek: str) -> str:
    """Önek kimliğe sonek ekler: `ekli("product-card-", "P-001") = "product-card-P-001"`."""
    if not onek.endswith("-"):
        raise ValueError(f"'{onek}' önek kimlik değil ('-' ile bitmeli)")
    if not sonek or not sonek.strip():
        raise ValueError(f"'{onek}' önek kimliği için sonek (ürün kodu / sipariş no) gerekli")
    return onek + sonek
