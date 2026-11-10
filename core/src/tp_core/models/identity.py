"""Kimlik: portal kullanıcıları ve MCP (IDE) kanalı token'ları."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, false, text
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
    # 0019: dış iptal sayacı (AI Probe oturum kontrolü `valid=false` → artar); çerezin `ae` alanı
    # ve `api_token.auth_epoch` bununla eşleşmezse reddedilir.
    auth_epoch: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    # 0019: kişi adı (JIT hesabında devir yanıtındaki `name`); yalnızca gösterim.
    ad_soyad: Mapped[str | None]


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
    # 0019: üretim anındaki sahibin `app_user.auth_epoch`'u; dış iptalde token düşer.
    auth_epoch: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
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
    # 0019 (AI Probe oturumu; yerel oturumda boş): kişi uid'si, devirdeki auth_time (epoch sn) ve
    # son başarılı `/v1/session/check` zamanı.
    external_uid: Mapped[str | None]
    auth_time: Mapped[int | None] = mapped_column(BigInteger)
    son_kontrol: Mapped[datetime | None]


class KimlikBagi(Base):
    """AI Probe kişisi (`external_uid`) ↔ TP rol hesabı (0019). Bir hesap tek kişiye bağlıdır;
    bir kişi birden çok rol hesabına bağlanabilir. Yetki yine `app_user.rol` ile verilir."""

    __tablename__ = "kimlik_bagi"
    __table_args__ = (Index("kimlik_bagi_external_ix", "external_uid"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    external_uid: Mapped[str]
    app_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), unique=True
    )
    olusturma: Mapped[datetime] = olusturma_col()
