"""Canlı eval denetleyicilerinin yakalama gücü (011 ikinci tur #2, #7, #9, #10, #13, #18).

Her test temiz bir golden çıktıdan başlar (golden denetleyiciden geçer), ona kasıtlı TEK bir bozulma
uygular ("kötü çıktı" fikstürü) ve denetleyicinin bunu yakaladığını gösterir. Kaynak, eval setinin
gerçek girdi mesajıdır (test verisi bloğu: P-001 25,00 · P-002 15,00 · P-003 8,00 · P-004 30,00 TL;
eşikler 500,00 / 750,00 / 2.000,00 TL yapı taşı değildir).
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from tests.unit.gateway.demo_sources import RULES, load_golden
from tp_core.gateway.eval_agents import (
    birim_fiyatlar,
    coverage_problems,
    deepening_problems,
    design_model_problems,
    en_yakin_kurulabilir,
    generation_stats,
    item_like_problems,
    nearest_value_problems,
    platform_problems,
    priority_problems,
    sepet_alt_toplamlari,
    source_problems,
)
from tp_core.gateway.eval_set import case_source


def _set_case(bundle: str, case_id: str) -> dict[str, Any]:
    data = json.loads((RULES / "evaluation" / f"{bundle}.json").read_text(encoding="utf-8"))
    return next(c for c in data["cases"] if c["id"] == case_id)


@pytest.fixture(scope="module")
def tpd1_vaka() -> dict[str, Any]:
    return _set_case("case-generation", "tpd-1-son-hal")


@pytest.fixture(scope="module")
def kaynak(tpd1_vaka: dict[str, Any]) -> str:
    return case_source(tpd1_vaka)


def _tpd1() -> dict[str, Any]:
    return copy.deepcopy(load_golden("case_generation", "TPD-1")["output"])


def _uydurma(failures: list[str]) -> list[str]:
    return [f for f in failures if "kaynakta olmayan" in f]


# ------------------------------------------------------------------ #2 tutar denetleyicisi


def test_unit_prices_come_only_from_product_lines(kaynak: str) -> None:
    """Yapı taşları yalnız test verisi bloğundaki ürün birim fiyatlarıdır; limit (500,00 /
    2.000,00), minimum tutar (750,00) ve biçim örneği (1.250,00) yapı taşı değildir."""
    assert birim_fiyatlar(kaynak) == {"P-001": 2500, "P-002": 1500, "P-003": 800, "P-004": 3000}


def test_golden_passes_the_strict_source_check(tpd1_vaka: dict[str, Any], kaynak: str) -> None:
    assert coverage_problems(_tpd1(), tpd1_vaka["expect"], kaynak=kaynak) == []


@pytest.mark.parametrize(
    ("cn", "metin", "beklenen"),
    [
        # C3 sepeti P-001 × 6: alt toplamlar 25'in katları, en çok 150,00. Eski denetleyici
        # 8/15/25/30/500/750… ile 98 TL üstü her tam tutarı kurabildiği için kabul ediyordu.
        (
            3,
            "toplam 501,00 TL",
            "C3: kaynakta olmayan tutar '501,00 TL' (case sepetiyle kurulamıyor)",
        ),
        (
            3,
            "toplam 775,00 TL",
            "C3: kaynakta olmayan tutar '775,00 TL' (case sepetiyle kurulamıyor)",
        ),
        # Kuruşlu uydurma da sepet yolunda yakalanır.
        (
            3,
            "toplam 124,99 TL",
            "C3: kaynakta olmayan tutar '124,99 TL' (case sepetiyle kurulamıyor)",
        ),
    ],
)
def test_fabricated_amount_outside_the_case_basket_is_caught(
    tpd1_vaka: dict[str, Any], kaynak: str, cn: int, metin: str, beklenen: str
) -> None:
    out = _tpd1()
    out["cases"][cn - 1]["expected_result"] += f"; {metin}"
    assert _uydurma(coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak)) == [beklenen]


def test_basket_sub_totals_are_accepted(tpd1_vaka: dict[str, Any], kaynak: str) -> None:
    """Sepetin yeniden hesaplanmış alt toplamları (ara toplam, ödenen, indirim) uydurma değildir."""
    assert sepet_alt_toplamlari([(2500, 6)]) == {0, 2500, 5000, 7500, 10000, 12500, 15000}
    out = _tpd1()
    out["cases"][2]["expected_result"] += "; ara toplam 150,00 TL, indirim 25,00 TL"
    assert coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak) == []


def test_amount_in_a_case_without_basket_is_caught(tpd1_vaka: dict[str, Any], kaynak: str) -> None:
    """Sepeti olmayan case'te kaynakta birebir geçmeyen tutar uydurmadır (birim fiyatlarla
    kurulabilse bile: 501,00 = 3 × P-002 + 57 × P-003)."""
    out = _tpd1()
    case = out["cases"][7]  # C8: sepet P-004 × 25 → sepeti kaldır
    case["test_data"] = [v for v in case["test_data"] if "P-" not in v["value"]]
    for adim in case["steps"]:
        adim["data"] = None
    case["expected_result"] += "; toplam 501,00 TL"
    assert _uydurma(coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C8: kaynakta olmayan tutar '501,00 TL' (case'te sepet yok)"
    ]


def test_amount_laundered_through_test_data_or_step_data_is_caught(
    tpd1_vaka: dict[str, Any], kaynak: str
) -> None:
    """Aklama: case'in kendi test verisine / adım verisine yazılan tutar ve alıntı kaynak
    sayılmaz (eskiden `test_data.value="1.234,56 TL"` ile `[]` dönüyordu)."""
    out = _tpd1()
    case = out["cases"][2]
    case["test_data"].append(
        {"name": "beklenen", "value": "1.234,56 TL", "synthetic": True, "is_attack_payload": False}
    )
    case["steps"][-1]["data"] = '"Sipariş başarıyla tamamlandı"'
    case["expected_result"] += '; toplam 1.234,56 TL ve "Sipariş başarıyla tamamlandı" mesajı'
    assert _uydurma(coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C3: kaynakta olmayan alıntı 'Sipariş başarıyla tamamlandı'",
        "C3: kaynakta olmayan tutar '1.234,56 TL' (case sepetiyle kurulamıyor)",
    ]


def test_preparation_precondition_is_the_only_extra_source(
    tpd1_vaka: dict[str, Any], kaynak: str
) -> None:
    """K17: "Test verisi hazırlığı" ön koşulu sentetik değeri tanımlar; o case için kaynaktır."""
    out = _tpd1()
    case = out["cases"][12]  # C13: kampanyasız, minimum tutarın hemen altı
    case["preconditions"].append(
        "Test verisi hazırlığı: fiyatı 749,99 TL olan kampanyasız sentetik ürün hazırlanır"
    )
    case["expected_result"] = 'Toplam 749,99 TL; "Minimum sipariş tutarı 750,00 TL" uyarısı'
    assert coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak) == []


def test_fabricated_limit_is_caught_even_if_the_basket_builds_it(
    tpd1_vaka: dict[str, Any], kaynak: str
) -> None:
    """Limit / minimum / eşik bağlamındaki tutar kaynakla birebir eşleşmeli. C12'nin sepeti
    P-001 × 12 ile 300,00 kurulabilir; ama "kredi limiti 300,00 TL" uydurma limittir."""
    out = _tpd1()
    out["cases"][11]["expected_result"] += "; bayinin kredi limiti 300,00 TL'yi aşmaz"
    assert _uydurma(coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C12: kaynakta olmayan eşik/limit tutarı '300,00 TL'"
    ]
    # Kaynaktaki limit birebir geçerse ve fark tutarı ("limitini 25,00 TL aşar") eşik değildir.
    temiz = _tpd1()
    temiz["cases"][11]["expected_result"] += (
        "; kredi limiti 500,00 TL olan bayi2'de tutar limitini 25,00 TL aşar"
    )
    assert coverage_problems(temiz, tpd1_vaka["expect"], kaynak=kaynak) == []


def test_source_problems_without_case_context_still_use_unit_prices_only(kaynak: str) -> None:
    """Tasarım modeli aksiyonları (case sepeti yok): birim fiyat birleşimi; eşikler yapı taşı
    değil. 0,01 TL kuruşlu uydurma yakalanır."""
    assert source_problems([("DT1", "toplam 750,00 TL")], kaynak) == []
    assert source_problems([("DT1", "toplam 749,99 TL")], kaynak) == [
        "DT1: kaynakta olmayan tutar '749,99 TL'"
    ]


# ------------------------------------------------------- #9 K17 "en yakın kurulabilir değer"


def test_nearest_constructible_value_is_computed(kaynak: str) -> None:
    fiyat = set(birim_fiyatlar(kaynak).values())
    assert en_yakin_kurulabilir(74999, fiyat, yon="alt") == 74900
    assert en_yakin_kurulabilir(50001, fiyat, yon="ust") == 50100  # 3 × P-002 + 57 × P-003
    assert en_yakin_kurulabilir(200001, fiyat, yon="ust") == 200100


def test_golden_nearest_value_claims_are_correct(kaynak: str) -> None:
    for name in ("TPD-1", "f2-kod-hatasi/TPD-1", "SERBEST"):
        assert nearest_value_problems(load_golden("case_generation", name)["output"], kaynak) == []
    assert nearest_value_problems(load_golden("design_model", "TPD-1")["output"], kaynak) == []


@pytest.mark.parametrize(
    ("tanim", "beklenen"),
    [
        (
            # Canlı tpd-1-son-hal#k1: 25'in katlarıyla düşünülmüş; 501,00 kurulabilir.
            "Sipariş tutarı limiti aşar: 525,00 TL (P-001 × 25); demo fiyatlarıyla kurulabilen, "
            "500,01 TL'ye en yakın değer",
            "BV-6: 500,01 TL için kurulabilen en yakın üst değer 501,00 TL, iddia 525,00 TL",
        ),
        (
            # Canlı design-model tpd-1-son-hal: yalnız P-003 ile düşünülmüş.
            "Kampanyasız tutar 749,99 TL; kurulabilen en yakın değer 744,00 TL (93 x 8,00 TL)",
            "BV-6: 749,99 TL için kurulabilen en yakın alt değer 749,00 TL, iddia 744,00 TL",
        ),
        (
            # Sınırın kendisi kurulabiliyor: ideal değer sınırın bir kuruş ötesi.
            "bayi2 sipariş tutarı 625,00 TL (P-001 × 30): 500,00 TL üstünde kurulabilen en yakın "
            "değer",
            "BV-6: 500,01 TL için kurulabilen en yakın üst değer 501,00 TL, iddia 625,00 TL",
        ),
    ],
)
def test_wrong_nearest_value_claim_is_caught(kaynak: str, tanim: str, beklenen: str) -> None:
    out = _tpd1()
    bv6 = next(o for o in out["coverage_items"] if o["id"] == "BV-6")
    bv6["definition"] = tanim
    assert nearest_value_problems(out, kaynak) == [beklenen]


def test_nearest_value_claim_is_part_of_source_grounding(
    tpd1_vaka: dict[str, Any], kaynak: str
) -> None:
    out = _tpd1()
    bv6 = next(o for o in out["coverage_items"] if o["id"] == "BV-6")
    bv6["definition"] = bv6["definition"].replace(
        "en yakın değer 749,00 TL", "en yakın değer 744,00 TL"
    )
    assert coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak) == [
        "BV-6: 749,99 TL için kurulabilen en yakın alt değer 749,00 TL, iddia 744,00 TL"
    ]
    model = copy.deepcopy(load_golden("design_model", "TPD-1")["output"])
    hedef = next(o for o in model["coverage_items"] if "749,00" in str(o.get("definition")))
    hedef["definition"] = hedef["definition"].replace("749,00", "725,00")
    dm = _set_case("design-model", "tpd-1-son-hal")
    fails = design_model_problems(model, dm["expect"], kaynak=case_source(dm))
    assert any("en yakın alt değer 749,00 TL, iddia 725,00 TL" in f for f in fails), fails


# ------------------------------------------------------------- #7 must_cover_items_like


def _bv_only(*tanimlar: str) -> dict[str, Any]:
    return {
        "coverage_items": [
            {"id": f"BV-{n}", "definition": t, "valid": True, "ac_ref": "AC2"}
            for n, t in enumerate(tanimlar, start=1)
        ]
    }


def test_wrong_boundaries_do_not_satisfy_numeric_topics(tpd1_vaka: dict[str, Any]) -> None:
    """Yanlış sınırlar ("15 adet / 16 adet / 1.750,00 TL") "5 adet / 6 adet / 750,00" konularını
    geçmez."""
    expect = {"must_cover_items_like": tpd1_vaka["expect"]["must_cover_items_like"]}
    yanlis = _bv_only("15 adet: bedava yok", "16 adet: 1 bedava", "Sepet 1.750,00 TL")
    assert item_like_problems(yanlis, expect) == [
        "kapsam öğesi ya da kararı yok: bedava eşiğinin altı: 5 adet",
        "kapsam öğesi ya da kararı yok: bedava eşiği: 6 adet",
        "kapsam öğesi ya da kararı yok: minimum sipariş tutarı sınırı 750,00 TL",
    ]
    dogru = _bv_only("5 adet: bedava yok", "6 adet: 1 bedava", "Sepet 750,00 TL")
    assert item_like_problems(dogru, expect) == []


def test_lock_threshold_topics_need_the_exact_count() -> None:
    expect = {
        "must_cover_items_like": _set_case("case-generation", "hesap-kilidi-st")["expect"][
            "must_cover_items_like"
        ][:2]
    }
    assert len(item_like_problems(_bv_only("12 hatalı deneme", "13 hatalı deneme"), expect)) == 2
    assert (
        item_like_problems(_bv_only("2 art arda hatalı deneme", "3. hatalı deneme"), expect) == []
    )


def test_numeric_topic_counts_only_in_bv_items(tpd1_vaka: dict[str, Any]) -> None:
    """Sayısal konu EP öğesinde ya da kapsanmayan kararında anılması sınır öğesi sayılmaz."""
    expect = {"must_cover_items_like": tpd1_vaka["expect"]["must_cover_items_like"][:1]}
    out = {
        "coverage_items": [{"id": "EP-V2", "definition": "Kampanyalı ürün 5 adet", "valid": True}],
        "not_covered": [{"item": "AC2", "reason": "5 adet sınırı yazılmadı"}],
    }
    assert item_like_problems(out, expect) == [
        "kapsam öğesi ya da kararı yok: bedava eşiğinin altı: 5 adet"
    ]
    # Sayısal olmayan anahtar sözcük (ör. "kilitli") eskisi gibi her öğe ve kararda aranır.
    kilit = {"must_cover_items_like": [{"topic": "kilitli giriş", "keywords": ["kilitli"]}]}
    st = {"coverage_items": [{"id": "ST-X1", "definition": "Kilitli + doğru parola"}]}
    assert item_like_problems(st, kilit) == []


# ---------------------------------------------------------------- #10 öncelik dağılımı


def test_too_many_p1_cases_are_caught(tpd1_vaka: dict[str, Any], kaynak: str) -> None:
    expect = tpd1_vaka["expect"]
    assert expect["max_p1_orani"] == 0.6
    out = _tpd1()
    assert generation_stats(out)["priority"] == {"P1": 8, "P2": 6, "P3": 1}
    assert generation_stats(out)["p1_orani"] == 0.5333
    for case in out["cases"]:
        case["priority"] = "P1"
    assert coverage_problems(out, expect, kaynak=kaynak) == ["P1 oranı 15/15 = 1.00, en çok 0.60"]
    assert priority_problems(out["cases"], {}) == []  # beklenti yoksa ölçülmez


def test_set_p1_thresholds_hold_for_every_golden() -> None:
    """Eşikler golden'ların P1 oranının üstündedir; TPD-4 (giriş: ana akış + güvenlik)
    eşiksizdir."""
    data = json.loads((RULES / "evaluation" / "case-generation.json").read_text(encoding="utf-8"))
    esik = {c["id"]: c["expect"].get("max_p1_orani") for c in data["cases"]}
    assert esik == {
        "tpd-1-son-hal": 0.6,
        "tpd-1-f2-kod-hatasi": 0.6,
        "tpd-3-arama": 0.5,
        "tpd-4-giris": None,
        "serbest-son-hal": 0.5,
        "hesap-kilidi-st": 0.75,
    }


# ------------------------------------------------------------- #13 mesaj iddiası deseni


@pytest.mark.parametrize(
    "beklenen",
    [
        '"Hesap askıya alındı" mesajını gösterir',
        "Uyarı ekranda belirir",
        "Kırmızı hata yazısı görünür",
        "Bayiye bilgilendirme mesajı iletilir",
        "Sistem ekrana uyarı yazar",
    ],
)
def test_message_claims_in_active_voice_are_checked(beklenen: str) -> None:
    out = {
        "cases": [
            {
                "title": "x",
                "type": "negative",
                "tags": ["N1"],
                "readiness": "ready",
                "expected_result": beklenen,
                "steps": [],
            }
        ]
    }
    fails = deepening_problems(out, {"source_messages": ["Kredi limiti aşıldı"]})
    assert any("kaynakta olmayan mesaj" in f for f in fails), (beklenen, fails)


def test_message_pattern_does_not_flag_typing_or_absent_messages() -> None:
    out = {
        "cases": [
            {
                "readiness": "ready",
                "expected_result": "Parola alana yazılır ve giriş butonu aktif olur",
                "steps": [{"expected": "Parola mesajda görünmez"}],
            }
        ]
    }
    fails = deepening_problems(out, {"source_messages": ["Kredi limiti aşıldı"]})
    assert not [f for f in fails if "kaynakta olmayan mesaj" in f]


# ------------------------------------------------------------- #18 gözlem (olumlu yön)


def test_mentioned_non_adopted_threshold_needs_an_observation() -> None:
    out = copy.deepcopy(load_golden("case_generation", "platform-web/TPD-4")["output"])
    expect = {"platforms": ["Web"], "observation_thresholds": ["44×44"]}
    out["observations"] = []
    assert platform_problems(out, expect) == []  # anılmıyorsa gözlem zorunlu değil
    out["testability_gaps"] = ["Dokunma hedefi 44×44 ölçülemiyor"]
    assert platform_problems(out, expect) == [
        "benimsenmeyen standart eşiği '44×44' anılıyor ama gözlem yok (observations'a yazılmalıydı)"
    ]
    out["observations"] = [{"standard_ref": "WCAG 2.5.5", "note": "Hedef 44×44 değil"}]
    assert platform_problems(out, expect) == []
    assert generation_stats(out)["observations"] == 1
