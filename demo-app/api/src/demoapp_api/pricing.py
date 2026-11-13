"""Sepet hesabı: satır tutarları, kampanya indirimi, minimum sipariş kontrolü.

Saf fonksiyonlar; veritabanı bilmez. Kampanya kuralı `campaign.bedava_adet`, ekilmiş hatalar
(`hata`: bayi bazlı kod, yoksa normal hesap) `faults.py` içindedir.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from demoapp_api import faults
from demoapp_api.money import format_tl, tutar

UYARI_MIN_SIPARIS = "min_siparis"


@dataclass(frozen=True)
class SatirGirdi:
    urun_kod: str
    urun_ad: str
    birim_fiyat: Decimal
    adet: int
    kampanyali: bool


@dataclass(frozen=True)
class SatirSonuc:
    urun_kod: str
    urun_ad: str
    birim_fiyat: Decimal
    adet: int
    kampanyali: bool
    bedava_adet: int
    ucretli_adet: int
    ara_tutar: Decimal
    indirim: Decimal
    satir_tutari: Decimal


@dataclass(frozen=True)
class Uyari:
    kod: str
    mesaj: str


@dataclass(frozen=True)
class SepetSonuc:
    satirlar: list[SatirSonuc]
    adet_toplam: int
    ara_toplam: Decimal
    indirim: Decimal
    toplam: Decimal
    min_siparis_tutari: Decimal
    min_siparis_saglandi: bool
    onaylanabilir: bool
    uyarilar: list[Uyari] = field(default_factory=list)


def min_siparis_mesaji(min_tutar: Decimal) -> str:
    return f"Minimum sipariş tutarı {format_tl(min_tutar)}"


def satir_hesapla(girdi: SatirGirdi, hata: str | None = None) -> SatirSonuc:
    if girdi.adet < 0:
        raise ValueError("adet negatif olamaz")
    fiyat = tutar(girdi.birim_fiyat)
    bedava = faults.bedava_adet(girdi.adet, hata) if girdi.kampanyali else 0
    bedava = max(0, min(bedava, girdi.adet))
    ara = tutar(fiyat * girdi.adet)
    indirim = tutar(fiyat * bedava * faults.indirim_kati(hata))
    return SatirSonuc(
        urun_kod=girdi.urun_kod,
        urun_ad=girdi.urun_ad,
        birim_fiyat=fiyat,
        adet=girdi.adet,
        kampanyali=girdi.kampanyali,
        bedava_adet=bedava,
        ucretli_adet=girdi.adet - bedava,
        ara_tutar=ara,
        indirim=indirim,
        satir_tutari=ara - indirim,
    )


def sepet_hesapla(
    girdiler: list[SatirGirdi], min_siparis_tutari: Decimal, hata: str | None = None
) -> SepetSonuc:
    satirlar = [satir_hesapla(g, hata) for g in girdiler]
    ara_toplam = tutar(sum((s.ara_tutar for s in satirlar), Decimal(0)))
    indirim = tutar(sum((s.indirim for s in satirlar), Decimal(0)))
    toplam = ara_toplam - indirim
    min_tutar = tutar(min_siparis_tutari)
    bos = not satirlar
    saglandi = faults.min_saglandi(toplam, min_tutar, hata)
    min_aranir = not any(s.kampanyali for s in satirlar)  # kampanyalı siparişte aranmaz
    uyarilar: list[Uyari] = []
    if not bos and (min_aranir or faults.muafiyet_yok(hata)) and not saglandi:
        uyarilar.append(Uyari(UYARI_MIN_SIPARIS, min_siparis_mesaji(min_tutar)))
    return SepetSonuc(
        satirlar=satirlar,
        adet_toplam=sum(s.adet for s in satirlar),
        ara_toplam=ara_toplam,
        indirim=indirim,
        toplam=toplam,
        min_siparis_tutari=min_tutar,
        min_siparis_saglandi=saglandi,
        onaylanabilir=not bos and not uyarilar,
        uyarilar=uyarilar,
    )
