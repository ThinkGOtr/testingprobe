"""012 review turu 1 (metamorfik): türetme sağlamlığı — yalnız uyumlu ve geçerli kontrol,
karşılaştırılamayan değer dönüştürülmez, değişen alanda kalan değer reddedilir (`degismez` ile
izin), türetilen case'in olguları modelsiz bilinir; ilişki tablonun onaylı sürümüne bağlıdır."""

from __future__ import annotations

import copy
import uuid
from collections.abc import Callable
from typing import Any

import pytest

from tests.unit.features.metamorfik.ornek import ILISKI, TABLO, case_icerik, grup, olgu
from tests.unit.features.metamorfik.test_turetme import Kurulum, _turet, kur  # noqa: F401
from tp_core.audit import content_hash
from tp_core.features.karar_tablosu import service as kt_service
from tp_core.features.karar_tablosu.hatalar import IliskiGecersiz
from tp_core.features.metamorfik import service
from tp_core.features.metamorfik import yeniden_yazim as yy
from tp_core.features.oracle import dogrulama
from tp_core.models import CaseOracleKontrol, KararTablosu, TestCase, enums, session_scope
from tp_core.workflow.service import SYSTEM, transition

# TPD-1 C2 benzeri: aynı alanda adet, bedava, indirim ve tablo kolonu olmayan ara toplam / toplam.
C2_ALAN = "7 adet: adet 7, bedava adet 1, indirim 25,00 TL, ara toplam 175,00 TL, toplam 150,00 TL"
T1_ILISKI: dict[str, Any] = {
    "ad": "Adet iki katı",
    "ac_refs": ["AC2"],
    "on_kosul": "adet >= 7 ve adet % 7 == 0",
    "donusum": {"adet": "adet * 2"},
    "iliski": {"bedava_adet": "bedava_adet * 2", "indirim": "indirim * 2"},
}


def _c2() -> tuple[dict[str, Any], dict[str, Any]]:
    icerik = case_icerik()
    icerik["acceptance_criteria_refs"] = ["AC2"]
    icerik["steps"][1]["data"] = "7"
    icerik["steps"][1]["expected"] = "Sepette ürün görünür"
    icerik["steps"][2]["expected"] = C2_ALAN
    icerik["expected_result"] = "Bedava 1 adet"
    alan = "steps[2].expected"
    g = {
        "tablo_id": "T1",
        "durum": "uyumlu",
        "girdiler": [
            olgu("adet", "7", "steps[1].data", "7"),
            olgu("adet", "7", alan, "7"),
        ],
        "karsilastirmalar": [
            {"column": "bedava_adet", "alan": alan, "alinti": "adet 1",
             "case_degeri": "1", "uyumlu": True},
            {"column": "indirim", "alan": alan, "alinti": "25,00 TL", "case_degeri": "25.00",
             "uyumlu": True},
            {"column": "bedava_adet", "alan": "expected_result", "alinti": "1 adet",
             "case_degeri": "1", "uyumlu": True},
        ],
    }  # fmt: skip
    return icerik, g


# ---------------------------------------------------------------------- saf çekirdek


def test_kalan_ara_toplam_tutarsiz_kalan_deger() -> None:
    """Review karşı örneği: 14 adette "ara toplam 175,00 TL" yaşayamaz."""
    icerik, g = _c2()
    s = yy.turet(icerik, g, T1_ILISKI)
    assert s.icerik is None
    beklenen = (
        yy.TUTARSIZ_KALAN_DEGER
        if yy.TUTARSIZ_KALAN_DEGER in enums.TURETME_SONUC
        else "belirsiz_alinti"
    )
    assert s.sonuc == beklenen
    assert (s.neden or "").startswith("tutarsiz_kalan_deger") or s.sonuc == yy.TUTARSIZ_KALAN_DEGER
    assert "175,00" in (s.neden or "") and "150,00" in (s.neden or "")


def test_degismez_parca_kalan_degere_izin_verir() -> None:
    icerik, g = _c2()
    icerik["steps"][2]["expected"] = (
        "7 adet: adet 7, bedava adet 1, indirim 25,00 TL (6 al 1 bedava)"
    )
    s = yy.turet(icerik, g, T1_ILISKI)
    assert s.sonuc != "turetildi"
    s = yy.turet(icerik, g, {**T1_ILISKI, "degismez": ["6 al 1 bedava"]})
    assert s.sonuc == "turetildi", s.neden
    assert s.icerik is not None
    assert s.icerik["steps"][2]["expected"] == (
        "14 adet: adet 14, bedava adet 2, indirim 50,00 TL (6 al 1 bedava)"
    )


def test_karsilastirilamayan_deger_donusturulmez() -> None:
    icerik, g = _c2()
    icerik["steps"][2]["expected"] = "7 adet: adet 7, bedava adet 1, indirim 25,00 TL"
    g["karsilastirmalar"] = [k for k in g["karsilastirmalar"] if k["column"] != "indirim"]
    g["karsilastirilamayan"] = [
        {**olgu("indirim", "25.00", "steps[2].expected", "25,00 TL"), "neden": "eksik girdi"}
    ]
    s = yy.turet(icerik, g, T1_ILISKI)
    assert s.icerik is None and "indirim" in (s.neden or "")
    assert "tutarsiz_kalan_deger" in f"{s.sonuc} {s.neden}"
    # Olgu olarak da okunmaz (eskiden dönüştürülüyordu).
    assert all(o.column != "indirim" for o in yy.grup_olgulari(icerik, g))


