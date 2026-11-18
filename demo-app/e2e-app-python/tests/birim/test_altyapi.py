"""Cihazsız altyapı birim testleri (Java birim/*BirimTesti karşılığı): ayarlar, kimlik seçicisi,
Appium yetenekleri, bayi seçimi, kırılma gövdeleri."""

from __future__ import annotations

import pytest

from altyapi import bayiler, kimlik, veri_yalitimi
from altyapi.ayarlar import Ayarlar, platform_coz
from altyapi.surucu import NOVA_WINDOWS, powershell_guvenli, yetenekler

pytestmark = pytest.mark.birim


def ayar(**ortam: str) -> Ayarlar:
    return Ayarlar.oku({"TP_PLATFORM": "android", **ortam})


def test_platform_coz() -> None:
    assert platform_coz(" iOS ") == "ios"
    with pytest.raises(ValueError, match="platform verilmedi"):
        platform_coz(None)
    with pytest.raises(ValueError, match="geçersiz platform"):
        platform_coz("web")


def test_kimlik_stratejisi_ve_ekli() -> None:
    assert kimlik.strateji("android") == kimlik.ID
    assert kimlik.strateji("ios") == kimlik.ERISILEBILIRLIK
    assert kimlik.strateji("android", "erisilebilirlik") == kimlik.ERISILEBILIRLIK
    with pytest.raises(ValueError, match="yalnızca Android"):
        kimlik.strateji("windows", "uiautomator")
    assert kimlik.ekli("product-card-", "P-001") == "product-card-P-001"
    with pytest.raises(ValueError):
        kimlik.ekli("product-card", "P-001")
    assert kimlik.bul(kimlik.UIAUTOMATOR, "a.b")[1] == (
        'new UiSelector().resourceIdMatches("(.+:id/)?a[.]b")'
    )


def test_android_yetenekleri() -> None:
    y = yetenekler(ayar(APP_ID="com.x", APP_ACTIVITY=".Main", DEVICE_NAME="emu"))
    assert y["appium:automationName"] == "UiAutomator2"
    assert y["appium:appPackage"] == "com.x" and y["appium:appActivity"] == ".Main"
    assert y["appium:disableIdLocatorAutocompletion"] is True
    assert y["appium:noReset"] is False
    with pytest.raises(ValueError, match="APP_PATH ya da APP_ID"):
        yetenekler(ayar())


def test_windows_novawindows_ve_powershell_korumasi() -> None:
    y = yetenekler(Ayarlar.oku({"TP_PLATFORM": "windows", "APP_PATH": r"C:\a\b.exe",
                                "APP_ARGS": "--api http://x"}))  # fmt: skip
    assert y["appium:automationName"] == NOVA_WINDOWS
    assert y["appium:appArguments"] == "--api http://x"
    for kotu in ("a'b", "a\u2019b", "a\nb"):
        with pytest.raises(ValueError, match="tek tırnak"):
            powershell_guvenli("APP_ARGS", kotu)


def test_bayi_secimi() -> None:
    assert bayiler.sec(None, 0).kullanici_adi == "bayi1"
    assert bayiler.sec("bayi2", 0).ad == "Sahil Bayi"
    with pytest.raises(ValueError, match="doğrulama ajanına"):
        bayiler.sec("bayi3", 0)
    with pytest.raises(ValueError, match="En fazla 2"):
        bayiler.sec(None, 2)


def test_kirilma_ve_kip() -> None:
    assert veri_yalitimi.kirilma({}) is None
    k = veri_yalitimi.kirilma({"BREAK_CAMPAIGN": "1"})
    assert k is not None and k.on == {"kampanya": True} and k.off == {"kampanya": False}
    f = veri_yalitimi.kirilma({"BREAK_CAMPAIGN": "1", "TP_FAULT": "kdv_hatasi"})
    assert f is not None and f.on == {"hata": "kdv_hatasi"} and f.off == {"hata": None}
    with pytest.raises(veri_yalitimi.KurulumHatasi, match="TP_FAULT geçersiz"):
        veri_yalitimi.kirilma({"TP_FAULT": "Kötü Kod"})
    assert veri_yalitimi.kip({"DEMOAPP_TEST_TOKEN": "x"}) == "sifirlama"
    assert veri_yalitimi.kip({"TP_E2E_NO_RESET": "1"}) == "yalniz_sepet"
    with pytest.raises(veri_yalitimi.KurulumHatasi, match="BREAK_CAMPAIGN=1 için"):
        veri_yalitimi.kip({"BREAK_CAMPAIGN": "1"})


def test_ios_klavye_suruklemesi_klavyenin_ustunde() -> None:
    """Java `Klavye.surukleme` eşi: sürükleme kabın klavye üstünde kalan bölümünde, tuşlara
    dokunmadan (iOS number-pad'de kapatma tuşu yok; `keyboardDismissMode="on-drag"`)."""
    from ekranlar.ekran import _klavye_suruklemesi

    kap = {"x": 0, "y": 100, "width": 390, "height": 700}  # klavyenin altına uzanan kap
    assert _klavye_suruklemesi(kap, 500) == (4, 484, 444)
    # Kap klavyeden önce bitiyorsa kabın altından.
    assert _klavye_suruklemesi({"x": 10, "y": 100, "width": 300, "height": 200}, 500) == (
        14, 284, 244,
    )
    # Klavye üstünde yer yok / dar kap: sürükleme yok.
    assert _klavye_suruklemesi(kap, 150) is None
    assert _klavye_suruklemesi({"x": 0, "y": 100, "width": 8, "height": 700}, 500) is None
