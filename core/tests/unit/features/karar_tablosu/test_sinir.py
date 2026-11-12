"""012 review turu 1 (tablo şeridi): tolerans tavanı ve sınır örnekleri / satır uyarıları.

Saf testler (DB yok, model yok)."""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

import pytest

from tp_core.features.karar_tablosu import ifade

# V9 T1 biçimi: girdiler adet, ara_toplam; çıktılar bedava_adet, indirim, toplam.
T1: dict[str, Any] = {
    "ad": "Kampanya: 6 al 1 bedava (7 adette 1 bedava)",
    "ac_refs": ["AC2"],
    "girdiler": [
        {"ad": "adet", "tur": "sayi"},
        {"ad": "ara_toplam", "tur": "sayi", "birim": "TL"},
    ],
    "ciktilar": [
        {"ad": "bedava_adet", "tur": "sayi"},
        {"ad": "indirim", "tur": "sayi", "birim": "TL", "tolerans": "0.01"},
        {"ad": "toplam", "tur": "sayi", "birim": "TL", "tolerans": "0.01"},
    ],
    "satirlar": [
        {
            "id": "R1",
            "kosul": "adet >= 7",
            "cikti": {
                "bedava_adet": "adet // 7",
                "indirim": "yuvarla(ara_toplam / adet * (adet // 7), 2)",
                "toplam": "ara_toplam - yuvarla(ara_toplam / adet * (adet // 7), 2)",
            },
        },
        {
            "id": "R2",
            "kosul": "adet < 7",
            "cikti": {"bedava_adet": "0", "indirim": "0", "toplam": "ara_toplam"},
        },
    ],
}

T2: dict[str, Any] = {
    "ad": "Minimum sipariş tutarı",
    "ac_refs": ["AC3", "AC6"],
    "girdiler": [
        {"ad": "kampanyali_sepet", "tur": "mantiksal"},
        {"ad": "sepet_tutari", "tur": "sayi", "birim": "TL"},
    ],
    "ciktilar": [{"ad": "minimum_uyarisi", "tur": "mantiksal"}],
    "satirlar": [
        {"id": "R1", "kosul": "kampanyali_sepet", "cikti": {"minimum_uyarisi": "yanlis"}},
        {"id": "R2", "kosul": "sepet_tutari < 750", "cikti": {"minimum_uyarisi": "dogru"}},
        {"id": "R3", "kosul": "dogru", "cikti": {"minimum_uyarisi": "yanlis"}},
    ],
}


def _cikti_tolerans(tablo: dict[str, Any], ad: str, tolerans: str) -> dict[str, Any]:
    t = copy.deepcopy(tablo)
    for k in t["ciktilar"]:
        if k["ad"] == ad:
            k["tolerans"] = tolerans
    return t


# ---------------------------------------------------------------------- tolerans tavanı


def test_v9_tablosu_gecerli() -> None:
    assert ifade.dogrula(copy.deepcopy(T1)) == []


@pytest.mark.parametrize(
    ("cikti", "tolerans", "gecerli"),
    [
        ("bedava_adet", "0", True),
        ("bedava_adet", "0.01", True),
        # Karşı örnek (review): "1" tolerans 6 ile 7 adet farkını, yani yakalanacak hatayı gizler.
        ("bedava_adet", "1", False),
        ("bedava_adet", "0.5", False),
        ("indirim", "0.01", True),  # yuvarla(…, 2) → hassasiyet 0.01
        ("indirim", "0.02", False),
        ("indirim", "0.005", True),
        ("toplam", "100", False),
    ],
)
def test_tolerans_hassasiyeti_asamaz(cikti: str, tolerans: str, gecerli: bool) -> None:
    hatalar = ifade.dogrula(_cikti_tolerans(T1, cikti, tolerans))
    if gecerli:
        assert hatalar == []
    else:
        assert any("tolerans" in h and "hassasiyet" in h for h in hatalar), hatalar


def test_yuvarla_hanesi_hassasiyeti_belirler() -> None:
    t = copy.deepcopy(T1)
    t["satirlar"][0]["cikti"]["indirim"] = "yuvarla(ara_toplam / adet * (adet // 7), 0)"
    assert ifade.cikti_hassasiyeti(t["ciktilar"][1], t["satirlar"]) == Decimal(1)
    assert ifade.dogrula(_cikti_tolerans(t, "indirim", "1")) == []
    assert ifade.dogrula(_cikti_tolerans(t, "indirim", "1.5")) != []
    # Sabit satır ("0") hassasiyeti etkilemez; yuvarlamasız ifade varsayılan tavana döner.
    assert ifade.cikti_hassasiyeti(T1["ciktilar"][0], T1["satirlar"]) == ifade.TOLERANS_AZAMI


# ---------------------------------------------------------------------- sınır örnekleri


def _girdi_kumesi(sonuc: dict[str, Any], ad: str) -> list[str]:
    return sorted({o["girdiler"][ad] for o in sonuc["ornekler"]}, key=Decimal)


