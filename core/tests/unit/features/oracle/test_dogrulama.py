"""Olgu doğrulama ve tablo karşılaştırması (012 §4.3 adım 3–4) — saf, DB'siz."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from tp_core.features.oracle import dogrulama as d

from . import tpd1
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
        "verification_point": "Sepet satırı doğrulanır",
        "teardown": "Sepeti boşalt",
        "test_data": [{"name": "adet", "value": 7}, {"name": "urun", "value": "P-001"}],
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
        ("verification_point", "Sepet satırı doğrulanır"),  # v3 (V12)
        ("teardown", "Sepeti boşalt"),
        ("test_data[0].value", "7"),  # sayı değer metne çevrilir
        ("test_data[1].value", "P-001"),
        ("test_data[2].value", None),
        ("test_data[0].name", None),
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
        ("7 adette 1 adet bedava", "7", True),  # alanın başında (birleştirme düzeltmesi)
        ("7 adette", "adette", True),
        ("−7 adet", "7", False),  # işaret düşmüş
        ("toplam 150", "150", True),  # alanın sonunda
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
        # Review 1 K4: -mAmAlI, -mAyAcAk ekleri, anlamca olumsuz kökler, tırnaklı arayüz metni.
        ("uyarı görünmemeli", False, True),
        ("uyarı görünmemeli", True, False),
        ("uyarı görünmeyecektir", False, True),
        ("uyarı kaybolur", False, True),
        ("uyarı kaybolur", True, False),
        ("uyarı gizlenir", False, True),
        ('"Sipariş verilemez" uyarısı görünür', True, True),
        ('"Sipariş verilemez" uyarısı görünür', False, False),
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


# ------------------------------------------------------------------ cümlecik kutbu (K4)

UYARI = '"Minimum sipariş tutarı 750,00 TL" uyarısı'


@pytest.mark.parametrize(
    ("alan", "alinti", "kutup"),
    [
        # Alıntı olumsuzluğu dışarıda bırakacak biçimde kırpılamaz.
        (f"Toplam 150,00 TL; {UYARI} görünmez", UYARI, None),
        (f"Toplam 150,00 TL; {UYARI} görünmez", f"{UYARI} görünmez", False),
        # Bağlaçtan sonraki cümlecik ("ve … pasiftir") alıntının kutbuna girmez.
        (
            f'Toplam 150,00 TL; {UYARI} görünür ve "Siparişi onayla" butonu pasiftir',
            f"{UYARI} görünür",
            True,
        ),
        (f'{UYARI} görünür ve "Siparişi onayla" butonu pasiftir', "butonu pasiftir", False),
        # Yan cümle ("… olsa da") ayrı cümleciktir.
        (
            "Kampanyalı sepette toplam 150,00 TL olsa da minimum sipariş uyarısı gösterilmez",
            "Kampanyalı sepette",
            True,
        ),
        (
            "Kampanyalı sepette toplam 150,00 TL olsa da minimum sipariş uyarısı gösterilmez",
            "minimum sipariş uyarısı gösterilmez",
            False,
        ),
        (
            "Toplam 750,00 TL olduğunda uyarı gösterilmez ve sipariş onaylanabilir",
            "uyarı gösterilmez",
            False,
        ),
        ("Sepet 900 TL iken uyarı görünmez", "Sepet 900 TL", True),
        ("uyarı görünmemeli", "uyarı", None),
        ('"Sipariş verilemez" uyarısı görünür', "uyarısı görünür", True),
        ("Uyarı görünür, buton pasif değil", "Uyarı görünür", True),
        ("uyarı görünür ya da kaybolur", "uyarı görünür", True),
        # Ondalık virgül cümlecik sınırı değildir.
        ("Toplam 750,00 TL uyarı yok", "Toplam 750", None),
    ],
)
def test_cumlecik_kutbu(alan: str, alinti: str, kutup: bool | None) -> None:
    k, neden = d.cumlecik_kutbu(alan, alinti)
    assert k is kutup, neden
    assert (neden is None) is (kutup is not None)


def test_kirpilmis_olumsuz_alinti_olgusu_reddedilir() -> None:
    """Review 1 K4 karşı örneği: alan `… uyarısı görünmez`, alıntı `"…" uyarısı`, değer true →
    olgu atılır; tablo true dese de `uyumlu` denmez."""
    case = tpd1.ana_yol_cases()[4]  # C5
    case = {**case, "expected_result": f"{UYARI} görünmez"}
    olgu = _grup(
        [_o("kampanyali_sepet", False, "preconditions[1]", "Sepette kampanyalı ürün yok")],
        [_o("minimum_uyarisi", True, "expected_result", UYARI)],
        "T2",
    )
    olgu["groups"][0]["inputs"].append(_o("sepet_tutari", "150.00", S4, "150,00 TL"))
    sonuc, ayr = d.degerlendir(case, TABLOLAR[1:], olgu)
    assert ayr["atilan_olgular"] == 1
    assert sonuc != d.UYUMLU


# ------------------------------------------------------------------ değerlendirme

S4 = "steps[3].expected"


def _kampanya_case(
    indirim: str = "25,00 TL", ara: str = "175,00 TL", toplam: str = "150,00 TL"
) -> dict[str, Any]:
    """TPD-1 C2'nin sade hali: sayılar yalnız S3 verisinde ve S4 beklenende (tamlık için)."""
    c = tpd1_cases()[1]
    return c | {
        "steps": [
            *c["steps"][:2],
            {**c["steps"][2], "expected": "Ürün sepete eklenir"},
            {
                "id": "S4",
                "action": "Üst menüden sepete git",
                "data": None,
                "expected": (
                    f"P-001 satırında adet 7, bedava adet 1; ara toplam {ara}, "
                    f"indirim {indirim}, toplam {toplam}"
                ),
            },
        ],
        "expected_result": "Kampanya indirimi uygulanır",
    }


