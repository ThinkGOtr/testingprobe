"""Sepet ekranı (Java: ekranlar/SepetEkrani.java; web: CartPage)."""

from __future__ import annotations

from altyapi.kimlik import ekli
from ekranlar.ekran import Ekran, _id
from ekranlar.kimlikler import MENU, ONAY, SEPET


class SepetEkrani(Ekran):
    """Sepet ekranı: satırlar, kampanya, toplamlar ve sipariş onayı."""

    def ac(self) -> None:
        """Sepet ekranını açar."""
        self._dokun(_id(MENU["SEPET"]))
        self._biri_gorunur_bekle(_id(SEPET["TABLO"]), _id(SEPET["BOS"]))

    def urunu_kaldir(self, urun_kodu: str) -> None:
        """Ürünü sepetten kaldırır."""
        self._dokun(ekli(_id(SEPET["SATIRI_KALDIR_ONEK"]), urun_kodu))
        satir = ekli(_id(SEPET["SATIR_ONEK"]), urun_kodu)
        self._o.bekle.kosul(f"satır sepetten kalkmadı: kimlik '{satir}'",
                            lambda: True if self._hemen_bul(None, satir) is None else None)  # fmt: skip

    def siparisi_onayla(self) -> None:
        """"Siparişi onayla" butonuna basar ve onay ekranının açılmasını bekler."""
        self._dokun(_id(SEPET["SIPARISI_ONAYLA"]))
        self._gorunur_bekle(_id(ONAY["ONAY_ALANI"]))

    def dogrula_satir_adedi(self, urun_kodu: str, adet: int) -> None:
        """Sepet satırındaki adedi doğrular."""
        self._metin_olmali(ekli(_id(SEPET["SATIR_ADEDI_ONEK"]), urun_kodu), str(adet))

    def dogrula_bedava_adet(self, urun_kodu: str, adet: int) -> None:
        """Sepet satırında kampanyayla bedava verilen adedi doğrular."""
        self._metin_olmali(ekli(_id(SEPET["BEDAVA_ADET_ONEK"]), urun_kodu), str(adet))

    def dogrula_satir_toplami(self, urun_kodu: str, tutar: str) -> None:
        """Sepet satırının indirim sonrası tutarını doğrular (ör. "150,00 TL")."""
        self._metin_olmali(ekli(_id(SEPET["SATIR_TOPLAMI_ONEK"]), urun_kodu), tutar)

    def dogrula_ara_toplam(self, tutar: str) -> None:
        """Ara toplamı doğrular (ör. "175,00 TL")."""
        self._metin_olmali(_id(SEPET["ARA_TOPLAM"]), tutar)

    def dogrula_indirim(self, tutar: str) -> None:
        """Kampanya indirimi tutarını doğrular (ör. "25,00 TL")."""
        self._metin_olmali(_id(SEPET["INDIRIM"]), tutar)

    def dogrula_toplam(self, tutar: str) -> None:
        """Sepetin indirim sonrası genel toplamını doğrular (ör. "150,00 TL")."""
        self._metin_olmali(_id(SEPET["TOPLAM"]), tutar)

    def dogrula_minimum_siparis_uyarisi(self, mesaj: str) -> None:
        """Minimum sipariş uyarısının verilen metni içerdiğini doğrular."""
        self._metin_icermeli(_id(SEPET["MIN_SIPARIS_UYARISI"]), mesaj)

    def dogrula_minimum_siparis_uyarisi_yok(self) -> None:
        """Minimum sipariş uyarısının gösterilmediğini doğrular."""
        self._yok_olmali(_id(SEPET["MIN_SIPARIS_UYARISI"]))

    def dogrula_onay_pasif(self) -> None:
        """"Siparişi onayla" butonunun pasif olduğunu doğrular."""
        self._etkin_olmali(_id(SEPET["SIPARISI_ONAYLA"]), False)

    def dogrula_onay_aktif(self) -> None:
        """"Siparişi onayla" butonunun aktif olduğunu doğrular."""
        self._etkin_olmali(_id(SEPET["SIPARISI_ONAYLA"]), True)

    def dogrula_urun_sepette_yok(self, urun_kodu: str) -> None:
        """Sepette ürünün bulunmadığını doğrular."""
        self._yok_olmali(ekli(_id(SEPET["SATIR_ONEK"]), urun_kodu))

    def dogrula_sepet_sayaci(self, adet: int) -> None:
        """Üst menüdeki sepet sayacının verilen adet olduğunu doğrular (sepet ekranında)."""
        self._metin_olmali(_id(MENU["SEPET_SAYACI"]), str(adet))

    def dogrula_sepet_bos(self) -> None:
        """Sepetin boş olduğunu doğrular."""
        self._gorunur_olmali(_id(SEPET["BOS"]))
