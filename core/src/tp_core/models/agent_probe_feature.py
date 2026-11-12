"""Agent Probe bütünleşmesinin tabloları (migrasyon 0025, specs/011 §4.3 satır 0025).

- `ajan_urunu_baglantisi`: gereksinim ↔ Agent Probe ajan ürünü (gereksinim başına en çok bir ürün).
  Ayrı tablodur, `requirement` kolonu değildir: bağlantı gereksinim içeriği değildir (içerik
  hash'ine ve PO onayına girmez), kim/ne zaman bağladığı tutulur, kaldırılabilir (satır
  silinir) ve sıcak `requirement` modeline dokunulmaz.
- `ajan_testi_talebi`: Agent Probe'a atılan ajan testi kaydı (talep no `APT-<yıl>-<n>`), durumu ve
  sonucu. `islenme`: Testing Probe sonucu işledi (geçti → gereksinim `done`; kaldı → bulgu); `surec`
  işlemenin sonucu (`simule`: simülasyon sonucu gösterildi, gereksinim ilerletilmedi). Bu sürümde
  talepler simülatöre gider (`simulasyon`); talep no `ajan_testi_talebi_no_seq` dizisinden (0027).
- `asistan_denetim`: asistan sorusu/cevabı için denetim puanı ve kodun verdiği karar (011 F7).
  `ai_call_id` geçit çağrısıdır (sim kaynağında boş); asistanın soru başı bütçesi bu kolonla denetim
  çağrılarını da sayar.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tp_core.models.base import Base, guncelleme_col, in_check, olusturma_col, uuid_pk

AJAN_TESTI_DURUM = frozenset({"queued", "running", "passed", "failed", "error"})
AJAN_TESTI_SUREC = frozenset({"tamamlandi", "bulgu", "onay_gecersiz", "hata", "simule"})
DENETIM_YON = frozenset({"soru", "cevap"})
DENETIM_KARAR = frozenset({"gec", "uyar", "engelle"})
DENETIM_KAYNAK = frozenset({"tp-gecit", "agent-probe", "sim"})


class AjanUrunuBaglantisi(Base):
    __tablename__ = "ajan_urunu_baglantisi"

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement.id", ondelete="CASCADE"), primary_key=True
    )
    urun_kodu: Mapped[str]
    baglayan: Mapped[str]
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()


class AjanTestiTalebi(Base):
    __tablename__ = "ajan_testi_talebi"
    __table_args__ = (
        in_check("durum", AJAN_TESTI_DURUM, "ajan_testi_talebi_durum_ck"),
        in_check("surec", AJAN_TESTI_SUREC, "ajan_testi_talebi_surec_ck", nullable=True),
        Index("ajan_testi_talebi_req_ix", "requirement_id", "olusturma"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement.id", ondelete="CASCADE")
    )
    urun_kodu: Mapped[str]
    talep_no: Mapped[str] = mapped_column(unique=True)
    durum: Mapped[str] = mapped_column(server_default="queued", default="queued")
    ozet: Mapped[str] = mapped_column(server_default="", default="")
    sonuc: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )
    url: Mapped[str | None]
    simulasyon: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    baslatan: Mapped[str | None]
    # Talep anındaki PO onaylı içerik hash'i (sonuç bu içeriğe aittir).
    gereksinim_hash: Mapped[str | None]
    islenme: Mapped[datetime | None]
    surec: Mapped[str | None]
    surec_notu: Mapped[str | None]
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()


class AsistanDenetim(Base):
    __tablename__ = "asistan_denetim"
    __table_args__ = (
        in_check("yon", DENETIM_YON, "asistan_denetim_yon_ck"),
        in_check("karar", DENETIM_KARAR, "asistan_denetim_karar_ck"),
        in_check("kaynak", DENETIM_KAYNAK, "asistan_denetim_kaynak_ck"),
        CheckConstraint("puan BETWEEN 0 AND 100", name="asistan_denetim_puan_ck"),
        Index("asistan_denetim_mesaj_ix", "mesaj_id"),
        Index("asistan_denetim_olusturma_ix", "olusturma"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    mesaj_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("asistan_mesaj.id", ondelete="CASCADE"))
    yon: Mapped[str]
    puan: Mapped[int] = mapped_column(Integer)
    kategoriler: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), default=list
    )
    karar: Mapped[str]
    gerekce: Mapped[str] = mapped_column(server_default="", default="")
    kaynak: Mapped[str]
    talep_no: Mapped[str | None]
    ai_call_id: Mapped[uuid.UUID | None]
    sure_ms: Mapped[int | None] = mapped_column(Integer)
    olusturma: Mapped[datetime] = olusturma_col()
