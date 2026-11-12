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
    # Eşleme gerçekten çalıştı (bayi, parola, ürün, etiket değerleri golden'larda geçer).
    assert eslenen_toplam > 20
