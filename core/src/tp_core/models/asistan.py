"""AI Asistan (portal içi sohbet) tabloları — migrasyon 0017 (AI-ASISTAN-PLANI §8).

- `asistan_sohbet`: kullanıcının sohbetleri; yumuşak silme (`silindi`, `silinme`). Öneriden açılan
  sohbet `oneri_kural_id` taşır (§17.6).
- `asistan_mesaj`: sohbetteki sıralı mesajlar (`user` soru, `assistant` cevap). Atomiklik
  kısıtlarla sağlanır:
  - `asistan_mesaj_sira_uq` (sohbet_id, sira): eşzamanlı iki POST aynı sırayı alamaz;
  - `asistan_mesaj_ust_uq` (ust_mesaj_id, dolu olanlar): bir cevap yalnız bir kez
    "Daha ayrıntılı incele"nir (409 `zaten_derin`);
  - `asistan_mesaj_bekleyen_uq` (kullanici_id; `assistant` + `kullanici` tetikli +
    `pending`/`running`): kullanıcı başına tek bekleyen soru (409 `bekleyen_var`); otomatik
    yükseltme çocukları (`tetik='otomatik'`) sayılmaz;
  - `asistan_mesaj_tetik_ck`: otomatik mesaj yalnız bir üst mesajın derin çocuğu olabilir.
  `durum` workflow.MACHINES'te değildir (asistan iş akışı onay kapısı taşımaz). `job_id` ve
  `ai_call_id` yabancı anahtar değildir: iş kuyruğu temizlenir, `ai_call` append-only'dir.
- `asistan_durum`: worker'ın yazdığı tekil satır (`id = 1`): mod, model/maskeleme hazırlığı,
  bilgi paketi sürümü, kalp atışı. API kalp atışı eskiyse asistanı kapalı gösterir.
- `asistan_oneri_geri_bildirim`: öneri "Gizle / Faydalı / Yaptım" (-1 / 1 / 2) kayıtları;
  `varlik_durum` sunucuda hesaplanır, gizlenen öneri varlık aynı durumdayken gösterilmez.
- `asistan_hiz`: sabit pencere hız sayacı (`INSERT … ON CONFLICT DO UPDATE SET sayi = sayi + 1`).
  `kullanici_id` boş olabilir (global kova, ör. `jira_global`); tekillik NULLS NOT DISTINCT'tir.
- `asistan_guvenlik_olay` (0021, specs/013 §6.1): sır/kişisel veri reddi, kanarya, istem
  sızıntısı, sinyal ve dondurma olayları; `ciddi` türden türetilir (kısıtla zorlanır).

Model ↔ şema eşitliği tests/unit/features/assistant/test_migration.py'de doğrulanır.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tp_core.models import enums
from tp_core.models.base import Base, guncelleme_col, in_check, olusturma_col, uuid_pk

# Kısıt adları sözleşmedir: API `IntegrityError`'ı kısıt adına göre 409'a eşler (§9).
MESAJ_SIRA_UQ = "asistan_mesaj_sira_uq"
MESAJ_UST_UQ = "asistan_mesaj_ust_uq"
MESAJ_BEKLEYEN_UQ = "asistan_mesaj_bekleyen_uq"
HIZ_UQ = "asistan_hiz_uq"


def _sayi_check(
    kolon: str, degerler: frozenset[int], ad: str, nullable: bool = False
) -> CheckConstraint:
    liste = ", ".join(str(d) for d in sorted(degerler))
    kosul = f"{kolon} IN ({liste})"
    if nullable:
        kosul = f"{kolon} IS NULL OR {kosul}"
    return CheckConstraint(kosul, name=ad)


class AsistanSohbet(Base):
    """Bir kullanıcının asistan sohbeti."""

    __tablename__ = "asistan_sohbet"
    __table_args__ = (Index("asistan_sohbet_kullanici_ix", "kullanici_id", "guncelleme"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    kullanici_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    baslik: Mapped[str | None]
    oneri_kural_id: Mapped[str | None]
    silindi: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    silinme: Mapped[datetime | None]
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()


class AsistanMesaj(Base):
    """Sohbetteki bir mesaj (kullanıcı sorusu veya asistan cevabı)."""

    __tablename__ = "asistan_mesaj"
    __table_args__ = (
        in_check("rol", enums.ASISTAN_ROL, "asistan_mesaj_rol_ck"),
        in_check("durum", enums.ASISTAN_MESAJ_DURUM, "asistan_mesaj_durum_ck"),
        in_check("kaynak", enums.ASISTAN_KAYNAK, "asistan_mesaj_kaynak_ck", nullable=True),
        in_check("amac", enums.ASISTAN_AMAC, "asistan_mesaj_amac_ck", nullable=True),
        in_check("kip", enums.ASISTAN_KIP, "asistan_mesaj_kip_ck"),
        in_check("tetik", enums.ASISTAN_TETIK, "asistan_mesaj_tetik_deger_ck"),
        _sayi_check(
            "geri_bildirim",
            enums.ASISTAN_GERI_BILDIRIM,
            "asistan_mesaj_geri_bildirim_ck",
            nullable=True,
        ),
        CheckConstraint(
            "tetik = 'kullanici' OR (ust_mesaj_id IS NOT NULL AND amac = 'assistant_deep')",
            name="asistan_mesaj_tetik_ck",
        ),
        UniqueConstraint("sohbet_id", "sira", name=MESAJ_SIRA_UQ),
        Index(
            MESAJ_UST_UQ,
            "ust_mesaj_id",
            unique=True,
            postgresql_where=text("ust_mesaj_id IS NOT NULL"),
        ),
        Index(
            MESAJ_BEKLEYEN_UQ,
            "kullanici_id",
            unique=True,
            postgresql_where=text(
                "rol = 'assistant' AND tetik = 'kullanici' AND durum IN ('pending', 'running')"
            ),
        ),
        Index("asistan_mesaj_kullanici_ix", "kullanici_id", "olusturma"),
        Index("asistan_mesaj_ai_call_ix", "ai_call_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    sohbet_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("asistan_sohbet.id", ondelete="CASCADE")
    )
    kullanici_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    sira: Mapped[int] = mapped_column(Integer)
    rol: Mapped[str]
    # "Daha ayrıntılı incele": derin cevabın bağlı olduğu asistan cevabı.
    ust_mesaj_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("asistan_mesaj.id", ondelete="CASCADE")
    )
    icerik: Mapped[str | None]
    # Ekran bağlamı (portaldan, ≤ 2KB; §5.5).
    baglam: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Doğrulanmış cevap (§7.2 şeması + `dogrulama`).
    cevap: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    durum: Mapped[str] = mapped_column(server_default="pending", default="pending")
    hata_kodu: Mapped[str | None]
    kaynak: Mapped[str | None]
    amac: Mapped[str | None]
    kip: Mapped[str] = mapped_column(server_default="soru", default="soru")
    tetik: Mapped[str] = mapped_column(server_default="kullanici", default="kullanici")
    job_id: Mapped[uuid.UUID | None]
    ai_call_id: Mapped[uuid.UUID | None]
    maliyet_usd: Mapped[Decimal | None]
    token_girdi: Mapped[int | None] = mapped_column(Integer)
    token_cikti: Mapped[int | None] = mapped_column(Integer)
    # Uçtan uca süre (soru → cevap).
    sure_ms: Mapped[int | None] = mapped_column(Integer)
    geri_bildirim: Mapped[int | None] = mapped_column(SmallInteger)
    olusturma: Mapped[datetime] = olusturma_col()
    tamamlanma: Mapped[datetime | None]


class AsistanDurum(Base):
    """Worker'ın yazdığı tekil durum satırı (`id = 1`)."""

    __tablename__ = "asistan_durum"
    __table_args__ = (
        CheckConstraint("id = 1", name="asistan_durum_tekil_ck"),
        in_check("mod", enums.ASISTAN_MOD, "asistan_durum_mod_ck"),
    )

    id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, server_default=text("1"), default=1
    )
    mod: Mapped[str] = mapped_column(server_default="off", default="off")
    model_hazir: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    maskeleme: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    musteri_verisi: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    paket_commit: Mapped[str | None]
    paket_uretim: Mapped[datetime | None]
    kalp_atisi: Mapped[datetime | None]


