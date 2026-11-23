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
        self._alanlari_yaz_ve_gonder(kullanici_adi, parola)
        # iOS: güvenli parola alanında tuş vuruşu yanlış karaktere düşebiliyor.
        self._ios_hatada_yeniden_dene(kullanici_adi, parola)

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

    # ------------------------------------------------ yardımcılar (sınıf sonunda: satırlar kaymasın)

    def _alanlari_yaz_ve_gonder(self, kullanici_adi: str, parola: str) -> None:
        self._yaz(_id(GIRIS["KULLANICI_ADI"]), kullanici_adi)
        self._yaz(_id(GIRIS["PAROLA"]), parola)
        self._dokun(_id(GIRIS["GIRIS_YAP"]))

    def _ios_hatada_yeniden_dene(self, kullanici_adi: str, parola: str) -> None:
        """iOS: parola güvenli alandır, değeri yalnız maskeli okunur; içerik doğrulanamaz. iOS 27
        simülatöründe tuş vuruşu ara sıra yanlış karaktere düşüyor (uzunluk aynı, API 401). Giriş
        hatası görünürse alanlar bir kez yeniden yazılıp gönderilir (Java GirisEkrani eşi); gerçekten
        yanlış parolada ikinci deneme de aynı hatayı verir."""
        if self._o.platform == "ios" and self._giris_hatasi_gorundu():
            self._alanlari_yaz_ve_gonder(kullanici_adi, parola)

    def _giris_hatasi_gorundu(self) -> bool:
        """Gönderimden sonra giriş tamamlanana ya da hata görünene kadar bekler; hata göründüyse True."""
        from selenium.common.exceptions import TimeoutException

        def sonuc() -> str | None:
            if self._hemen_bul(None, _id(GIRIS["HATA"])) is not None:
                return "hata"
            return "giris" if self._hemen_bul(None, _id(MENU["BAYI_ADI"])) is not None else None

        try:
            return self._o.bekle.kosul("giriş sonucu görünmedi", sonuc) == "hata"
        except TimeoutException:
            return False
