"""Java/Appium yerel kontrol raporunun deterministik sınıfı (009 §2.3; Ş6)."""

from __future__ import annotations

from typing import Any

from tp_core.features.codegen.classify import classify, java_beklenen_gorulen
from tp_core.features.codegen.classify import test_error_kind as hata_turu

ASSERT_JAVA = (
    "java.lang.AssertionError: cart-total metni: beklenen <150,00 TL>, görülen <175,00 TL> "
    "(10000 ms)"
)
TIMEOUT_JAVA = (
    "org.openqa.selenium.TimeoutException: Expected condition failed: öğe tıklanabilir olmadı: "
    "kimlik 'product-card-P-001' içinde 'add-to-cart' (tried for 10 second(s) with 250 "
    "milliseconds interval)"
)
ORTAM_JAVA = (
    "org.openqa.selenium.SessionNotCreatedException: Could not start a new session. "
    "Response code 500"
)
KURULUM_JAVA = "java.lang.AssertionError: POST /test/reset başarısız: 401"


def jrapor(*testler: dict[str, Any], conclusion: str = "failure", **ek: Any) -> dict[str, Any]:
    r: dict[str, Any] = {
        "conclusion": conclusion,
        "summary": "Yerel CI başarısız: run",
        "lang": "java",
        "platform": "android",
        "app": {"ok": True},
        "deps": {"ok": True},
        "guard": {"ok": True},
        "compile": {"ok": True},
        "run": {
            "run_id": "r1",
            "status": "passed" if conclusion == "success" else "failed",
            "saglik": {"ok": True},
            "tests": list(testler),
        },
    }
    r.update(ek)
    return r


def kt(status: str, error: str | None = None) -> dict[str, Any]:
    return {"title": "TPD1C3_0a1b2c3dTest.senaryo", "status": status, "error": error}


def test_java_hata_turleri() -> None:
    assert hata_turu(ASSERT_JAVA) == "assertion"
    assert hata_turu(TIMEOUT_JAVA) == "locator"
    assert hata_turu("org.openqa.selenium.NoSuchElementException: no such element") == "locator"
    assert hata_turu("StaleElementReferenceException: stale") == "locator"
    assert hata_turu(ORTAM_JAVA) == "ortam"
    assert hata_turu("java.net.ConnectException: Connection refused") == "ortam"
    # Kurulum kaynaklı assertion defect adayı değildir.
    assert hata_turu(KURULUM_JAVA) == "ortam"
    # Runner'ın biçimsel türü önce gelir.
    assert hata_turu(TIMEOUT_JAVA, "assertion") == "assertion"


def test_java_beklenen_gorulen() -> None:
    assert java_beklenen_gorulen(ASSERT_JAVA) == ("150,00 TL", "175,00 TL")
    assert java_beklenen_gorulen("AssertionError: expected [1] but found [2]") == ("1", "2")
    assert java_beklenen_gorulen("başka") == (None, None)


def test_java_gecti_ve_adimlar() -> None:
    s = classify(jrapor(kt("passed"), conclusion="success"))
    assert s.sinif == "gecti" and "Appium" in s.aciklama
    assert set(s.adimlar) == {"deps", "guard", "compile"}


def test_java_guard_ya_da_compile_derleme() -> None:
    s = classify(jrapor(guard={"ok": False}))
    assert s.sinif == "derleme" and "guard" in (s.hata or "")
    s = classify(jrapor(compile={"ok": False}))
    assert s.sinif == "derleme" and "compile" in (s.hata or "")


def test_java_defect_adayi_tekrarlar_tutarli() -> None:
    s = classify(
        jrapor(kt("failed", ASSERT_JAVA), kt("failed", ASSERT_JAVA), kt("failed", ASSERT_JAVA))
    )
    assert s.sinif == "defect_adayi"
    h = s.basarisiz[0]
    assert (h["beklenen"], h["gerceklesen"], h["tekrar"]) == ("150,00 TL", "175,00 TL", 3)


def test_java_kararsiz_ve_locator_ve_ortam() -> None:
    assert classify(jrapor(kt("passed"), kt("failed", ASSERT_JAVA))).sinif == "kararsiz"
    assert classify(jrapor(kt("failed", TIMEOUT_JAVA))).sinif == "locator"
    assert classify(jrapor(kt("failed", ORTAM_JAVA))).sinif == "ortam"


def test_java_uygulama_adimi_ortam() -> None:
    s = classify(jrapor(app={"ok": False, "error": "Appium erişilemedi"}))
    assert s.sinif == "ortam"


def test_ts_raporu_degismedi() -> None:
    r = jrapor(kt("passed"), conclusion="success")
    for k in ("lang", "platform", "guard", "compile"):
        r.pop(k)
    r.update(tsc={"ok": True}, eslint={"ok": True}, ast_guard={"ok": True})
    s = classify(r)
    assert list(s.adimlar) == ["deps", "tsc", "eslint", "ast_guard"]
    assert "Playwright" in s.aciklama