def _kampanya_olgulari(
    indirim: str = "25,00 TL",
    indirim_deger: str = "25.00",
    ara: str = "175,00 TL",
    toplam: str = "150,00 TL",
) -> dict:
    return _grup(
        [
            _o("adet", "7", "steps[2].data", "7"),
            _o("adet", "7", S4, "7"),
            _o("ara_toplam", ara.split()[0].replace(",", "."), S4, ara),
        ],
        [
            _o("bedava_adet", "1", S4, "adet 1"),
            _o("indirim", indirim_deger, S4, indirim),
            _o("toplam", toplam.split()[0].replace(",", "."), S4, toplam),
        ],
    )


GRUP_ALANLARI = {
    "tablo_id",
    "tablo_ad",
    "satir_id",
    "girdiler",
    "karsilastirmalar",
    "karsilastirilamayan",
    "durum",
    "neden",
}
AYRINTI_ALANLARI = {
    "gruplar",
    "atilan_olgular",
    "degerler",
    "kapsanmayan_sayilar",
    "yok_sayilan",
    "degerlendirilmeyen_tablolar",
}


def test_tablolar_s1_taslak_goldenindan() -> None:
    """Oracle şeridinin TPD-1 tabloları Ş1 taslağıyla birebir aynı (kopya yok); V9 T1."""
    assert T1["ac_refs"] == ["AC2"]
    assert [k["ad"] for k in T1["girdiler"]] == ["adet", "ara_toplam"]
    assert [k["ad"] for k in T1["ciktilar"]] == ["bedava_adet", "indirim", "toplam"]
    assert T1["satirlar"][0]["cikti"]["bedava_adet"] == "adet // 7"
    assert T1["satirlar"][0]["cikti"]["indirim"] == "yuvarla(ara_toplam / adet * (adet // 7), 2)"
    assert T1["satirlar"][1]["cikti"]["toplam"] == "ara_toplam"
    assert T2["ac_refs"] == ["AC3", "AC6"]
    assert [k["ad"] for k in T2["girdiler"]] == ["kampanyali_sepet", "sepet_tutari"]
    assert [k["ad"] for k in T2["ciktilar"]] == ["minimum_uyarisi"]
    assert T2["satirlar"][1]["kosul"] == "sepet_tutari < 750"


