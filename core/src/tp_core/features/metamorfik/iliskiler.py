# Ş1 ile birleştirmede değiştirilecek: ilişki sorguları Ş1'in `features/karar_tablosu`
# servisindeki `gecerli_iliskiler`'e (ve bayatlık yardımcısına) bağlanacak; bu dosya o zaman
# yalnız onları yeniden dışa aktarır ya da silinir.
"""Metamorfik türetmenin kullandığı ilişki sorguları (ANALIZ §4.5, §11.2).

Geçerli ilişki: `durum == "approved"` ve bayat değil. Bayat (§11.2): onay anındaki gereksinim
hash'i (`gereksinim_hash`) gereksinimin güncel içerik hash'inden farklı.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from tp_core.models import MetamorfikIliski, Requirement
from tp_core.workflow.service import content_hash_of


def bayat_mi(iliski: MetamorfikIliski, req: Requirement) -> bool:
    """Onaylı ilişki, onaydan sonra gereksinim değiştiği için kullanılamaz mı (§11.2)."""
    return iliski.durum == "approved" and iliski.gereksinim_hash != content_hash_of(req)


def gecerli_iliskiler(session: Session, requirement_id: uuid.UUID) -> list[MetamorfikIliski]:
    """Gereksinimin onaylı ve bayat olmayan ilişkileri (`sira_no` sırasıyla)."""
    req = session.get(Requirement, requirement_id)
    if req is None:
        return []
    adaylar = session.scalars(
        select(MetamorfikIliski)
        .where(
            MetamorfikIliski.requirement_id == requirement_id,
            MetamorfikIliski.durum == "approved",
        )
        .order_by(MetamorfikIliski.sira_no)
    ).all()
    return [n for n in adaylar if not bayat_mi(n, req)]


__all__ = ["bayat_mi", "gecerli_iliskiler"]
