"""Case şeridinin ek tabloları (migrasyon 0007).

`case_goruntuleme`: insan review süresinin başlangıcı (TEKNIK-TASARIM §12 "AI + review süresi").
Portal case kartını açtığında `POST /cases/{id}/viewed` bir satır yazar; karar anındaki review
süresi = karar zamanı − kararı veren kullanıcının, o case'in bir önceki kararından SONRAKİ ilk
görüntülemesi. Tablo uygulama rolü için yalnızca INSERT/SELECT'tir (ölçüm geriye dönük
değiştirilemez).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from tp_core.models.base import Base, olusturma_col, uuid_pk


class CaseGoruntuleme(Base):
    """Bir kullanıcının bir case'i görüntülediği an (review süresi ölçümü)."""

    __tablename__ = "case_goruntuleme"
    __table_args__ = (Index("case_goruntuleme_ix", "test_case_id", "user_id", "zaman"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    test_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_case.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    zaman: Mapped[datetime] = olusturma_col()
