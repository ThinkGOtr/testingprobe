"""Swift / XCUITest triage eklentisi (014, Ş4): hata türü, beklenen/görülen, test kimliği."""

from __future__ import annotations

import pytest

from tp_core.features.triage.diller import swift


@pytest.mark.parametrize(
    ("mesaj", "tur"),
    [
        (
            '[TP-BEKLENTI] \'cart-total\' metni: beklenen "150,00 TL", görülen "175,00 TL"',
            "assertion",
        ),
        (
            '[TP-BEKLENTI] \'cart-total\' metni: beklenen "150,00 TL", görülen "(öğe yok)"',
            "locator",
        ),
        ("[TP-EYLEM] öğe görünmedi: kimlik 'login-username'", "locator"),
        (
            "[TP-EYLEM] öğe dokunulabilir olmadı: kimlik 'product-card-P-001' içinde 'add-to-cart'",
            "locator",
        ),
        ("[TP-EYLEM] sepete ekleme tamamlanmadı: 'product-status-P-001' mesajı", "timeout"),
        ("[TP-EYLEM] bu testte onaylanmış sipariş yok", "locator"),
        ("Failed to launch com.antreklabs.bayisiparis", "environment"),
        ("Application com.x is not running", "environment"),
        ("DEMO_API_URL / DEMOAPP_TEST_TOKEN tanımlı değil; test verisi sıfırlanamaz", "test_data"),
        ("POST /test/reset başarısız: 403", "test_data"),
        ("UITests/TPUretilen/X.swift:12:9: error: cannot find 'x' in scope", "derleme"),
        ("** TEST BUILD FAILED **", "derleme"),
        ("Testing failed:\n\tCompiling X.swift failed", "derleme"),
        ('XCTAssertEqual failed: ("1") is not equal to ("2")', "assertion"),
        ("tanınmayan bir şey", None),
    ],
)
def test_hata_turu(mesaj: str, tur: str | None) -> None:
    assert swift.EKLENTI.hata_turu(mesaj) == tur


def test_bekleme_kimliksiz_zaman_asimi() -> None:
    assert swift.hata_turu("[TP-EYLEM] sepet sayacı okunamadı") == "timeout"


def test_beklenen_gorulen() -> None:
    assert swift.beklenen_gorulen(
        '[TP-BEKLENTI] \'cart-total\' metni: beklenen "150,00 TL", görülen "175,00 TL"'
    ) == ("150,00 TL", "175,00 TL")
    assert swift.beklenen_gorulen('XCTAssertEqual failed: ("a") is not equal to ("b")') == (
        "b",
        "a",
    )
    assert swift.beklenen_gorulen(None) == (None, None)


@pytest.mark.parametrize(
    ("test_adi", "dosya", "u8"),
    [
        ("BayiSiparisUITests.TPD1IosC2_3f9b1c2eTests", None, "3f9b1c2e"),
        ("testSenaryo()", "UITests/TPUretilen/SerbestIosC3_0a1b2c3dTests.swift", "0a1b2c3d"),
        ("GirisTesti.testGecerliBilgilerleGiris", "Testler/GirisTesti.swift", None),
    ],
)
def test_test_kimligi(test_adi: str, dosya: str | None, u8: str | None) -> None:
    assert swift.EKLENTI.test_kimligi(test_adi, dosya) == u8


@pytest.mark.parametrize(
    ("dosya", "beklenen"),
    [
        ("UITests/TPUretilen/TPD1IosC2_3f9b1c2eTests.swift", True),
        ("BayiSiparisUITests.TPD1IosC2_3f9b1c2eTests", True),
        ("Antreklabs.Bayi.Tests.Generated.TPD1WebC2_3f9b1c2eTests", False),
        ("com.antreklabs.bayi.uretilen.TPD1IosC2_3f9b1c2eTest", False),
        ("e2e/tests/generated/tpd-1-c2-3f9b1c2e.spec.ts", False),
        (None, False),
    ],
)
def test_test_dosyasi_mi(dosya: str | None, beklenen: bool) -> None:
    assert swift.EKLENTI.test_dosyasi_mi(dosya) is beklenen
