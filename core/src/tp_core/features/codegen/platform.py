"""Platform boyutu (009 mobil-masaüstü §2.1): web | android | ios | windows.

Case platformdan bağımsızdır; kod üretimi (case, platform) çiftinedir. `web` mevcut
Playwright/TypeScript hattının aynısıdır (varsayılan, geriye uyum); `android`, `ios`, `windows`
Appium + Java + TestNG hattıdır (`demo-app/e2e-app`, `toolchain/java-araclar`, app-mcp).

Bu modül saf yardımcıdır (veritabanı/ağ yok): hem core-api hem core-worker kullanır.
"""

from __future__ import annotations

from typing import Literal

Platform = Literal["web", "android", "ios", "windows"]
WEB = "web"
UYGULAMA_PLATFORMLARI: tuple[str, ...] = ("android", "ios", "windows")
PLATFORMLAR: tuple[str, ...] = (WEB, *UYGULAMA_PLATFORMLARI)
# Forge deposunda Java test projesinin kökü (uygulama köküne göre): `<app root>/e2e-app`.
E2E_APP_DIZINI = "e2e-app"
JAVA_URETILEN_DIZIN = "src/test/java/com/antreklabs/bayi/uretilen"  # e2e-app köküne göre


def gecerli(platform: str | None) -> str:
    """Boş → `web`; bilinmeyen değer `ValueError` (Türkçe)."""
    deger = (platform or WEB).strip().lower()
    if deger not in PLATFORMLAR:
        raise ValueError(f"platform yalnızca {', '.join(PLATFORMLAR)} olabilir: {platform!r}")
    return deger


def uygulama_mi(platform: str | None) -> bool:
    """Appium/Java hattı mı? (`android` | `ios` | `windows`)"""
    return (platform or WEB) in UYGULAMA_PLATFORMLARI


def dil(platform: str | None) -> str:
    """toolchain-worker `lang` karşılığı: web → `ts`, diğerleri → `java`."""
    return "java" if uygulama_mi(platform) else "ts"
