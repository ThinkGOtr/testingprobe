"""Ortak ORM tabanı: uuid PK, `olusturma`/`guncelleme` zaman damgaları, JSONB eşlemesi."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, MetaData, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from tp_core.proje.baglam import mevcut_pid

NOW = text("now()")


class Base(DeclarativeBase):
    metadata = MetaData()
    type_annotation_map = {  # noqa: RUF012 — SQLAlchemy sınıf düzeyi eşlemesi
        str: Text(),
        Decimal: Numeric(12, 6),
        uuid.UUID: UUID(as_uuid=True),
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
    }


class ProjeKapsamli:
    """Mixin: proje kapsamlı tablo (TP-COK-PROJE-PLANI §1.1 A, §2.3).

    Sütun NOT NULL; INSERT'te bağlamdan dolar (`before_flush` ve Python varsayılanı). ORM
    sorgularına `tp_core.proje.orm` otomatik `project_id` ölçütü ekler.
    """

    project_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default=lambda: mevcut_pid()
    )


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


def olusturma_col() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=NOW)


def guncelleme_col() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=NOW, onupdate=func.now()
    )


def in_check(
    kolon: str, degerler: Iterable[str], ad: str, nullable: bool = False
) -> CheckConstraint:
    liste = ", ".join(f"'{d}'" for d in sorted(degerler))
    kosul = f"{kolon} IN ({liste})"
    if nullable:
        kosul = f"{kolon} IS NULL OR {kosul}"
    return CheckConstraint(kosul, name=ad)
