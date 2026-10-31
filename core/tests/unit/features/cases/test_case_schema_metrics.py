"""Case şeması (§7), kabul kriteri referansları ve düzeltme ölçüsü (§12) — DB'siz."""

from __future__ import annotations

import json

import pytest

from tp_core.features.cases import metrics
from tp_core.features.cases.schema import (
    acceptance_criteria,
    content_errors,
    unknown_ac_refs,
    validate_case,
)
from tp_core.gateway import find_rules_dir

from .helpers import case_icerik

GOLDENS = sorted((find_rules_dir() / "replay" / "case_generation" / "golden").glob("*.json"))


@pytest.mark.parametrize("path", GOLDENS, ids=lambda p: p.stem)
def test_golden_caseleri_tek_case_semasina_uyar(path) -> None:
    for case in json.loads(path.read_text(encoding="utf-8"))["output"]["cases"]:
        assert validate_case(case) == []


@pytest.mark.parametrize(
    ("bozma", "beklenen"),
    [
        ({"tags": ["manual"]}, "tags"),
        ({"type": "smoke"}, "type"),
        ({"title": "x" * 121}, "title"),
        ({"steps": [{"id": "1", "action": "a", "data": None, "expected": "b"}]}, "steps/0/id"),
        ({"steps": []}, "steps"),
        ({"ekstra": 1}, "(kök)"),
    ],
)
def test_sema_hatalari_alan_yoluyla_doner(bozma, beklenen) -> None:
    hatalar = validate_case(case_icerik(**bozma))
    assert hatalar and any(h.startswith(beklenen) for h in hatalar), hatalar


def test_eksik_alan_reddedilir() -> None:
    icerik = case_icerik()
    del icerik["expected_result"]
    assert any("expected_result" in h for h in validate_case(icerik))


def test_kabul_kriteri_bicimleri() -> None:
    assert acceptance_criteria(["AC1: Bir", "ac 2 - İki", "Önek yok"]) == [
        ("AC1", "Bir"),
        ("AC2", "İki"),
        ("AC3", "Önek yok"),
    ]
    assert acceptance_criteria([{"ref": "AC7", "metin": "Yedi"}, {"text": "x"}]) == [
        ("AC7", "Yedi"),
        ("AC2", "x"),
    ]


def test_bilinmeyen_kabul_kriteri() -> None:
    acs = ["AC1: a", "AC2: b"]
    assert unknown_ac_refs(case_icerik(ref="AC2"), acs) == []
    assert unknown_ac_refs(case_icerik(ref="AC9"), acs) == ["AC9"]
    assert unknown_ac_refs(case_icerik(ref="AC9"), []) == []  # AC'siz gereksinimde kural yok
    hatalar = content_errors(case_icerik(ref="AC9"), acs)
    assert hatalar == ["acceptance_criteria_refs: gereksinimde olmayan kabul kriteri: AC9"]


# ------------------------------------------------------------------- düzeltme ölçüsü


def test_levenshtein() -> None:
    assert metrics.levenshtein("kitten", "sitting") == 3
    assert metrics.levenshtein("", "abc") == 3
    assert metrics.levenshtein("aynı", "aynı") == 0


def test_kucuk_duzeltme_beklenen_sonuc_ayni() -> None:
    once = case_icerik()
    sonra = case_icerik(title="Geçerli bilgilerle giriş yapılır")
    m = metrics.edit_metrics(once, sonra)
    assert m["degisen_alanlar"] == ["title"]
    assert 0 < m["mesafe"] <= metrics.KUCUK_DUZELTME_ESIGI
    assert m["beklenen_sonuc_degisti"] is False
    assert m["beklenen_sonuc_kaynagi"] == "metin_karsilastirma"
    assert m["kucuk_duzeltme"] is True


def test_buyuk_ve_beklenen_sonucu_degistiren_duzeltme() -> None:
    once = case_icerik()
    sonra = case_icerik(expected_result="Hata mesajı gösterilir")
    m = metrics.edit_metrics(once, sonra)
    assert m["beklenen_sonuc_degisti"] is True and m["kucuk_duzeltme"] is False
    # İnsan "anlamca değişmedi" derse onun yargısı geçerlidir (kaynak kaydedilir).
    m2 = metrics.edit_metrics(once, sonra, beklenen_anlam_degisti=False)
    assert m2["beklenen_sonuc_kaynagi"] == "insan"
    tamamen = case_icerik(
        title="Tamamen başka bir başlık",
        preconditions=["Hiçbiri"],
        steps=[{"id": "S1", "action": "Sepeti boşalt", "data": "x", "expected": "Sepet boş"}],
    )
    assert metrics.edit_metrics(once, tamamen)["mesafe"] > metrics.KUCUK_DUZELTME_ESIGI


def test_normalize_buyuk_kucuk_ve_bosluk_duzeltme_sayilmaz() -> None:
    once = case_icerik()
    sonra = case_icerik(title="  GEÇERLİ   bilgilerle giriş ")
    # Boşluk sadeleşir; Türkçe "İ" casefold'da birleşik nokta bırakır (1 karakter) — yine küçük.
    assert metrics.edit_metrics(once, sonra)["mesafe"] < 0.02


def test_ilk_karar_kabul_mu() -> None:
    assert metrics.first_decision_accepted("approve", None)
    assert metrics.first_decision_accepted("edit", {"kucuk_duzeltme": True})
    assert not metrics.first_decision_accepted("edit", {"kucuk_duzeltme": False})
    assert not metrics.first_decision_accepted("reject", None)


def test_manuel_baz_yalnizca_verilirse_doner(monkeypatch) -> None:
    from tp_core.features.cases.service import manual_baseline_ms

    monkeypatch.delenv("TP_MANUAL_BASELINE_S", raising=False)
    assert manual_baseline_ms() is None
    monkeypatch.setenv("TP_MANUAL_BASELINE_S", "abc")
    assert manual_baseline_ms() is None
    monkeypatch.setenv("TP_MANUAL_BASELINE_S", "0")
    assert manual_baseline_ms() is None
    monkeypatch.setenv("TP_MANUAL_BASELINE_S", "5400")
    assert manual_baseline_ms() == 5_400_000
