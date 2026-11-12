"""Olgu doğrulama ve tablo karşılaştırması (012 §4.3 adım 3–4) — saf, DB'siz."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from tp_core.features.oracle import dogrulama as d

from .tpd1 import OLGULAR, T1, T2, tablo_id, tpd1_cases

TABLOLAR = [d.Tablo(tablo_id(1), "T1", T1["ad"], T1), d.Tablo(tablo_id(2), "T2", T2["ad"], T2)]


def _case(**over: Any) -> dict[str, Any]:
    case = {
        "title": "Kampanya",
        "type": "positive",
        "risk": "high",
        "acceptance_criteria_refs": ["AC2"],
        "preconditions": ["Sepet boş", "Sepette kampanyalı ürün yok"],
        "steps": [
            {"id": "S1", "action": "Sepete ekle", "data": "P-001 × 7", "expected": "Sayaç 7"},
            {
                "id": "S2",
                "action": "Sepete git",
                "data": None,
                "expected": "ara toplam 1.250,00 TL, indirim −25,00 TL, toplam 150 TL",
            },
        ],
        "expected_result": "Toplam 150 TL",
        "tags": ["AI-generated"],
    }
    case.update(over)
    return case


def _o(column: str, value: Any, field: str, quote: str) -> dict[str, Any]:
    return {"column": column, "value": value, "field": field, "quote": quote}


def _grup(inputs: list, expected: list, ref: str = "T1") -> dict[str, Any]:
    return {"groups": [{"table_ref": ref, "inputs": inputs, "expected": expected}]}


# ------------------------------------------------------------------ alan ve alıntı


@pytest.mark.parametrize(
    ("yol", "beklenen"),
    [
        ("title", "Kampanya"),
        ("expected_result", "Toplam 150 TL"),
        ("preconditions[1]", "Sepette kampanyalı ürün yok"),
        ("steps[0].data", "P-001 × 7"),
        ("steps[1].expected", "ara toplam 1.250,00 TL, indirim −25,00 TL, toplam 150 TL"),
        ("steps[1].data", None),  # null alan metin değil
        ("steps[5].expected", None),  # olmayan adım
        ("preconditions[9]", None),
        ("steps[0].id", None),  # izinli alan değil
        ("tags", None),
        ("steps.0.data", None),
        (None, None),
    ],
)
def test_alan_yolu(yol: Any, beklenen: str | None) -> None:
    assert d.alan_coz(_case(), yol) == beklenen


@pytest.mark.parametrize(
    ("alan", "alinti", "gecer"),
    [
        ("P-001 × 7", "7", True),
        ("P-001 × 17", "7", False),  # rakama bitişik
        ("P-001 × 7", "1", False),  # P-001'in içinde
        ("ara toplam 125,00 TL", "25,00 TL", False),
        ("indirim −25,00 TL", "25,00 TL", False),  # işaret düşmüş
        ("indirim −25,00 TL", "−25,00 TL", True),
        ("toplam 1.250,00 TL", "250,00 TL", False),
        ("butonu pasiftir", "butonu pasif", False),  # sözcük ortası
        ("butonu pasiftir.", "butonu pasiftir", True),
        ("Toplam 150 TL", "150 TL", True),
        ("Toplam 150 TL", "  ", False),
        ("Toplam 150 TL", "Toplam 160 TL", False),
    ],
)
def test_alinti_birebir_ve_sinirda(alan: str, alinti: str, gecer: bool) -> None:
    assert d.alinti_geciyor_mu(alan, alinti) is gecer


@pytest.mark.parametrize(
    ("alinti", "deger", "kabul"),
    [
        ("1.250,00 TL", "1250.00", True),
        ("1.250,00 TL", 1250, True),
        ("1.250,00 TL", "1.250,00 TL", True),
        ("1.250,00 TL", "1250.01", False),
        ("−25,00 TL", "-25.00", True),
        ("−25,00 TL", "25.00", False),
        ("150 TL", "150", True),
        ("150 TL", 150.0, True),
        ("150 TL", True, False),  # bool sayı değil
        ("adet 1", "1", True),
        ("P-004", "4", False),  # tek sayı değil
        ("indirim 25,00 TL", "25", False),  # uzun önek: sayı metni değil
    ],
)
def test_sayi_kurali(alinti: str, deger: Any, kabul: bool) -> None:
    okunan, neden = d.deger_oku("sayi", alinti, deger)
    assert (neden is None) is kabul, neden
    if kabul:
        assert isinstance(okunan, Decimal)


@pytest.mark.parametrize(
    ("alinti", "deger", "kabul"),
    [
        ("Sepette kampanyalı ürün yok", False, True),
        ("Sepette kampanyalı ürün yok", True, False),
        ("uyarısı görünür", True, True),
        ("uyarısı görünmez", False, True),
        ("butonu pasiftir", False, True),
        ("butonu aktiftir", True, True),
        ("sipariş onaylanamaz", False, True),
        ('P-001 "6 al 1 bedava" kampanyasında', True, True),
        ("uyarı yok değil", False, False),  # çifte olumsuzluk: belirsiz
        ("uyarı yok değil", True, False),
        ("uyarısı görünür", "dogru", False),  # metin değer kabul edilmez
    ],
)
def test_mantiksal_kural(alinti: str, deger: Any, kabul: bool) -> None:
    _, neden = d.deger_oku("mantiksal", alinti, deger)
    assert (neden is None) is kabul, neden


@pytest.mark.parametrize(
    ("alinti", "deger", "kabul"),
    [
        ('"Kredi limiti aşıldı"', "Kredi limiti aşıldı", True),
        ("Kredi  limiti aşıldı", "Kredi limiti aşıldı", True),  # boşluk daraltma
        ("Kredi limiti aşıldı", "kredi limiti aşıldı", False),  # büyük/küçük harf
        ("Kredi limiti", "Kredi limiti aşıldı", False),
        ("7", 7, False),
    ],
)
def test_metin_kurali(alinti: str, deger: Any, kabul: bool) -> None:
    _, neden = d.deger_oku("metin", alinti, deger)
    assert (neden is None) is kabul, neden


# ------------------------------------------------------------------ değerlendirme


def _kampanya_case(toplam: str = "150,00 TL") -> dict[str, Any]:
    return tpd1_cases()[1] | {
        "steps": [
            *tpd1_cases()[1]["steps"][:3],
            {
                "id": "S4",
                "action": "Üst menüden sepete git",
                "data": None,
                "expected": "P-001 satırında adet 7, bedava adet 1; ara toplam 175,00 TL, "
                f"indirim 25,00 TL, toplam {toplam}",
            },
        ]
    }


def _kampanya_olgulari(toplam: str = "150,00 TL", toplam_deger: str = "150.00") -> dict:
    s4 = "steps[3].expected"
    return _grup(
        [_o("adet", "7", "steps[2].data", "7"), _o("ara_toplam", "175.00", s4, "175,00 TL")],
        [
            _o("bedava_adet", "1", s4, "adet 1"),
            _o("indirim", "25.00", s4, "25,00 TL"),
            _o("toplam", toplam_deger, s4, toplam),
        ],
    )


def test_uyumlu_tpd1_golden_olgulari() -> None:
    cases = tpd1_cases()
    for n, groups in OLGULAR.items():
        sonuc, ayr = d.degerlendir(cases[n - 1], TABLOLAR, {"groups": groups})
        assert sonuc == d.UYUMLU, n
        assert ayr["atilan_olgular"] == 0
        assert set(ayr) == {"gruplar", "atilan_olgular"}
        g = ayr["gruplar"][0]
        assert set(g) == {
            "tablo_id",
            "tablo_ad",
            "satir_id",
            "girdiler",
            "karsilastirmalar",
            "durum",
            "neden",
        }
        assert g["satir_id"] is not None and g["durum"] == "uyumlu"
        for k in g["karsilastirmalar"]:
            assert set(k) == {"column", "alan", "alinti", "case_degeri", "tablo_degeri", "uyumlu"}


def test_uyumsuz_tek_karsilastirma_yeter() -> None:
    case = _kampanya_case("175,00 TL")
    sonuc, ayr = d.degerlendir(case, TABLOLAR, _kampanya_olgulari("175,00 TL", "175.00"))
    assert sonuc == d.UYUMSUZ
    g = ayr["gruplar"][0]
    assert g["durum"] == "uyumsuz" and g["satir_id"] == "R1"
    bozuk = [k for k in g["karsilastirmalar"] if not k["uyumlu"]]
    assert bozuk == [
        {
            "column": "toplam",
            "alan": "steps[3].expected",
            "alinti": "175,00 TL",
            "case_degeri": "175.00",
            "tablo_degeri": "150.00",
            "uyumlu": False,
        }
    ]
    assert "uyuşmuyor" in d.ozet(sonuc, ayr)


def test_tolerans_icinde_uyumlu_disinda_uyumsuz() -> None:
    sonuc, _ = d.degerlendir(
        _kampanya_case("150,01 TL"), TABLOLAR, _kampanya_olgulari("150,01 TL", "150.01")
    )
    assert sonuc == d.UYUMLU  # toplam toleransı 0.01
    sonuc, _ = d.degerlendir(
        _kampanya_case("150,02 TL"), TABLOLAR, _kampanya_olgulari("150,02 TL", "150.02")
    )
    assert sonuc == d.UYUMSUZ
    # bedava_adet toleranssız: 1 yerine 2 yazılırsa uyumsuz
    case = _kampanya_case()
    case["steps"][3]["expected"] = case["steps"][3]["expected"].replace(
        "bedava adet 1", "bedava adet 2"
    )
    olgu = _kampanya_olgulari()
    olgu["groups"][0]["expected"][0] = _o("bedava_adet", "2", "steps[3].expected", "adet 2")
    assert d.degerlendir(case, TABLOLAR, olgu)[0] == d.UYUMSUZ


def test_kapsam_disi_modele_bakilmaz() -> None:
    sonuc, ayr = d.degerlendir(_kampanya_case(), [], _kampanya_olgulari())
    assert sonuc == d.KAPSAM_DISI and ayr == {"gruplar": [], "atilan_olgular": 0}


def test_kontrol_edilemedi_bos_cikti_ve_none() -> None:
    for cikti in ({"groups": []}, None, {}):
        sonuc, ayr = d.degerlendir(_kampanya_case(), TABLOLAR, cikti)
        assert sonuc == d.KONTROL_EDILEMEDI and ayr["gruplar"] == []
    assert "çıkarılamadı" in d.ozet(d.KONTROL_EDILEMEDI, {"gruplar": []})


def test_tutmayan_olgular_atilir_ve_sayilir() -> None:
    s4 = "steps[3].expected"
    olgu = _grup(
        [
            _o("adet", "7", "steps[2].data", "7"),
            _o("ara_toplam", "175.00", "steps[1].expected", "175,00 TL"),  # yanlış alan
        ],
        [
            _o("indirim", "30.00", s4, "25,00 TL"),  # değer alıntıya eşit değil
            _o("toplam", "150.00", s4, "150,00TL"),  # alıntı birebir değil
            _o("kdv", "1", s4, "adet 1"),  # bilinmeyen kolon
            _o("adet", "7", s4, "adet 7"),  # girdi kolonu beklenende
        ],
    )
    sonuc, ayr = d.degerlendir(_kampanya_case(), TABLOLAR, olgu)
    assert ayr["atilan_olgular"] == 5
    g = ayr["gruplar"][0]
    assert g["durum"] == "cikarilamadi" and "ara_toplam" in g["neden"]  # girdi eksik
    assert sonuc == d.KONTROL_EDILEMEDI


def test_bilinmeyen_tablo_grubu_atilir() -> None:
    olgu = _kampanya_olgulari()
    olgu["groups"][0]["table_ref"] = "T9"
    sonuc, ayr = d.degerlendir(_kampanya_case(), TABLOLAR, olgu)
    assert sonuc == d.KONTROL_EDILEMEDI
    assert ayr == {"gruplar": [], "atilan_olgular": 5}
    # Tablo kimliğiyle (uuid) atıf da kabul edilir.
    olgu["groups"][0]["table_ref"] = tablo_id(1)
    assert d.degerlendir(_kampanya_case(), TABLOLAR, olgu)[0] == d.UYUMLU


def test_celiskili_girdi_cikarilamadi() -> None:
    olgu = _kampanya_olgulari()
    olgu["groups"][0]["inputs"].append(_o("adet", "1", "steps[3].expected", "adet 1"))
    sonuc, ayr = d.degerlendir(_kampanya_case(), TABLOLAR, olgu)
    assert sonuc == d.KONTROL_EDILEMEDI
    assert ayr["gruplar"][0]["durum"] == "cikarilamadi"
    assert "çelişkili" in ayr["gruplar"][0]["neden"]


def test_satir_yok_ve_hata_kontrol_edilemedi() -> None:
    case = _kampanya_case()
    case["steps"][2]["data"] = "P-001 × 0"
    olgu = _kampanya_olgulari()
    olgu["groups"][0]["inputs"][0] = _o("adet", "0", "steps[2].data", "0")
    sonuc, ayr = d.degerlendir(case, TABLOLAR, olgu)  # R1 koşulu adet >= 1
    assert sonuc == d.KONTROL_EDILEMEDI and ayr["gruplar"][0]["durum"] == "satir_yok"
    bolen = {**T1, "satirlar": [{**T1["satirlar"][0], "kosul": "adet >= 0"}]}
    sonuc, ayr = d.degerlendir(case, [d.Tablo("x", "T1", "k", bolen)], olgu)
    assert sonuc == d.KONTROL_EDILEMEDI and ayr["gruplar"][0]["durum"] == "hata"


def test_beklenen_yoksa_karsilastirma_yok() -> None:
    olgu = _kampanya_olgulari()
    olgu["groups"][0]["expected"] = []
    sonuc, ayr = d.degerlendir(_kampanya_case(), TABLOLAR, olgu)
    assert sonuc == d.KONTROL_EDILEMEDI and ayr["gruplar"][0]["durum"] == "karsilastirma_yok"


def test_bir_grup_uyumsuz_digeri_uyumlu_genel_uyumsuz() -> None:
    case = _kampanya_case()
    iyi = _kampanya_olgulari()["groups"][0]
    kotu = {
        **iyi,
        "expected": [_o("indirim", "25.00", "steps[3].expected", "25,00 TL")],
        "inputs": [
            _o("adet", "7", "steps[2].data", "7"),
            _o("ara_toplam", "150.00", "expected_result", "150,00 TL"),  # 150/7 ≠ 25
        ],
    }
    sonuc, ayr = d.degerlendir(case, TABLOLAR, {"groups": [iyi, kotu]})
    assert [g["durum"] for g in ayr["gruplar"]] == ["uyumlu", "uyumsuz"]
    assert sonuc == d.UYUMSUZ


def test_mantiksal_tablo_degerlendirmesi() -> None:
    case = tpd1_cases()[4]  # C5: kampanyasız, 150 TL → uyarı görünür, onay pasif
    sonuc, ayr = d.degerlendir(case, TABLOLAR, {"groups": OLGULAR[5]})
    assert sonuc == d.UYUMLU
    assert ayr["gruplar"][0]["satir_id"] == "R2"
    degerler = {k["column"]: k["case_degeri"] for k in ayr["gruplar"][0]["karsilastirmalar"]}
    assert degerler == {"minimum_uyarisi": True, "onay_aktif": False}
