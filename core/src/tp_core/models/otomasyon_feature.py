"""Sprint otomasyonu tabloları (migrasyon 0030, specs/013-sprint-otomasyonu).

- `otomasyon_ayari`: portaldan yönetilen otomasyon ayarları; anahtarlar ve varsayılanlar
  `tp_core.features.otomasyon.ayarlar`'da.
- `test_verisi`: merkezi test verisi kataloğu. Case metni değeri değil `{veri:anahtar}` atfını
  taşır (`tp_core.features.testveri.atif`). Gizli kayıtta değer tutulmaz; `sir_adi` ortam
  değişkeninin adıdır.
- `test_verisi_surum`: her oluşturma / güncelleme / silmenin değişmez kaydı.
- `test_verisi_kaynagi` (0049): projenin salt okuma veritabanından kataloğu dolduran sorgu
  tanımları (`tp_core.features.testveri.kaynak`). Kaynaktan gelen kayıt `test_verisi.kaynak_id`
  taşır; kaynağın son yenilemesinde dönmeyen kayıt silinmez, `kaynakta_yok` işaretlenir.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tp_core.models.base import (
    Base,
    ProjeKapsamli,
    guncelleme_col,
    in_check,
    olusturma_col,
    uuid_pk,
)
from tp_core.proje.baglam import mevcut_pid

TEST_VERISI_ISLEM = frozenset({"olustur", "guncelle", "sil"})


class OtomasyonAyari(ProjeKapsamli, Base):
    __tablename__ = "otomasyon_ayari"

    # Ayar proje başına (§1.2): PK (project_id, anahtar).
    project_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: mevcut_pid()
    )
    anahtar: Mapped[str] = mapped_column(primary_key=True)
    deger: Mapped[Any] = mapped_column(JSONB)
    guncelleyen: Mapped[str]
    guncelleme: Mapped[datetime] = guncelleme_col()


class TestVerisiKaynagi(ProjeKapsamli, Base):
    __tablename__ = "test_verisi_kaynagi"
    __test__ = False
    __table_args__ = (
        UniqueConstraint("project_id", "grup", name="test_verisi_kaynagi_grup_uq"),
        CheckConstraint("grup ~ '^[a-z0-9_]+$'", name="test_verisi_kaynagi_grup_ck"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    grup: Mapped[str]
    aciklama: Mapped[str] = mapped_column(server_default="", default="")
    sorgu: Mapped[str]
    anahtar_kolonu: Mapped[str]
    # [{kolon, alan, bicim: metin|tutar, aciklama}] (`kaynak.KolonTanimi`).
    deger_kolonlari: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    sira: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    on_tanimli: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    surum: Mapped[int] = mapped_column(Integer, server_default="1", default=1)
    silindi: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    guncelleyen: Mapped[str]
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()
    son_yenileme: Mapped[datetime | None]
    # Son yenilemenin özeti (sayılar + uyarılar; değer içermez).
    son_durum: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class TestVerisi(ProjeKapsamli, Base):
    __tablename__ = "test_verisi"
    __test__ = False  # pytest bu sınıfı test sınıfı sanmasın
    __table_args__ = (
        UniqueConstraint("project_id", "anahtar", name="test_verisi_anahtar_uq"),
        CheckConstraint(
            "anahtar ~ '^[a-z0-9_]+(\\.[a-z0-9_]+){0,5}$'", name="test_verisi_anahtar_ck"
        ),
        CheckConstraint(
            "(gizli AND deger IS NULL AND sir_adi IS NOT NULL) "
            "OR (NOT gizli AND deger IS NOT NULL AND sir_adi IS NULL)",
            name="test_verisi_gizli_ck",
        ),
        Index("test_verisi_kaynak_ix", "project_id", "kaynak_id"),
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
    # 0049: kaydı dolduran veritabanı kaynağı (elle kayıtta NULL) ve kaynağın son yenilemesinde
    # dönmediği (silinmez, işaretlenir).
    kaynak_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("test_verisi_kaynagi.id", ondelete="SET NULL")
    )
    kaynakta_yok: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)


class TestVerisiSurum(ProjeKapsamli, Base):
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
