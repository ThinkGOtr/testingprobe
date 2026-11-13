"""Sprint otomasyonu tabloları (migrasyon 0030, specs/013-sprint-otomasyonu).

- `otomasyon_ayari`: portaldan yönetilen otomasyon ayarları; anahtarlar ve varsayılanlar
  `tp_core.features.otomasyon.ayarlar`'da.
- `test_verisi`: merkezi test verisi kataloğu. Case metni değeri değil `{veri:anahtar}` atfını
  taşır (`tp_core.features.testveri.atif`). Gizli kayıtta değer tutulmaz; `sir_adi` ortam
  değişkeninin adıdır.
- `test_verisi_surum`: her oluşturma / güncelleme / silmenin değişmez kaydı.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, UniqueConstraint, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tp_core.models.base import Base, guncelleme_col, in_check, olusturma_col, uuid_pk

TEST_VERISI_ISLEM = frozenset({"olustur", "guncelle", "sil"})


class OtomasyonAyari(Base):
    __tablename__ = "otomasyon_ayari"

    anahtar: Mapped[str] = mapped_column(primary_key=True)
    deger: Mapped[Any] = mapped_column(JSONB)
    guncelleyen: Mapped[str]
    guncelleme: Mapped[datetime] = guncelleme_col()


class TestVerisi(Base):
    __tablename__ = "test_verisi"
    __test__ = False  # pytest bu sınıfı test sınıfı sanmasın
    __table_args__ = (
        UniqueConstraint("anahtar", name="test_verisi_anahtar_uq"),
        CheckConstraint(
            "anahtar ~ '^[a-z0-9_]+(\\.[a-z0-9_]+){0,5}$'", name="test_verisi_anahtar_ck"
        ),
        CheckConstraint(
            "(gizli AND deger IS NULL AND sir_adi IS NOT NULL) "
            "OR (NOT gizli AND deger IS NOT NULL AND sir_adi IS NULL)",
            name="test_verisi_gizli_ck",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    anahtar: Mapped[str]
    grup: Mapped[str] = mapped_column(server_default="", default="")
    aciklama: Mapped[str] = mapped_column(server_default="", default="")
    deger: Mapped[str | None]
    gizli: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    sir_adi: Mapped[str | None]
    surum: Mapped[int] = mapped_column(Integer, server_default="1", default=1)
    silindi: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    guncelleyen: Mapped[str]
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()


class TestVerisiSurum(Base):
    __tablename__ = "test_verisi_surum"
    __test__ = False
    __table_args__ = (
        UniqueConstraint("test_verisi_id", "surum", name="test_verisi_surum_uq"),
        in_check("islem", TEST_VERISI_ISLEM, "test_verisi_surum_islem_ck"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    test_verisi_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_verisi.id", ondelete="RESTRICT")
    )
    surum: Mapped[int] = mapped_column(Integer)
    islem: Mapped[str]
    deger: Mapped[str | None]
    gizli: Mapped[bool] = mapped_column(Boolean)
    sir_adi: Mapped[str | None]
    degistiren: Mapped[str]
    zaman: Mapped[datetime] = olusturma_col()
