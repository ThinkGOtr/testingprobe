"""Uygulama oturumu durumu (Java: altyapi/UygulamaOturumu.java): sürücü başına bekleme ve
testte onay ekranında görülen son sipariş numarası.

Ekran nesneleri yalnız sürücüyü alır (`GirisEkrani(driver)`; şablon sözleşmesi); paylaşılan
durum burada sürücüye bağlanır. conftest `driver` fikstürü oturumu `kaydet` ile kurar.
"""

from __future__ import annotations

import weakref
from dataclasses import dataclass
from typing import Any

from altyapi.bekle import Bekle


@dataclass
class Oturum:
    platform: str
    strateji: str
    bekle: Bekle
    son_siparis_numarasi: str | None = None


_OTURUMLAR: weakref.WeakKeyDictionary[Any, Oturum] = weakref.WeakKeyDictionary()


def kaydet(surucu: Any, oturum: Oturum) -> None:
    _OTURUMLAR[surucu] = oturum


def oturum(surucu: Any) -> Oturum:
    try:
        return _OTURUMLAR[surucu]
    except KeyError:
        raise RuntimeError(
            "uygulama oturumu yok (conftest `driver` fikstürü kullanılmalı)"
        ) from None
