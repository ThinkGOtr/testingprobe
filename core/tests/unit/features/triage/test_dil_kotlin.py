"""Ş3 Kotlin / Espresso triage eklentisi: hata türü, beklenen/görülen, derleme satırları, kimlik."""

from __future__ import annotations

import pytest

from tp_core.features.triage.diller import kotlin as kt

# ruff: noqa: E501 (gerçek günlük / hata satırları bölünmez)

DERLEME_LOG = """\
> Task :app:compileReleaseAndroidTestKotlin FAILED
e: file:///home/runner/work/x/x/demo-app/mobile/android-test/java/com/antreklabs/bayisiparis/tp/uretilen/TPD1AndroidC2_3f9b1c2eTest.kt:24:20 Unresolved reference 'sepeteEkl'.
e: file:///home/runner/work/x/x/app/src/androidTest/java/com/acme/tp/uretilen/XC1_0a1b2c3dTest.kt:9:5 Argument type mismatch: actual type is 'Int', but 'Double' was expected.
FAILURE: Build failed with an exception.
"""


@pytest.mark.parametrize(
    ("mesaj", "beklenen"),
    [
        (DERLEME_LOG, "derleme"),
        ("Execution failed for task ':app:compileReleaseAndroidTestKotlin'.", "derleme"),
        ("Instrumentation run failed due to 'Process crashed.'", "environment"),
        ("com.android.ddmlib.InstallException: INSTALL_FAILED_UPDATE_INCOMPATIBLE", "environment"),
        ("java.net.ConnectException: Failed to connect to /10.0.2.2:18000", "environment"),
        ("androidx.test.espresso.AppNotIdleException: Looped for 3000 iterations", "environment"),
        ("org.junit.runners.model.TestTimedOutException: test timed out after 60000 ms", "timeout"),
        (
            "java.lang.AssertionError: 'cart-total' metni: beklenen <150,00 TL>, görülen <175,00 TL> (15000 ms)",
            "assertion",
        ),
        ("junit.framework.AssertionFailedError: x", "assertion"),
        ("java.lang.AssertionError: POST /test/reset başarısız: 404", "environment"),
        (
            "java.util.concurrent.TimeoutException: öğe görünmedi: kimlik 'login-username'",
            "locator",
        ),
        (
            "androidx.test.espresso.NoMatchingViewException: No views in hierarchy found matching: kimlik 'x'",
            "locator",
        ),
        ("androidx.test.espresso.PerformException: Error performing 'single click'", "locator"),
        ("java.lang.IllegalStateException: bilinmeyen", None),
        ("", None),
        (None, None),
    ],
)
def test_hata_turu(mesaj: str | None, beklenen: str | None) -> None:
    assert kt.hata_turu(mesaj) == beklenen
    assert kt.EKLENTI.hata_turu(mesaj or "") == beklenen


def test_istisna_adi_ilk_satirdan_once() -> None:
    assert kt.hata_turu("mesaj", "androidx.test.espresso.NoMatchingViewException") == "locator"


def test_derleme_hatalari_goreli_ve_sinirli() -> None:
    h = kt.derleme_hatalari(DERLEME_LOG)
    assert h == [
        {
            "dosya": "com/antreklabs/bayisiparis/tp/uretilen/TPD1AndroidC2_3f9b1c2eTest.kt",
            "satir": 24,
            "sutun": 20,
            "mesaj": "Unresolved reference 'sepeteEkl'.",
        },
        {
            "dosya": "com/acme/tp/uretilen/XC1_0a1b2c3dTest.kt",
            "satir": 9,
            "sutun": 5,
            "mesaj": "Argument type mismatch: actual type is 'Int', but 'Double' was expected.",
        },
    ]
    assert "/home/runner" not in str(h)
    assert len(kt.derleme_hatalari(DERLEME_LOG * 40, en_cok=5)) == 5
    assert kt.derleme_hatalari(None) == []


def test_beklenen_gorulen() -> None:
    assert kt.beklenen_gorulen(
        "AssertionError: 'cart-total' metni: beklenen <150,00 TL>, görülen <175,00 TL> (15000 ms)"
    ) == ("150,00 TL", "175,00 TL")
    assert kt.beklenen_gorulen("org.junit.ComparisonFailure: expected:<1> but was:<2>") == (
        "1",
        "2",
    )
    assert kt.beklenen_gorulen("yok") == (None, None)


@pytest.mark.parametrize(
    ("test_adi", "dosya", "u8"),
    [
        ("TPD1AndroidC2_3f9b1c2eTest › senaryo", None, "3f9b1c2e"),
        ("senaryo", "a/b/uretilen/TPD1AndroidC2_3f9b1c2eTest.kt", "3f9b1c2e"),
        ("senaryo", "com.acme.tp.uretilen.SerbestAndroidC1_0a1b2c3dTest", "0a1b2c3d"),
        ("GirisTesti › hataliParola", "com/acme/tp/testler/GirisTesti.kt", None),
    ],
)
def test_test_kimligi(test_adi: str, dosya: str | None, u8: str | None) -> None:
    assert kt.test_kimligi(test_adi, dosya) == u8


def test_test_dosyasi_mi() -> None:
    assert kt.test_dosyasi_mi("a/B.kt")
    assert not kt.test_dosyasi_mi("a/B.java")
    assert not kt.test_dosyasi_mi(None)
    assert kt.EKLENTI.ad == "kotlin"
