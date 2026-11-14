"""Canlı eval denetleyicilerinin yakalama gücü (011 ikinci tur #2, #7, #9, #10, #13, #18; test
mimarı 3. tur #3, #4, #5).

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
    SEPET_OKUNAMADI,
    birim_fiyatlar,
    case_sepeti,
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
    sepet_okunamadi_sayisi,
    source_problems,
    urun_adlari,
)
from tp_core.gateway.eval_set import CaseResult, case_source, uretim_dagilimi


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


# ------------------------------------------- 3. tur #3: sepet okuma (yanlış pozitif riski)


def _sepeti_yaz(case: dict[str, Any], *yazimlar: str) -> None:
    """Case'in sepetini (test verisi + adım verisi) verilen yazımlarla değiştirir: ilk yazım test
    verisine, her yazım ayrı bir adıma (adımlarda biriken sepet)."""
    sepet = next(v for v in case["test_data"] if "P-" in v["value"])
    sepet["value"] = yazimlar[0]
    adimlar = [a for a in case["steps"] if a.get("data") and "P-" in a["data"]]
    adimlar[0]["data"] = yazimlar[0]
    for yazim in yazimlar[1:]:
        case["steps"].insert(case["steps"].index(adimlar[0]) + 1, {**adimlar[0], "data": yazim})


def test_product_names_map_to_codes_from_the_test_data_block(kaynak: str) -> None:
    assert urun_adlari(kaynak) == {
        "portakal gazozu 1l": "P-001",
        "limonata 330ml": "P-002",
        "maden suyu 200ml": "P-003",
        "şeftalili soğuk çay 1l": "P-004",
    }


@pytest.mark.parametrize(
    "yazim",
    [
        "6 × P-001",  # ters yazım
        "6 adet P-001",
        "6x P-001",
        "Portakal Gazozu 1L × 6",  # kodsuz, test verisi bloğundaki ad
        '6 adet "Portakal Gazozu 1L"',
        'P-001 "Portakal Gazozu 1L" × 6',
    ],
)
def test_basket_spellings_are_read(tpd1_vaka: dict[str, Any], kaynak: str, yazim: str) -> None:
    """TEMİZ: C3 (6 adette 1 bedava; indirim 25,00, toplam 125,00) sepeti farklı yazımlarla;
    eskiden kodsuz ad ve ters yazım "kaynakta olmayan tutar" sayılıyordu."""
    out = _tpd1()
    _sepeti_yaz(out["cases"][2], yazim)
    assert coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak) == []


@pytest.mark.parametrize("yazim", ["6 × P-001", "Portakal Gazozu 1L × 6"])
def test_fabricated_amount_with_other_basket_spellings_is_caught(
    tpd1_vaka: dict[str, Any], kaynak: str, yazim: str
) -> None:
    """KÖTÜ: okunan sepetle (P-001 × 6) kurulamayan tutar ters yazımda da uydurmadır."""
    out = _tpd1()
    _sepeti_yaz(out["cases"][2], yazim)
    out["cases"][2]["expected_result"] += "; toplam 501,00 TL"
    assert _uydurma(coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C3: kaynakta olmayan tutar '501,00 TL' (case sepetiyle kurulamıyor)"
    ]


def test_basket_accumulated_over_steps_is_summed(tpd1_vaka: dict[str, Any], kaynak: str) -> None:
    """TEMİZ: C12 (12 adette 2 bedava; indirim 50,00, toplam 250,00) iki adımda 6'şar adet
    eklenir: sepet 12 adettir (eskiden en büyük adım alınıyordu: 6 → 250,00 reddediliyordu).
    KÖTÜ: aynı sepette 13. adetin tutarı (325,00) kurulamaz."""
    out = _tpd1()
    case = out["cases"][11]
    _sepeti_yaz(case, "P-001 × 6", "P-001 × 6")
    assert case_sepeti(case, birim_fiyatlar(kaynak)) == [(2500, 12)]
    assert coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak) == []
    case["expected_result"] += "; toplam 325,00 TL"
    assert _uydurma(coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C12: kaynakta olmayan tutar '325,00 TL' (case sepetiyle kurulamıyor)"
    ]


def _okunamayan_c3() -> dict[str, Any]:
    """C3'ün sepeti ürünü anıyor ama adedi okunamıyor ("P-001, altı tane")."""
    out = _tpd1()
    _sepeti_yaz(out["cases"][2], "P-001, altı tane")
    return out