@pytest.mark.parametrize(("n", "senaryo"), [*((n, None) for n in OLGULAR), (3, tpd1.SENARYO)])
def test_tpd1_golden_olgulari_story_tablolariyla(n: int, senaryo: str | None) -> None:
    case = tpd1_cases(senaryo)[n - 1]
    cikti = tpd1.SENARYO_OLGULARI[n] if senaryo else OLGULAR[n]
    kapsayan = [
        t for t in TABLOLAR if set(t.icerik["ac_refs"]) & set(case["acceptance_criteria_refs"])
    ]
    sonuc, ayr = d.degerlendir(case, kapsayan, cikti)
    beklenen = tpd1.BEKLENEN_SONUC_ANA_YOL if senaryo else tpd1.BEKLENEN_SONUC_FIX_DOC
    assert sonuc == beklenen[n]
    assert ayr["atilan_olgular"] == 0 and ayr["kapsanmayan_sayilar"] == []
    assert set(ayr) == AYRINTI_ALANLARI
    assert ayr["degerler"]["karsilastirilamayan"] == 0
    g = ayr["gruplar"][0]
    assert set(g) == GRUP_ALANLARI
    assert g["satir_id"] is not None and g["durum"] == sonuc
    for k in g["karsilastirmalar"]:
        assert set(k) == {"column", "alan", "alinti", "case_degeri", "tablo_degeri", "uyumlu"}


def test_c2_ara_toplamla_tum_degerler_karsilastirilir() -> None:
    """V9: case ara toplamı yazar; 7 adette indirim ve toplam da karşılaştırılır."""
    sonuc, ayr = d.degerlendir(tpd1_cases()[1], TABLOLAR[:1], OLGULAR[2])
    g = ayr["gruplar"][0]
    assert sonuc == d.UYUMLU and g["satir_id"] == "R1" and g["karsilastirilamayan"] == []
    assert {(k["column"], k["case_degeri"], k["tablo_degeri"]) for k in g["karsilastirmalar"]} == {
        ("bedava_adet", "1", "1"),
        ("indirim", "25.00", "25.00"),
        ("toplam", "150.00", "150.00"),
    }
    assert ayr["degerler"] == {
        "uyumlu": 7,
        "uyumsuz": 0,
        "karsilastirilamayan": 0,
        "atilan": 0,
        "kapsanmayan": 0,
    }
    assert "7 beklenen değer" in d.ozet(sonuc, ayr)


def test_c3_ana_yol_uyumlu_fix_doc_uyumsuz() -> None:
    """Demo ana yolu C3 (6 adette bedava yok) tabloyla aynı; koda uyarlanmış C3 uyuşmaz."""
    ana = tpd1.ana_yol_cases()[2]
    sonuc, ayr = d.degerlendir(ana, TABLOLAR[:1], tpd1.SENARYO_OLGULARI[3])
    assert sonuc == d.UYUMLU and ayr["gruplar"][0]["satir_id"] == "R2"
    assert {
        (k["column"], k["case_degeri"], k["tablo_degeri"])
        for k in ayr["gruplar"][0]["karsilastirmalar"]
    } == {("bedava_adet", "0", "0"), ("indirim", "0.00", "0"), ("toplam", "150.00", "150.00")}
    assert ayr["yok_sayilan"] == [
        {
            "alan": "expected_result",
            "alinti": "7. adette",
            "neden": "kuralın açıklaması (sıra sayısı); tabloda kolonu yok",
        }
    ]
    sonuc, ayr = d.degerlendir(tpd1_cases()[2], TABLOLAR[:1], OLGULAR[3])
    assert sonuc == d.UYUMSUZ
    assert "bedava_adet" in d.ozet(sonuc, ayr)


def test_tam_karsilastirma() -> None:
    sonuc, ayr = d.degerlendir(_kampanya_case(), TABLOLAR[:1], _kampanya_olgulari())
    g = ayr["gruplar"][0]
    assert sonuc == d.UYUMLU and g["karsilastirilamayan"] == []
    assert {k["column"] for k in g["karsilastirmalar"]} == {"bedava_adet", "indirim", "toplam"}
    # Kapsayan ama hiç grubu olmayan tablo (T2) eksik sayılır: kısmen.
    sonuc, ayr = d.degerlendir(_kampanya_case(), TABLOLAR, _kampanya_olgulari())
    assert sonuc == d.KISMEN and ayr["degerlendirilmeyen_tablolar"] == ["T2"]
    assert "T2 için değer çıkarılmadı" in d.ozet(sonuc, ayr)


