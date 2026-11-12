"""Ekilmiş hatalar (012 §4.6): katalog, `/test/break {hata}`, `/test/faults` ve her hatanın etkisi.

Beklenen sayılar tohum verisinden elle hesaplanmıştır: P-001 25,00 (kampanyalı, 6 al 1 bedava),
P-002 15,00, P-003 8,00, P-004 30,00; minimum sipariş 750,00 (indirim sonrası toplam, sınır dahil);
kampanyalı ürün içeren sepet minimumdan muaftır. Her testte hatalı bayi (bayi1) ile birlikte
etkilenmemesi gereken bir bayi (bayi2) de doğrulanır.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text

from demoapp_api import db, faults
from demoapp_api.models import Ayar, Kampanya, TestKirilma, Urun
from demoapp_api.pricing import SatirGirdi, sepet_hesapla

from .conftest import TEST_HEADERS, giris

# ANALIZ §4.6 tablosundaki dokuz kod (tür ile). `rules/hata-katalogu.yaml` ile eşitlik denetimi
# birleştirme adımında core tarafında eklenir; burada liste bilerek elle yazılıdır.
ANALIZ_KODLARI = {
    "kampanya_bedava_yok": "kod",
    "kampanya_tek_bedava": "kod",
    "kampanya_cift_indirim": "kod",
    "min_siparis_haric": "kod",
    "min_siparis_muafiyet_yok": "kod",
    "min_siparis_500": "veri",
    "min_siparis_1000": "veri",
    "fiyat_p004_31": "veri",
    "kampanya_urunu_p002": "veri",
}

MIN_750 = "Minimum sipariş tutarı 750,00 TL"


def _hata(c: TestClient, kullanici: str, kod: str | None):
    return c.post(
        "/test/break", json={"kullanici_adi": kullanici, "hata": kod}, headers=TEST_HEADERS
    )


def _bayi(c: TestClient, kullanici: str) -> TestClient:
    """Aynı istemcide bayi değiştirir (çerez temizlenir)."""
    c.cookies.clear()
    assert giris(c, kullanici).status_code == 200
    return c


def _sepet(c: TestClient, *satirlar: tuple[str, int]) -> dict:
    """Sepeti boşaltıp verilen (ürün kodu, adet) satırlarını ekler; son sepet yanıtını döndürür."""
    yanit = c.delete("/cart").json()
    for kod, adet in satirlar:
        r = c.post("/cart/lines", json={"urun_kod": kod, "adet": adet})
        assert r.status_code == 200, r.text
        yanit = r.json()
    return yanit


def _ozet(sepet: dict) -> tuple[str, str, str, bool]:
    return sepet["ara_toplam"], sepet["indirim"], sepet["toplam"], sepet["onaylanabilir"]


def _uyarilar(sepet: dict) -> list[str]:
    return [u["mesaj"] for u in sepet["uyarilar"]]


def _urunler(c: TestClient) -> dict[str, tuple[str, str | None]]:
    return {u["kod"]: (u["fiyat"], u["kampanya"]) for u in c.get("/products").json()}


NORMAL_URUNLER = {
    "P-001": ("25.00", "6 al 1 bedava"),
    "P-002": ("15.00", None),
    "P-003": ("8.00", None),
    "P-004": ("30.00", None),
}


# ------------------------------------------------------------------ katalog
def test_katalog_analizdeki_dokuz_kodla_ayni():
    assert {h.kod: h.tur for h in faults.KATALOG} == ANALIZ_KODLARI
    assert len(faults.KATALOG) == 9  # kod yinelenmez
    for h in faults.KATALOG:
        assert h.ad.strip() and h.aciklama.strip()
        assert len(h.kod) <= faults.KOD_UZUNLUGU
        assert all(c.islower() or c.isdigit() or c == "_" for c in h.kod)  # ^[a-z0-9_]{1,40}$
    assert TestKirilma.__table__.c.hata.type.length == faults.KOD_UZUNLUGU


def test_faults_ucu_katalogu_dondurur(client):
    r = client.get("/test/faults", headers=TEST_HEADERS)
    assert r.status_code == 200
    hatalar = r.json()["hatalar"]
    assert {h["kod"]: h["tur"] for h in hatalar} == ANALIZ_KODLARI
    assert all(set(h) == {"kod", "tur", "ad", "aciklama"} for h in hatalar)
    assert hatalar[0] == {
        "kod": "kampanya_bedava_yok",
        "tur": "kod",
        "ad": "Kampanya: bedava adet verilmez",
        "aciklama": "Kampanyalı satırda bedava adet her zaman 0 olur; indirim uygulanmaz.",
    }


def test_faults_ucu_korumasi(client, monkeypatch):
    assert client.get("/test/faults").status_code == 403
    assert client.get("/test/faults", headers={"X-Demoapp-Test-Token": "yanlis"}).status_code == 403
    monkeypatch.delenv("DEMOAPP_TEST_TOKEN")
    assert client.get("/test/faults", headers=TEST_HEADERS).status_code == 404
    monkeypatch.setenv("DEMOAPP_TEST_TOKEN", "birim-test-tokeni")
    monkeypatch.delenv("DEMOAPP_TEST_MODE")
    assert client.get("/test/faults", headers=TEST_HEADERS).status_code == 404


# ------------------------------------------------------------------ /test/break {hata}
def test_break_hata_ac_degistir_kapat(client):
    assert _hata(client, "bayi1", "kampanya_tek_bedava").json() == {
        "kullanici_adi": "bayi1",
        "kampanya": False,
        "hata": "kampanya_tek_bedava",
    }
    # Bayi başına en çok bir etkin hata: yenisi öncekinin yerini alır.
    assert _hata(client, "bayi1", "fiyat_p004_31").json()["hata"] == "fiyat_p004_31"
    with db.session_scope() as s:
        satirlar = s.scalars(select(TestKirilma)).all()
        assert [(x.hata, x.kampanya) for x in satirlar] == [("fiyat_p004_31", False)]
    _bayi(client, "bayi1")
    assert _ozet(_sepet(client, ("P-001", 6))) == ("150.00", "25.00", "125.00", True)  # eşik 6
    assert _urunler(client)["P-004"] == ("31.00", None)

    assert _hata(client, "bayi1", None).json() == {
        "kullanici_adi": "bayi1",
        "kampanya": False,
        "hata": None,
    }
    assert _hata(client, "bayi1", None).status_code == 200  # kapatma idempotent
    assert _urunler(client) == NORMAL_URUNLER
    with db.session_scope() as s:
        assert s.scalars(select(TestKirilma)).all() == []


def test_break_kampanya_true_bedava_yok_ile_esanlamli(client):
    r = client.post(
        "/test/break", json={"kullanici_adi": "bayi1", "kampanya": True}, headers=TEST_HEADERS
    )
    assert r.json() == {"kullanici_adi": "bayi1", "kampanya": True, "hata": "kampanya_bedava_yok"}
    with db.session_scope() as s:
        (satir,) = s.scalars(select(TestKirilma)).all()
        assert (satir.hata, satir.kampanya) == ("kampanya_bedava_yok", True)
    # `kampanya: false` hangi hata açıksa onu kaldırır (koşucunun koşu sonu geri alması).
    _hata(client, "bayi1", "min_siparis_500")
    r = client.post(
        "/test/break", json={"kullanici_adi": "bayi1", "kampanya": False}, headers=TEST_HEADERS
    )
    assert r.json() == {"kullanici_adi": "bayi1", "kampanya": False, "hata": None}
    _bayi(client, "bayi1")
    assert _sepet(client, ("P-004", 1))["min_siparis_tutari"] == "750.00"


def test_break_ikisi_birlikte_verilirse_hata_gecerli(client):
    r = client.post(
        "/test/break",
        json={"kullanici_adi": "bayi1", "kampanya": True, "hata": "min_siparis_1000"},
        headers=TEST_HEADERS,
    )
    assert r.json() == {"kullanici_adi": "bayi1", "kampanya": False, "hata": "min_siparis_1000"}


def test_break_bilinmeyen_kod_422(bayi1):
    _hata(bayi1, "bayi1", "kampanya_tek_bedava")
    r = _hata(bayi1, "bayi1", "boyle_bir_hata_yok")
    assert r.status_code == 422
    mesaj = r.json()["detail"]
    assert mesaj.startswith("Bilinmeyen hata kodu: 'boyle_bir_hata_yok'. Geçerli kodlar: ")
    assert all(kod in mesaj for kod in ANALIZ_KODLARI)
    assert _hata(bayi1, "bayi1", "x" * 41).status_code == 422  # uzunluk sınırı
    assert _hata(bayi1, "bayi1", 7).status_code == 422
    # Reddedilen istek etkin hatayı değiştirmez.
    assert _ozet(_sepet(bayi1, ("P-001", 12))) == ("300.00", "25.00", "275.00", True)


def test_break_hata_korumasi(bayi1, monkeypatch):
    govde = {"kullanici_adi": "bayi1", "hata": "fiyat_p004_31"}
    assert bayi1.post("/test/break", json=govde).status_code == 403
    yanlis = {"X-Demoapp-Test-Token": "yanlis"}
    assert bayi1.post("/test/break", json=govde, headers=yanlis).status_code == 403
    assert _hata(bayi1, "yok", "fiyat_p004_31").status_code == 404
    bos = bayi1.post("/test/break", json={"kullanici_adi": "bayi1"}, headers=TEST_HEADERS)
    assert (
        bos.status_code == 422 and bos.json()["detail"] == "kampanya ya da hata alanı verilmelidir"
    )
    assert _urunler(bayi1) == NORMAL_URUNLER
    monkeypatch.delenv("DEMOAPP_TEST_TOKEN")
    assert _hata(bayi1, "bayi1", "fiyat_p004_31").status_code == 404
    monkeypatch.setenv("DEMOAPP_TEST_TOKEN", "birim-test-tokeni")
    monkeypatch.delenv("DEMOAPP_TEST_MODE")
    assert _hata(bayi1, "bayi1", "fiyat_p004_31").status_code == 404


@pytest.mark.parametrize("kod", sorted(ANALIZ_KODLARI))
def test_reset_hatayi_kaldirir(client, kod):
    # Tek sepet bütün hataları ayırt eder: normalde 6×P-001 + 6×P-002 + 1×P-004 = 270,00 − 25,00.
    sepet = (("P-001", 6), ("P-002", 6), ("P-004", 1))
    normal = {**_sepet(_bayi(client, "bayi1"), *sepet), "urunler": _urunler(client)}
    assert _ozet(normal) == ("270.00", "25.00", "245.00", True)
    assert normal["min_siparis_tutari"] == "750.00"

    _hata(client, "bayi1", kod)
    client.post("/test/reset", json={"kullanici_adi": "bayi1"}, headers=TEST_HEADERS)
    assert {**_sepet(client, *sepet), "urunler": _urunler(client)} == normal

    _hata(client, "bayi1", kod)
    client.post("/test/reset", headers=TEST_HEADERS)  # tam reset oturumu da siler
    _bayi(client, "bayi1")
    assert {**_sepet(client, *sepet), "urunler": _urunler(client)} == normal
    with db.session_scope() as s:
        assert s.scalars(select(TestKirilma)).all() == []


def test_hata_test_modu_kapaninca_etkisiz(bayi1, monkeypatch):
    _hata(bayi1, "bayi1", "fiyat_p004_31")
    assert _urunler(bayi1)["P-004"] == ("31.00", None)
    monkeypatch.delenv("DEMOAPP_TEST_MODE")
    assert _urunler(bayi1) == NORMAL_URUNLER
    assert _ozet(_sepet(bayi1, ("P-004", 2))) == ("60.00", "0.00", "60.00", False)


@pytest.mark.parametrize("kod", sorted(ANALIZ_KODLARI))
def test_hata_diger_bayileri_ve_tablolari_etkilemez(client, kod):
    def tablolar():
        with db.session_scope() as s:
            return (
                s.get(Ayar, "min_siparis_tutari").deger,
                [(u.kod, u.fiyat) for u in s.scalars(select(Urun).order_by(Urun.kod))],
                [(k.kod, k.urun.kod, k.aktif) for k in s.scalars(select(Kampanya))],
            )

    once = tablolar()
    _hata(client, "bayi1", kod)
    for bayi in ("bayi2", "bayi3"):
        _bayi(client, bayi)
        assert _urunler(client) == NORMAL_URUNLER
        # 7×P-001: 175,00 − 25,00; kampanyalı sepet minimumdan muaf.
        assert _ozet(_sepet(client, ("P-001", 7))) == ("175.00", "25.00", "150.00", True)
        # 6×P-001 (eşik) + 6×P-002 (kampanyasız): 150,00 + 90,00 − 25,00.
        assert _ozet(_sepet(client, ("P-001", 6), ("P-002", 6))) == (
            "240.00",
            "25.00",
            "215.00",
            True,
        )
        # 25×P-004 = 750,00 (sınır dahil) onaylanır; 24×P-004 = 720,00 onaylanmaz.
        assert _ozet(_sepet(client, ("P-004", 25))) == ("750.00", "0.00", "750.00", True)
        sinir_alti = _sepet(client, ("P-004", 24))
        assert _ozet(sinir_alti) == ("720.00", "0.00", "720.00", False)
        assert _uyarilar(sinir_alti) == [MIN_750]
    # Veri hataları tabloya yazılmaz.
    assert tablolar() == once


# ------------------------------------------------------------------ kod hataları
def test_kampanya_bedava_yok(client):
    _hata(client, "bayi1", "kampanya_bedava_yok")
    _bayi(client, "bayi1")
    sepet = _sepet(client, ("P-001", 7))  # normal: 175,00 − 25,00 = 150,00
    assert _ozet(sepet) == ("175.00", "0.00", "175.00", True)
    assert (sepet["satirlar"][0]["bedava_adet"], sepet["satirlar"][0]["ucretli_adet"]) == (0, 7)
    assert _urunler(client) == NORMAL_URUNLER  # kampanya etiketi durur; hesap bozuk
    siparis = client.post("/orders").json()
    assert (siparis["indirim"], siparis["toplam"]) == ("0.00", "175.00")
    assert siparis["satirlar"][0]["bedava_adet"] == 0

    assert _ozet(_sepet(_bayi(client, "bayi2"), ("P-001", 7))) == (
        "175.00",
        "25.00",
        "150.00",
        True,
    )


def test_kampanya_tek_bedava(client):
    _hata(client, "bayi1", "kampanya_tek_bedava")
    _bayi(client, "bayi1")
    # 6 ve 7 adet: iki kuralda da 1 bedava (bu adetler hatayı yakalamaz).
    assert _ozet(_sepet(client, ("P-001", 6))) == ("150.00", "25.00", "125.00", True)
    assert _ozet(_sepet(client, ("P-001", 7))) == ("175.00", "25.00", "150.00", True)
    # 12 adet: normalde 2 bedava (300,00 − 50,00); hatada 1 bedava (300,00 − 25,00).
    on_iki = _sepet(client, ("P-001", 12))
    assert _ozet(on_iki) == ("300.00", "25.00", "275.00", True)
    assert (on_iki["satirlar"][0]["bedava_adet"], on_iki["satirlar"][0]["ucretli_adet"]) == (1, 11)
    # 14 adet (katalogdaki ayırt edici girdi): doğru 2 bedava, hatalı 1.
    on_dort = _sepet(client, ("P-001", 14))
    assert on_dort["satirlar"][0]["bedava_adet"] == 1
    assert _ozet(on_dort) == ("350.00", "25.00", "325.00", True)
    siparis = client.post("/orders").json()
    assert (siparis["indirim"], siparis["toplam"]) == ("25.00", "325.00")
    assert siparis["satirlar"][0]["bedava_adet"] == 1

    _bayi(client, "bayi2")
    assert _sepet(client, ("P-001", 14))["satirlar"][0]["bedava_adet"] == 2
    assert _ozet(_sepet(client, ("P-001", 12))) == ("300.00", "50.00", "250.00", True)


def test_kampanya_cift_indirim(client):
    _hata(client, "bayi1", "kampanya_cift_indirim")
    _bayi(client, "bayi1")
    # 7×P-001 = 175,00; 1 bedava → indirim 25,00 yerine 50,00; toplam 150,00 yerine 125,00.
    sepet = _sepet(client, ("P-001", 7), ("P-002", 2))
    assert _ozet(sepet) == ("205.00", "50.00", "155.00", True)
    p001, p002 = sepet["satirlar"]
    assert (p001["bedava_adet"], p001["ucretli_adet"]) == (1, 6)  # adetler değişmez
    assert (p001["indirim"], p001["satir_tutari"]) == ("50.00", "125.00")
    assert (p002["indirim"], p002["satir_tutari"]) == ("0.00", "30.00")
    # 5 adet: bedava yok, hata görünmez.
    assert _ozet(_sepet(client, ("P-001", 5))) == ("125.00", "0.00", "125.00", True)
    _sepet(client, ("P-001", 7))
    siparis = client.post("/orders").json()
    assert (siparis["ara_toplam"], siparis["indirim"], siparis["toplam"]) == (
        "175.00",
        "50.00",
        "125.00",
    )
    assert siparis["satirlar"][0]["satir_tutari"] == "125.00"

    assert _ozet(_sepet(_bayi(client, "bayi2"), ("P-001", 7))) == (
        "175.00",
        "25.00",
        "150.00",
        True,
    )


def test_min_siparis_haric(client):
    _hata(client, "bayi1", "min_siparis_haric")
    _bayi(client, "bayi1")
    # 25×P-004 = 750,00: normalde sınır dahil (onaylanır); hatada onaylanmaz.
    sinir = _sepet(client, ("P-004", 25))
    assert _ozet(sinir) == ("750.00", "0.00", "750.00", False)
    assert sinir["min_siparis_saglandi"] is False
    assert _uyarilar(sinir) == [MIN_750]
    r = client.post("/orders")
    assert (r.status_code, r.json()["detail"]) == (422, MIN_750)
    # 26×P-004 = 780,00: sınırın üstü iki kuralda da onaylanır.
    assert _ozet(_sepet(client, ("P-004", 26))) == ("780.00", "0.00", "780.00", True)
    assert client.post("/orders").status_code == 201

    _bayi(client, "bayi2")
    assert _ozet(_sepet(client, ("P-004", 25))) == ("750.00", "0.00", "750.00", True)
    assert client.post("/orders").status_code == 201


def test_min_siparis_muafiyet_yok(client):
    _hata(client, "bayi1", "min_siparis_muafiyet_yok")
    _bayi(client, "bayi1")
    # 7×P-001 = 150,00 (indirimli): normalde kampanyalı sepet muaf; hatada minimuma takılır.
    sepet = _sepet(client, ("P-001", 7))
    assert _ozet(sepet) == ("175.00", "25.00", "150.00", False)
    assert _uyarilar(sepet) == [MIN_750]
    r = client.post("/orders")
    assert (r.status_code, r.json()["detail"]) == (422, MIN_750)
    # 36×P-001 = 900,00 − 6×25,00 = 750,00: minimumu sağlayan kampanyalı sepet onaylanır.
    assert _ozet(_sepet(client, ("P-001", 36))) == ("900.00", "150.00", "750.00", True)
    # Kampanyasız sepette davranış aynıdır.
    assert _ozet(_sepet(client, ("P-004", 24))) == ("720.00", "0.00", "720.00", False)

    _bayi(client, "bayi2")
    assert _ozet(_sepet(client, ("P-001", 7))) == ("175.00", "25.00", "150.00", True)
    assert client.post("/orders").status_code == 201


# ------------------------------------------------------------------ veri hataları
def test_min_siparis_500(client):
    _hata(client, "bayi1", "min_siparis_500")
    _bayi(client, "bayi1")
    # 17×P-004 = 510,00: normalde 750,00'nin altında (onaylanmaz); hatada onaylanır.
    sepet = _sepet(client, ("P-004", 17))
    assert _ozet(sepet) == ("510.00", "0.00", "510.00", True)
    assert (sepet["min_siparis_tutari"], sepet["min_siparis_saglandi"]) == ("500.00", True)
    # 16×P-004 = 480,00: yeni sınırın altı; mesaj da ezilen tutarı gösterir.
    alti = _sepet(client, ("P-004", 16))
    assert _ozet(alti) == ("480.00", "0.00", "480.00", False)
    assert _uyarilar(alti) == ["Minimum sipariş tutarı 500,00 TL"]
    _sepet(client, ("P-004", 17))
    assert client.post("/orders").status_code == 201

    _bayi(client, "bayi2")
    normal = _sepet(client, ("P-004", 17))
    assert _ozet(normal) == ("510.00", "0.00", "510.00", False)
    assert (normal["min_siparis_tutari"], _uyarilar(normal)) == ("750.00", [MIN_750])
    assert client.post("/orders").status_code == 422


def test_min_siparis_1000(client):
    _hata(client, "bayi1", "min_siparis_1000")
    _bayi(client, "bayi1")
    # 25×P-004 = 750,00: normalde onaylanır; hatada 1.000,00'nin altında.
    sepet = _sepet(client, ("P-004", 25))
    assert _ozet(sepet) == ("750.00", "0.00", "750.00", False)
    assert sepet["min_siparis_tutari"] == "1000.00"
    assert _uyarilar(sepet) == ["Minimum sipariş tutarı 1.000,00 TL"]
    r = client.post("/orders")
    assert (r.status_code, r.json()["detail"]) == (422, "Minimum sipariş tutarı 1.000,00 TL")
    # 34×P-004 = 1.020,00 onaylanır; kampanyalı sepet yine muaf.
    assert _ozet(_sepet(client, ("P-004", 34))) == ("1020.00", "0.00", "1020.00", True)
    assert _ozet(_sepet(client, ("P-001", 7))) == ("175.00", "25.00", "150.00", True)

    _bayi(client, "bayi2")
    assert _ozet(_sepet(client, ("P-004", 25))) == ("750.00", "0.00", "750.00", True)
    assert client.post("/orders").status_code == 201


def test_fiyat_p004_31(client):
    _hata(client, "bayi1", "fiyat_p004_31")
    _bayi(client, "bayi1")
    assert _urunler(client) == {**NORMAL_URUNLER, "P-004": ("31.00", None)}
    # 2×P-004: 60,00 yerine 62,00; 3×P-002 = 45,00 değişmez.
    sepet = _sepet(client, ("P-004", 2), ("P-002", 3))
    assert _ozet(sepet) == ("107.00", "0.00", "107.00", False)
    p002, p004 = sepet["satirlar"]
    assert (p004["birim_fiyat"], p004["satir_tutari"]) == ("31.00", "62.00")
    assert (p002["birim_fiyat"], p002["satir_tutari"]) == ("15.00", "45.00")
    # 25×P-004: 750,00 yerine 775,00; sipariş satırına da ezilen fiyat yazılır.
    assert _ozet(_sepet(client, ("P-004", 25))) == ("775.00", "0.00", "775.00", True)
    siparis = client.post("/orders").json()
    assert siparis["toplam"] == "775.00"
    assert siparis["satirlar"][0]["birim_fiyat"] == "31.00"

    _bayi(client, "bayi2")
    assert _urunler(client) == NORMAL_URUNLER
    assert _ozet(_sepet(client, ("P-004", 2))) == ("60.00", "0.00", "60.00", False)


def test_kampanya_urunu_p002(client):
    _hata(client, "bayi1", "kampanya_urunu_p002")
    _bayi(client, "bayi1")
    assert _urunler(client) == {
        **NORMAL_URUNLER,
        "P-001": ("25.00", None),
        "P-002": ("15.00", "6 al 1 bedava"),
    }
    # 6×P-002 = 90,00: normalde indirim yok ve minimuma tabi; hatada 1 bedava (−15,00) ve muaf.
    p002 = _sepet(client, ("P-002", 6))
    assert _ozet(p002) == ("90.00", "15.00", "75.00", True)
    assert (p002["satirlar"][0]["kampanya"], p002["satirlar"][0]["bedava_adet"]) == (
        "6 al 1 bedava",
        1,
    )
    # 7×P-001 = 175,00: normalde 25,00 indirim ve muaf; hatada indirim yok ve minimuma takılır.
    p001 = _sepet(client, ("P-001", 7))
    assert _ozet(p001) == ("175.00", "0.00", "175.00", False)
    assert (p001["satirlar"][0]["kampanya"], p001["satirlar"][0]["bedava_adet"]) == (None, 0)
    assert _uyarilar(p001) == [MIN_750]
    assert client.post("/orders").status_code == 422
    _sepet(client, ("P-002", 6))
    siparis = client.post("/orders").json()
    assert (siparis["indirim"], siparis["toplam"]) == ("15.00", "75.00")
    assert siparis["satirlar"][0]["bedava_adet"] == 1

    _bayi(client, "bayi2")
    assert _urunler(client) == NORMAL_URUNLER
    assert _ozet(_sepet(client, ("P-002", 6))) == ("90.00", "0.00", "90.00", False)


# ------------------------------------------------------------------ saf işlevler
def test_hatasiz_islevler_normal_kurali_verir():
    assert [faults.bedava_adet(n) for n in (5, 6, 7, 12)] == [0, 1, 1, 2]
    assert faults.indirim_kati() == 1
    assert faults.min_saglandi(Decimal("750"), Decimal("750")) is True
    assert faults.muafiyet_yok() is False
    assert faults.min_siparis(None, Decimal("750.00")) == Decimal("750.00")
    assert faults.fiyat(None, "P-004", Decimal("30.00")) == Decimal("30.00")
    assert faults.kampanya_urunu(None) is None
    # Bir hata yalnızca kendi kuralını değiştirir.
    for kod in ANALIZ_KODLARI:
        assert faults.fiyat(kod, "P-001", Decimal("25.00")) == Decimal("25.00")
        assert faults.gecerli(kod)
    assert not faults.gecerli(None) and not faults.gecerli("") and not faults.gecerli("yok")


def test_surec_geneli_break_campaign_tek_bedava_ile_de_sifir_verir(monkeypatch):
    monkeypatch.setenv("BREAK_CAMPAIGN", "1")
    assert faults.bedava_adet(14, "kampanya_tek_bedava") == 0
    assert faults.bedava_adet(14) == 0
    h = sepet_hesapla(
        [SatirGirdi("P-001", "Portakal Gazozu 1L", Decimal("25.00"), 14, True)],
        Decimal("750"),
        hata="kampanya_cift_indirim",
    )
    assert h.indirim == Decimal("0.00")


def test_satir_hatasi_eski_satir_ve_taninmayan_kod():
    assert faults.satir_hatasi(None) is None
    assert faults.satir_hatasi(TestKirilma(kampanya=True, hata=None)) == "kampanya_bedava_yok"
    assert faults.satir_hatasi(TestKirilma(kampanya=False, hata=None)) is None
    assert faults.satir_hatasi(TestKirilma(kampanya=False, hata="min_siparis_500")) == (
        "min_siparis_500"
    )
    # Katalogdan çıkarılmış / elle yazılmış kod hesabı bozmaz.
    assert faults.satir_hatasi(TestKirilma(kampanya=True, hata="eski_kod")) is None


# ------------------------------------------------------------------ eski şema (kolon eklenir)
ESKI_TEST_KIRILMA = (
    "CREATE TABLE test_kirilma (bayi_id INTEGER NOT NULL PRIMARY KEY, kampanya BOOLEAN NOT NULL, "
    "guncelleme DATETIME NOT NULL)"
)


def test_eski_veritabanina_hata_kolonu_eklenir(tmp_path, monkeypatch):
    """`hata` kolonu olmayan (önceki sürümle kurulmuş) SQLite dosyasıyla uygulama yine çalışır."""
    yol = tmp_path / "eski.db"
    eski = create_engine(f"sqlite:///{yol}")
    with eski.begin() as conn:
        conn.execute(text(ESKI_TEST_KIRILMA))
    eski.dispose()
    monkeypatch.setenv("DEMOAPP_DATABASE_URL", f"sqlite:///{yol}")
    db.clear_caches()

    from demoapp_api.main import app

    with TestClient(app) as c:
        kolonlar = {k["name"] for k in inspect(db.get_engine()).get_columns("test_kirilma")}
        assert kolonlar == {"bayi_id", "kampanya", "guncelleme", "hata"}
        assert db.kolonlari_tamamla(db.get_engine()) == []  # idempotent
        db.init_db()
        assert _hata(c, "bayi1", "fiyat_p004_31").status_code == 200
        assert _urunler(_bayi(c, "bayi1"))["P-004"] == ("31.00", None)
        # Eski sürümün yazdığı satır (hata NULL, kampanya açık) hâlâ kampanyayı kırar.
        with db.session_scope() as s:
            s.execute(text("UPDATE test_kirilma SET hata = NULL, kampanya = 1"))
        assert _ozet(_sepet(c, ("P-001", 7))) == ("175.00", "0.00", "175.00", True)


def test_kolonlari_tamamla_eklenen_kolonu_bildirir(tmp_path):
    motor = create_engine(f"sqlite:///{tmp_path / 'eski2.db'}")
    try:
        with motor.begin() as conn:
            conn.execute(text(ESKI_TEST_KIRILMA))
            conn.execute(text("INSERT INTO test_kirilma VALUES (1, 1, '2026-01-01 00:00:00')"))
        assert db.kolonlari_tamamla(motor) == ["test_kirilma.hata"]
        assert db.kolonlari_tamamla(motor) == []
        with motor.connect() as conn:
            assert conn.execute(text("SELECT bayi_id, hata FROM test_kirilma")).all() == [(1, None)]
    finally:
        motor.dispose()


def test_kampanya_tek_bedava_kurali_min_1_adet_bolu_6():
    """K9: bedava adet `min(1, adet // 6)`; 12 adetten önce normal kuralla ayırt edilemez."""
    for adet in range(0, 40):
        assert faults.bedava_adet(adet, "kampanya_tek_bedava") == min(1, adet // 6)
        assert (faults.bedava_adet(adet, "kampanya_tek_bedava") != faults.bedava_adet(adet)) == (
            adet >= 12
        )
