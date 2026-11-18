# AI-generated — AI Testing Probe (CasesToCode). Elle düzenlemeyin; değişiklik case'in yeniden
# onayı ve yeniden üretimle yapılır.
# Case: TPD-1 C3 (0a1b2c3d-0000-4000-8000-000000000003) · Story: TPD-1 · Jira Test: TPD-T3
# Onaylı case hash: ornek-referans-dosyasi
# Eşleme: verify_and_map_app · platform: android · dil: python · mod: ornek · bundle: ornek
# Eşleme hash: ornek · şablon: ornek
import pytest

from ekranlar.giris_ekrani import GirisEkrani
from ekranlar.katalog_ekrani import KatalogEkrani
from ekranlar.sepet_ekrani import SepetEkrani


@pytest.mark.uretilen
@pytest.mark.android
@pytest.mark.tp_case("0a1b2c3d-0000-4000-8000-000000000003")
@pytest.mark.story("TPD-1")
@pytest.mark.dealer("bayi2")
def test_tpd_1_android_c3_0a1b2c3d(driver) -> None:
    giris_ekrani = GirisEkrani(driver)
    katalog_ekrani = KatalogEkrani(driver)
    sepet_ekrani = SepetEkrani(driver)

    # 1 — bayi2 / Demo123! ile giriş yapılır
    giris_ekrani.giris_yap("bayi2", "Demo123!")
    # 2 — Katalogda P-001 ürününden 7 adet sepete eklenir
    katalog_ekrani.sepete_ekle("P-001", 7)
    # 3 — Sepet açılır
    katalog_ekrani.sepeti_ac()
    # Beklenen sonuç (değerler onaylı case metninden)
    sepet_ekrani.dogrula_bedava_adet("P-001", 1)
    sepet_ekrani.dogrula_indirim("25,00 TL")
    sepet_ekrani.dogrula_toplam("150,00 TL")
