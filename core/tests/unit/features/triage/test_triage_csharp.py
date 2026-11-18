"""C# triage eklentisi (014 Ş2): JunitXml.TestLogger ileti öneki, tür sözlüğü, kimlik,
beklenen/görülen.

İleti örnekleri gerçektir: NUnit 4.6.1 + JunitXml.TestLogger 8.1.0 çıktısı ve demo-app
e2e-csharp / e2e-app-csharp README'lerindeki (Playwright .NET 1.64.1, Appium .NET 8.4.0) biçimler.
"""

from __future__ import annotations

import pytest

from tp_core.features.triage.diller import csharp as cs

PW_ASSERT = (
    "Locator expected to have text '150,00 TL'\nBut was: '175,00 TL'\nCall log:\n"
    '  - Expect "ToHaveTextAsync" GetByTestId("cart-total") with timeout 5000ms\n'
    '  - waiting for GetByTestId("cart-total")'
)
PW_YOK = (
    "Locator expected to have text '150,00 TL'\nBut was: ''\nError: element(s) not found\n"
    'Call log:\n  - waiting for GetByTestId("cart-totl")'
)
PW_ZAMAN = (
    "System.TimeoutException : Timeout 5000ms exceeded.\nCall log:\n"
    '  - waiting for GetByTestId("add-to-cart")'
)
NAV = "Microsoft.Playwright.PlaywrightException : net::ERR_CONNECTION_REFUSED at http://web:8081/giris"
KURULUM = "SetUp : System.InvalidOperationException : demo API /test/reset başarısız: 401"
WIN_ASSERT = "sepet toplamı: beklenen <150,00 TL>, görülen <175,00 TL> (5000 ms)"
WIN_YOK = (
    "OpenQA.Selenium.WebDriverTimeoutException : Expected condition failed: öğe görünmedi: "
    "kimlik 'login-username' (tried for 5 second(s) with 250 milliseconds interval)"
)
WIN_TIKLA = (
    "OpenQA.Selenium.WebDriverTimeoutException : Expected condition failed: öğe tıklanabilir "
    "olmadı: kimlik 'login-submit' (tried for 5 second(s) with 250 milliseconds interval)"
)


def test_onek_ayristirma() -> None:
    assert cs.istisna_ve_ileti(PW_ASSERT) == (cs.ASSERTION, PW_ASSERT, False)
    tur, ileti, asama = cs.istisna_ve_ileti(KURULUM)
    assert (tur, asama) == ("System.InvalidOperationException", True)
    assert ileti.startswith("demo API /test/reset")
    assert cs.istisna_ve_ileti(PW_ZAMAN)[0] == "System.TimeoutException"
    assert cs.istisna_ve_ileti(None) == (cs.ASSERTION, "", False)


@pytest.mark.parametrize(
    ("mesaj", "platform", "beklenen"),
    [
        (PW_ASSERT, "web", "assertion"),
        (PW_YOK, "web", "locator_not_found"),
        (PW_ZAMAN, "web", "locator_timeout"),
        (NAV, "web", "navigation"),
        (KURULUM, "web", "test_data"),
        (KURULUM, "windows", "test_data"),
        (WIN_ASSERT, "windows", "assertion"),
        (WIN_YOK, "windows", "locator_not_found"),
        (WIN_TIKLA, "windows", "locator_timeout"),
        ("System.NullReferenceException : Object reference not set", "windows", "other"),
        ("System.NullReferenceException : Object reference not set", "web", "other"),
    ],
)
def test_hata_turu(mesaj: str, platform: str, beklenen: str) -> None:
    assert cs.hata_turu(mesaj, platform=platform) == beklenen


def test_beklenen_gorulen() -> None:
    assert cs.beklenen_gorulen(WIN_ASSERT) == ("150,00 TL", "175,00 TL")
    assert cs.beklenen_gorulen("x") == (None, None)


def test_kirik_kimlik() -> None:
    assert cs.kirik_kimlik(PW_YOK) == ("cart-totl", None, False)
    assert cs.kirik_kimlik(WIN_YOK)[0] == "login-username"


def test_test_kimligi_ve_kanit() -> None:
    assert cs.test_kimligi(
        "Antreklabs.Bayi.Tests.Generated.TPD1WebC2_3f9b1c2eTests", "Senaryo"
    ) == (
        "Tests/Generated/TPD1WebC2_3f9b1c2eTests.cs",
        "TPD1WebC2_3f9b1c2eTests › Senaryo",
    )
    assert cs.test_kimligi("kötü ad!", "x") == ("kötü ad!", "x")
    assert cs.sinif_adi("e2e-csharp/Tests/Generated/XTests.cs") == "XTests"
    assert cs.kanit_dizini_adi("Tests/Generated/XTests.cs", "XTests › Senaryo") == "XTests.Senaryo"


def test_csharp_mi() -> None:
    assert cs.csharp_mi(None, dil="csharp") and not cs.csharp_mi("a.cs", dil="java")
    assert cs.csharp_mi("Tests/GirisTests.cs")
    assert cs.csharp_mi(None, "NUnit.Framework.AssertionException : x")
    assert not cs.csharp_mi("e2e/tests/a.spec.ts", "Error: x")