def test_unreadable_basket_is_a_separate_category_not_fabrication(
    tpd1_vaka: dict[str, Any], kaynak: str
) -> None:
    """TEMİZ (uydurma değil): sepet okunamadığında ürünle açıklanabilen tutar (125,00 / 150,00;
    indirim 25,00 kaynakta birebir) "sepet okunamadı" olarak ayrı döner; eval raporunun
    `uydurma` listesine girmez."""
    fails = coverage_problems(_okunamayan_c3(), tpd1_vaka["expect"], kaynak=kaynak)
    assert _uydurma(fails) == []
    # Beklenen sonuç (125,00) ve S4 beklenen sonucu (ara toplam 150,00; toplam 125,00).
    assert fails == [
        f"C3: {SEPET_OKUNAMADI}: tutar '125,00 TL' doğrulanamadı",
        f"C3: {SEPET_OKUNAMADI}: tutar '150,00 TL' doğrulanamadı",
        f"C3: {SEPET_OKUNAMADI}: tutar '125,00 TL' doğrulanamadı",
    ]
    assert sepet_okunamadi_sayisi(fails) == 3
    rapor = uretim_dagilimi([CaseResult("tpd-1-son-hal#k1", False, fails, _okunamayan_c3())])
    assert rapor["uydurma"] == []


def test_unreadable_basket_does_not_hide_an_unexplainable_amount(
    tpd1_vaka: dict[str, Any], kaynak: str
) -> None:
    """KÖTÜ: okunamayan sepetin ürünüyle (25,00 TL'nin katları) açıklanamayan tutar yine
    uydurmadır."""
    out = _okunamayan_c3()
    out["cases"][2]["expected_result"] += "; toplam 124,99 TL"
    assert _uydurma(coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C3: kaynakta olmayan tutar '124,99 TL' (case'te sepet yok)"
    ]


# ------------------------------------------------- 3. tur #4: kalan yanlış negatifler


def test_preparation_precondition_is_not_a_quote_source(
    tpd1_vaka: dict[str, Any], kaynak: str
) -> None:
    """#4a KÖTÜ: hazırlığa yazılan tırnaklı mesaj alıntıyı aklamaz (hazırlık yalnız veri/tutar
    kaynağıdır). TEMİZ karşılığı: `test_preparation_precondition_is_the_only_extra_source`."""
    out = _tpd1()
    case = out["cases"][12]
    case["preconditions"].append(
        'Test verisi hazırlığı: "Sipariş tutarı yetersiz" mesajı tanımlanır'
    )
    case["expected_result"] += '; "Sipariş tutarı yetersiz" mesajı'
    assert _uydurma(coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C13: kaynakta olmayan alıntı 'Sipariş tutarı yetersiz'"
    ]


@pytest.mark.parametrize(
    "hazirlik",
    [
        "Test verisi hazırlığı: fiyatı 749,99 TL olan kampanyasız sentetik ürün hazırlanır",
        "Test verisi hazırlığı: 749,99 TL'lik kampanyasız sentetik ürün eklenir",
        "Test verisi hazırlığı: sentetik ürün (749,99 TL, kampanyasız) katalogda",
        'Test verisi hazırlığı: P-901 · "Deneme Ürünü" · 749,99 TL sentetik ürün',
    ],
)
def test_preparation_amount_needs_a_synthetic_product_price(
    tpd1_vaka: dict[str, Any], kaynak: str, hazirlik: str
) -> None:
    """#4b TEMİZ: hazırlıktaki sentetik ürün fiyatı kaynaktır. KÖTÜ: aynı tutar ürün/fiyat
    kalıbı olmadan ("sepet toplamı 749,99 TL") yazılırsa kaynak sayılmaz."""
    out = _tpd1()
    case = out["cases"][12]
    case["preconditions"].append(hazirlik)
    case["expected_result"] = 'Toplam 749,99 TL; "Minimum sipariş tutarı 750,00 TL" uyarısı'
    assert coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak) == []
    case["preconditions"][-1] = "Test verisi hazırlığı: sepet toplamı 749,99 TL olacak şekilde"
    assert _uydurma(coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C13: kaynakta olmayan tutar '749,99 TL' (case sepetiyle kurulamıyor)"
    ]


