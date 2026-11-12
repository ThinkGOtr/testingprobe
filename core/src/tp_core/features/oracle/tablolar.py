# Ş1 `gecerli_tablolar` ile birleştirmede değiştirilecek.
#
# Ş1 (karar tablosu şeridi) `tp_core.features.karar_tablosu.service.gecerli_tablolar` işlevini
# aynı imzayla sunacak. Birleştirmede bu modüldeki tanım silinir ve `gecerli_tablolar` oradan içe
# aktarılır; oracle şeridinin geri kalanı tablo aramasını YALNIZ bu işlev üzerinden yapar.
"""Kontrolde kullanılabilecek karar tabloları (012 ANALIZ §4.3 adım 1, §11.2 "Bayat").

Geçerli tablo: `durum == "approved"`, bayat değil (`gereksinim_hash == content_hash_of(gereksinim)`)
ve `icerik.ac_refs` verilen AC atıflarıyla kesişiyor (`ac_refs=None` → kesişim aranmaz).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tp_core.models import KararTablosu, Requirement
from tp_core.workflow.service import content_hash_of


def ac_normalize(ref: Any) -> str:
    """`"ac 2"` → `"AC2"` (case şemasındaki ve tablodaki atıflar aynı biçime indirgenir)."""
    return re.sub(r"\s+", "", str(ref)).upper()


def kesisiyor(tablo: KararTablosu, ac_refs: Iterable[Any] | None) -> bool:
    """Tablonun `ac_refs`'i verilen atıflarla kesişiyor mu (`None` → her tablo)."""
    if ac_refs is None:
        return True
    istenen = {ac_normalize(r) for r in ac_refs}
    return any(ac_normalize(r) in istenen for r in (tablo.icerik or {}).get("ac_refs") or [])


def gecerli_tablolar(
    session: Session, requirement_id: uuid.UUID, ac_refs: Sequence[str] | None = None
) -> list[KararTablosu]:
    """Gereksinimin onaylı, bayat olmayan ve AC atıflarıyla kesişen tabloları (`sira_no` sırası)."""
    req = session.get(Requirement, requirement_id)
    if req is None:
        return []
    guncel = content_hash_of(req)
    tablolar = session.scalars(
        select(KararTablosu)
        .where(KararTablosu.requirement_id == requirement_id, KararTablosu.durum == "approved")
        .order_by(KararTablosu.sira_no)
    ).all()
    return [t for t in tablolar if t.gereksinim_hash == guncel and kesisiyor(t, ac_refs)]


def tablo_ref(tablo: KararTablosu) -> str:
    """Modele verilen kısa tablo kimliği (`T<sira_no>`; `metamorfik_iliski.icerik.tablo_ref` ile
    aynı biçim)."""
    return f"T{tablo.sira_no}"


def tablo_hashleri(tablolar: Iterable[KararTablosu]) -> dict[str, str]:
    """Kontrol kaydının `tablo_hashleri` alanı: `{<karar_tablosu.id>: <icerik_hash>}`."""
    return {str(t.id): t.icerik_hash for t in tablolar}


def kapsayanlar(
    tablolar: Iterable[KararTablosu], icerik: Mapping[str, Any] | None
) -> list[KararTablosu]:
    """Gereksinimin geçerli tablolarından case içeriğinin AC atıflarıyla kesişenler."""
    refs = list((icerik or {}).get("acceptance_criteria_refs") or [])
    return [t for t in tablolar if kesisiyor(t, refs)]
