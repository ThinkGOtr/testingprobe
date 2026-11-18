"""Ekran nesnelerinin tabanı (Java: ekranlar/Ekran.java): platformdan bağımsız, kimlik
sabitleriyle çalışan yardımcılar.

Sözleşme: alt sınıfların public (alt çizgisiz) metotları sembol tablosuna girer — eylem (fiil) ya
da beklenti (`dogrula_` ön eki); dönüş `None`, parametreler yalnız `str | int | float | bool`. Bu
sınıfın yardımcıları `_` ile başlar, sembol tablosuna girmez.

Hata türleri: eylem ön koşulu sağlanmazsa (öğe yok, tıklanamıyor) `TimeoutException` ("öğe
görünmedi: kimlik 'x'" / "kimlik 'kapsayıcı' içinde 'aranan'"); beklenti sağlanmazsa
`AssertionError`. Metin karşılaştırması web `toHaveText` gibi boşlukları sadeleştirir (NBSP dahil).
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from typing import Any

from selenium.common.exceptions import WebDriverException

from altyapi import kimlik as kimlikmod
from altyapi.oturum import oturum

YOK = "(öğe yok)"
_METIN_NITELIKLERI = ("label", "value", "Name", "content-desc", "text")
_KENAR = 4
# iOS klavye kapatma sürüklemesi (Java Klavye.MESAFE / PAY): klavyenin üst kenarının PAY kadar
# üstünden MESAFE kadar yukarı. PAY: iOS 27'de görünen klavye kabı öğe çerçevesinin ~17 pt, öneri
# şeridi ~44 pt üstünden başlar; 16 pt sürüklemeyi klavyeye düşürüyordu.
_KLAVYE_MESAFE = 40
_KLAVYE_PAY = 72
# Sürükleme kabın üst bölümünde başlar (Java Klavye.UST_BOSLUK): bayat klavye çerçevesi (y=764,
# gerçekte 550) yalnız çerçeveye göre hesaplanan noktayı tuşlara düşürüyordu ("bayi1" → "bayi1q").
_KLAVYE_UST_BOSLUK = 96


def _id(spec: Mapping[str, str]) -> str:
    return spec["testId"]


def _ad(kapsayici: str | None, kimlik: str) -> str:
    return f"'{kimlik}'" if kapsayici is None else f"'{kapsayici}' içinde '{kimlik}'"


def _klavye_suruklemesi(kap: Mapping[str, int], klavye_ust: int) -> tuple[int, int, int] | None:
    """iOS klavye kapatma çizgisi (Java `Klavye.surukleme`, saf hesap): (x, başlangıç y, bitiş y).
    Sürükleme kabın KLAVYENİN ÜSTÜNDE kalan bölümünde yapılır (klavye tuşlarına dokunmaz); o bölüm
    yetmiyorsa None."""
    alt = min(kap["y"] + _KLAVYE_UST_BOSLUK, min(kap["y"] + kap["height"], klavye_ust) - _KLAVYE_PAY)
    ust = alt - _KLAVYE_MESAFE
    if kap["width"] <= 2 * _KENAR or ust <= kap["y"]:
        return None
    return kap["x"] + _KENAR, alt, ust


def _deger_tutuyor(okunan: str | None, metin: str) -> bool:
    """Java `Klavye.degerTutuyor` eşi: okunamayan/boş değer kabul; maskeli (•••) değerde uzunluk."""
    if not okunan:
        return True
    if all(c in "•●*" for c in okunan):
        return len(okunan) == len(metin)
    return _sade(okunan) == _sade(metin)


def _sade(s: str | None) -> str:
    """NBSP / dar NBSP → boşluk, ardışık boşluk → tek, baş/son kırpılır."""
    return re.sub(r"\s+", " ", (s or "").replace(" ", " ").replace(" ", " ")).strip()


class Ekran:
    def __init__(self, driver: Any) -> None:
        self._d = driver
        self._o = oturum(driver)

    # ------------------------------------------------------------------ bulma

    def _bul(self, kimlik: str) -> tuple[str, str]:
        return kimlikmod.bul(self._o.strateji, kimlik)

    def _ilk_gorunur(self, kapsayici: str | None, kimlik: str) -> Any:
        kokler = [self._d] if kapsayici is None else self._d.find_elements(*self._bul(kapsayici))
        for kok in kokler:
            for e in kok.find_elements(*self._bul(kimlik)):
                if e.is_displayed():
                    return e
        return None

    def _kaydir(self, kapsayici: str | None, kimlik: str) -> None:
        """Ekran dışındaki öğeyi görünür alana getirmeyi bir kez dener (Java: Kaydirma.getir).
        Android: UiScrollable; iOS: kaydırma kabında kısa sürükleme; Windows: kaydırma yok."""
        try:
            if self._o.platform == "android":
                s = self._o.strateji
                hedef = kimlikmod.ui_selector(s, kimlik)
                if kapsayici is not None:
                    hedef = f"{kimlikmod.ui_selector(s, kapsayici)}.childSelector({hedef})"
                self._d.find_elements(
                    kimlikmod.UIAUTOMATOR,
                    "new UiScrollable(new UiSelector().scrollable(true))"
                    f".scrollIntoView({hedef})",
                )
            elif self._o.platform == "ios":
                kok = self._d
                if kapsayici is not None:
                    k = self._d.find_elements(*self._bul(kapsayici))
                    if not k:
                        return
                    kok = k[0]
                ogeler = kok.find_elements(*self._bul(kimlik))
                if ogeler and not ogeler[0].is_displayed():
                    self._ios_surukle(ogeler[0].rect)
        except WebDriverException:
            pass  # kaydırılabilir kap yok / öğe kayboldu: bekleme döngüsü yeniden dener

    def _ios_surukle(self, hedef: Mapping[str, int]) -> None:
        kap = None
        for k in self._d.find_elements("class name", "XCUIElementTypeScrollView"):
            r = k.rect
            if k.is_displayed() and (kap is None or r["height"] > kap["height"]):
                kap = r
        if kap is None or kap["height"] < 50 or kap["width"] <= 2 * _KENAR:
            return
        alt, ust = kap["y"] + kap["height"] * 3 // 4, kap["y"] + kap["height"] * 7 // 20
        x = kap["x"] + _KENAR
        ustte = hedef["y"] + hedef["height"] <= kap["y"]
        bas, son = (ust, alt) if ustte else (alt, ust)
        self._d.execute_script(
            "mobile: dragFromToForDuration",
            {"duration": 0.2, "fromX": x, "fromY": bas, "toX": x, "toY": son},
        )

    def _hemen_bul(self, kapsayici: str | None, kimlik: str) -> Any:
        """Öğeyi beklemeden bir kez arar (gerekirse bir kez kaydırır); görünür değilse None."""
        e = self._ilk_gorunur(kapsayici, kimlik)
        if e is not None:
            return e
        self._kaydir(kapsayici, kimlik)
        return self._ilk_gorunur(kapsayici, kimlik)

    def _gorunur_bekle(self, kimlik: str, kapsayici: str | None = None) -> Any:
        return self._o.bekle.kosul(
            f"öğe görünmedi: kimlik {_ad(kapsayici, kimlik)}",
            lambda: self._hemen_bul(kapsayici, kimlik),
        )

    def _biri_gorunur_bekle(self, kimlik1: str, kimlik2: str) -> None:
        self._o.bekle.kosul(
            f"öğe görünmedi: kimlik '{kimlik1}' ya da '{kimlik2}'",
            lambda: self._ilk_gorunur(None, kimlik1) is not None
            or self._ilk_gorunur(None, kimlik2) is not None
            or None,
        )

    # ------------------------------------------------------------------ eylemler

    def _dokun(self, kimlik: str, kapsayici: str | None = None) -> None:
        def tiklanabilir() -> Any:
            g = self._hemen_bul(kapsayici, kimlik)
            return g if g is not None and g.is_enabled() else None

        self._o.bekle.kosul(
            f"öğe tıklanabilir olmadı: kimlik {_ad(kapsayici, kimlik)}", tiklanabilir
        ).click()

    def _yaz(self, kimlik: str, metin: str) -> None:
        """Alana metin yazar (önce temizler), sonra ekran klavyesini kapatır."""
        e = self._gorunur_bekle(kimlik)
        # Soğuk simülatörde tuş vuruşları düşebiliyor ("bayi2" → "ba"; Java Ekran.yaz eşi):
        # alanın değeri yazılanı tutmazsa temizleyip yeniden yazılır (en çok 3 deneme).
        for deneme in range(1, 4):
            e.clear()
            e.send_keys(metin)
            if deneme >= 3 or _deger_tutuyor(self._alan_degeri(e), metin):
                break
        self._klavyeyi_kapat()

    @staticmethod
    def _alan_degeri(e: Any) -> str | None:
        try:
            v = e.get_attribute("value")
            return v if v is not None else e.text
        except WebDriverException:
            return None

    def _klavyeyi_kapat(self) -> None:
        if self._o.platform == "windows":
            return
        try:
            if hasattr(self._d, "is_keyboard_shown") and not self._d.is_keyboard_shown():
                return
            if self._o.platform == "ios":
                # XCUITest hideKeyboard yalnız klavye tuşuyla kapatır (number-pad'de yok):
                # uygulamanın `keyboardDismissMode="on-drag"` yolu (Klavye.java notu).
                # Sürükleme klavyenin üstünde kalır (Java Klavye.iosSurukleyerekKapat): kabın 3/4'ünden
                # başlayan genel kaydırma klavye tuşlarına basar, klavye açık kalır.
                # Klavyenin üst kenarı açılış animasyonu oturunca okunur (Java Klavye.oturmusKlavyeUst):
                # erken okunan çerçeve (ör. y=764, oturunca 567) sürüklemeyi tuşlara düşürür.
                for _ in range(3):
                    ust = self._oturmus_klavye_ust()
                    if ust is None or not self._klavye_surukle(ust):
                        return
                    if self._oturmus_klavye_ust() is None or (
                        hasattr(self._d, "is_keyboard_shown") and not self._d.is_keyboard_shown()
                    ):
                        return
                return
            self._d.hide_keyboard()
        except WebDriverException:
            pass  # sonraki eylemin beklemesi (ve kaydırma) devralır

    def _oturmus_klavye_ust(self) -> int | None:
        """Klavye çerçevesinin üst kenarı, art arda iki okumada aynı kalınca; klavye yoksa None."""
        onceki: int | None = None
        for _ in range(12):
            klavye = self._d.find_elements("class name", "XCUIElementTypeKeyboard")
            if not klavye:
                return None
            ust = klavye[0].rect["y"]
            if onceki is not None and onceki == ust:
                return ust
            onceki = ust
            time.sleep(0.15)
        return onceki

    def _klavye_surukle(self, ust: int) -> bool:
        for k in self._d.find_elements("class name", "XCUIElementTypeScrollView"):
            cizgi = _klavye_suruklemesi(k.rect, ust)
            if cizgi is not None:
                x, bas, son = cizgi
                self._d.execute_script(
                    "mobile: dragFromToForDuration",
                    {"duration": 0.2, "fromX": x, "fromY": bas, "toX": x, "toY": son},
                )
                return True
        return False

    # ------------------------------------------------------------------ metin

    def _kendi_metni(self, e: Any) -> str:
        t = e.text
        if t and t.strip():
            return _sade(t)
        for nitelik in _METIN_NITELIKLERI:
            try:
                v = e.get_attribute(nitelik)
            except WebDriverException:
                continue
            if v and v.strip() and v != "null":
                return _sade(v)
        return ""

    def _alt_metinler(self, e: Any) -> str:
        parcalar: list[str] = []
        for alt in e.find_elements("xpath", ".//*"):
            t = self._kendi_metni(alt)
            if t and t not in parcalar:
                parcalar.append(t)
        return _sade(" ".join(parcalar))

    def _metin(self, e: Any) -> str:
        """Kendi metni, yoksa alt öğelerin metinleri (RN'de testID View'da, metin alt Text'te)."""
        return self._kendi_metni(e) or self._alt_metinler(e)

    def _gorulen(self, kimlik: str, tum: bool = False) -> str:
        e = self._hemen_bul(None, kimlik)
        if e is None:
            return YOK
        return _sade(f"{self._kendi_metni(e)} {self._alt_metinler(e)}") if tum else self._metin(e)

    # ------------------------------------------------------------------ beklentiler (AssertionError)

    def _metin_olmali(self, kimlik: str, beklenen: str) -> None:
        b = _sade(beklenen)
        self._o.bekle.dogrula(f"'{kimlik}' metni", b, lambda: self._gorulen(kimlik),
                              lambda: self._gorulen(kimlik) == b)  # fmt: skip

    def _metin_kalibina_uymali(self, kimlik: str, kalip: re.Pattern[str]) -> None:
        self._o.bekle.dogrula(f"'{kimlik}' metni", f"/{kalip.pattern}/",
                              lambda: self._gorulen(kimlik),
                              lambda: kalip.fullmatch(self._gorulen(kimlik)) is not None)  # fmt: skip

    def _metin_icermeli(self, kimlik: str, parca: str, tum: bool = False) -> None:
        p = _sade(parca)
        ne = "içeriği" if tum else "metni"
        self._o.bekle.dogrula(f"'{kimlik}' {ne}", f"… {p} …", lambda: self._gorulen(kimlik, tum),
                              lambda: p in self._gorulen(kimlik, tum))  # fmt: skip

    def _gorunur_olmali(self, kimlik: str) -> None:
        self._o.bekle.dogrula(f"'{kimlik}' görünürlüğü", "görünür", lambda: YOK,
                              lambda: self._hemen_bul(None, kimlik) is not None)  # fmt: skip

    def _yok_olmali(self, kimlik: str) -> None:
        self._o.bekle.dogrula(f"'{kimlik}' yokluğu", YOK, lambda: "görünür",
                              lambda: self._hemen_bul(None, kimlik) is None)  # fmt: skip

    def _etkin_olmali(self, kimlik: str, etkin: bool) -> None:
        def durum() -> str:
            e = self._hemen_bul(None, kimlik)
            return YOK if e is None else ("etkin" if e.is_enabled() else "pasif")

        beklenen = "etkin" if etkin else "pasif"
        self._o.bekle.dogrula(f"'{kimlik}' durumu", beklenen, durum, lambda: durum() == beklenen)