def test_arbitrary_amount_in_preparation_is_caught(tpd1_vaka: dict[str, Any], kaynak: str) -> None:
    """#4b KÖTÜ: sepetsiz case'te hazırlığa yazılan keyfi tutar ("sepet toplamı 1.234,56 TL")
    beklenen sonucu aklamaz. TEMİZ: hazırlıktaki sepet (P-004 × 25 + P-003 × 1) yeniden
    hesaplanır; toplamı 758,00 TL'dir. KÖTÜ: hazırlığa yazılan yanlış toplam (760,00) aklanmaz."""
    out = _tpd1()
    case = out["cases"][7]  # C8: sepet P-004 × 25 → sepeti hazırlığa taşı
    case["test_data"] = [v for v in case["test_data"] if "P-" not in v["value"]]
    for adim in case["steps"]:
        adim["data"] = None
    case["preconditions"].append("Test verisi hazırlığı: sepet toplamı 1.234,56 TL")
    case["expected_result"] += "; toplam 1.234,56 TL"
    assert _uydurma(coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C8: kaynakta olmayan tutar '1.234,56 TL' (case'te sepet yok)"
    ]
    case["preconditions"][-1] = (
        "Test verisi hazırlığı: sepete P-004 × 25 ve P-003 × 1 eklenir (toplam 758,00 TL)"
    )
    case["expected_result"] = case["expected_result"].replace("1.234,56", "758,00")
    assert coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak) == []
    case["preconditions"][-1] = case["preconditions"][-1].replace("758,00", "760,00")
    case["expected_result"] = case["expected_result"].replace("758,00", "760,00")
    assert _uydurma(coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C8: kaynakta olmayan tutar '760,00 TL' (case sepetiyle kurulamıyor)"
    ]


@pytest.mark.parametrize(
    "ek", ["300,00 TL olan kredi limiti aşılmaz", "bayinin 300,00 TL'lik kredi limiti"]
)
def test_fabricated_limit_in_reverse_order_is_caught(
    tpd1_vaka: dict[str, Any], kaynak: str, ek: str
) -> None:
    """#4c KÖTÜ: tutar önce, eşik adı sonra ("300,00 TL olan kredi limiti"); C12 sepeti
    (P-001 × 12) 300,00'ü kurabildiği halde uydurma limittir."""
    out = _tpd1()
    out["cases"][11]["expected_result"] += f"; {ek}"
    assert _uydurma(coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C12: kaynakta olmayan eşik/limit tutarı '300,00 TL'"
    ]


@pytest.mark.parametrize(
    "ek",
    [
        "toplam 300,00 TL olan sepet kredi limitini aşmaz",
        "toplam 300,00 TL olan sipariş limiti aşmaz",
        "ara toplam 300,00 TL olan sepet minimum sipariş tutarının altındadır",
    ],
)
def test_basket_total_compared_to_a_limit_is_not_a_limit(
    tpd1_vaka: dict[str, Any], kaynak: str, ek: str
) -> None:
    """#4c TEMİZ: sepet tutarı bir eşikle karşılaştırılıyorsa (etken "aşmaz", "altında") tutar
    eşik değil sepet toplamıdır."""
    out = _tpd1()
    out["cases"][11]["expected_result"] += f"; {ek}"
    assert coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak) == []