def test_uyumsuz_tek_karsilastirma_yeter() -> None:
    case = _kampanya_case("30,00 TL")
    sonuc, ayr = d.degerlendir(case, TABLOLAR[:1], _kampanya_olgulari("30,00 TL", "30.00"))
    assert sonuc == d.UYUMSUZ
    g = ayr["gruplar"][0]
    assert g["durum"] == "uyumsuz" and g["satir_id"] == "R1"
    bozuk = [k for k in g["karsilastirmalar"] if not k["uyumlu"]]
    assert bozuk == [
        {
            "column": "indirim",
            "alan": S4,
            "alinti": "30,00 TL",
            "case_degeri": "30.00",
            "tablo_degeri": "25.00",
            "uyumlu": False,
        }
    ]
    assert ayr["degerler"]["uyumsuz"] == 1
    assert "uyuşmuyor" in d.ozet(sonuc, ayr)


def test_tolerans_icinde_uyumlu_disinda_uyumsuz() -> None:
    sonuc, _ = d.degerlendir(
        _kampanya_case("25,01 TL"), TABLOLAR[:1], _kampanya_olgulari("25,01 TL", "25.01")
    )
    assert sonuc == d.UYUMLU  # indirim toleransı 0.01
    sonuc, _ = d.degerlendir(
        _kampanya_case("25,02 TL"), TABLOLAR[:1], _kampanya_olgulari("25,02 TL", "25.02")
    )
    assert sonuc == d.UYUMSUZ
    # bedava_adet toleranssız: 1 yerine 2 yazılırsa uyumsuz
    case = _kampanya_case()
    case["steps"][3]["expected"] = case["steps"][3]["expected"].replace(
        "bedava adet 1", "bedava adet 2"
    )
    olgu = _kampanya_olgulari()
    olgu["groups"][0]["expected"][0] = _o("bedava_adet", "2", S4, "adet 2")
    assert d.degerlendir(case, TABLOLAR[:1], olgu)[0] == d.UYUMSUZ


def test_kapsam_disi_modele_bakilmaz() -> None:
    sonuc, ayr = d.degerlendir(_kampanya_case(), [], _kampanya_olgulari())
    assert sonuc == d.KAPSAM_DISI and ayr["gruplar"] == [] and ayr["atilan_olgular"] == 0
    assert set(ayr) == AYRINTI_ALANLARI and ayr["kapsanmayan_sayilar"] == []


def test_kontrol_edilemedi_bos_cikti_ve_none() -> None:
    for cikti in ({"groups": []}, None, {}):
        sonuc, ayr = d.degerlendir(_kampanya_case(), TABLOLAR, cikti)
        assert sonuc == d.KONTROL_EDILEMEDI and ayr["gruplar"] == []
        # Olgu yokken beklenen alandaki sayılar kapsanmamış sayılır (S4: 7, 1, 175, 25, 150).
        assert ayr["degerler"]["kapsanmayan"] == 5
    assert "çıkarılamadı" in d.ozet(d.KONTROL_EDILEMEDI, {"gruplar": []})


def test_tutmayan_olgular_atilir_ve_sayilir() -> None:
    olgu = _grup(
        [
            _o("adet", "7", "steps[2].data", "7"),
            _o("ara_toplam", "175.00", "steps[1].expected", "175,00 TL"),  # yanlış alan
        ],
        [
            _o("indirim", "25.00", S4, "25,00 TL"),  # geçerli; ara toplamsız hesaplanamaz
            _o("indirim", "30.00", S4, "25,00 TL"),  # değer alıntıya eşit değil
            _o("indirim", "25.00", S4, "25,00TL"),  # alıntı birebir değil
            _o("kdv", "1", S4, "adet 1"),  # bilinmeyen kolon
            _o("adet", "7", S4, "adet 7"),  # girdi kolonu beklenende
        ],
    )
    sonuc, ayr = d.degerlendir(_kampanya_case(), TABLOLAR[:1], olgu)
    assert ayr["atilan_olgular"] == 5 and ayr["degerler"]["atilan"] == 5
    g = ayr["gruplar"][0]
    assert g["durum"] == "cikarilamadi" and "ara_toplam" in g["neden"]
    assert [o["column"] for o in g["karsilastirilamayan"]] == ["indirim"]
    assert sonuc == d.KONTROL_EDILEMEDI


