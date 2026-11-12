"""Case setinin review (P8) ve denetim (P9) kayıtları (migrasyon 0023, specs/011 §4.3).

`case_set_review`: üretimden sonra otomatik çalışan eleştirmen turu (12 madde, tavsiye niteliğinde).
`case_set_audit`: Agent Probe portu arkasındaki denetim kapısı (KABUL / DÜZELTME_GEREKLİ /
ENGELLE). İkisi de gereksinimin güncel v3 case setinin `set_hash`'ine bağlıdır: set değişince
(case eklendi, düzeltildi, reddedildi) kayıt bayat olur, yayın kapısı (K3) yeni KABUL ister.

Satırlar iş kuyruğa alınırken `bekliyor` yazılır; iş sonucu `tamamlandi` (içerik + karar) ya da
`hata` (neden) ile kapatır. Denetimde modelin kararı (`model_karari`) ile kodun deterministik
sertleştirmesinden sonraki karar (`karar`) ayrı saklanır (Constitution XI).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tp_core.models.base import Base, guncelleme_col, in_check, olusturma_col, uuid_pk

KALITE_DURUM = frozenset({"bekliyor", "tamamlandi", "hata"})
DENETIM_KARARLARI = frozenset({"KABUL", "DÜZELTME_GEREKLİ", "ENGELLE"})
DENETIM_KAYNAK = frozenset({"tp-gecit", "agent-probe", "sim"})


class CaseSetReview(Base):
    """P8 review sonucu (gereksinim + set hash'i başına, en yenisi geçerli)."""

    __tablename__ = "case_set_review"
    __table_args__ = (
        in_check("durum", KALITE_DURUM, "case_set_review_durum_ck"),
        Index("case_set_review_req_ix", "requirement_id", "olusturma"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement.id", ondelete="CASCADE")
    )
    uretim_no: Mapped[int | None] = mapped_column(Integer)
    set_hash: Mapped[str]
    durum: Mapped[str] = mapped_column(server_default="bekliyor", default="bekliyor")
    skor: Mapped[int | None] = mapped_column(Integer)
    icerik: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    hata: Mapped[str | None]
    ai_call_id: Mapped[uuid.UUID | None]
    job_id: Mapped[uuid.UUID | None]
    isteyen: Mapped[str] = mapped_column(server_default="system", default="system")
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()


class CaseSetAudit(Base):
    """P9 denetim kararı (gereksinim + set hash'i başına, en yenisi geçerli)."""

    __tablename__ = "case_set_audit"
    __table_args__ = (
        in_check("durum", KALITE_DURUM, "case_set_audit_durum_ck"),
        in_check("karar", DENETIM_KARARLARI, "case_set_audit_karar_ck", nullable=True),
        in_check("model_karari", DENETIM_KARARLARI, "case_set_audit_model_karar_ck", nullable=True),
        in_check("kaynak", DENETIM_KAYNAK, "case_set_audit_kaynak_ck"),
        # 0026: tamamlanmış denetimin kararı vardır (kapı kararsız satırı okuyamaz).
        CheckConstraint(
            "durum <> 'tamamlandi' OR karar IS NOT NULL", name="case_set_audit_tamam_karar_ck"
        ),
        Index("case_set_audit_req_ix", "requirement_id", "olusturma"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement.id", ondelete="CASCADE")
    )
    set_hash: Mapped[str]
    durum: Mapped[str] = mapped_column(server_default="bekliyor", default="bekliyor")
    karar: Mapped[str | None]
    model_karari: Mapped[str | None]
    icerik: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    kaynak: Mapped[str] = mapped_column(server_default="tp-gecit", default="tp-gecit")
    talep_no: Mapped[str | None]
    hata: Mapped[str | None]
    ai_call_id: Mapped[uuid.UUID | None]
    job_id: Mapped[uuid.UUID | None]
    review_id: Mapped[uuid.UUID | None]
    isteyen: Mapped[str] = mapped_column(server_default="system", default="system")
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()