class AsistanOneriGeriBildirim(Base):
    """Öneri geri bildirimi: -1 gizle, 1 faydalı, 2 yaptım (§17)."""

    __tablename__ = "asistan_oneri_geri_bildirim"
    __table_args__ = (
        _sayi_check("deger", enums.ASISTAN_ONERI_DEGER, "asistan_oneri_geri_bildirim_deger_ck"),
        Index("asistan_oneri_geri_bildirim_ix", "kullanici_id", "kural_id", "varlik_id"),
        # Kullanıcılar arası "Gizle/Yaptım" bastırma sorgusu (kullanici_id süzmez).
        Index("asistan_oneri_geri_bildirim_varlik_ix", "kural_id", "varlik_id", "varlik_durum"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kullanici_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    kural_id: Mapped[str]
    varlik_id: Mapped[uuid.UUID | None]
    # Geri bildirim anındaki varlık durumu (sunucuda hesaplanır).
    varlik_durum: Mapped[str | None]
    deger: Mapped[int] = mapped_column(SmallInteger)
    # "Yaptım" (deger=2) ile açılan Jira anahtarı.
    jira_anahtari: Mapped[str | None]
    olusturma: Mapped[datetime] = olusturma_col()


class AsistanHiz(Base):
    """Sabit pencere hız sayacı (kullanıcı veya global kova)."""

    __tablename__ = "asistan_hiz"
    __table_args__ = (
        UniqueConstraint(
            "kullanici_id",
            "kova",
            "pencere_baslangic",
            name=HIZ_UQ,
            postgresql_nulls_not_distinct=True,
        ),
        Index("asistan_hiz_pencere_ix", "pencere_baslangic"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kullanici_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE")
    )
    kova: Mapped[str]
    pencere_baslangic: Mapped[datetime]
    sayi: Mapped[int] = mapped_column(Integer, server_default=text("1"), default=1)


class AsistanGuvenlikOlay(Base):
    """Asistan güvenlik olayı (0021, specs/013 §6.1). `ayrinti` yalnız kimlik/sayı taşır."""

    __tablename__ = "asistan_guvenlik_olay"
    __table_args__ = (
        in_check("tur", enums.ASISTAN_OLAY_TUR, "asistan_guvenlik_olay_tur_ck"),
        CheckConstraint(
            "ciddi = (tur IN ("
            + ", ".join(f"'{t}'" for t in sorted(enums.ASISTAN_CIDDI_OLAY))
            + "))",
            name="asistan_guvenlik_olay_ciddi_ck",
        ),
        Index("asistan_guvenlik_olay_kullanici_ix", "kullanici_id", text("zaman DESC")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kullanici_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    # Reddedilen sorunun mesajı yoktur; mesaj saklama temizliğiyle silinince olay kalır.
    mesaj_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("asistan_mesaj.id", ondelete="SET NULL")
    )
    tur: Mapped[str]
    ciddi: Mapped[bool] = mapped_column(Boolean)
    ayrinti: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )
    zaman: Mapped[datetime] = olusturma_col()
