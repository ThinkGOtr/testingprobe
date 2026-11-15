"""Proje kaydı ve proje başına sayaç (TP-COK-PROJE-PLANI §1.4, §1.5; migrasyon 0044).

`tp_proje`: TP'nin arka plan işi planladığı projeler (kimlik = Home `pid`; yetki kaynağı Home
`allowed_pids` olarak kalır). Kurulum geneli tablolardır; proje filtresine girmez.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, String, true
from sqlalchemy.orm import Mapped, mapped_column

from tp_core.models.base import Base, guncelleme_col, in_check, olusturma_col

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
