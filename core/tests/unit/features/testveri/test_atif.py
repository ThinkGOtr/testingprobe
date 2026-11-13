"""`{veri:anahtar}` atfı: saf eşleme/çözüm kenar durumları ve değişmez (013 §3.3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tp_core.features.testveri import atif

from .conftest import DEMO_PAROLA, seed_sorgu

GOLDEN = Path(__file__).resolve().parents[5] / "rules" / "replay" / "case_generation" / "golden"

KAT = {
    "bayi.bayi1.kullanici_adi": "bayi1",
    "bayi.bayi1.ad": "Merkez Bayi",
    "urun.p_001.kod": "P-001",
    "etiket.siparislerim": "Siparişlerim",
    "etiket.siparislerime_git": "Siparişlerime git",
}


def test_esle_kelime_sinirinda_ve_uzun_deger_once() -> None:
    m = "bayi1 ile gir; Merkez Bayi seçili; Siparişlerime git düğmesi; Siparişlerim sayfası"
    assert atif.esle(m, KAT) == (
        "{veri:bayi.bayi1.kullanici_adi} ile gir; {veri:bayi.bayi1.ad} seçili; "
        "{veri:etiket.siparislerime_git} düğmesi; {veri:etiket.siparislerim} sayfası"
    )
    # Kelime sınırı: bayi10 / xbayi1 / bayi1a eşlenmez; noktalama ve tire sınırdır.
    assert atif.esle("bayi10 xbayi1 bayi1a", KAT) == "bayi10 xbayi1 bayi1a"
    assert atif.esle("(bayi1).", KAT) == "({veri:bayi.bayi1.kullanici_adi})."
    assert atif.esle("cart-line-free-P-001", KAT) == "cart-line-free-{veri:urun.p_001.kod}"


def test_belirsiz_kisa_ve_bosluklu_deger_eslenmez() -> None:
    kat = {"a.x": "ortak", "b.x": "ortak", "c.x": "ab", "d.x": " bosluk", "e.x": "tekil"}
    assert atif.esle("ortak ab bosluk tekil", kat) == "ortak ab bosluk {veri:e.x}"
    assert atif.esle("", kat) == ""
    assert atif.esle("metin", {}) == "metin"


def test_mevcut_atfa_dokunulmaz() -> None:
    kat = {"a.b": "veri", "c.d": "bayi.bayi1"}
    m = "{veri:x.y} veri {veri:bayi.bayi1.ad}"
    assert atif.esle(m, kat) == "{veri:x.y} {veri:a.b} {veri:bayi.bayi1.ad}"
    assert atif.esle(atif.esle(m, kat), kat) == atif.esle(m, kat)  # idempotent


def test_coz_bilinmeyen_ve_gecersiz_anahtar() -> None:
    assert atif.coz("{veri:a.b} x", {"a.b": "D"}) == "D x"
    with pytest.raises(KeyError):
        atif.coz("{veri:yok.bu}", {})
    assert atif.coz("{veri:yok.bu}", {}, bilinmeyen="birak") == "{veri:yok.bu}"
    with pytest.raises(ValueError):
        atif.atif("Büyük.Harf")
    assert atif.atiflar("{veri:a} {veri:b.c} {veri:a} {veri:X}") == ["a", "b.c"]


def test_case_alanlari_baslik_eslenmez() -> None:
    case = {
        "title": "bayi1 girişi",
        "preconditions": ["bayi1 tanımlı", 3],
        "steps": [{"id": "S1", "action": "bayi1 gir", "data": None, "expected": "Merkez Bayi"}],
        "expected_result": "P-001 sepette",
        "tags": ["bayi1"],
    }
    e = atif.case_esle(case, KAT)
    assert e["title"] == "bayi1 girişi" and e["tags"] == ["bayi1"]
    assert e["preconditions"] == ["{veri:bayi.bayi1.kullanici_adi} tanımlı", 3]
    assert e["steps"][0]["expected"] == "{veri:bayi.bayi1.ad}" and e["steps"][0]["data"] is None
    assert atif.case_atiflari(e) == [
        "bayi.bayi1.kullanici_adi",
        "bayi.bayi1.ad",
        "urun.p_001.kod",
    ]
    assert atif.bilinmeyen_atiflar(e, ["bayi.bayi1.ad"]) == [
        "bayi.bayi1.kullanici_adi",
        "urun.p_001.kod",
    ]
    assert atif.case_coz(e, KAT) == case
    assert case["preconditions"] == ["bayi1 tanımlı", 3]  # girdi değişmez


def _tohum_katalogu() -> dict[str, str]:
    from tp_core.features.testveri.service import tohum_kayitlari

    out = {}
    for satir in tohum_kayitlari(seed_sorgu):
        out[satir["anahtar"]] = DEMO_PAROLA if satir.get("gizli") else satir["deger"]
    return out


def test_golden_case_metinleri_esle_coz_sonrasi_birebir() -> None:
    """Değişmez: tohum kataloğuyla eşlenen golden case'ler çözülünce bugünkü metne döner.

    Doğrulama ajanına giden case metni çözülmüş olduğundan replay anahtarları değişmez.
    """
    kat = _tohum_katalogu()
    eslenen_toplam = 0
    for yol in sorted(GOLDEN.rglob("*.json")):
        cases = json.loads(yol.read_text(encoding="utf-8")).get("output", {}).get("cases") or []
        for case in cases:
            e = atif.case_esle(case, kat)
            eslenen_toplam += len(atif.case_atiflari(e))
            assert atif.case_coz(e, kat) == case, (yol.name, case.get("title"))
    # Eşleme gerçekten çalıştı (bayi, parola, ürün değerleri golden'larda geçer); K18 gereği
    # etiket / ayar atfı yok.
    assert eslenen_toplam > 20
    for yol in sorted(GOLDEN.rglob("*.json")):
        for case in (
            json.loads(yol.read_text(encoding="utf-8")).get("output", {}).get("cases") or []
        ):
            for a in atif.case_atiflari(atif.case_esle(case, kat)):
                assert atif.eslenebilir_mi(a), a


def test_k18_grup_ve_tutar_kurallari() -> None:
    kat = {
        "bayi.bayi2.kredi_limiti": "500,00 TL",
        "urun.p_001.fiyat": "25,00 TL",
        "ayar.min_siparis_tutari": "750.00",
        "etiket.katalog": "Katalog",
        "kampanya.k_6al1.kod": "K-6AL1",
        "ortak.sayi": "1234",
    }
    case = {
        "title": "Limit",
        "preconditions": ["Kredi limiti 500,00 TL", "Katalog açık"],
        "steps": [
            {"id": "S1", "action": "Katalog'da K-6AL1 seç; 750.00", "data": "25,00 TL; 1234",
             "expected": "Toplam 500,00 TL"},
        ],
        "expected_result": "Toplam 25,00 TL ve 1234",
    }  # fmt: skip
    e = atif.case_esle(case, kat)
    # Tutar biçimli değerler yalnız ön koşul ve adım verisinde eşlenir.
    assert e["preconditions"] == ["Kredi limiti {veri:bayi.bayi2.kredi_limiti}", "Katalog açık"]
    assert e["steps"][0]["data"] == "{veri:urun.p_001.fiyat}; {veri:ortak.sayi}"
    assert e["steps"][0]["expected"] == "Toplam 500,00 TL"
    assert e["expected_result"] == "Toplam 25,00 TL ve 1234"
    # etiket.* / ayar.* hiç eşlenmez; diğer gruplar serbest metinde eşlenir.
    assert e["steps"][0]["action"] == "Katalog'da {veri:kampanya.k_6al1.kod} seç; 750.00"
    assert atif.case_coz(e, kat) == case
    assert atif.tutar_mi("1.250,00 TL") and atif.tutar_mi("12") and not atif.tutar_mi("P-001")


def test_maskele() -> None:
    gizli = ["Demo123!", "Demo"]
    assert atif.maskele("bayi1 / Demo123! ve Demo", gizli) == "bayi1 / ••• ve •••"
    assert atif.maskele_obje({"a": ["Demo123!", 3], "b": None}, gizli) == {
        "a": ["•••", 3],
        "b": None,
    }
    assert atif.maskele_obje({"a": "x"}, []) == {"a": "x"}
