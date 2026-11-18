"""Katalog ve sepet (TPD-1) — Java testler/SepetTesti.java karşılığı (temsilî alt küme).

6 adet sınırı bilerek doğrulanmaz (demo senaryosuna bağlı); yalnız 7 → 1 bedava doğrulanır.
"""

from __future__ import annotations

from typing import Any

import pytest

from ekranlar.katalog_ekrani import KatalogEkrani
from ekranlar.sepet_ekrani import SepetEkrani

pytestmark = pytest.mark.oturumlu


@pytest.fixture
def katalog_ekrani(driver: Any) -> KatalogEkrani:
    ekran = KatalogEkrani(driver)
    ekran.ac()
    return ekran


@pytest.mark.duman
def test_katalog_fiyatlari(katalog_ekrani: KatalogEkrani) -> None:
    katalog_ekrani.dogrula_urun_fiyati("P-001", "25,00 TL")
    katalog_ekrani.dogrula_urun_fiyati("P-002", "15,00 TL")
    katalog_ekrani.dogrula_kampanya("P-001", "6 al 1 bedava")


@pytest.mark.kampanya
def test_kampanya_yedi_adet(driver: Any, katalog_ekrani: KatalogEkrani) -> None:
    sepet_ekrani = SepetEkrani(driver)
    katalog_ekrani.sepete_ekle("P-001", 7)
    katalog_ekrani.sepeti_ac()
    sepet_ekrani.dogrula_satir_adedi("P-001", 7)
    sepet_ekrani.dogrula_bedava_adet("P-001", 1)
    sepet_ekrani.dogrula_ara_toplam("175,00 TL")
    sepet_ekrani.dogrula_indirim("25,00 TL")
    sepet_ekrani.dogrula_toplam("150,00 TL")


@pytest.mark.kampanya
def test_kampanyasiz_urunde_bedava_yok(driver: Any, katalog_ekrani: KatalogEkrani) -> None:
    sepet_ekrani = SepetEkrani(driver)
    katalog_ekrani.sepete_ekle("P-002", 12)
    katalog_ekrani.sepeti_ac()
    sepet_ekrani.dogrula_bedava_adet("P-002", 0)
    sepet_ekrani.dogrula_indirim("0,00 TL")
