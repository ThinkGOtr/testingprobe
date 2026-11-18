"""Ürün kataloğu ekranı (Java: ekranlar/KatalogEkrani.java; web: CatalogPage)."""

from __future__ import annotations

from altyapi.kimlik import ekli
from ekranlar.ekran import Ekran, _id
from ekranlar.kimlikler import KATALOG, MENU, SEPET

# Başarılı eklemede ürün kartındaki bilgi mesajının parçası (web: "{n} adet sepete eklendi.").
_EKLENDI = "sepete eklendi"


class KatalogEkrani(Ekran):
    """Ürün kataloğu ekranı."""

    @staticmethod
    def _kart(urun_kodu: str) -> str:
        return ekli(_id(KATALOG["URUN_KARTI_ONEK"]), urun_kodu)

    def ac(self) -> None:
        """Katalog ekranını açar."""
        self._dokun(_id(MENU["KATALOG"]))
        self._gorunur_bekle(_id(KATALOG["URUN_LISTESI"]))

    def menuden_ac(self) -> None:
        """Üst menüden kataloğa gider."""
        self.ac()

    def adet_gir(self, urun_kodu: str, adet: int) -> None:
        """Ürün kartındaki adet alanına değer yazar."""
        self._yaz(ekli(_id(KATALOG["ADET_ONEK"]), urun_kodu), str(adet))

    def sepete_ekle(self, urun_kodu: str, adet: int) -> None:
        """Ürün kartında adedi girip "Sepete ekle" butonuna basar ve sepetin güncellenmesini
        bekler."""
        once = self._sepet_sayaci()
        self.adet_gir(urun_kodu, adet)
        self._dokun(_id(KATALOG["SEPETE_EKLE"]), self._kart(urun_kodu))
        durum = ekli(_id(KATALOG["EKLEME_DURUMU_ONEK"]), urun_kodu)

        def tamam() -> bool | None:
            oge = self._hemen_bul(None, durum)
            mesaj = "" if oge is None else self._metin(oge)
            if mesaj and _EKLENDI not in mesaj:
                raise AssertionError(f"sepete ekleme başarısız: {mesaj}")
            return True if _EKLENDI in mesaj and self._sayac_hemen() == once + adet else None

        # Web isteğin yanıtını bekler; uygulamada ağ görünmez: kart mesajı + sayaç artışı.
        self._o.bekle.kosul(
            f"sepete ekleme tamamlanmadı: '{durum}' mesajı ve sepet sayacı {once + adet}", tamam
        )

    def sepeti_ac(self) -> None:
        """Üst menüden sepete gider."""
        self._dokun(_id(MENU["SEPET"]))
        self._biri_gorunur_bekle(_id(SEPET["TABLO"]), _id(SEPET["BOS"]))

    def dogrula_urun_gorunur(self, urun_kodu: str) -> None:
        """Ürün kartının katalogda göründüğünü doğrular."""
        self._gorunur_olmali(self._kart(urun_kodu))

    def dogrula_urun_fiyati(self, urun_kodu: str, fiyat: str) -> None:
        """Ürün kartındaki fiyatın verilen tutar olduğunu doğrular (ör. "25,00 TL")."""
        self._metin_olmali(ekli(_id(KATALOG["URUN_FIYATI_ONEK"]), urun_kodu), fiyat)

    def dogrula_kampanya(self, urun_kodu: str, kampanya_adi: str) -> None:
        """Ürün kartında verilen kampanya adının göründüğünü doğrular (ör. "6 al 1 bedava")."""
        self._metin_icermeli(self._kart(urun_kodu), kampanya_adi, tum=True)

    def dogrula_sepet_sayaci(self, adet: int) -> None:
        """Üst menüdeki sepet sayacının verilen adet olduğunu doğrular."""
        self._metin_olmali(_id(MENU["SEPET_SAYACI"]), str(adet))

    # ------------------------------------------------ yardımcılar (sembol tablosu dışı)

    def _sepet_sayaci(self) -> int:
        sayac = _id(MENU["SEPET_SAYACI"])
        self._gorunur_bekle(sayac)
        return self._o.bekle.kosul(
            f"sepet sayacı okunamadı: kimlik '{sayac}'",
            lambda: n if (n := self._sayac_hemen()) >= 0 else None,
        )

    def _sayac_hemen(self) -> int:
        """Sayacı beklemeden okur; yoksa ya da sayı değilse -1."""
        e = self._hemen_bul(None, _id(MENU["SEPET_SAYACI"]))
        if e is None:
            return -1
        try:
            return int(self._metin(e))
        except ValueError:
            return -1
