from decimal import Decimal

import pytest

from demoapp_api.campaign import bedava_adet
from demoapp_api.money import format_tl, tutar_str
from demoapp_api.pricing import SatirGirdi, min_siparis_mesaji, sepet_hesapla

P001 = dict(urun_kod="P-001", urun_ad="Portakal Gazozu 1L", birim_fiyat=Decimal("25.00"))
P004 = dict(urun_kod="P-004", urun_ad="Şeftalili Soğuk Çay 1L", birim_fiyat=Decimal("30.00"))


@pytest.mark.parametrize(
    ("adet", "bedava"),
    [(0, 0), (1, 0), (5, 0), (6, 1), (7, 1), (11, 1), (12, 2), (13, 2), (36, 6)],
)
def test_bedava_adet_her_6_adette_1(adet, bedava):
    assert bedava_adet(adet) == bedava


def test_break_campaign_indirimi_kapatir(monkeypatch):
    monkeypatch.setenv("BREAK_CAMPAIGN", "1")
    assert bedava_adet(6) == 0
    assert bedava_adet(70) == 0
    monkeypatch.setenv("BREAK_CAMPAIGN", "0")
    assert bedava_adet(6) == 1


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (Decimal("0"), "0,00 TL"),
        (Decimal("8"), "8,00 TL"),
        (Decimal("750"), "750,00 TL"),
        (Decimal("1250"), "1.250,00 TL"),
        (Decimal("1234567.891"), "1.234.567,89 TL"),
        (Decimal("-25"), "-25,00 TL"),
        ("0.005", "0,01 TL"),
    ],
)
def test_format_tl(value, text):
    assert format_tl(value) == text


def test_tutar_str_iki_ondalik():
    assert tutar_str(Decimal("25")) == "25.00"
    assert tutar_str("8.5") == "8.50"


def test_yedi_adet_kampanyali_urun():
    h = sepet_hesapla([SatirGirdi(**P001, adet=7, kampanyali=True)], Decimal("750"))
    (s,) = h.satirlar
    assert (s.bedava_adet, s.ucretli_adet) == (1, 6)
    assert h.ara_toplam == Decimal("175.00")
    assert h.indirim == Decimal("25.00")
    assert h.toplam == Decimal("150.00")
    assert h.adet_toplam == 7


def test_kampanyasiz_urunde_bedava_yok():
    h = sepet_hesapla([SatirGirdi(**P004, adet=12, kampanyali=False)], Decimal("0"))
    assert h.satirlar[0].bedava_adet == 0
    assert h.indirim == Decimal("0.00")
    assert h.toplam == Decimal("360.00")


def test_min_siparis_altinda_uyari_ve_onay_pasif():
    h = sepet_hesapla([SatirGirdi(**P004, adet=5, kampanyali=False)], Decimal("750.00"))
    assert not h.min_siparis_saglandi
    assert not h.onaylanabilir
    assert [(u.kod, u.mesaj) for u in h.uyarilar] == [
        ("min_siparis", "Minimum sipariş tutarı 750,00 TL")
    ]


def test_kampanyali_sipariste_min_siparis_aranmaz():
    # 7 x 25 = 175; 1 bedava → 150 < 750, ama sipariş kampanyalı ürün içeriyor.
    h = sepet_hesapla([SatirGirdi(**P001, adet=7, kampanyali=True)], Decimal("750.00"))
    assert h.toplam == Decimal("150.00")
    assert not h.min_siparis_saglandi
    assert h.onaylanabilir
    assert h.uyarilar == []


def test_karisik_sepette_tek_kampanyali_satir_yeterli():
    h = sepet_hesapla(
        [
            SatirGirdi(**P004, adet=1, kampanyali=False),
            SatirGirdi(**P001, adet=1, kampanyali=True),
        ],
        Decimal("750"),
    )
    assert h.toplam == Decimal("55.00")
    assert h.onaylanabilir
    assert h.uyarilar == []


def test_kampanya_kirikken_de_kampanyali_siparis_muaf(monkeypatch):
    monkeypatch.setenv("BREAK_CAMPAIGN", "1")
    h = sepet_hesapla([SatirGirdi(**P001, adet=7, kampanyali=True)], Decimal("750"))
    assert h.indirim == Decimal("0.00")
    assert h.onaylanabilir


def test_min_siparis_indirim_sonrasi_toplama_bakar():
    # Kampanyasız siparişte eşik indirim sonrası toplama uygulanır (indirim yok: toplam = ara).
    h = sepet_hesapla([SatirGirdi(**P004, adet=24, kampanyali=False)], Decimal("750"))
    assert h.toplam == Decimal("720.00")
    assert not h.onaylanabilir


def test_min_siparis_tam_esik_kabul():
    h = sepet_hesapla([SatirGirdi(**P004, adet=25, kampanyali=False)], Decimal("750"))
    assert h.toplam == Decimal("750.00")
    assert h.onaylanabilir
    assert h.uyarilar == []


def test_bos_sepet_onaylanamaz_ama_uyari_yok():
    h = sepet_hesapla([], Decimal("750"))
    assert not h.onaylanabilir
    assert h.uyarilar == []
    assert h.toplam == Decimal("0.00")


def test_buyuk_sepet_uyarisiz_onaylanabilir():
    h = sepet_hesapla([SatirGirdi(**P004, adet=100, kampanyali=False)], Decimal("750"))
    assert h.onaylanabilir
    assert h.uyarilar == []


def test_min_siparis_mesaji():
    assert min_siparis_mesaji(Decimal("500")) == "Minimum sipariş tutarı 500,00 TL"


def test_negatif_adet_reddedilir():
    with pytest.raises(ValueError):
        sepet_hesapla([SatirGirdi(**P001, adet=-1, kampanyali=True)], Decimal("0"))


def test_bozuk_parametresi_indirimi_kapatir():
    assert bedava_adet(12, bozuk=True) == 0
    h = sepet_hesapla(
        [SatirGirdi(**P001, adet=7, kampanyali=True)], Decimal("750"), hata="kampanya_bedava_yok"
    )
    assert (h.indirim, h.toplam) == (Decimal("0.00"), Decimal("175.00"))
