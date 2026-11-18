"""Bayi girişi (TPD-4) — Java testler/GirisTesti.java, CikisTesti.java karşılığı."""

from __future__ import annotations

from typing import Any

import pytest

from altyapi.bayiler import Bayi
from ekranlar.giris_ekrani import GirisEkrani
from ekranlar.katalog_ekrani import KatalogEkrani


@pytest.mark.duman
def test_dogru_bilgilerle_giris_yapilir(driver: Any, dealer: Bayi) -> None:
    giris_ekrani, katalog_ekrani = GirisEkrani(driver), KatalogEkrani(driver)
    giris_ekrani.ac()
    giris_ekrani.giris_yap(dealer.kullanici_adi, dealer.parola)
    giris_ekrani.dogrula_giris_yapildi(dealer.ad)
    katalog_ekrani.dogrula_urun_gorunur("P-001")


def test_hatali_parolada_hata_mesaji(driver: Any, dealer: Bayi) -> None:
    giris_ekrani = GirisEkrani(driver)
    giris_ekrani.ac()
    giris_ekrani.giris_yap(dealer.kullanici_adi, "YanlisParola1")
    giris_ekrani.dogrula_hata_mesaji("Kullanıcı adı veya parola hatalı")
    giris_ekrani.dogrula_giris_ekraninda()


@pytest.mark.oturumlu
def test_cikis_yapinca_giris_ekranina_donulur(driver: Any) -> None:
    giris_ekrani = GirisEkrani(driver)
    giris_ekrani.cikis_yap()
    giris_ekrani.dogrula_giris_ekraninda()
