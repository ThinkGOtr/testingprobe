"""Proje kaydı ve proje başına sayaç (TP-COK-PROJE-PLANI §1.4, §1.5; migrasyon 0044).

`tp_proje`: TP'nin arka plan işi planladığı projeler (kimlik = Home `pid`; yetki kaynağı Home
`allowed_pids` olarak kalır). Kurulum geneli tablolardır; proje filtresine girmez.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Index, String, false, text, true
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from tp_core.models.base import Base, guncelleme_col, in_check, olusturma_col, uuid_pk

PROJE_KAYNAKLARI = ("env", "kesif")


class TpProje(Base):
    __tablename__ = "tp_proje"
    __table_args__ = (in_check("kaynak", PROJE_KAYNAKLARI, "tp_proje_kaynak_ck"),)

    pid: Mapped[str] = mapped_column(String(64), primary_key=True)
    kod: Mapped[str | None]
    ad: Mapped[str | None]
    kaynak: Mapped[str]
    aktif: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()


class ProjeSayac(Base):
    __tablename__ = "proje_sayac"

    project_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ad: Mapped[str] = mapped_column(String(64), primary_key=True)
    deger: Mapped[int] = mapped_column(BigInteger)


DEMO_SIFIRLAMA_DURUMLARI = ("kuyrukta", "calisiyor", "tamam", "hata")


class DemoSifirlama(Base):
    """Home "Sıfırla" düğmesinin işlem kaydı (migrasyon 0052; `features/demo/tam_sifirlama.py`).

    Kurulum geneli tablodur (proje filtresine girmez; `project_id` sıfırlanan projedir). Yalnız
    ham SQL ile okunur/yazılır; model şema karşılaştırması içindir."""

    __tablename__ = "demo_sifirlama"
    __table_args__ = (
        in_check("durum", DEMO_SIFIRLAMA_DURUMLARI, "demo_sifirlama_durum_ck"),
        Index("demo_sifirlama_proje_ix", "project_id", "olusturma"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[str] = mapped_column(String(64))
    durum: Mapped[str] = mapped_column(server_default="kuyrukta", default="kuyrukta")
    adimlar: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), default=list
    )
    kontrol: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), default=list
    )
    aktor: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )
    hazir: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    hata: Mapped[str | None]
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()
    bitis: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
