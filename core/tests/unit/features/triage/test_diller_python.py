"""014 Ş1: Python triage eklentisi (`triage/diller/python.py`) — hata kalıpları ve kimlik eşleme.

Metinler Playwright Python sürücüsünün ve demo hedef projelerin (`demo-app/e2e-python`,
`demo-app/e2e-app-python`: `altyapi/bekle.py`, `ekranlar/ekran.py`, `KurulumHatasi`) gerçek
ileti biçimleridir.
"""

from __future__ import annotations

import pytest

from tp_core.features.triage.diller import python as tp

PW_ASSERT = (
    "AssertionError: Locator expected to have text '150,00 TL'\n"
    "Actual value: 175,00 TL\n"
    "Call log:\n"
    '  - Expect "to_have_text" with timeout 5000ms\n'
    '  - waiting for get_by_test_id("cart-total")\n'
)
PW_ASSERT_YOK = (
    "AssertionError: Locator expected to have text '150,00 TL'\n"
    "Actual value: None\n"
    "Error: element(s) not found\n"
    "Call log:\n"
    '  - waiting for get_by_test_id("cart-totl")\n'
)
PW_TIMEOUT = (
    "playwright._impl._errors.TimeoutError: Locator.click: Timeout 30000ms exceeded.\n"
    "Call log:\n"
    '  - waiting for get_by_test_id("login-submit")\n'
)


@pytest.mark.parametrize(
    ("mesaj", "istisna", "tur"),
    [
        (PW_ASSERT, None, "assertion"),
        (PW_ASSERT_YOK, None, "locator"),
        (PW_TIMEOUT, "playwright._impl._errors.TimeoutError", "locator"),
        (
            'Error: strict mode violation: get_by_test_id("line") resolved to 2 elements',
            None,
            "locator",
        ),
        ("Page.goto: net::ERR_ABORTED at http://web/sepet", None, "navigation"),
        ("Page.goto: Timeout 30000ms exceeded.", None, "navigation"),
        (
            "urllib.error.URLError: <urlopen error [Errno 111] Connection refused>",
            None,
            "environment",
        ),
        ("BrowserType.launch: Executable doesn't exist at /ms-playwright/x", None, "environment"),
        (
            "selenium.common.exceptions.SessionNotCreatedException: Could not start a new session",
            None,
            "environment",
        ),
        ("KurulumHatasi: /test/reset başarısız: 401", None, "test_data"),
        ("KurulumHatasi: giriş başarısız: bayi2", "KurulumHatasi", "test_data"),
        (
            "AssertionError: sepet toplamı: beklenen <150,00 TL>, görülen <175,00 TL> (5000 ms)",
            "AssertionError",
            "assertion",
        ),
        (
            "AssertionError: sepet toplamı: beklenen <150,00 TL>, görülen <(öğe yok)> (5000 ms)",
            None,
            "locator",
        ),
        (
            "selenium.common.exceptions.TimeoutException: Message: öğe görünmedi: kimlik "
            "'sepet-toplam'",
            "selenium.common.exceptions.TimeoutException",
            "locator",
        ),
        (
            "TimeoutException: öğe tıklanabilir olmadı: kimlik 'katalog' içinde 'sepete-ekle'",
            None,
            "locator",
        ),
        ("TimeoutError: bayi kilidi 40 sn içinde alınamadı", None, "timeout"),
        ("ZeroDivisionError: division by zero", None, None),
        ("", None, None),
    ],
)
def test_hata_turu(mesaj: str, istisna: str | None, tur: str | None) -> None:
    assert tp.EKLENTI.hata_turu(mesaj, istisna) == tur