def test_t1_adet_sinirlari_ve_degerlendirme() -> None:
    sonuc = ifade.sinir_ornekleri(copy.deepcopy(T1))
    assert _girdi_kumesi(sonuc, "adet") == ["6", "7", "8", "13", "14", "15"]
    assert _girdi_kumesi(sonuc, "ara_toplam") == ["100.00"]
    satirlar = {o["girdiler"]["adet"]: o for o in sonuc["ornekler"]}
    assert satirlar["6"]["satir_id"] == "R2" and satirlar["6"]["ciktilar"]["bedava_adet"] == "0"
    assert satirlar["7"]["satir_id"] == "R1" and satirlar["7"]["ciktilar"]["bedava_adet"] == "1"
    assert satirlar["14"]["ciktilar"] == {
        "bedava_adet": "2",
        "indirim": "14.29",
        "toplam": "85.71",
    }
    assert all(set(o) >= {"girdiler", "satir_id", "ciktilar"} for o in sonuc["ornekler"])
    assert sonuc["uyarilar"] == []


def test_t2_para_sinirlari_kurus_adimiyla() -> None:
    sonuc = ifade.sinir_ornekleri(copy.deepcopy(T2))
    assert _girdi_kumesi(sonuc, "sepet_tutari") == ["749.99", "750.00", "750.01"]
    assert {o["girdiler"]["kampanyali_sepet"] for o in sonuc["ornekler"]} == {True, False}
    tam = next(
        o
        for o in sonuc["ornekler"]
        if o["girdiler"] == {"kampanyali_sepet": False, "sepet_tutari": "750.00"}
    )
    assert tam["satir_id"] == "R3" and tam["ciktilar"] == {"minimum_uyarisi": False}
    # Kampanyalı sepet + 749,99: R1 ve R2 birlikte sağlanır, çıktıları farklı → örtüşme uyarısı.
    [ortusme] = [u for u in sonuc["uyarilar"] if u["tur"] == "ortusme"]
    assert ortusme["satirlar"] == ["R1", "R2"]
    assert ortusme["girdiler"]["kampanyali_sepet"] is True


def test_ortusen_hic_eslesmeyen_golgede_ve_satir_yok() -> None:
    t = {
        "ad": "Sınır",
        "ac_refs": ["AC1"],
        "girdiler": [{"ad": "adet", "tur": "sayi"}],
        "ciktilar": [{"ad": "kademe", "tur": "sayi"}],
        "satirlar": [
            {"id": "R1", "kosul": "adet >= 5", "cikti": {"kademe": "1"}},
            {"id": "R2", "kosul": "adet >= 10", "cikti": {"kademe": "2"}},  # R1'in gölgesinde
            {"id": "R3", "kosul": "adet > 20 ve adet < 3", "cikti": {"kademe": "3"}},
        ],
    }
    sonuc = ifade.sinir_ornekleri(t)
    turler = {(u["tur"], tuple(u.get("satirlar") or ())) for u in sonuc["uyarilar"]}
    assert ("ortusme", ("R1", "R2")) in turler
    assert ("golgede", ("R2",)) in turler
    assert ("hic_eslesmez", ("R3",)) in turler
    [yok] = [u for u in sonuc["uyarilar"] if u["tur"] == "satir_yok"]
    assert Decimal(yok["girdiler"]["adet"]) < 5


def test_ayni_ciktili_ortusme_ve_genel_satir_uyari_vermez() -> None:
    t = copy.deepcopy(T2)
    t["satirlar"][1]["cikti"]["minimum_uyarisi"] = "yanlis"  # R1 ile aynı çıktı
    assert [u for u in ifade.sinir_ornekleri(t)["uyarilar"] if u["tur"] == "ortusme"] == []


def test_sifira_bolme_hata_uyarisi() -> None:
    t = {
        "ad": "Bölme",
        "ac_refs": ["AC1"],
        "girdiler": [{"ad": "adet", "tur": "sayi"}],
        "ciktilar": [{"ad": "pay", "tur": "sayi"}],
        "satirlar": [{"id": "R1", "kosul": "adet <= 1", "cikti": {"pay": "10 / adet"}}],
    }
    sonuc = ifade.sinir_ornekleri(t)
    assert _girdi_kumesi(sonuc, "adet") == ["0", "1", "2"]
    assert any(u["tur"] == "hata" for u in sonuc["uyarilar"])


def test_eksik_tablo_ornek_uretmez() -> None:
    sonuc = ifade.sinir_ornekleri({"ad": "Boş", "ac_refs": [], "girdiler": [], "ciktilar": [],
                                   "satirlar": []})  # fmt: skip
    assert sonuc["ornekler"] == []
    assert [u["tur"] for u in sonuc["uyarilar"]] == ["gecersiz"]


def test_cok_girdide_izgara_sinirli() -> None:
    girdiler = [{"ad": f"g{i}", "tur": "sayi"} for i in range(6)]
    t = {
        "ad": "Çok girdi",
        "ac_refs": ["AC1"],
        "girdiler": girdiler,
        "ciktilar": [{"ad": "c", "tur": "sayi"}],
        "satirlar": [
            {"id": "R1", "kosul": " ve ".join(f"g{i} >= 5" for i in range(6)), "cikti": {"c": "1"}},
            {"id": "R2", "kosul": "dogru", "cikti": {"c": "0"}},
        ],
    }
    sonuc = ifade.sinir_ornekleri(t)
    assert 1 < len(sonuc["ornekler"]) <= ifade.AZAMI_ORNEK
    assert any(u["tur"] == "ornek_sinirli" for u in sonuc["uyarilar"])