def test_uyumlu_olmayan_grup_turetmez() -> None:
    for durum in ("uyumsuz", "cikarilamadi", "satir_yok"):
        s = yy.turet(case_icerik(), grup(durum=durum), ILISKI)
        assert s.sonuc == "olgu_yok" and durum in (s.neden or "")
    g = grup()
    g["karsilastirmalar"][0]["uyumlu"] = False
    assert all(o.alan != "steps[2].expected" for o in yy.grup_olgulari(case_icerik(), g))


def test_turetilen_olgular_modelsiz_oracle_uyumlu() -> None:
    icerik, g = _c2()
    icerik["steps"][2]["expected"] = "7 adet: adet 7, bedava adet 1, indirim 25,00 TL"
    s = yy.turet(icerik, g, T1_ILISKI)
    assert s.sonuc == "turetildi" and s.icerik is not None and s.olgular is not None
    [gr] = s.olgular["groups"]
    assert gr["table_ref"] == "T1"
    assert {(o["field"], o["quote"], o["value"]) for o in gr["inputs"]} >= {
        ("steps[1].data", "14", "14"),
        ("steps[2].expected", "14", "14"),
    }
    assert ("steps[2].expected", "50,00 TL", "50.00") in {
        (o["field"], o["quote"], o["value"]) for o in gr["expected"]
    }
    assert yy.turetilen_olgular(icerik, g, T1_ILISKI) == s.olgular
    # Olgular model çağırmadan oracle değerlendirmesine verilir: birim fiyat 25 TL'lik tabloyla.
    tablo = {
        "ad": "Kampanya",
        "ac_refs": ["AC2"],
        "girdiler": [{"ad": "adet", "tur": "sayi"}],
        "ciktilar": [
            {"ad": "bedava_adet", "tur": "sayi"},
            {"ad": "indirim", "tur": "sayi", "tolerans": "0.01"},
        ],
        "satirlar": [
            {"id": "R1", "kosul": "adet >= 7",
             "cikti": {"bedava_adet": "adet // 7", "indirim": "(adet // 7) * 25"}},
            {"id": "R2", "kosul": "dogru", "cikti": {"bedava_adet": "0", "indirim": "0"}},
        ],
    }  # fmt: skip
    sonuc, ayrinti = dogrulama.degerlendir(
        s.icerik, [dogrulama.Tablo("T1", "T1", "Kampanya", tablo)], s.olgular
    )
    assert sonuc == "uyumlu", ayrinti
    assert ayrinti["atilan_olgular"] == 0


# ---------------------------------------------------------------------- servis (DB)


def _kontrol_guncelle(k: Kurulum, **alanlar: Any) -> None:
    with session_scope() as s:
        tc = s.get(TestCase, k.kaynaklar[0])
        kontrol = s.query(CaseOracleKontrol).filter_by(test_case_id=tc.id).one()
        for ad, deger in alanlar.items():
            setattr(kontrol, ad, deger)


def test_uyumsuz_kontrolden_turetilmez(kur: Callable[..., Kurulum]) -> None:  # noqa: F811
    k = kur()
    _kontrol_guncelle(k, sonuc="uyumsuz")
    [a] = _turet(k)["atlanan"]
    assert a["sonuc"] == "olgu_yok" and "uyumlu değil" in a["neden"]


def test_eski_tablo_surumuyle_yapilmis_kontrol_gecersiz(kur: Callable[..., Kurulum]) -> None:  # noqa: F811
    k = kur()
    _kontrol_guncelle(k, tablo_hashleri={str(k.tablo_id): "eski-tablo-hash"})
    [a] = _turet(k)["atlanan"]
    assert a["sonuc"] == "olgu_yok" and "güncel tablolarla" in a["neden"]


def test_tablo_yeniden_acilinca_turetme_reddedilir(kur: Callable[..., Kurulum]) -> None:  # noqa: F811
    k = kur()
    with session_scope() as s:
        t = s.get(KararTablosu, k.tablo_id)
        transition(s, t, "draft", SYSTEM, "approved")
    with pytest.raises(IliskiGecersiz, match="PO onaylı değil"):
        _turet(k)


def test_turetilen_olgulari_servisi(kur: Callable[..., Kurulum]) -> None:  # noqa: F811
    k = kur()
    [t] = _turet(k)["turetilen"]
    with session_scope() as s:
        yeni = s.get(TestCase, uuid.UUID(t["case_id"]))
        olgular = service.turetilen_olgulari(s, yeni)
        assert olgular is not None
        [gr] = olgular["groups"]
        assert gr["table_ref"] == str(k.tablo_id)
        assert ("steps[1].data", "50") in {(o["field"], o["quote"]) for o in gr["inputs"]}
        # Kaynak case türetme ürünü değildir.
        assert service.turetilen_olgulari(s, s.get(TestCase, k.kaynaklar[0])) is None
        # Analist türetilen case'i düzeltirse olgular artık bilinmez (model yolu).
        icerik = copy.deepcopy(yeni.icerik)
        icerik["expected_result"] = "Ara toplam değişti"
        yeni.icerik = icerik
        yeni.icerik_hash = content_hash(icerik)
        s.flush()
        assert service.turetilen_olgulari(s, yeni) is None


def test_iliski_bulunamadi_kodu() -> None:
    assert service.IliskiBulunamadi.kod == "iliski_bulunamadi"
    assert service.IliskiBulunamadi.status_code == 404


def test_ilişki_tablo_kaydi_onayda_yazilir(kur: Callable[..., Kurulum]) -> None:  # noqa: F811
    k = kur()
    with session_scope() as s:
        from tp_core.models import MetamorfikIliski

        n = s.get(MetamorfikIliski, k.iliski_id)
        t = s.get(KararTablosu, k.tablo_id)
        assert kt_service.iliski_tablo_kaydi(s, n) == {
            "id": str(t.id),
            "onaylanan_hash": t.onaylanan_hash,
        }
    assert TABLO["ac_refs"] == ["AC1"]
