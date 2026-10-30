"""Kimlik: portal kullanıcıları ve MCP (IDE) kanalı token'ları."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, false
from sqlalchemy.orm import Mapped, mapped_column

from tp_core.models import enums
from tp_core.models.base import Base, in_check, olusturma_col, uuid_pk


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = (in_check("rol", enums.ROLLER, "app_user_rol_ck"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    kullanici_adi: Mapped[str] = mapped_column(unique=True)
    rol: Mapped[str]
    parola_hash: Mapped[str]
    olusturma: Mapped[datetime] = olusturma_col()  # 0002: NOT NULL


class ApiToken(Base):
    """8 saatlik kapsamlı bearer token; yalnızca sha256 özeti saklanır (§8.3)."""

    __tablename__ = "api_token"
    __table_args__ = (
        in_check("kapsam", enums.TOKEN_KAPSAM, "api_token_kapsam_ck"),
        Index("api_token_user_ix", "user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    kapsam: Mapped[str]
    token_hash: Mapped[str] = mapped_column(unique=True)
    son_kullanma: Mapped[datetime]
    iptal: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    son_kullanim: Mapped[datetime | None]
    # Üretim anındaki parola hash'inin parmak izi (0003); parola değişince token geçersizdir.
    parola_izi: Mapped[str | None]
    olusturma: Mapped[datetime] = olusturma_col()


class Oturum(Base):
    """Portal oturumu (0003): çerez `sid` taşır; çıkışta `iptal_zamani` dolar ve çerez ölür."""

    __tablename__ = "oturum"
    __table_args__ = (Index("oturum_user_ix", "user_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    son_kullanma: Mapped[datetime]
    iptal_zamani: Mapped[datetime | None]
    olusturma: Mapped[datetime] = olusturma_col()