def test_bilinmeyen_tablo_grubu_atilir() -> None:
    olgu = _kampanya_olgulari()
    olgu["groups"][0]["table_ref"] = "T9"
    sonuc, ayr = d.degerlendir(_kampanya_case(), TABLOLAR[:1], olgu)
    assert sonuc == d.KONTROL_EDILEMEDI
    assert ayr["gruplar"] == [] and ayr["atilan_olgular"] == 6
    assert ayr["degerlendirilmeyen_tablolar"] == ["T1"]
    # Tablo kimliğiyle (uuid) atıf da kabul edilir.
    olgu["groups"][0]["table_ref"] = tablo_id(1)
    assert d.degerlendir(_kampanya_case(), TABLOLAR[:1], olgu)[0] == d.UYUMLU


def test_celiskili_girdi_cikarilamadi() -> None:
    olgu = _kampanya_olgulari()
    olgu["groups"][0]["inputs"].append(_o("adet", "1", S4, "adet 1"))
    sonuc, ayr = d.degerlendir(_kampanya_case(), TABLOLAR[:1], olgu)
    assert sonuc == d.KONTROL_EDILEMEDI
    assert ayr["gruplar"][0]["durum"] == "cikarilamadi"
    assert "çelişkili" in ayr["gruplar"][0]["neden"]
    assert ayr["degerler"]["karsilastirilamayan"] == 3  # grubun doğrulanmış beklenenleri


def test_satir_yok_ve_hata_kontrol_edilemedi() -> None:
    yalniz_r1 = d.Tablo("x", "T1", "k", {**T1, "satirlar": T1["satirlar"][:1]})
    case = _kampanya_case()
    case["steps"][2]["data"] = "P-001 × 5"
    olgu = _kampanya_olgulari()
    olgu["groups"][0]["inputs"] = [_o("adet", "5", "steps[2].data", "5")]
    sonuc, ayr = d.degerlendir(case, [yalniz_r1], olgu)  # R1 koşulu adet >= 7
    assert sonuc == d.KONTROL_EDILEMEDI and ayr["gruplar"][0]["durum"] == "satir_yok"
    r1 = T1["satirlar"][0]
    bolen = {
        **T1,
        "satirlar": [
            {**r1, "cikti": {**r1["cikti"], "bedava_adet": "adet // (adet - 7)"}},
            *T1["satirlar"][1:],
        ],
    }
    sonuc, ayr = d.degerlendir(
        _kampanya_case(), [d.Tablo("x", "T1", "k", bolen)], _kampanya_olgulari()
    )
    assert sonuc == d.KONTROL_EDILEMEDI and ayr["gruplar"][0]["durum"] == "hata"


def test_beklenen_yoksa_karsilastirma_yok() -> None:
    olgu = _kampanya_olgulari()
    olgu["groups"][0]["expected"] = []
    sonuc, ayr = d.degerlendir(_kampanya_case(), TABLOLAR[:1], olgu)
    assert sonuc == d.KONTROL_EDILEMEDI and ayr["gruplar"][0]["durum"] == "karsilastirma_yok"


def test_bir_grup_uyumsuz_digeri_uyumlu_genel_uyumsuz() -> None:
    case = _kampanya_case()
    case["steps"][3]["expected"] += "; ikinci satır ara toplam 140,00 TL"
    iyi = _kampanya_olgulari()["groups"][0]
    kotu = {
        **iyi,
        "expected": [_o("indirim", "25.00", S4, "25,00 TL")],
        "inputs": [
            _o("adet", "7", "steps[2].data", "7"),
            _o("ara_toplam", "140.00", S4, "140,00 TL"),  # 140 / 7 = 20 ≠ 25
        ],
    }
    sonuc, ayr = d.degerlendir(case, TABLOLAR[:1], {"groups": [iyi, kotu]})
    assert [g["durum"] for g in ayr["gruplar"]] == ["uyumlu", "uyumsuz"]
    assert sonuc == d.UYUMSUZ


def test_mantiksal_tablo_degerlendirmesi() -> None:
    case = tpd1_cases()[4]  # C5: kampanyasız, 150 TL → uyarı görünür
    sonuc, ayr = d.degerlendir(case, TABLOLAR[1:], OLGULAR[5])
    assert sonuc == d.UYUMLU
    assert ayr["gruplar"][0]["satir_id"] == "R2"
    degerler = {k["column"]: k["case_degeri"] for k in ayr["gruplar"][0]["karsilastirmalar"]}
    assert degerler == {"minimum_uyarisi": True}


# ------------------------------------------------------------------ kısmen (K11) ve tamlık


