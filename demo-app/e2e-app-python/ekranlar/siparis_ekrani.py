"""Sipariş geçmişi (Siparişlerim) ekranı (Java: ekranlar/SiparisEkrani.java)."""

from __future__ import annotations

from altyapi.kimlik import ekli
from ekranlar.ekran import Ekran, _id
from ekranlar.kimlikler import MENU, SIPARIS


class SiparisEkrani(Ekran):
    """Sipariş geçmişi ekranı."""

    def ac(self) -> None:
        """Sipariş geçmişi ekranını açar."""
        self._dokun(_id(MENU["SIPARISLER"]))
        self._biri_gorunur_bekle(_id(SIPARIS["TABLO"]), _id(SIPARIS["BOS"]))

    def menuden_ac(self) -> None:
        """Üst menüden sipariş geçmişine gider."""
        self.ac()

    def dogrula_siparis_gecmiste(self, siparis_no: str) -> None:
        """Verilen sipariş numarasının sipariş geçmişinde listelendiğini doğrular."""
        self._gorunur_olmali(ekli(_id(SIPARIS["SATIR_ONEK"]), siparis_no))

    def dogrula_siparis_toplami(self, siparis_no: str, tutar: str) -> None:
        """Sipariş geçmişindeki siparişin genel toplamını doğrular."""
        self._metin_olmali(ekli(_id(SIPARIS["SATIR_TOPLAMI_ONEK"]), siparis_no), tutar)

    def dogrula_onaylanan_siparis_toplami(self, tutar: str) -> None:
        """Bu testte onay ekranında görülen son siparişin geçmişteki genel toplamını doğrular."""
        numara = self._o.son_siparis_numarasi
        if numara is None:
            raise RuntimeError(
                "bu testte onaylanmış sipariş yok (önce onay ekranı doğrulanmalı)"
            )
        self.dogrula_siparis_toplami(numara, tutar)

    def dogrula_siparis_yok(self) -> None:
        """Sipariş geçmişinin boş olduğunu doğrular."""
        self._gorunur_olmali(_id(SIPARIS["BOS"]))