def test_sub_total_outside_basket_context_is_caught(tpd1_vaka: dict[str, Any], kaynak: str) -> None:
    """#4d KÖTÜ: "kalan bakiye 100,00 TL" C3 sepetinin (P-001 × 6) bir alt toplamıdır ama
    sepette karşılığı yoktur. TEMİZ: gerçek alt toplamlar (sepet toplamı, satır toplamı) her
    bağlamda; diğer alt toplamlar sepet/toplam bağlamında ("ödenecek tutar 125,00 TL")
    geçerlidir."""
    out = _tpd1()
    out["cases"][2]["expected_result"] += "; kalan bakiye 100,00 TL"
    assert _uydurma(coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C3: kaynakta olmayan tutar '100,00 TL' "
        "(sepet/toplam bağlamında değil; yalnız sepet ya da satır toplamı)"
    ]
    temiz = _tpd1()
    temiz["cases"][2]["expected_result"] += (
        "; ödenecek tutar 125,00 TL; 150,00 TL ekranda görünür; kalan bakiye 150,00 TL"
    )
    assert coverage_problems(temiz, tpd1_vaka["expect"], kaynak=kaynak) == []


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


@pytest.mark.parametrize(
    "beklenen",
    [
        "Hata mesajı görüntülenmelidir",
        "Uyarı penceresi açılır",
        "Bildirim gösterilir",
        "Limit aşım metni ekranda yer alır",
        "Toast mesajı listelenir",
    ],
)
def test_message_claims_with_more_verbs_and_nouns_are_checked(beklenen: str) -> None:
    """3. tur #5 KÖTÜ: kaynakta olmayan mesaj iddiası geniş fiil/ad kalıplarıyla da yakalanır.
    TEMİZ: aynı cümle "AÇIK NOKTA" (büyük/küçük harf duyarsız) ya da kaynak mesajıyla geçer."""
    out = {"cases": [{"readiness": "ready", "expected_result": beklenen, "steps": []}]}
    expect = {"source_messages": ["Kredi limiti aşıldı"]}
    fails = deepening_problems(out, expect)
    assert any("kaynakta olmayan mesaj" in f for f in fails), (beklenen, fails)
    for temiz in (
        f"{beklenen} (mesaj metni: açık nokta)",
        f"{beklenen} (mesaj metni: Açık Nokta)",
        f'{beklenen}: "Kredi limiti aşıldı"',
    ):
        out["cases"][0]["expected_result"] = temiz
        assert not [f for f in deepening_problems(out, expect) if "kaynakta olmayan mesaj" in f]


