"""Tablolar (Türkçe adlar). Postgres ve SQLite'ta aynı şema."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

PARA = Numeric(12, 2, asdecimal=True)


def simdi() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Bayi(Base):
    __tablename__ = "bayi"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kullanici_adi: Mapped[str] = mapped_column(String(64), unique=True)
    parola_hash: Mapped[str] = mapped_column(String(256))
    ad: Mapped[str] = mapped_column(String(128))
    kredi_limiti: Mapped[Decimal] = mapped_column(PARA)
    olusturma: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=simdi)


class Urun(Base):
    __tablename__ = "urun"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kod: Mapped[str] = mapped_column(String(16), unique=True)
    ad: Mapped[str] = mapped_column(String(128))
    fiyat: Mapped[Decimal] = mapped_column(PARA)
    sira: Mapped[int] = mapped_column(Integer, default=0)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)


class Kampanya(Base):
    __tablename__ = "kampanya"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kod: Mapped[str] = mapped_column(String(32), unique=True)
    ad: Mapped[str] = mapped_column(String(128))
    urun_id: Mapped[int] = mapped_column(ForeignKey("urun.id"))
    aktif: Mapped[bool] = mapped_column(Boolean, default=True)

    urun: Mapped[Urun] = relationship()


class Ayar(Base):
    __tablename__ = "ayar"

    anahtar: Mapped[str] = mapped_column(String(64), primary_key=True)
    deger: Mapped[str] = mapped_column(String(256))
    aciklama: Mapped[str] = mapped_column(String(256), default="")


class Oturum(Base):
    __tablename__ = "oturum"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    bayi_id: Mapped[int] = mapped_column(ForeignKey("bayi.id", ondelete="CASCADE"))
    olusturma: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=simdi)
    son_kullanma: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Sepet(Base):
    __tablename__ = "sepet"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bayi_id: Mapped[int] = mapped_column(ForeignKey("bayi.id", ondelete="CASCADE"), unique=True)
    guncelleme: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=simdi)

    satirlar: Mapped[list["SepetSatiri"]] = relationship(
        back_populates="sepet", cascade="all, delete-orphan", order_by="SepetSatiri.id"
    )


class SepetSatiri(Base):
    __tablename__ = "sepet_satiri"
    __table_args__ = (UniqueConstraint("sepet_id", "urun_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sepet_id: Mapped[int] = mapped_column(ForeignKey("sepet.id", ondelete="CASCADE"))
    urun_id: Mapped[int] = mapped_column(ForeignKey("urun.id"))
    adet: Mapped[int] = mapped_column(Integer)

    sepet: Mapped[Sepet] = relationship(back_populates="satirlar")
    urun: Mapped[Urun] = relationship()


class Siparis(Base):
    __tablename__ = "siparis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    numara: Mapped[str] = mapped_column(String(32), unique=True)
    bayi_id: Mapped[int] = mapped_column(ForeignKey("bayi.id", ondelete="CASCADE"))
    adet_toplam: Mapped[int] = mapped_column(Integer)
    ara_toplam: Mapped[Decimal] = mapped_column(PARA)
    indirim: Mapped[Decimal] = mapped_column(PARA)
    toplam: Mapped[Decimal] = mapped_column(PARA)
    olusturma: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=simdi)

    satirlar: Mapped[list["SiparisSatiri"]] = relationship(
        back_populates="siparis", cascade="all, delete-orphan", order_by="SiparisSatiri.id"
    )


class SiparisSatiri(Base):
    __tablename__ = "siparis_satiri"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    siparis_id: Mapped[int] = mapped_column(ForeignKey("siparis.id", ondelete="CASCADE"))
    urun_id: Mapped[int] = mapped_column(ForeignKey("urun.id"))
    urun_kod: Mapped[str] = mapped_column(String(16))
    urun_ad: Mapped[str] = mapped_column(String(128))
    birim_fiyat: Mapped[Decimal] = mapped_column(PARA)
    adet: Mapped[int] = mapped_column(Integer)
    bedava_adet: Mapped[int] = mapped_column(Integer)
    satir_tutari: Mapped[Decimal] = mapped_column(PARA)

    siparis: Mapped[Siparis] = relationship(back_populates="satirlar")


class TestKirilma(Base):
    """Bayi kapsamlı ekilmiş hata (`POST /test/break`, yalnızca test modu). Satır yoksa normal.

    `hata`: `faults.KATALOG` kodu (bayi başına en çok bir etkin hata). `kampanya` eski kolondur ve
    `hata == "kampanya_bedava_yok"` ile eşanlamlı tutulur. Ad `Test` ile başlasa da pytest sınıfı
    değildir."""

    __test__ = False
    __tablename__ = "test_kirilma"

    bayi_id: Mapped[int] = mapped_column(
        ForeignKey("bayi.id", ondelete="CASCADE"), primary_key=True
    )
    kampanya: Mapped[bool] = mapped_column(Boolean, default=False)
    # Sonradan eklendi: var olan veritabanında `db.kolonlari_tamamla` açılışta ekler.
    hata: Mapped[str | None] = mapped_column(String(40), nullable=True, default=None)
    guncelleme: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=simdi)
