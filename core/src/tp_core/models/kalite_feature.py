"""Test kalite doğrulama (012; specs/012-test-kalite-dogrulama/ANALIZ.md §5) tabloları —
migrasyon 0022.

- `karar_tablosu`: bir hesaplama kuralının PO onaylı girdi → çıktı tanımı (§4.1). `icerik`
  `rules/schemas/icerik/karar_tablosu.schema.json` biçimindedir; `icerik_hash =
  content_hash(icerik)`. `durum` ve `onaylanan_hash` yalnız `workflow.transition()` ile değişir.
  `gereksinim_hash`: onay anındaki gereksinim içerik hash'i; gereksinim sonradan değişirse tablo
  "bayat" sayılır (hesaplanan özellik, durum değil).
- `metamorfik_iliski`: onaylı metamorfik ilişki (§4.5); aynı durum makinesi. `karar_tablosu_id`
  ilişkinin kolon adlarını aldığı tablodur (`icerik.tablo_ref` çözülmüş hali; olmayabilir).
- `case_oracle_kontrol`: bir case içeriğinin (hash'iyle) karar tablolarına göre kontrol sonucu
  (§4.3). Anahtar `(test_case_id, icerik_hash)`. Satır yeniden kontrolde güncellenir
  (`guncelleme`); `olusturma` ilk yazımdır. İstisna kolonları geriye uyum içindir.
- `oracle_istisna`: gerekçeli istisnaların append-only kaydı (review 1 V10; §13.2). Sayaçlar
  buradan yapılır; `tp_app` yalnız INSERT/SELECT yapar.
- `metamorfik_turetme`: (ilişki, kaynak case) çifti başına tek türetme kaydı (§4.5).
- `hata_kosusu` / `hata_kosusu_adim`: ekilmiş hata koşusu ve platform × hata adımları (§4.6).
  `hata_kosusu.durum` iş durumudur (workflow.MACHINES'te değildir).

`tp_app` bu tablolarda SELECT, INSERT, UPDATE yapabilir (`oracle_istisna`'da yalnız SELECT,
INSERT); DELETE yoktur.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, UniqueConstraint, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tp_core.models import enums
from tp_core.models.base import Base, guncelleme_col, in_check, olusturma_col, uuid_pk
from tp_core.models.requirements import EMPTY_LIST, EMPTY_OBJ, _durum


class KararTablosu(Base):
    """PO onaylı karar tablosu (§4.1). `sira_no` gereksinim içinde tekildir; yeniden kullanılmaz."""

    __tablename__ = "karar_tablosu"
    __table_args__ = (
        in_check("durum", enums.durumlar("karar_tablosu"), "karar_tablosu_durum_ck"),
        in_check("uretim_modu", enums.URETIM_MODU, "karar_tablosu_uretim_modu_ck", True),
        UniqueConstraint("requirement_id", "sira_no", name="karar_tablosu_sira_uq"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement.id", ondelete="CASCADE")
    )
    sira_no: Mapped[int] = mapped_column(Integer)
    icerik: Mapped[dict[str, Any]] = mapped_column(JSONB)
    icerik_hash: Mapped[str]
    onaylanan_hash: Mapped[str | None]
    durum: Mapped[str] = _durum("karar_tablosu")
    # Onay anındaki gereksinim içerik hash'i (`content_hash_of(requirement)`); servis yazar.
    gereksinim_hash: Mapped[str | None]
    ai_generated: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    ai_call_id: Mapped[uuid.UUID | None]
    uretim_modu: Mapped[str | None]
    olusturan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()


class MetamorfikIliski(Base):
    """PO onaylı metamorfik ilişki (§4.5). `sira_no` gereksinim içinde tekildir."""

    __tablename__ = "metamorfik_iliski"
    __table_args__ = (
        in_check("durum", enums.durumlar("metamorfik_iliski"), "metamorfik_iliski_durum_ck"),
        in_check("uretim_modu", enums.URETIM_MODU, "metamorfik_iliski_uretim_modu_ck", True),
        UniqueConstraint("requirement_id", "sira_no", name="metamorfik_iliski_sira_uq"),
        Index("metamorfik_iliski_tablo_ix", "karar_tablosu_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement.id", ondelete="CASCADE")
    )
    karar_tablosu_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("karar_tablosu.id", ondelete="SET NULL")
    )
    sira_no: Mapped[int] = mapped_column(Integer)
    icerik: Mapped[dict[str, Any]] = mapped_column(JSONB)
    icerik_hash: Mapped[str]
    onaylanan_hash: Mapped[str | None]
    durum: Mapped[str] = _durum("metamorfik_iliski")
    gereksinim_hash: Mapped[str | None]
    ai_generated: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    ai_call_id: Mapped[uuid.UUID | None]
    uretim_modu: Mapped[str | None]
    olusturan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()


class CaseOracleKontrol(Base):
    """Bir case içeriğinin karar tablolarına göre kontrol sonucu (§4.3)."""

    __tablename__ = "case_oracle_kontrol"
    __table_args__ = (
        in_check("sonuc", enums.ORACLE_SONUC, "case_oracle_kontrol_sonuc_ck"),
        in_check("uretim_modu", enums.URETIM_MODU, "case_oracle_kontrol_uretim_modu_ck", True),
        UniqueConstraint("test_case_id", "icerik_hash", name="case_oracle_kontrol_case_hash_uq"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    test_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_case.id", ondelete="CASCADE"))
    # Kontrol edilen içeriğin hash'i: case'in o anki ya da önerilen (düzeltme formundaki) içeriği.
    icerik_hash: Mapped[str]
    sonuc: Mapped[str]
    # {gruplar: [{tablo_id, tablo_ad, satir_id, girdiler, karsilastirmalar, durum, neden}],
    #  atilan_olgular: n}
    ayrintilar: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=EMPTY_OBJ, default=dict
    )
    # Kontrolde kullanılan tablolar: {<karar_tablosu.id>: <icerik_hash>}
    tablo_hashleri: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=EMPTY_OBJ, default=dict
    )
    # Bu hash AI'ın ürettiği (insan düzeltmesinden önceki) içeriğe mi ait (§4.7 metriği).
    ai_icerik: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    ai_call_id: Mapped[uuid.UUID | None]
    uretim_modu: Mapped[str | None]
    istisna_gerekce: Mapped[str | None]
    istisna_veren_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    istisna_zamani: Mapped[datetime | None]
    olusturma: Mapped[datetime] = olusturma_col()
    # Son yeniden hesaplama zamanı (iş anahtarının sürüm damgası; `olusturma` değişmez).
    guncelleme: Mapped[datetime] = guncelleme_col()


class OracleIstisna(Base):
    """Gerekçeli istisna (append-only; §13.2). `tur`: `uyumsuz` (tabloya rağmen onay) ya da
    `kontrolsuz` (kontrol edilemeyen yüksek riskli case'in onayı). `tablo_hashleri` istisnanın
    verildiği karşılaştırmanın tablolarıdır: tablo değişince istisna geçerliliğini yitirir."""

    __tablename__ = "oracle_istisna"
    __table_args__ = (
        in_check("tur", enums.ORACLE_ISTISNA_TUR, "oracle_istisna_tur_ck"),
        Index("oracle_istisna_case_ix", "test_case_id", "icerik_hash"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    test_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_case.id", ondelete="CASCADE"))
    icerik_hash: Mapped[str]
    tur: Mapped[str]
    gerekce: Mapped[str]
    veren_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    tablo_hashleri: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=EMPTY_OBJ, default=dict
    )
    zaman: Mapped[datetime] = olusturma_col()


class MetamorfikTuretme(Base):
    """(ilişki, kaynak case) başına türetme kaydı (§4.5); aynı çift ikinci kez türetilmez."""

    __tablename__ = "metamorfik_turetme"
    __table_args__ = (
        in_check("sonuc", enums.TURETME_SONUC, "metamorfik_turetme_sonuc_ck"),
        UniqueConstraint("iliski_id", "kaynak_case_id", name="metamorfik_turetme_cift_uq"),
        Index("metamorfik_turetme_kaynak_ix", "kaynak_case_id"),
        Index("metamorfik_turetme_turetilen_ix", "turetilen_case_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    iliski_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("metamorfik_iliski.id", ondelete="CASCADE")
    )
    kaynak_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_case.id", ondelete="CASCADE")
    )
    turetilen_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("test_case.id", ondelete="SET NULL")
    )
    sonuc: Mapped[str]
    neden: Mapped[str | None]
    olusturan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    olusturma: Mapped[datetime] = olusturma_col()


class HataKosusu(Base):
    """Ekilmiş hata koşusu (§4.6): seçilen platformlarda temel → her hata → kapanış."""

    __tablename__ = "hata_kosusu"
    __table_args__ = (
        in_check("durum", enums.HATA_KOSUSU_DURUM, "hata_kosusu_durum_ck"),
        Index("hata_kosusu_durum_ix", "durum"),
        Index("hata_kosusu_olusturma_ix", "olusturma"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    durum: Mapped[str] = mapped_column(server_default="queued", default="queued")
    # ["web", "android", …] (enums.PLATFORM) ve koşulacak hata kodları (rules/hata-katalogu.yaml).
    platformlar: Mapped[list[Any]] = mapped_column(JSONB, server_default=EMPTY_LIST, default=list)
    hatalar: Mapped[list[Any]] = mapped_column(JSONB, server_default=EMPTY_LIST, default=list)
    commit: Mapped[str | None]
    baslatan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    # {oran, yakalanan, kacan, gecersiz, platformlar: [...]} — koşu bitince yazılır.
    ozet: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJ, default=dict)
    uyarilar: Mapped[list[Any]] = mapped_column(JSONB, server_default=EMPTY_LIST, default=list)
    baslama: Mapped[datetime | None]
    bitis: Mapped[datetime | None]
    olusturma: Mapped[datetime] = olusturma_col()


class HataKosusuAdim(Base):
    """Koşunun bir adımı: (platform, aşama, hata). Temel ve kapanışta `hata_kodu` boştur."""

    __tablename__ = "hata_kosusu_adim"
    __table_args__ = (
        in_check("platform", enums.PLATFORM, "hata_kosusu_adim_platform_ck"),
        in_check("asama", enums.HATA_KOSUSU_ASAMA, "hata_kosusu_adim_asama_ck"),
        in_check("sonuc", enums.HATA_KOSUSU_ADIM_SONUC, "hata_kosusu_adim_sonuc_ck"),
        CheckConstraint(
            "(asama = 'hata') = (hata_kodu IS NOT NULL)", name="hata_kosusu_adim_hata_kodu_ck"
        ),
        UniqueConstraint("kosu_id", "sira", name="hata_kosusu_adim_sira_uq"),
        Index("hata_kosusu_adim_run_ix", "run_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kosu_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hata_kosusu.id", ondelete="CASCADE"))
    platform: Mapped[str]
    hata_kodu: Mapped[str | None]
    asama: Mapped[str]
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("run.id", ondelete="SET NULL"))
    sonuc: Mapped[str] = mapped_column(server_default="bekliyor", default="bekliyor")
    # Hatayı yakalayan (kırmızıya dönen) testler: [{test, dosya?, mesaj?}]
    kiran_testler: Mapped[list[Any]] = mapped_column(JSONB, server_default=EMPTY_LIST, default=list)
    neden: Mapped[str | None]
    sure_ms: Mapped[int | None] = mapped_column(Integer)
    # Koşu içindeki yürütme sırası (0'dan başlar).
    sira: Mapped[int] = mapped_column(Integer)
