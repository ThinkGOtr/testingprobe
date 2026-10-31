"""Yerel kontrol raporunun deterministik sınıfı (§8.4 adım 5)."""

from __future__ import annotations

from typing import Any

from tp_core.features.codegen.classify import classify
from tp_core.features.codegen.classify import test_error_kind as hata_turu

ASSERT_MSG = (
    "Error: expect(locator).toHaveText(expected) failed\n\n"
    "Locator: getByTestId('cart-line-free-P-001')"
    '\nExpected: "0"\nReceived: "1"\nTimeout: 5000ms'
)
LOCATOR_MSG = (
    "Error: locator.click: Timeout 5000ms exceeded.\nCall log:\n"
    "  - waiting for getByTestId('product-card-P-001').getByTestId('add-to-cart')"
)
NOT_FOUND_MSG = (
    "Error: expect(locator).toHaveText(expected) failed\n\nLocator: getByTestId('cart-total')\n"
    'Expected: "150,00 TL"\nTimeout: 5000ms\nError: element(s) not found'
)


def rapor(*testler: dict[str, Any], conclusion: str = "failure", **ek: Any) -> dict[str, Any]:
    r: dict[str, Any] = {
        "conclusion": conclusion,
        "summary": "Yerel CI başarısız: run",
        "deps": {"ok": True},
        "tsc": {"ok": True},
        "eslint": {"ok": True},
        "ast_guard": {"ok": True},
        "run": {
            "run_id": "r1",
            "status": "passed" if conclusion == "success" else "failed",
            "saglik": {"ok": True},
            "tests": list(testler),
        },
    }
    r.update(ek)
    return r


def kt(status: str, error: str | None = None, failure: dict | None = None) -> dict[str, Any]:
    return {"title": "TPD-1 · C3 › 6 adet", "status": status, "error": error, "failure": failure}


def test_gecti() -> None:
    s = classify(rapor(kt("expected"), kt("expected"), kt("expected"), conclusion="success"))
    assert (s.sinif, s.sonuc, s.gecen, s.toplam) == ("gecti", "success", 3, 3)


def test_assertion_defect_adayi_ve_ayrintilar() -> None:
    s = classify(rapor(kt("unexpected", ASSERT_MSG)))
    assert s.sinif == "defect_adayi" and s.sonuc == "failure"
    h = s.basarisiz[0]
    assert (h["beklenen"], h["gerceklesen"]) == ('"0"', '"1"')
    assert "Otomatik onarım yapılmaz" in s.aciklama


def test_runner_failure_turu_onceliklidir() -> None:
    f = {"type": "locator_timeout", "locator": "getByTestId('add-to-cart')", "step": None}
    s = classify(rapor(kt("unexpected", "Test timeout of 20000ms exceeded.", f)))
    assert s.sinif == "locator" and s.basarisiz[0]["locator"] == "getByTestId('add-to-cart')"
    f2 = {"type": "assertion", "expected": "1", "received": "0"}
    assert classify(rapor(kt("unexpected", "x", f2))).sinif == "defect_adayi"


def test_locator_onceliklidir() -> None:
    s = classify(rapor(kt("unexpected", ASSERT_MSG), kt("unexpected", LOCATOR_MSG)))
    assert s.sinif == "locator"
    assert hata_turu(NOT_FOUND_MSG) == "locator"


def test_derleme_ve_ortam() -> None:
    r = rapor(tsc={"ok": False, "errors": []})
    r["run"] = {}
    r["eslint"] = r["ast_guard"] = {"ok": False, "skipped": True}
    s = classify(r)
    assert s.sinif == "derleme" and s.adimlar["tsc"] is False and s.adimlar["eslint"] is None
    r = rapor()
    r["run"] = {"status": "error", "error": "sağlık", "saglik": {"ok": False}, "tests": []}
    assert classify(r).sinif == "ortam"
    nav = kt("unexpected", "page.goto: net::ERR_CONNECTION_REFUSED at http://x")
    assert classify(rapor(nav)).sinif == "ortam"


def test_bilinmiyor() -> None:
    assert classify(rapor(kt("unexpected", "TypeError: x is undefined"))).sinif == "bilinmiyor"


def test_calisan_uygulama_commitle_eslesmezse_ortam() -> None:
    """`/check` `app` adımı (sha_eslesmesi='farkli') koşuyu yapmaz → ortam, defect değil."""
    r = rapor()
    r["app"] = {
        "ok": False,
        "sha_eslesmesi": "farkli",
        "farkli_yollar": ["api"],
        "error": "Uygulama commit ile eşleşmiyor: …",
    }
    r["run"] = {}
    for ad in ("deps", "tsc", "eslint", "ast_guard"):
        r[ad] = {"ok": False, "skipped": True}
    s = classify(r)
    assert (s.sinif, s.sonuc) == ("ortam", "error")
    assert s.hata and "eşleşmiyor" in s.hata
    # Uyarıyla geçen (dogrulanamadi) app adımı sınıfı değiştirmez.
    r2 = rapor(kt("expected"), conclusion="success")
    r2["app"] = {"ok": True, "sha_eslesmesi": "dogrulanamadi"}
    assert classify(r2).sinif == "gecti"
