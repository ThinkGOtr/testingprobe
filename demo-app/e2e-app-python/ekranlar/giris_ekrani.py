"""Bayi giriş ekranı (Java: ekranlar/GirisEkrani.java; web: LoginPage)."""

from __future__ import annotations

from ekranlar.ekran import Ekran, _id
from ekranlar.kimlikler import GIRIS, KATALOG, MENU


class GirisEkrani(Ekran):
    """Bayi giriş ekranı."""

    def ac(self) -> None:
        """Giriş ekranını açar (uygulama her testte sıfırdan, giriş ekranında başlar)."""
        self._gorunur_bekle(_id(GIRIS["KULLANICI_ADI"]))

    def giris_yap(self, kullanici_adi: str, parola: str) -> None:
        """Bayi kullanıcı adı ve parolasıyla giriş yapar."""
        self._yaz(_id(GIRIS["KULLANICI_ADI"]), kullanici_adi)
        self._yaz(_id(GIRIS["PAROLA"]), parola)
        self._dokun(_id(GIRIS["GIRIS_YAP"]))

    def cikis_yap(self) -> None:
        """Oturumu kapatır."""
        self._dokun(_id(MENU["CIKIS"]))

    def dogrula_hata_mesaji(self, beklenen: str) -> None:
        """Hata mesajının göründüğünü ve metnini doğrular."""
        self._metin_olmali(_id(GIRIS["HATA"]), beklenen)

    def dogrula_giris_yapildi(self, bayi_adi: str) -> None:
        """Verilen bayi adıyla oturum açıldığını ve kataloğun açıldığını doğrular."""
        self._metin_olmali(_id(MENU["BAYI_ADI"]), bayi_adi)
        self._gorunur_olmali(_id(KATALOG["URUN_LISTESI"]))

    def dogrula_giris_ekraninda(self) -> None:
        """Giriş ekranında olunduğunu doğrular."""
        self._gorunur_olmali(_id(GIRIS["GIRIS_YAP"]))
        self._yok_olmali(_id(MENU["BAYI_ADI"]))
