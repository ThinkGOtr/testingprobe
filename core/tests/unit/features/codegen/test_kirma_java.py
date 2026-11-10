"""Uygulama (Java) kırarak doğrulama kararı ve cihaz tekrar sayısı (009 §2.9, Ş6b)."""

from __future__ import annotations

from typing import Any

from tp_core.features.codegen.classify import classify
from tp_core.features.codegen.service import _kirma_karari, tekrar_sayisi

ASSERT = "'cart-total' metni: beklenen <150,00 TL>, görülen <175,00 TL> (10000 ms)"


def _rapor(testler: list[dict[str, Any]], kirmizi: Any = None, sonuc: str = "failure") -> dict:
    return {
        "lang": "java",
        "platform": "android",
        "conclusion": sonuc,
        "app": {"ok": True},
        "deps": {"ok": True},
        "guard": {"ok": True},
        "compile": {"ok": True},
        "run": {"status": "failed", "saglik": {"ok": True}, "tests": testler,
                "kirmizi_denetimi": kirmizi},
    }  # fmt: skip


def _kirmizi(tur: str = "assertion", mesaj: str = ASSERT) -> dict[str, Any]:
    return {
        "title": "TPD1AndroidC2_0a1b2c3dTest › senaryo",
        "status": "unexpected",
        "error": mesaj,
        "failure": {"type": tur, "message": mesaj},
    }


def test_tekrar_sayisi_cihazda_bir() -> None:
    assert tekrar_sayisi("web") == 3 and tekrar_sayisi(None) == 3
    assert tekrar_sayisi("android") == tekrar_sayisi("ios") == tekrar_sayisi("windows") == 1


def test_kirmizi_denetimi_classifyya_tasinir() -> None:
    assert classify(_rapor([_kirmizi()])).kirmizi_ok is None
    assert classify(_rapor([_kirmizi()], {"ok": True})).kirmizi_ok is True
    assert classify(_rapor([_kirmizi()], {"ok": False})).kirmizi_ok is False


def test_kirma_karari_java() -> None:
    yesil = classify(_rapor([{"title": "t", "status": "expected"}], None, "success"))
    assert yesil.sinif == "gecti"
    kirik = classify(_rapor([_kirmizi()], {"ok": True, "kirmizi": ["t"], "kotu": []}))
    assert kirik.sinif == "defect_adayi"
    assert _kirma_karari(kirik, yesil, False)[0] == "passed"
    # test-runner kırmızı denetimi çelişirse kanıt sayılmaz.
    celiski = classify(_rapor([_kirmizi()], {"ok": False, "kirmizi": [], "kotu": ["t"]}))
    durum, neden = _kirma_karari(celiski, yesil, False)
    assert durum == "failed" and "kırmızı denetimi" in neden
    # Locator kırmızısı (ör. kampanya kırılması ekranı değiştirdi): kanıt değil.
    loc = classify(
        _rapor([_kirmizi("locator_not_found", "Expected condition failed: öğe görünmedi")])
    )
    assert _kirma_karari(loc, yesil, False)[0] == "failed"
    # Kırık koşu yeşil: zayıf test.
    assert _kirma_karari(yesil, yesil, False)[0] == "weak"
