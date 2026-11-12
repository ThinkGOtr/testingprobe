"""Kontrolde kullanılabilecek karar tabloları (012 ANALIZ §4.3 adım 1, §11.2 "Bayat").

Tablo araması tek kaynaktan yapılır: `tp_core.features.karar_tablosu.service.gecerli_tablolar`
(onaylı, bayat olmayan, `icerik.ac_refs`'i verilen AC atıflarıyla kesişen; `ac_refs=None` → hepsi).
Bu modül onu yeniden dışa aktarır ve oracle'ın küçük yardımcılarını taşır.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from tp_core.features.karar_tablosu.service import gecerli_tablolar
from tp_core.models import KararTablosu


def ac_normalize(ref: Any) -> str:
    """`"ac 2"` → `"AC2"` (case şemasındaki ve tablodaki atıflar aynı biçime indirgenir)."""
    return re.sub(r"\s+", "", str(ref)).upper()


def kesisiyor(tablo: KararTablosu, ac_refs: Iterable[Any] | None) -> bool:
    """Tablonun `ac_refs`'i verilen atıflarla kesişiyor mu (`None` → her tablo)."""
    if ac_refs is None:
        return True
    istenen = {ac_normalize(r) for r in ac_refs}
    return any(ac_normalize(r) in istenen for r in (tablo.icerik or {}).get("ac_refs") or [])


def tablo_ref(tablo: KararTablosu) -> str:
    """Modele verilen kısa tablo kimliği (`T<sira_no>`; `metamorfik_iliski.icerik.tablo_ref` ile
    aynı biçim)."""
    return f"T{tablo.sira_no}"


def tablo_hashleri(tablolar: Iterable[KararTablosu]) -> dict[str, str]:
    """Kontrol kaydının `tablo_hashleri` alanı: `{<karar_tablosu.id>: <icerik_hash>}`."""
    return {str(t.id): t.icerik_hash for t in tablolar}


def kapsayanlar(
    tablolar: Iterable[KararTablosu],
    icerik: Mapping[str, Any] | None,
    refs: Iterable[Any] | None = None,
) -> list[KararTablosu]:
    """Gereksinimin geçerli tablolarından AC atıflarıyla kesişenler: `refs` verilirse onunla
    (oracle'ın tek kuralı taban ∪ içerik, `service.kontrol_refleri`), değilse içeriğin
    kendi atıflarıyla."""
    if refs is None:
        refs = list((icerik or {}).get("acceptance_criteria_refs") or [])
    refs = list(refs)
    return [t for t in tablolar if kesisiyor(t, refs)]


__all__ = [
    "ac_normalize",
    "gecerli_tablolar",
    "kapsayanlar",
    "kesisiyor",
    "tablo_hashleri",
    "tablo_ref",
]