def test_turler_soezlukte() -> None:
    try:
        from tp_core.features.triage.diller import TURLER  # type: ignore[attr-defined]
    except ImportError:  # Ş0 öncesi: sözleşmedeki sözlük
        TURLER = frozenset(
            {"locator", "assertion", "navigation", "environment", "timeout", "test_data",
             "derleme"}
        )  # fmt: skip
    for m in (
        PW_ASSERT,
        PW_TIMEOUT,
        "Page.goto: net::ERR_X",
        "KurulumHatasi",
        "Timeout 1ms exceeded",
    ):
        # 014 entegrasyonu: eklentinin kısa türü `Sinyal.tur()` sözlüğüne `normal_tur` ile eşlenir.
        from tp_core.features.triage.diller import normal_tur

        assert normal_tur(tp.hata_turu(m), m) in TURLER


@pytest.mark.parametrize(
    ("mesaj", "beklenen"),
    [
        (PW_ASSERT, ("150,00 TL", "175,00 TL")),
        (
            "Locator expected to have text: 150,00 TL\nReceived: 175,00 TL",
            ("150,00 TL", "175,00 TL"),
        ),
        (
            "AssertionError: 'sepet-toplam' metni: beklenen <150,00 TL>, "
            "görülen <175,00 TL> (5000 ms)",
            ("150,00 TL", "175,00 TL"),
        ),
        ("Call log:\n  Locator expected to have text 'x'\nActual value: y", (None, None)),
        ("ZeroDivisionError", (None, None)),
        (None, (None, None)),
    ],
)
def test_beklenen_gorulen(mesaj: str | None, beklenen: tuple[str | None, str | None]) -> None:
    assert tp.EKLENTI.beklenen_gorulen(mesaj) == beklenen


@pytest.mark.parametrize(
    ("ad", "dosya", "u8"),
    [
        ("test_tpd_1_c2_3f9b1c2e", None, "3f9b1c2e"),
        ("test_tpd_1_android_c2_3f9b1c2e", None, "3f9b1c2e"),
        (
            "tests.generated.test_tpd_1_ios_c12_0a1b2c3d.test_tpd_1_ios_c12_0a1b2c3d",
            None,
            "0a1b2c3d",
        ),
        ("test_serbest_c3_3f9b1c2e[2-3]", None, "3f9b1c2e"),
        ("senaryo", "tests/generated/test_tpd_1_windows_c3_0a1b2c3d.py", "0a1b2c3d"),
        ("test_giris_basarili", "tests/test_giris.py", None),
        ("TPD1AndroidC2_3f9b1c2eTest.senaryo", None, None),
    ],
)
def test_test_kimligi(ad: str, dosya: str | None, u8: str | None) -> None:
    assert tp.EKLENTI.test_kimligi(ad, dosya) == u8


@pytest.mark.parametrize(
    ("dosya", "beklenen"),
    [
        ("tests/generated/test_tpd_1_c2_3f9b1c2e.py", True),
        ("e2e-python/tests/test_login.py", True),
        ("tests.generated.test_tpd_1_c2_3f9b1c2e", True),
        ("tests/conftest.py", False),
        ("e2e/tests/generated/tpd-1-c2-3f9b1c2e.spec.ts", False),
        ("com.antreklabs.bayi.uretilen.TPD1C3_0a1b2c3dTest", False),
        ("src/test/java/com/x/YTest.java", False),
        ("", False),
        (None, False),
    ],
)
def test_test_dosyasi_mi(dosya: str | None, beklenen: bool) -> None:
    assert tp.EKLENTI.test_dosyasi_mi(dosya) is beklenen


def test_python_istisnasi_mi() -> None:
    assert tp.python_istisnasi_mi(PW_TIMEOUT)
    assert tp.python_istisnasi_mi("x", "selenium.common.exceptions.TimeoutException")
    assert not tp.python_istisnasi_mi("java.lang.AssertionError: x")


def test_eklenti_kesfedilir() -> None:
    """Ş0 keşfi (varsa) Python eklentisini bulur; yoksa modül düzeyi `EKLENTI` yeterlidir."""
    try:
        from tp_core.features.triage import diller
    except ImportError:  # pragma: no cover
        return
    eklenti = getattr(diller, "eklenti", None)
    if eklenti is not None:
        assert eklenti("python") is tp.EKLENTI
    assert tp.EKLENTI.ad == "python"
