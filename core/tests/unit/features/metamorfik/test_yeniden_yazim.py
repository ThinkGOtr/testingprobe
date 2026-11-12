"""012 Ş6: metamorfik türetmenin saf çekirdeği (DB'siz, model çağrısı yok)."""

from __future__ import annotations

import copy
from decimal import Decimal

import pytest

from tests.unit.features.metamorfik.ornek import (
    ILISKI,
    case_icerik,
    grup,
    karsilastirma,
    olgu,
)
from tp_core.features.cases.schema import validate_case
from tp_core.features.metamorfik import yeniden_yazim as yy


def test_adet_iki_kati_bicim_korunur() -> None:
    kaynak = case_icerik()
    once = copy.deepcopy(kaynak)
    s = yy.turet(kaynak, grup(), ILISKI)
    assert (s.sonuc, s.neden) == ("turetildi", None)
    c = s.icerik
    assert c is not None
    assert c["steps"][1]["data"] == "50"
    assert c["steps"][1]["expected"] == "Sepette 50 adet P-004 görünür"
    assert c["steps"][2]["expected"] == "Satır tutarı 1.500,00 TL görünür"
    assert c["expected_result"] == "Ara toplam 1.500,00 TL olarak gösterilir"
    # Değişmeyen girdi (birim fiyat) ve olgusu olmayan metin aynı kalır.
    assert c["preconditions"] == kaynak["preconditions"]
    assert c["steps"][0] == kaynak["steps"][0]
    assert c["title"] == "Kampanyasız üründe satır tutarı (P-004) (ilişki: Adet iki katı)"
    assert c["tags"] == ["AI-generated", "sepet", "metamorfik"]
    assert validate_case(c) == []
    assert kaynak == once  # kaynak içerik değiştirilmez


def test_deterministik() -> None:
    assert yy.turet(case_icerik(), grup(), ILISKI) == yy.turet(case_icerik(), grup(), ILISKI)


@pytest.mark.parametrize(
    ("deger", "ornek", "beklenen"),
    [
        (Decimal("1500.00"), "750,00 TL", "1.500,00 TL"),
        (Decimal("2500.00"), "1.250,00 TL", "2.500,00 TL"),
        (Decimal("1500.00"), "750.00", "1,500.00"),
        (Decimal("50"), "25", "50"),
        (Decimal("1500"), "750", "1500"),  # ondalıksız örnek: binlik eklenmez
        (Decimal("187.5"), "125 TL", "187,5 TL"),  # yuvarlanmaz
        (Decimal("300.00"), "150,00 TL", "300,00 TL"),
        (Decimal("-1500.00"), "−750,00 TL", "−1.500,00 TL"),
    ],
)
def test_bicimle(deger: Decimal, ornek: str, beklenen: str) -> None:
    assert yy.bicimle(deger, ornek) == beklenen


def test_bicimle_sayi_olmayan_ornek() -> None:
    with pytest.raises(ValueError):
        yy.bicimle(Decimal(1), "P-004")


def test_on_kosul_saglanmaz() -> None:
    iliski = {**ILISKI, "on_kosul": "adet >= 500"}
    s = yy.turet(case_icerik(), grup(), iliski)
    assert s.sonuc == "iliski_gecersiz" and s.icerik is None
    assert "Ön koşul sağlanmadı" in (s.neden or "")


def test_eksik_ad_ve_belirlenmeyen_cikti() -> None:
    eksik = {**ILISKI, "donusum": {"adet": "adet * kat"}}
    s = yy.turet(case_icerik(), grup(), eksik)
    assert s.sonuc == "iliski_gecersiz" and "kat" in (s.neden or "")
    baska = {**ILISKI, "iliski": {"indirim": "0"}}
    s = yy.turet(case_icerik(), grup(), baska)
    assert s.sonuc == "iliski_gecersiz" and "ara_tutar" in (s.neden or "")


def test_girdi_olgusu_yoksa_olgu_yok() -> None:
    s = yy.turet(case_icerik(), grup(girdiler=[]), ILISKI)
    assert s.sonuc == "olgu_yok"


def test_dogrulanamayan_olgu_atilir() -> None:
    # Alıntı alanda yok / değer alıntıyla uyuşmuyor → olgu yok sayılır.
    g = grup(
        girdiler=[
            olgu("adet", "25", "steps[1].data", "26"),
            olgu("adet", "26", "steps[1].data", "25"),
            olgu("adet", "25", "steps[9].data", "25"),
        ]
    )
    assert yy.grup_olgulari(case_icerik(), g) == [
        yy.Olgu("ara_tutar", "steps[2].expected", "750,00 TL", Decimal("750.00"), True),
        yy.Olgu("ara_tutar", "expected_result", "750,00 TL", Decimal("750.00"), True),
    ]
    assert yy.turet(case_icerik(), g, ILISKI).sonuc == "olgu_yok"