def test_kismen_karsilastirilamayan_deger() -> None:
    """Fark yok ama bir beklenen değer karşılaştırılamadı (ara toplam yok) → `kismen`."""
    olgu = _kampanya_olgulari()
    olgu["groups"][0]["inputs"] = olgu["groups"][0]["inputs"][:2]  # ara toplam olgusu yok
    sonuc, ayr = d.degerlendir(_kampanya_case(), TABLOLAR[:1], olgu)
    assert sonuc == d.KISMEN
    # 175,00 artık hiçbir olguyla kapsanmıyor; indirim ve toplam karşılaştırılamadı.
    assert ayr["degerler"] == {
        "uyumlu": 1,
        "uyumsuz": 0,
        "karsilastirilamayan": 2,
        "atilan": 0,
        "kapsanmayan": 1,
    }
    ozet = d.ozet(sonuc, ayr)
    assert ozet.startswith("Kısmen kontrol edildi: 1 beklenen değer") and "175" in ozet


def test_kismen_atilan_olgu() -> None:
    olgu = _kampanya_olgulari()
    olgu["groups"][0]["expected"].append(_o("indirim", "25.00", S4, "25,00TL"))  # atılır
    sonuc, ayr = d.degerlendir(_kampanya_case(), TABLOLAR[:1], olgu)
    assert sonuc == d.KISMEN and ayr["degerler"]["atilan"] == 1


def test_kismen_bir_grup_degerlendirilemedi() -> None:
    """Review 1 K3: AC2+AC6 case'inde T1 eşleşir, T2 grubu girdisiz kalır → uyumlu denmez."""
    case = _kampanya_case()
    case = {**case, "expected_result": "Minimum sipariş uyarısı gösterilmez"}
    olgu = _kampanya_olgulari()
    olgu["groups"].append(
        {
            "table_ref": "T2",
            "inputs": [],
            "expected": [
                _o(
                    "minimum_uyarisi",
                    False,
                    "expected_result",
                    "Minimum sipariş uyarısı gösterilmez",
                )
            ],
        }
    )
    sonuc, ayr = d.degerlendir(case, TABLOLAR, olgu)
    assert [g["durum"] for g in ayr["gruplar"]] == ["uyumlu", "cikarilamadi"]
    assert sonuc == d.KISMEN and ayr["degerler"]["karsilastirilamayan"] == 1


def test_tamlik_atlanan_sayi_kismen() -> None:
    """Model yanlış bir değeri hiç çıkarmazsa (atlanan alıntı) deterministik tamlık denetimi
    onu yakalar: S4'te toplam 140 yazıyor ama olgusu yok → `kismen` (uyumlu değil)."""
    case = _kampanya_case(toplam="140,00 TL")
    olgu = _kampanya_olgulari()
    olgu["groups"][0]["expected"] = olgu["groups"][0]["expected"][:2]  # toplam olgusu yok
    sonuc, ayr = d.degerlendir(case, TABLOLAR[:1], olgu)
    assert sonuc == d.KISMEN
    assert ayr["kapsanmayan_sayilar"] == [{"alan": S4, "alinti": "140,00"}]


def test_tamlik_ignored_kapsar_ama_listelenir() -> None:
    case = _kampanya_case()
    case["steps"][2]["expected"] = "Sepet sayacı 7 olur"
    olgu = _kampanya_olgulari()
    assert d.degerlendir(case, TABLOLAR[:1], olgu)[0] == d.KISMEN
    olgu["ignored"] = [
        {"field": "steps[2].expected", "quote": "Sepet sayacı 7", "reason": "sayaç"},
        {"field": "steps[2].expected", "quote": "Sepet sayacı 8", "reason": "yok"},  # geçmiyor
        {"field": "steps[2].action", "quote": "adedi 7", "reason": "beklenen alan değil"},
        {"field": "steps[2].expected", "quote": "Sepet sayacı", "reason": "sayı yok"},
    ]
    sonuc, ayr = d.degerlendir(case, TABLOLAR[:1], olgu)
    assert sonuc == d.UYUMLU
    assert ayr["yok_sayilan"] == [
        {"alan": "steps[2].expected", "alinti": "Sepet sayacı 7", "neden": "sayaç"}
    ]


