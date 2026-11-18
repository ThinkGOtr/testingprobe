"""Sipariş onayı ekranı (Java: ekranlar/OnayEkrani.java).

Web `readOrderNumber()` değer döndürür; ekran nesnesi sözleşmesinde yalnız `None` dönen metot
olduğundan okunan numara oturumda saklanır (`SiparisEkrani.dogrula_onaylanan_siparis_toplami`).
"""

from __future__ import annotations

import re

from ekranlar.ekran import Ekran, _id
from ekranlar.kimlikler import KATALOG, ONAY, SIPARIS
from ekranlar.siparis_ekrani import SiparisEkrani

_SIPARIS_NUMARASI = re.compile(r"SP-\d{6}")


class OnayEkrani(Ekran):
    """Sipariş onayı ekranı."""

    def _siparis_numarasini_oku(self) -> str:
        kimlik = _id(ONAY["SIPARIS_NUMARASI"])
        self._metin_kalibina_uymali(kimlik, _SIPARIS_NUMARASI)
        numara = self._metin(self._gorunur_bekle(kimlik))
        self._o.son_siparis_numarasi = numara
        return numara

    def dogrula_siparis_onayi(self) -> None:
        """Sipariş onayının ve sipariş numarasının gösterildiğini doğrular."""
        self._gorunur_olmali(_id(ONAY["ONAY_ALANI"]))
        self._siparis_numarasini_oku()

    def dogrula_onaylanan_toplam(self, tutar: str) -> None:
        """Onaylanan siparişin genel toplamını doğrular (ör. "1.025,00 TL")."""
        self._metin_olmali(_id(ONAY["TOPLAM"]), tutar)

    def dogrula_onaylanan_indirim(self, tutar: str) -> None:
        """Onaylanan siparişin kampanya indirimini doğrular (ör. "25,00 TL")."""
        self._metin_olmali(_id(ONAY["INDIRIM"]), tutar)

    def dogrula_onaylanan_siparis_gecmiste(self) -> None:
        """Onay ekranında gösterilen siparişin sipariş geçmişinde listelendiğini doğrular."""
        numara = self._siparis_numarasini_oku()
        gecmis = SiparisEkrani(self._d)
        gecmis.menuden_ac()
        gecmis.dogrula_siparis_gecmiste(numara)

    def siparislerime_git(self) -> None:
        """Onay ekranından "Siparişlerime git" ile sipariş geçmişine gider."""
        self._dokun(_id(ONAY["SIPARISLERIME_GIT"]))
        self._biri_gorunur_bekle(_id(SIPARIS["TABLO"]), _id(SIPARIS["BOS"]))

    def alisverise_devam_et(self) -> None:
        """Onay ekranından "Alışverişe devam et" ile kataloğa döner."""
        self._dokun(_id(ONAY["ALISVERISE_DEVAM"]))
        self._gorunur_bekle(_id(KATALOG["URUN_LISTESI"]))
