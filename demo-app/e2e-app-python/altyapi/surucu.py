"""Platform → Appium seçenekleri ve sürücü (Java: altyapi/SurucuFabrikasi.java; Appium 3:
uiautomator2, xcuitest, novawindows).

Her test YENİ bir oturum açar (`noReset=false`): uygulama sıfırdan başlar, giriş testler arasında
taşınmaz. Appium istemcisi işlev içinde içe aktarılır (birim testleri bağımlılıksız koşar).
"""

from __future__ import annotations

import re
from typing import Any

from altyapi.ayarlar import Ayarlar

NOVA_WINDOWS = "NovaWindows"
KOMUT_ZAMAN_ASIMI_S = 120
# NovaWindows `app`/`appArguments`'ı PowerShell'de tek tırnak içine kaçışsız gömer: tek tırnak
# (akıllı tırnaklar dahil) ya da denetim karakteri keyfi komuta dönüşür (SurucuFabrikasi notu).
_PS_YASAK = re.compile(r"['‘’‚‛\x00-\x1f\x7f]")


def powershell_guvenli(ad: str, deger: str) -> str:
    if _PS_YASAK.search(deger):
        raise ValueError(
            f"{ad} tek tırnak ya da denetim karakteri içeremez (NovaWindows PowerShell'e kaçışsız "
            "geçirir)"
        )
    return deger


def _eksik(platform: str, ne: str) -> ValueError:
    return ValueError(f"{platform} için {ne} gerekir (ortam; bkz. README)")


def yetenekler(a: Ayarlar) -> dict[str, Any]:
    """Platformun Appium yetenekleri (oturum açmadan; birim testleri bunu doğrular)."""
    ortak: dict[str, Any] = {"appium:newCommandTimeout": KOMUT_ZAMAN_ASIMI_S}
    if a.platform in ("android", "ios"):
        ortak.update({"appium:noReset": False, "appium:fullReset": False})
        if a.device_name:
            ortak["appium:deviceName"] = a.device_name
        if a.udid:
            ortak["appium:udid"] = a.udid
        if a.platform_version:
            ortak["appium:platformVersion"] = a.platform_version
    if a.platform == "android":
        y = {
            "platformName": "Android",
            "appium:automationName": "UiAutomator2",
            "appium:autoGrantPermissions": True,
            "appium:disableWindowAnimation": True,
            # RN testID resource-id'ye paket öneki OLMADAN yazılır; `id` stratejisinin
            # "<paket>:id/" otomatik tamamlaması kapatılır.
            "appium:disableIdLocatorAutocompletion": True,
            **ortak,
        }
        if a.app_path:
            y.update({"appium:app": a.app_path, "appium:enforceAppInstall": True})
        else:
            if not a.app_id:
                raise _eksik("android", "APP_PATH ya da APP_ID (paket adı)")
            y["appium:appPackage"] = a.app_id
            if a.app_activity:
                y["appium:appActivity"] = a.app_activity
        return y
    if a.platform == "ios":
        y = {"platformName": "iOS", "appium:automationName": "XCUITest", **ortak}
        if a.app_path:
            y["appium:app"] = a.app_path
        elif a.app_id:
            y["appium:bundleId"] = a.app_id
        else:
            raise _eksik("ios", "APP_PATH ya da APP_ID (bundle id)")
        return y
    uygulama = a.app_path or a.app_id
    if not uygulama:
        raise _eksik("windows", "APP_PATH (exe) ya da APP_ID (AUMID)")
    y = {
        "platformName": "Windows",
        "appium:automationName": NOVA_WINDOWS,
        "appium:app": powershell_guvenli("APP_PATH/APP_ID", uygulama),
        **ortak,
    }
    if a.app_args:
        y["appium:appArguments"] = powershell_guvenli("APP_ARGS", a.app_args)
    if a.app_workdir:
        y["appium:appWorkingDir"] = powershell_guvenli("APP_WORKDIR", a.app_workdir)
    return y


def olustur(a: Ayarlar) -> Any:
    """Yeni Appium oturumu açar; örtük bekleme kapalıdır (yalnız açık beklemeler, bkz. Bekle)."""
    from appium import webdriver
    from appium.options.common.base import AppiumOptions

    secenek = AppiumOptions()
    secenek.load_capabilities(yetenekler(a))
    surucu = webdriver.Remote(a.appium_url, options=secenek)
    surucu.implicitly_wait(0)
    return surucu
