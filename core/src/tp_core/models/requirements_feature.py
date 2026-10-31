"""Gereksinim özelliğinin (F2 adım 1–3) ek tabloları — migrasyon 0006.

Platform tablolarına (`requirement`, `consistency_finding`, `requirement_review`) dokunmadan,
özelliğin ihtiyaç duyduğu ek kayıtlar ayrı tablolarda tutulur:

- `requirement_kontrol`: her tutarlılık denetimi koşusu (tur, denetlenen belge hash'i, kodun
  denetlendiği forge commit'i, model modu, doğrulanan/elenen bulgu sayıları). Elenen (kanıtı
  doğrulanamayan) bulgu sayısı buradan portala gösterilir (Constitution XI).
- `consistency_finding_ek`: bulgunun model çıktısındaki kimliği (F1…), iddia/gözlem metinleri,
  AI'ın ilk önerisi (analist düzenlerse `consistency_finding.onerilen_metin` değişir, bu kalır),
  bulgu anındaki belge metni ve deterministik kanıt doğrulamasının ayrıntısı.
- `requirement_akis`: belgenin "son hal" (doc_final) hash'i ve zamanı. PO onayı bu hash'e
  bağlanır: etiket geldiğinde güncel içerik bu hash değilse onay kaydedilmez, denetim yeniden koşar;
  son hal anından önce konmuş etiket de onay sayılmaz.
- `requirement_review_ek`: ön incelemenin model özeti (`summary`; şüpheli içerik bildirimi dahil)
  ve incelenen belge (açıklama + AC) anlık görüntüsü. PO'ya soru yorumu son halde yazılır;
  düzeltmeyle değişen AC'lere ait sorular bu görüntüyle ayırt edilir.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tp_core.models import enums
from tp_core.models.base import Base, guncelleme_col, in_check, olusturma_col, uuid_pk
from tp_core.models.requirements import EMPTY_LIST


class RequirementKontrol(Base):
    """Bir tutarlılık denetimi koşusu (§8.2b adım 2–4, 7)."""

    __tablename__ = "requirement_kontrol"
    __table_args__ = (
        in_check("uretim_modu", enums.URETIM_MODU, "requirement_kontrol_mod_ck", True),
        UniqueConstraint("requirement_id", "sira", name="requirement_kontrol_sira_uq"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement.id", ondelete="CASCADE")
    )
    # Gereksinim ömrü boyunca artan sıra (1, 2, …); `tur` ise içinde bulunulan döngünün turu.
    sira: Mapped[int] = mapped_column(Integer)
    tur: Mapped[int] = mapped_column(Integer)
    belge_hash: Mapped[str]
    head_sha: Mapped[str | None]
    workflow_id: Mapped[uuid.UUID | None]
    ai_call_id: Mapped[uuid.UUID | None]
    uretim_modu: Mapped[str | None]
    bulgu_toplam: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    dogrulanan: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    elenen: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    engelleyici: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    notlar: Mapped[str | None]
    olusturma: Mapped[datetime] = olusturma_col()


class ConsistencyFindingEk(Base):
    """Bulgunun model çıktısı ayrıntısı ve kanıt doğrulama sonucu."""

    __tablename__ = "consistency_finding_ek"

    finding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("consistency_finding.id", ondelete="CASCADE"), primary_key=True
    )
    kontrol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement_kontrol.id", ondelete="CASCADE"), index=True
    )
    bulgu_no: Mapped[str]
    iddia: Mapped[str] = mapped_column(server_default="", default="")
    gozlem: Mapped[str] = mapped_column(server_default="", default="")
    # Düzeltmenin değiştireceği belge metni (öneri hedefleri; yoksa doc_ref'in metni).
    mevcut_doc_text: Mapped[str | None]
    # doc_ref'in bulgu anındaki metni (önceki kararı devralma eşleşmesi bunu karşılaştırır).
    ref_metni: Mapped[str | None]
    ai_onerisi: Mapped[str | None]
    dogrulama: Mapped[list[Any]] = mapped_column(JSONB, server_default=EMPTY_LIST, default=list)
    # Aynı fark önceki turda insan kararıyla kapandıysa (code_defect / accept_difference) o bulgu;
    # bu bulgu yeniden karar istemez (bayatlatılır) ve kararı oradan gösterilir.
    onceki_finding_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("consistency_finding.id", ondelete="SET NULL")
    )
    olusturma: Mapped[datetime] = olusturma_col()


class RequirementAkis(Base):
    """Gereksinim akışının özellik durumu: belgenin son hali (doc_final) hash'i."""

    __tablename__ = "requirement_akis"

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement.id", ondelete="CASCADE"), primary_key=True
    )
    son_hal_hash: Mapped[str | None]
    son_hal_zamani: Mapped[datetime | None]
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()


class RequirementReviewEk(Base):
    """Ön incelemenin model özeti ve incelenen belgenin anlık görüntüsü (§8.2a, §5)."""

    __tablename__ = "requirement_review_ek"

    review_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requirement_review.id", ondelete="CASCADE"), primary_key=True
    )
    ozet: Mapped[str] = mapped_column(server_default="", default="")
    aciklama: Mapped[str] = mapped_column(server_default="", default="")
    kabul_kriterleri: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=EMPTY_LIST, default=list
    )
    olusturma: Mapped[datetime] = olusturma_col()
