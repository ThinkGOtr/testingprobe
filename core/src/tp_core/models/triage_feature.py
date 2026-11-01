"""Triage şeridinin (Faz 4: FailureToFix sınıflandırması, TEKNIK-TASARIM §8.6) ek tabloları —
migrasyon 0011.

Platform tablosu `failure` (sınıf, alt tür, eşleşen sinyaller, karar kaynağı, öneri türü/durumu)
olduğu gibi kullanılır; şeridin ihtiyaç duyduğu ek kayıtlar ayrı tablolardadır:

- `failure_ek` (failure ile 1:1): idempotens anahtarı (`<run_id>:<test anahtarı>`, UNIQUE — aynı
  koşunun aynı testi iki kez sınıflandırılmaz), kaynak (`ci` | `codegen` | `kirma`), bağlı script /
  yerel kontrol, eşleşen kuralın adı, triage'ın baktığı kanıtın özeti (hata metni, beklenen /
  gerçekleşen, konum, aria parçası, sağlık, locator yoklaması — güvenilmeyen veri, kırpılmış),
  kanıt bağlantıları, locator onarım önerisi (`{locator_key, old_testid, new_testid, …}`; onarım
  şeridi `POST /failures/{id}/fix` ile kullanır), öneri yoksa nedeni ve LLM yorumu.
- `triage_kosu` (run ile 1:1): koşunun triage'ı yapıldı mı (`done` | `skipped`) ve neden. Süpürme
  işi bu tablodan bakılmamış kırmızı koşuları bulur; aynı koşu iki kez işlenmez.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tp_core.models.base import Base, in_check, olusturma_col
from tp_core.models.requirements import EMPTY_LIST, EMPTY_OBJ

TRIAGE_KAYNAK = frozenset({"ci", "codegen", "kirma"})
TRIAGE_KOSU_DURUM = frozenset({"done", "skipped"})


class FailureEk(Base):
    """Triage sonucunun ek kaydı (failure ile 1:1)."""

    __tablename__ = "failure_ek"
    __table_args__ = (
        in_check("kaynak", TRIAGE_KAYNAK, "failure_ek_kaynak_ck"),
        Index("failure_ek_script_ix", "script_id"),
    )

    failure_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("failure.id", ondelete="CASCADE"), primary_key=True
    )
    anahtar: Mapped[str] = mapped_column(unique=True)
    kaynak: Mapped[str] = mapped_column(server_default="ci", default="ci")
    kirma: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    script_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("script.id", ondelete="SET NULL")
    )
    script_kontrol_id: Mapped[uuid.UUID | None]
    kural: Mapped[str | None]
    # TriageKaniti: {hata_mesaji, hata_turu, beklenen, gerceklesen, konum, adim, locator,
    # aria_snippet, aria_kapsami, saglik, locator_probe, tekrar, denemeler, trace}
    kanit: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJ, default=dict)
    # [{etiket, yol (koşu dizinine göre)}]
    kanit_linkleri: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=EMPTY_LIST, default=list
    )
    # Locator onarım önerisi: {locator_key, old_testid, new_testid, dosya, sinif, rol, ad, within,
    # scope_test_id, url_path, sha, probe{…dört sha alanı…}, son_yesil_run_id}
    oneri: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    oneri_yok_nedeni: Mapped[str | None]
    # LLM yorumu (yalnızca kural eşleşmediğinde): {class, sub_type, rationale, signals, mod}
    llm: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    olusturma: Mapped[datetime] = olusturma_col()


class TriageKosu(Base):
    """Koşu başına triage kaydı (süpürme ve idempotens)."""

    __tablename__ = "triage_kosu"
    __table_args__ = (in_check("durum", TRIAGE_KOSU_DURUM, "triage_kosu_durum_ck"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("run.id", ondelete="CASCADE"), primary_key=True
    )
    durum: Mapped[str]
    neden: Mapped[str | None]
    sayilar: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJ, default=dict)
    olusturma: Mapped[datetime] = olusturma_col()
