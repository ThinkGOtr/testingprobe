"""Ortak ORM tabanı: uuid PK, `olusturma`/`guncelleme` zaman damgaları, JSONB eşlemesi."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, MetaData, Numeric, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

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