def test_belirsiz_alinti_ayni_alanda_farkli_olgular() -> None:
    # "25" hem adet hem de (iki katına çıkmayan) başka bir girdi olarak aynı alanda.
    icerik = case_icerik()
    icerik["steps"][1]["data"] = "25 adet, kupon 25"
    g = grup(
        girdiler=[
            olgu("adet", "25", "steps[1].data", "25"),
            olgu("kupon", "25", "steps[1].data", "25"),
            olgu("adet", "25", "steps[1].expected", "25"),
            olgu("birim_fiyat", "30.00", "preconditions[1]", "30,00 TL"),
        ]
    )
    s = yy.turet(icerik, g, ILISKI)
    assert s.sonuc == "belirsiz_alinti"
    assert "steps[1].data" in (s.neden or "")


def test_ayni_alinti_ayni_degerse_tum_gecisler_degisir() -> None:
    icerik = case_icerik()
    icerik["steps"][1]["data"] = "25 (adet: 25)"
    s = yy.turet(icerik, grup(), ILISKI)
    assert s.sonuc == "turetildi" and s.icerik is not None
    assert s.icerik["steps"][1]["data"] == "50 (adet: 50)"


def test_olgusuz_alanda_kalan_kopya_belirsiz() -> None:
    g = grup(girdiler=[olgu("adet", "25", "steps[1].data", "25")])
    s = yy.turet(case_icerik(), g, ILISKI)
    assert s.sonuc == "belirsiz_alinti"
    assert "steps[1].expected" in (s.neden or "")


def test_alinti_sayinin_parcasi_olarak_aranmaz() -> None:
    # "25" yalnız "125" ve "25,5" içinde: sınırlı geçiş yok → belirsiz.
    icerik = case_icerik()
    icerik["steps"][1]["data"] = "125 ya da 25,5"
    icerik["steps"][1]["expected"] = "Sepet güncellenir"
    g = grup(girdiler=[olgu("adet", "25", "steps[1].data", "25")])
    s = yy.turet(icerik, g, ILISKI)
    assert s.sonuc == "belirsiz_alinti"
    assert "bulunamadı" in (s.neden or "")


def test_celiskili_olgular() -> None:
    g = grup(
        karsilastirmalar=[
            karsilastirma("ara_tutar", "steps[2].expected", "750,00 TL", "750.00"),
            karsilastirma("ara_tutar", "preconditions[1]", "30,00 TL", "30.00"),
        ]
    )
    s = yy.turet(case_icerik(), g, ILISKI)
    assert s.sonuc == "belirsiz_alinti" and "ara_tutar" in (s.neden or "")


def test_metin_olgusu_degisemez() -> None:
    iliski = {**ILISKI, "donusum": {"adet": "adet * 2", "urun": "'P-005'"}}
    icerik = case_icerik()
    g = grup()
    g["girdiler"].append(olgu("urun", "P-004", "steps[1].action", "P-004"))
    s = yy.turet(icerik, g, iliski)
    assert s.sonuc == "iliski_gecersiz" and "urun" in (s.neden or "")


def test_uzun_baslik_kisaltilir() -> None:
    icerik = case_icerik()
    icerik["title"] = "B" * 118
    s = yy.turet(icerik, grup(), {**ILISKI, "ad": "A" * 120})
    assert s.icerik is not None
    assert len(s.icerik["title"]) == 120
    # İlişki adına 8 karakter kalmıyor: başlık da kısalır (mock `turetilenBaslik` ile aynı).
    assert s.icerik["title"] == "B" * 100 + "… (ilişki: " + "A" * 7 + "…)"
    assert validate_case(s.icerik) == []


def test_uzun_baslikta_once_iliski_adi_kisalir() -> None:
    """Review 2 u2 N11 (birleştirme): case başlığı korunur, önce ilişki adı kısalır; portal mock
    testiyle aynı örnekler (`kalite.test.ts` "türetilen başlık")."""
    assert yy._baslik("Kısa", "İlişki") == "Kısa (ilişki: İlişki)"
    c2 = yy._baslik(
        "14 adet kampanyalı üründe 2 adet bedava verilir",
        "Adet iki katına çıkınca bedava adet ve tutarlar iki katına çıkar",
    )
    assert len(c2) <= 120
    assert c2.startswith("14 adet kampanyalı üründe 2 adet bedava verilir (ilişki: Adet iki katına")
    assert c2.endswith("…)")
    uzun = yy._baslik("x" * 115, "y" * 100)
    assert len(uzun) <= 120
    assert uzun == "x" * 100 + "… (ilişki: " + "y" * 7 + "…)"


@pytest.mark.parametrize(
    ("alan", "beklenen"),
    [
        ("title", "Kampanyasız üründe satır tutarı (P-004)"),
        ("preconditions[1]", "P-004 birim fiyatı 30,00 TL"),
        ("steps[2].expected", "Satır tutarı 750,00 TL görünür"),
        ("steps[0].data", None),
        ("steps[5].data", None),
        ("steps[0].id", None),
        ("tags[0]", None),
    ],
)
def test_alan_oku(alan: str, beklenen: str | None) -> None:
    assert yy.alan_oku(case_icerik(), alan) == beklenen