@pytest.mark.parametrize(
    ("metin", "sayilar"),
    [
        ("P-001 satırında adet 7, bedava adet 1", ["7", "1"]),
        ("Portakal Gazozu 1L ve Limonata 330ml", []),
        ("bayi1 / Demo123!", []),
        ("ara toplam 1.250,00 TL; toplam 150,00 TL.", ["1.250,00", "150,00"]),
        ("bedava 7. adette başlar", ["7"]),
        ("indirim −25,00 TL", ["25,00"]),
    ],
)
def test_sayi_gecisleri(metin: str, sayilar: list[str]) -> None:
    assert [metin[a:b] for a, b in d.sayi_gecisleri(metin)] == sayilar


def test_v3_alanlari_tamlikta_ve_olguda() -> None:
    """V12: `verification_point` beklenen alandır; `test_data[i].value` olgu alanı olabilir."""
    case = _kampanya_case() | {
        "verification_point": "Sepette toplam 150,00 TL görünür",
        "test_data": [{"name": "adet", "value": "7"}],
    }
    olgu = _kampanya_olgulari()
    sonuc, ayr = d.degerlendir(case, TABLOLAR[:1], olgu)
    assert sonuc == d.KISMEN
    assert ayr["kapsanmayan_sayilar"] == [{"alan": "verification_point", "alinti": "150,00"}]
    olgu["groups"][0]["expected"].append(_o("toplam", "150.00", "verification_point", "150,00 TL"))
    olgu["groups"][0]["inputs"].append(_o("adet", "7", "test_data[0].value", "7"))
    sonuc, ayr = d.degerlendir(case, TABLOLAR[:1], olgu)
    assert sonuc == d.UYUMLU and ayr["atilan_olgular"] == 0


@pytest.mark.parametrize(
    ("icerik", "yuksek"),
    [
        ({"risk": "high"}, True),
        ({"risk": "High"}, True),
        ({"risk": "medium"}, False),
        ({"priority": "P1"}, True),
        ({"priority": "p1"}, True),
        ({"priority": "P2"}, False),
        ({"risk": "low", "priority": "P1"}, True),
        ({}, False),
        (None, False),
    ],
)
def test_yuksek_risk_mi(icerik: Any, yuksek: bool) -> None:
    assert d.yuksek_risk_mi(icerik) is yuksek


# ------------------------------------------------------------------ kısmi değerlendirme


def test_kismi_degerlendir_tam_girdide_ifade_ile_ayni() -> None:
    from tp_core.features.karar_tablosu import ifade

    for girdi in ({"adet": 7, "ara_toplam": "175"}, {"adet": 6, "ara_toplam": 150}):
        tam = ifade.degerlendir(T1, girdi)
        k = d.kismi_degerlendir(T1, girdi)
        assert (k.satir_id, k.ciktilar, k.hesaplanamayan, k.eksik_girdiler, k.hata) == (
            tam.satir_id,
            tam.ciktilar,
            {},
            [],
            None,
        )


def test_kismi_degerlendir_eksik_girdi_yalniz_onu_kullanani_etkiler() -> None:
    k = d.kismi_degerlendir(T1, {"adet": 14})
    assert k.satir_id == "R1" and k.ciktilar == {"bedava_adet": Decimal(2)}
    assert k.hesaplanamayan == {"indirim": ["ara_toplam"], "toplam": ["ara_toplam"]}
    k = d.kismi_degerlendir(T1, {"adet": 6})
    assert k.satir_id == "R2" and k.hesaplanamayan == {"toplam": ["ara_toplam"]}
    assert k.ciktilar == {"bedava_adet": Decimal(0), "indirim": Decimal(0)}
    # Koşul eksik girdiyi kullanıyorsa satır seçilemez (tam değerlendirme farklı seçebilirdi).
    k = d.kismi_degerlendir(T2, {"sepet_tutari": "150"})
    assert k.satir_id is None and k.eksik_girdiler == ["kampanyali_sepet"]
    # Koşulu değerlendirilebilen önceki satırlar atlanır, eksik girdili ilk koşulda durulur.
    ters = {**T2, "satirlar": [T2["satirlar"][1], T2["satirlar"][0], T2["satirlar"][2]]}
    k = d.kismi_degerlendir(ters, {"sepet_tutari": "900"})
    assert k.satir_id is None and k.eksik_girdiler == ["kampanyali_sepet"]
    k = d.kismi_degerlendir(ters, {"sepet_tutari": "100"})
    assert k.satir_id == "R2" and k.ciktilar == {"minimum_uyarisi": True}
    assert d.kismi_degerlendir(T1, {"adet": "yedi"}).hata is not None