def test_message_pattern_does_not_flag_typing_or_absent_messages() -> None:
    out = {
        "cases": [
            {
                "readiness": "ready",
                "expected_result": "Parola alana yazılır ve giriş butonu aktif olur",
                "steps": [
                    {"expected": "Parola mesajda görünmez"},
                    {"expected": "Uyarı penceresi açılmaz; hata mesajı listelenmemeli"},
                    {"expected": "Sipariş geçmişinde listelenir"},
                ],
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


# ------------------------------------------- e10: 2026-11-13 canlı turunun yanlış pozitifleri
# Her düzeltme için TEMİZ fikstür (canlı çıktıdaki doğru yazım artık geçer) ve KÖTÜ fikstür
# (aynı kalıpla yazılmış gerçek uydurma hâlâ yakalanır).


def _bekleneni_ekle(out: dict[str, Any], cn: int, ek: str) -> dict[str, Any]:
    """Case'in beklenen sonucunu YALNIZ `ek` yapar (aynı tutar önceki metinde geçip denetimi
    atlatmasın); adım beklenenleri tutarsız bir gözleme indirilir."""
    case = out["cases"][cn - 1]
    case["expected_result"] = ek
    for adim in case["steps"]:
        adim["expected"] = "Sepetim sayfası açılır"
    return out


def test_order_amount_qualifying_minimum_rule_is_not_a_threshold(
    tpd1_vaka: dict[str, Any], kaynak: str
) -> None:
    """TEMİZ (canlı tpd-1-son-hal#k1 C9, platform-desktop C10): "125,00 TL'lik sipariş minimum
    tutar şartı aranmadan onaylanır" siparişin tutarıdır (C3 sepeti P-001 × 6, 5 adet ödenir).
    KÖTÜ: eşiğin adı tutara bağlıysa ("125,00 TL'lik minimum sipariş tutarı", "300,00 TL'lik
    sipariş limiti") uydurma eşiktir."""
    temiz = _bekleneni_ekle(_tpd1(), 3, "125,00 TL'lik sipariş minimum tutar şartı aranmadan geçer")
    assert coverage_problems(temiz, tpd1_vaka["expect"], kaynak=kaynak) == []
    kotu = _bekleneni_ekle(_tpd1(), 3, "125,00 TL'lik minimum sipariş tutarı uygulanır")
    assert _uydurma(coverage_problems(kotu, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C3: kaynakta olmayan eşik/limit tutarı '125,00 TL'"
    ]
    kotu = _bekleneni_ekle(_tpd1(), 12, "bayinin 300,00 TL'lik sipariş limiti aşılmaz")
    assert _uydurma(coverage_problems(kotu, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C12: kaynakta olmayan eşik/limit tutarı '300,00 TL'"
    ]


def test_result_of_an_arithmetic_chain_keeps_the_expression_context(
    tpd1_vaka: dict[str, Any], kaynak: str
) -> None:
    """TEMİZ (canlı platform-common C3/C4, f2-kod-hatasi#k1 C4/C6): "ödenecek tutar 5 × 25,00 TL
    = 125,00 TL" — sonuç tutarının bağlamı ifadenin başıdır, "= " değil. KÖTÜ: ifade yabancı bir
    kavramın tutarıysa ("kalan bakiye 4 × 25,00 TL = 100,00 TL") ya da sepet kuramıyorsa
    ("5 × 25,00 TL = 135,00 TL") yakalanır."""
    temiz = _bekleneni_ekle(_tpd1(), 3, "ödenecek tutar 5 × 25,00 TL = 125,00 TL")
    assert coverage_problems(temiz, tpd1_vaka["expect"], kaynak=kaynak) == []
    kotu = _bekleneni_ekle(_tpd1(), 3, "kalan bakiye 4 × 25,00 TL = 100,00 TL")
    assert _uydurma(coverage_problems(kotu, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C3: kaynakta olmayan tutar '100,00 TL' "
        "(sepet/toplam bağlamında değil; yalnız sepet ya da satır toplamı)"
    ]
    kotu = _bekleneni_ekle(_tpd1(), 3, "ödenecek tutar 5 × 25,00 TL = 135,00 TL")
    assert _uydurma(coverage_problems(kotu, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C3: kaynakta olmayan tutar '135,00 TL' (case sepetiyle kurulamıyor)"
    ]


def test_comparison_object_after_a_basket_total_does_not_taint_it(
    tpd1_vaka: dict[str, Any], kaynak: str
) -> None:
    """TEMİZ (canlı case-negative C3): "indirim sonrası toplam (125,00 TL) kredi limitini
    aşmaz" — önceki bağlam sepet toplamıdır; sonraki "kredi limitini" karşılaştırmanın nesnesidir.
    KÖTÜ: önceki bağlam yabancı kavramsa ("kredi bakiyesi (100,00 TL) sepet toplamını
    karşılar") yakalanır."""
    temiz = _bekleneni_ekle(
        _tpd1(), 3, "indirim sonrası toplam (125,00 TL) kredi limitini (2.000,00 TL) aşmaz"
    )
    assert coverage_problems(temiz, tpd1_vaka["expect"], kaynak=kaynak) == []
    kotu = _bekleneni_ekle(_tpd1(), 3, "kredi bakiyesi (100,00 TL) sepet toplamını karşılar")
    assert _uydurma(coverage_problems(kotu, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C3: kaynakta olmayan tutar '100,00 TL' "
        "(sepet/toplam bağlamında değil; yalnız sepet ya da satır toplamı)"
    ]


def test_quoted_amount_is_checked_as_an_amount_not_as_a_message(
    tpd1_vaka: dict[str, Any], kaynak: str
) -> None:
    """TEMİZ (canlı platform-desktop C11): "Toplam '150,00 TL' biçiminde gösterilir" — tırnaklı
    tutar mesaj alıntısı değildir; tutar kuralıyla denetlenir (C3 sepeti 150,00). KÖTÜ: tırnaklı
    uydurma tutar tutar kuralına takılır; tutar içeren uydurma mesaj alıntı kuralına takılır."""
    temiz = _bekleneni_ekle(_tpd1(), 3, "Toplam '150,00 TL' biçiminde gösterilir")
    assert coverage_problems(temiz, tpd1_vaka["expect"], kaynak=kaynak) == []
    kotu = _bekleneni_ekle(_tpd1(), 3, "Toplam '135,00 TL' biçiminde gösterilir")
    assert _uydurma(coverage_problems(kotu, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C3: kaynakta olmayan tutar '135,00 TL' (case sepetiyle kurulamıyor)"
    ]
    kotu = _bekleneni_ekle(_tpd1(), 3, "'Ödenecek: 150,00 TL' mesajı gösterilir")
    assert _uydurma(coverage_problems(kotu, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C3: kaynakta olmayan alıntı 'Ödenecek: 150,00 TL'"
    ]


def _sentetik_sepet(hazirlik: str, sepet: str, beklenen: str) -> dict[str, Any]:
    out = _tpd1()
    case = out["cases"][12]  # C13: kampanyasız, minimum tutarın altı
    case["preconditions"].append(hazirlik)
    case["test_data"] = [
        {"name": "Sepet", "value": sepet, "class": None, "synthetic": True},
    ]
    for adim in case["steps"]:
        if adim.get("data") and "P-" in adim["data"]:
            adim["data"] = None
    case["expected_result"] = beklenen
    return out


@pytest.mark.parametrize(
    ("hazirlik", "sepet"),
    [
        # Kod fiyattan sonra (canlı serbest-son-hal#k1 C4).
        (
            "Test verisi hazırlığı: fiyatı 749,99 TL olan sentetik ürün SENT-749 hazırlanır",
            "SENT-749 × 1; P-003 × 1",
        ),
        # "olan"dan sonra virgüllü niteleyici (canlı tpd-1-f2-kod-hatasi#k2 C10, 2026-11-14).
        (
            "Test verisi hazırlığı: fiyatı 749,99 TL olan, kampanyası olmayan sentetik ürün "
            "SENT-749 hazırlanır",
            "SENT-749 × 1; P-003 × 1",
        ),
        # Kod biçimi dışı ad / kodsuz sentetik ürün (canlı serbest-son-hal#k2 C4, #k3 C6).
        (
            "Test verisi hazırlığı: fiyatı 749,99 TL olan sentetik ürün (SENTETIK-1) hazırlanır",
            "SENTETIK-1 × 1; P-003 × 1",
        ),
        (
            "Test verisi hazırlığı: fiyatı 749,99 TL olan kampanyasız sentetik ürün hazırlanır",
            "Sentetik ürün × 1; P-003 × 1",
        ),
    ],
)
def test_basket_with_a_prepared_synthetic_product_is_recomputed(
    tpd1_vaka: dict[str, Any], kaynak: str, hazirlik: str, sepet: str
) -> None:
    """TEMİZ: hazırlıktaki sentetik ürün (749,99) + P-003 (8,00) = 757,99 TL. KÖTÜ: aynı sepetle
    kurulamayan toplam (758,99) ve sepet bağlamı dışındaki alt toplam yakalanır."""
    temiz = _sentetik_sepet(hazirlik, sepet, "Toplam 757,99 TL; P-003 çıkınca toplam 749,99 TL")
    assert coverage_problems(temiz, tpd1_vaka["expect"], kaynak=kaynak) == []
    kotu = _sentetik_sepet(hazirlik, sepet, "Toplam 758,99 TL")
    assert _uydurma(coverage_problems(kotu, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C13: kaynakta olmayan tutar '758,99 TL' (case sepetiyle kurulamıyor)"
    ]
    # Kodlu sentetik ürünle 757,99 sepetin gerçek toplamıdır (her bağlamda kabul, #4d); kodsuz
    # üründe yalnız sepet bağlamında kabul edilir.
    if "SENT-749" not in sepet:
        kotu = _sentetik_sepet(hazirlik, sepet, "Kalan bakiye 757,99 TL")
        assert _uydurma(coverage_problems(kotu, tpd1_vaka["expect"], kaynak=kaynak))


def test_difference_of_grounded_amounts_next_to_a_threshold_is_accepted(
    tpd1_vaka: dict[str, Any], kaynak: str
) -> None:
    """TEMİZ (canlı platform-mobile C7): hazırlıkta 2.000,01 TL'lik sentetik ürün; "limiti 0,01
    TL aşan sipariş" = 2.000,01 − 2.000,00 (kaynak). KÖTÜ: farkı kaynağa dayanmayan tutar
    ("limitini 0,01 TL aşar", sentetik ürün yok) ve eşik adı olmadan "altında" denen tutar fark
    sayılmaz."""
    out = _tpd1()
    case = out["cases"][7]  # C8: sepeti hazırlıktaki sentetik ürünle değiştir
    case["test_data"] = [v for v in case["test_data"] if "P-" not in v["value"]]
    for adim in case["steps"]:
        adim["data"] = None
    case["preconditions"].append(
        "Test verisi hazırlığı: fiyatı 2.000,01 TL olan sentetik ürün hazırlanır"
    )
    case["expected_result"] = "Limiti 0,01 TL aşan sipariş 'Kredi limiti aşıldı' uyarısı alır"
    assert coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak) == []
    kotu = _bekleneni_ekle(_tpd1(), 12, "tutar kredi limitini 0,01 TL aşar")
    assert _uydurma(coverage_problems(kotu, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C12: kaynakta olmayan tutar '0,01 TL' (case sepetiyle kurulamıyor)"
    ]
    kotu = _bekleneni_ekle(_tpd1(), 3, "sepet 725,00 TL altında kalır")
    assert _uydurma(coverage_problems(kotu, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C3: kaynakta olmayan tutar '725,00 TL' (case sepetiyle kurulamıyor)"
    ]


def test_changed_threshold_in_preparation_is_still_caught(
    tpd1_vaka: dict[str, Any], kaynak: str
) -> None:
    """KÖTÜ (canlı platform-data C7, düzeltilmedi): hazırlıkta eşiği değiştirmek ("kredi limiti
    499,99 TL yapılır") kaynak sayılmaz; değiştirilmiş eşik beklenen sonuçta uydurmadır."""
    out = _tpd1()
    case = out["cases"][11]
    case["preconditions"].append(
        "Test verisi hazırlığı: bayi2'nin kredi limiti geçici olarak 499,99 TL yapılır"
    )
    case["expected_result"] += "; 500,00 TL sipariş, 499,99 TL limiti aştığı için reddedilir"
    assert _uydurma(coverage_problems(out, tpd1_vaka["expect"], kaynak=kaynak)) == [
        "C12: kaynakta olmayan tutar '499,99 TL' (case sepetiyle kurulamıyor)"
    ]


def test_subtotal_grounded_in_cart_context_may_repeat_in_the_same_case(kaynak: str) -> None:
    """TEMİZ (canlı tpd-1-son-hal#k3 C7, 2026-11-14): P-001 × 6 (bedava 1) ödenen alt toplam
    125,00 TL bir adımda sepet bağlamında kabul edildi; aynı case'in başka metninde bağlamsız
    yinelenmesi uydurma değildir (metin sırası fark etmez). KÖTÜ: başka case'te ya da yabancı
    kavram bağlamında ("kalan bakiye") yineleme yine yakalanır."""
    sepet = {"C1": [(2500, 6)], "C2": [(2500, 6)]}
    temiz = [
        ("C1", "125,00 TL 750,00 TL altında olsa da uyarı yoktur"),
        ("C1", "1 adet bedava; sepet toplamı 125,00 TL'dir"),
    ]
    assert source_problems(temiz, kaynak, sepetler=sepet) == []
    kotu = [("C1", "1 adet bedava; sepet toplamı 125,00 TL'dir"), ("C2", "125,00 TL görünür")]
    assert source_problems(kotu, kaynak, sepetler=sepet)
    kotu = [("C1", "sepet toplamı 125,00 TL"), ("C1", "kalan bakiye 125,00 TL")]
    assert source_problems(kotu, kaynak, sepetler=sepet)
