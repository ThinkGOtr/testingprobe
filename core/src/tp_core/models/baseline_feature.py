"""Faz 5: story başına manuel test tasarımı baz değeri (TEKNIK-TASARIM §12 "Hazırlık süresi").

- `requirement_baz_deger`: gereksinim başına manuel baz değer girişlerinin **append-only**
  geçmişi. Her `PUT /requirements/{id}/baseline` bir `islem='set'` satırı, her `DELETE` bir
  `islem='clear'` satırı yazar; güncel değer, gereksinimin en büyük `sira`'lı satırıdır
  (`clear` ise ölçüm yok). Satır kim (`giren`, `giren_rol`), ne zaman (`zaman`), hangi kaynaktan
  (`not_metni`, ör. "F0 ölçümü – İsmail") girildiğini taşır; `onceki_s` bir önceki güncel değerdir.
  tp_app yalnızca SELECT/INSERT yapabilir (geçmiş değiştirilemez); gereksinim silinirse cascade.

Değer uydurulmaz: satır yoksa story'nin baz değeri "ölçülmedi"dir; `TP_MANUAL_BASELINE_S`
yalnızca açıkça "varsayılan" etiketiyle yedek olarak kullanılır (tp_core.features.requirements.
baseline). Model ↔ şema eşitliği tests/unit/features/requirements/test_baseline.py'de denetlenir.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from tp_core.models.base import Base, in_check, olusturma_col, uuid_pk

# Saniye; 40 saat = 5 iş günü. Tek bir story için manuel test tasarımı bundan uzunsa değer
# büyük olasılıkla dakika/saniye karışıklığıdır (ör. 3600 yerine 360000).
BAZ_UST_SINIR_S = 40 * 3600
BAZ_ISLEM = ("set", "clear")


class RequirementBazDeger(Base):
    """Story başına manuel baz değer girişi (append-only geçmiş; güncel = en büyük `sira`)."""

    __tablename__ = "requirement_baz_deger"
    __table_args__ = (
        in_check("islem", BAZ_ISLEM, "requirement_baz_deger_islem_ck"),
        CheckConstraint(
            f"(islem = 'set' AND deger_s IS NOT NULL AND deger_s > 0 "
            f"AND deger_s <= {BAZ_UST_SINIR_S}) OR (islem = 'clear' AND deger_s IS NULL)",
            name="requirement_baz_deger_deger_ck",
        ),
        UniqueConstraint("requirement_id", "sira", name="requirement_baz_deger_sira_uq"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement.id", ondelete="CASCADE")
    )
    # Gereksinim başına 1, 2, … (gereksinim satırı kilitlenerek atanır).
    sira: Mapped[int] = mapped_column(Integer)
    islem: Mapped[str]
    deger_s: Mapped[int | None] = mapped_column(Integer)
    onceki_s: Mapped[int | None] = mapped_column(Integer)
    giren: Mapped[str]
    giren_rol: Mapped[str]
    not_metni: Mapped[str | None]
    zaman: Mapped[datetime] = olusturma_col()
