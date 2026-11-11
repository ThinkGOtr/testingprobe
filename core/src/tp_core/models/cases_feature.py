"""Case şeridinin ek tabloları (migrasyon 0007, 0021).

`case_goruntuleme`: insan review süresinin başlangıcı (TEKNIK-TASARIM §12 "AI + review süresi").
Portal case kartını açtığında `POST /cases/{id}/viewed` bir satır yazar; karar anındaki review
süresi = karar zamanı − kararı veren kullanıcının, o case'in bir önceki kararından SONRAKİ ilk
görüntülemesi. Tablo uygulama rolü için yalnızca INSERT/SELECT'tir (ölçüm geriye dönük
değiştirilemez).

`case_uretim` (0021, specs/011 §4.3): bir üretimin (portal model çağrısı ya da IDE taslak gönderimi)
case dışındaki üst düzey listeleri (`ozet`: açık sorular, varsayımlar, kapsam öğeleri, negatif
kapsam kararları, kapsanmayanlar, gözlemler…). Case'ler `(requirement_id, uretim_no)` ile bu satıra
bağlanır; tutarlılık kuralları ve kapsam matrisi bu özetten kodda hesaplanır.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tp_core.models.base import Base, in_check, olusturma_col, uuid_pk

URETIM_TUR = frozenset({"uretim", "negatif", "teknik"})


class CaseGoruntuleme(Base):
    """Bir kullanıcının bir case'i görüntülediği an (review süresi ölçümü)."""

    __tablename__ = "case_goruntuleme"
    __table_args__ = (Index("case_goruntuleme_ix", "test_case_id", "user_id", "zaman"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    test_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_case.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    zaman: Mapped[datetime] = olusturma_col()


class CaseUretim(Base):
    """Bir case üretiminin üst düzey listeleri (`ozet`); gereksinim + üretim no başına tek satır."""

    __tablename__ = "case_uretim"
    __table_args__ = (
        in_check("kanal", ("portal", "ide"), "case_uretim_kanal_ck"),
        in_check("tur", URETIM_TUR, "case_uretim_tur_ck"),
        UniqueConstraint("requirement_id", "uretim_no", name="case_uretim_uq"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement.id", ondelete="CASCADE")
    )
    uretim_no: Mapped[int] = mapped_column(Integer)
    kanal: Mapped[str] = mapped_column(server_default="portal", default="portal")
    tur: Mapped[str] = mapped_column(server_default="uretim", default="uretim")
    ai_call_id: Mapped[uuid.UUID | None]
    ozet: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    olusturma: Mapped[datetime] = olusturma_col()
