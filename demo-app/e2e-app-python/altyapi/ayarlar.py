"""Koşum ayarları (Java: altyapi/Ayarlar.java, Platform.java): ortam değişkeninden, yoksa
varsayılan. Sır (demo test token'ı) yalnız ortamdan gelir; depoda varsayılanı yoktur.

Bu modül appium/selenium içe aktarmaz (birim testleri cihazsız ve bağımlılıksız koşar).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PLATFORMLAR = ("android", "ios", "windows")


def _deger(ortam: Mapping[str, str], ad: str) -> str | None:
    v = (ortam.get(ad) or "").strip()
    return v or None


def platform_coz(deger: str | None) -> str:
    """`TP_PLATFORM` ya da `PLATFORM` değeri; geçersizse izinli değerleri sayan hata."""
    if not deger or not deger.strip():
        raise ValueError(
            f"platform verilmedi: TP_PLATFORM={'|'.join(PLATFORMLAR)} (ya da PLATFORM)"
        )
    aranan = deger.strip().lower()
    if aranan not in PLATFORMLAR:
        raise ValueError(f"geçersiz platform '{deger}'; izinli: {'|'.join(PLATFORMLAR)}")
    return aranan


@dataclass(frozen=True)
class Ayarlar:
    platform: str
    appium_url: str
    app_path: str | None
    app_id: str | None
    app_activity: str | None
    app_args: str | None
    app_workdir: str | None
    device_name: str | None
    udid: str | None
    platform_version: str | None
    bekleme_s: float
    kanit_dizini: Path
    kimlik_stratejisi: str | None  # KIMLIK_<P>: id | erisilebilirlik | uiautomator

    @classmethod
    def oku(cls, ortam: Mapping[str, str] = os.environ) -> Ayarlar:
        platform = platform_coz(_deger(ortam, "TP_PLATFORM") or _deger(ortam, "PLATFORM"))
        app_path = _deger(ortam, "APP_PATH")
        if app_path and not Path(app_path).is_absolute() and Path(app_path).exists():
            # Appium sunucusu göreli yolu kendi dizinine göre çözer: yerelde var olan dosya mutlak
            # yola çevrilir; yerelde olmayan yol (ör. Windows VM içindeki exe) olduğu gibi geçer.
            app_path = str(Path(app_path).resolve())
        try:
            bekleme_ms = int(_deger(ortam, "BEKLEME_MS") or 10_000)
        except ValueError as exc:
            raise ValueError(f"BEKLEME_MS sayı olmalı: {ortam.get('BEKLEME_MS')!r}") from exc
        return cls(
            platform=platform,
            appium_url=(_deger(ortam, "APPIUM_URL") or "http://127.0.0.1:4723").rstrip("/"),
            app_path=app_path,
            app_id=_deger(ortam, "APP_ID"),
            app_activity=_deger(ortam, "APP_ACTIVITY"),
            app_args=_deger(ortam, "APP_ARGS"),
            app_workdir=_deger(ortam, "APP_WORKDIR"),
            device_name=_deger(ortam, "DEVICE_NAME"),
            udid=_deger(ortam, "DEVICE_UDID"),
            platform_version=_deger(ortam, "PLATFORM_VERSION"),
            # Web expect 5 sn; cihazda daha yavaş: 10 sn.
            bekleme_s=bekleme_ms / 1000,
            kanit_dizini=Path(_deger(ortam, "KANIT_DIZINI") or "results/kanit"),
            kimlik_stratejisi=_deger(ortam, f"KIMLIK_{platform.upper()}"),
        )
