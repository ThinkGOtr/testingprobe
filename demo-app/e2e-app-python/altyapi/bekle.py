"""Deterministik bekleme (Java: altyapi/Bekle.java). Yalnız açık bekleme; örtük bekleme 0.

İki hata türü bilerek ayrıdır — triage ve kırarak doğrulama buna dayanır:

- `kosul`: eylem ön koşulu (öğe bulunamadı / tıklanamadı) → selenium `TimeoutException`
  (JUnit XML `<failure type="selenium.common.exceptions.TimeoutException">`; locator hatası).
- `dogrula`: beklenen sonuç → `AssertionError` ("…: beklenen <x>, görülen <y> (N ms)").
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)

T = TypeVar("T")
ARALIK_S = 0.25
_YOK_SAYILAN = (NoSuchElementException, StaleElementReferenceException)


class Bekle:
    def __init__(self, ust_sinir_s: float) -> None:
        self.ust_sinir_s = ust_sinir_s

    def kosul(self, aciklama: str, kosul: Callable[[], T | None]) -> T:
        """Koşul None/False dışında bir değer döndürene kadar bekler ve o değeri döndürür."""
        bitis = time.monotonic() + self.ust_sinir_s
        while True:
            try:
                deger = kosul()
            except _YOK_SAYILAN:
                deger = None
            if deger is not None and deger is not False:
                return deger
            if time.monotonic() >= bitis:
                raise TimeoutException(aciklama)
            time.sleep(ARALIK_S)

    def dogrula(
        self,
        aciklama: str,
        beklenen: str,
        gorulen: Callable[[], str],
        saglandi: Callable[[], bool],
    ) -> None:
        """Beklenen sonuç sağlanana kadar bekler; sağlanmazsa son görülen değerle AssertionError."""
        try:
            self.kosul(aciklama, lambda: True if saglandi() else None)
        except TimeoutException:
            try:
                son = gorulen()
            except Exception as exc:  # noqa: BLE001 - okuma hatası beklentiyi gölgelemez
                son = f"(okunamadı: {type(exc).__name__})"
            raise AssertionError(
                f"{aciklama}: beklenen <{beklenen}>, görülen <{son}> "
                f"({int(self.ust_sinir_s * 1000)} ms)"
            ) from None
