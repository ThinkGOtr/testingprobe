"""İş kuyruğu, iş akışı örnekleri ve append-only denetim tabloları."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, Index, Integer, Numeric, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tp_core.models import enums
from tp_core.models.base import NOW, Base, guncelleme_col, in_check, olusturma_col, uuid_pk
from tp_core.models.requirements import EMPTY_OBJ, _durum


class Job(Base):
    """Postgres iş kuyruğu (FOR UPDATE SKIP LOCKED). Durumları `workflow.jobs` yönetir."""

    __tablename__ = "job"
    __table_args__ = (
        in_check("durum", enums.JOB_DURUM, "job_durum_ck"),
        Index(
            "job_kuyruk_ix",
            "run_after",
            "olusturma",
            postgresql_where=text("durum IN ('queued', 'retry')"),
        ),
        Index(
            "job_idempotency_uq",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        # 012 oracle hız sınırı ve gereksinim işi birleştirme (migrasyon 0034; review 2 t2 N10).
        Index(
            "job_oracle_case_ix",
            text("(yuk ->> 'case_id')"),
            "olusturma",
            postgresql_where=text("tur = 'oracle.check_case'"),
        ),
        Index(
            "job_oracle_gereksinim_ix",
            text("(yuk ->> 'requirement_id')"),
            "olusturma",
            postgresql_where=text("tur IN ('oracle.check_case', 'oracle.check_requirement')"),
        ),
        Index(
            "job_oracle_isteyen_ix",
            text("(yuk ->> 'isteyen_id')"),
            "olusturma",
            postgresql_where=text("tur = 'oracle.check_case'"),
        ),
        # 0030: gereksinim → son otomatik case işi (otomatik akış rozeti, 013 §9).
        Index(
            "job_otomatik_case_req_ix",
            text("(yuk ->> 'requirement_id')"),
            "olusturma",
            postgresql_where=text("tur = 'requirements.otomatik_case'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tur: Mapped[str]
    durum: Mapped[str] = mapped_column(server_default="queued", default="queued")
    yuk: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    deneme: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    max_deneme: Mapped[int | None] = mapped_column(Integer)
    son_hata: Mapped[str | None]
    run_after: Mapped[datetime] = mapped_column(server_default=NOW)
    idempotency_key: Mapped[str | None]
    workflow_id: Mapped[uuid.UUID | None]
    sonuc: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    kilitleyen: Mapped[str | None]
    baslama: Mapped[datetime | None]
    bitis: Mapped[datetime | None]
    # NULL = işleyicinin kayıttaki politikası (0003); satırdaki değer onu ezer.
    zaman_asimi_s: Mapped[int | None] = mapped_column(Integer)
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()


class WorkflowInstance(Base):
    """İş akışı örneği (demo: Temporal yerine Postgres; `temporal_id` yerine `job_id`)."""

    __tablename__ = "workflow_instance"
    __table_args__ = (
        in_check("durum", enums.durumlar("workflow_instance"), "workflow_instance_durum_ck"),
        Index("workflow_instance_nesne_ix", "nesne_turu", "nesne_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tur: Mapped[str]
    job_id: Mapped[uuid.UUID | None]
    durum: Mapped[str] = _durum("workflow_instance")
    baslatan: Mapped[str]
    nesne_turu: Mapped[str | None]
    nesne_id: Mapped[uuid.UUID | None]
    baglam: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJ, default=dict)
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()


class AiCall(Base):
    """Her model çağrısı (append-only; uygulama rolü yalnızca INSERT/SELECT)."""

    __tablename__ = "ai_call"
    __table_args__ = (
        in_check("mod", enums.AI_MOD, "ai_call_mod_ck"),
        Index("ai_call_workflow_ix", "workflow_id"),
        Index("ai_call_olusturma_ix", "olusturma"),
        Index("ai_call_parent_ix", "parent_call_id"),  # 0017: asistan soru başı harcama
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    parent_call_id: Mapped[uuid.UUID | None]
    workflow_id: Mapped[uuid.UUID | None]
    amac: Mapped[str]
    saglayici: Mapped[str]
    model: Mapped[str]
    surum: Mapped[str | None]
    bundle_hash: Mapped[str | None]
    maskeli_girdi: Mapped[Any | None] = mapped_column(JSONB)
    cikti: Mapped[Any | None] = mapped_column(JSONB)
    sema_gecerli: Mapped[bool | None] = mapped_column(Boolean)
    deneme: Mapped[int] = mapped_column(Integer, server_default="1", default=1)
    girdi_token: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    cikti_token: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    maliyet: Mapped[Decimal] = mapped_column(Numeric(12, 6), server_default="0", default=0)
    sure_ms: Mapped[int | None] = mapped_column(Integer)
    mod: Mapped[str]
    replay_anahtari: Mapped[str | None]
    hata: Mapped[str | None]
    maskeleme_farki: Mapped[Any | None] = mapped_column(JSONB)
    # Kolonu olmayan geçit ayrıntıları: replay_kaynagi, replay_kokeni, sema_hatalari, … (0005)
    ek: Mapped[Any | None] = mapped_column(JSONB)
    olusturma: Mapped[datetime] = olusturma_col()


class ToolCall(Base):
    """Her araç çağrısı (ajan veya IDE kanalı); append-only."""

    __tablename__ = "tool_call"
    __table_args__ = (
        in_check("kanal", enums.TOOL_KANAL, "tool_call_kanal_ck"),
        Index("tool_call_ai_call_ix", "ai_call_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    ai_call_id: Mapped[uuid.UUID | None]
    kanal: Mapped[str]
    cagiran_user_id: Mapped[uuid.UUID | None]
    arac: Mapped[str]
    arguman_ozeti: Mapped[Any | None] = mapped_column(JSONB)
    sonuc_ozeti: Mapped[str | None]
    izin_verildi: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    sure_ms: Mapped[int | None] = mapped_column(Integer)
    zaman: Mapped[datetime] = olusturma_col()


class AuditEvent(Base):
    """Hash zincirli denetim kaydı; yazım yalnızca `audit_on_commit` / `append_audit` ile."""

    __tablename__ = "audit_event"
    __table_args__ = (
        # 0030 (013): Jira tetiği ve model kipi denetim sorguları için kısmi indeksler.
        Index(
            "audit_event_jira_tetik_ix",
            "id",
            postgresql_where=text("eylem = 'requirements.jira_tetik'"),
        ),
        Index(
            "audit_event_jira_tetik_key_ix",
            text("(ozet ->> 'jira_key')"),
            "id",
            postgresql_where=text("eylem = 'requirements.jira_tetik'"),
        ),
        Index(
            "audit_event_model_kipi_ix",
            "id",
            postgresql_where=text("eylem = 'worker.model_mode'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    zaman: Mapped[datetime] = olusturma_col()
    aktor: Mapped[str]
    eylem: Mapped[str]
    nesne: Mapped[str | None]
    ozet: Mapped[Any | None] = mapped_column(JSONB)
    prev_hash: Mapped[str] = mapped_column(unique=True)
    hash: Mapped[str] = mapped_column(unique=True)
