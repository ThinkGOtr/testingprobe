"""Kod üretimi, PR (LocalForge), koşular, triage, bug taslakları ve dış sistem idempotency'si."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    UniqueConstraint,
    false,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tp_core.models import enums
from tp_core.models.base import Base, guncelleme_col, in_check, olusturma_col, uuid_pk
from tp_core.models.requirements import EMPTY_LIST, EMPTY_OBJ, _durum


class Script(Base):
    """Üretilen Playwright testi veya locator onarımı (§8.4, §8.7)."""

    __tablename__ = "script"
    __table_args__ = (
        in_check("tur", enums.SCRIPT_TUR, "script_tur_ck"),
        in_check("durum", enums.durumlar("script"), "script_durum_ck"),
        in_check("uretim_modu", enums.URETIM_MODU, "script_mod_ck", True),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tur: Mapped[str] = mapped_column(server_default="test", default="test")
    dosya_yolu: Mapped[str]
    icerik: Mapped[str | None]
    icerik_hash: Mapped[str | None]
    onaylanan_hash: Mapped[str | None]
    branch: Mapped[str | None]
    pr_no: Mapped[int | None] = mapped_column(Integer)
    head_sha: Mapped[str | None]
    durum: Mapped[str] = _durum("script")
    pass_at_1: Mapped[bool | None] = mapped_column(Boolean)
    onarim_sonrasi_sonuc: Mapped[str | None]
    insan_review_sonucu: Mapped[str | None]
    zayif_test: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    kirma_dogrulama: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # script → failure → run → script döngüsü: FK tablo oluşturulduktan sonra eklenir.
    failure_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("failure.id", use_alter=True, name="script_failure_id_fkey")
    )
    uretim_modu: Mapped[str | None]
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()


class ScriptTestCase(Base):
    __tablename__ = "script_test_case"
    __table_args__ = (PrimaryKeyConstraint("script_id", "test_case_id"),)

    script_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("script.id", ondelete="CASCADE"))
    test_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_case.id", ondelete="CASCADE"))


class StepMapping(Base):
    """Adım → page object metodu eşlemesi; uygulamada doğrulanmış (§8.4)."""

    __tablename__ = "step_mapping"
    __table_args__ = (
        UniqueConstraint("test_case_id", "script_id", "adim_no", name="step_mapping_adim_uq"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    test_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_case.id", ondelete="CASCADE"))
    script_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("script.id", ondelete="CASCADE"))
    adim_no: Mapped[int] = mapped_column(Integer)
    adim_kimligi: Mapped[str | None]  # "S1"
    po_sinifi: Mapped[str]
    po_metodu: Mapped[str]
    argumanlar: Mapped[list[Any]] = mapped_column(JSONB, server_default=EMPTY_LIST, default=list)
    beklenen: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    dogrulandi: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    ekran_goruntusu_ref: Mapped[str | None]
    kanit_ref: Mapped[str | None]
    olusturma: Mapped[datetime] = olusturma_col()


class PullRequest(Base):
    """LocalForge PR kaydı (TP_FORGE=local); GitHub'da PR GitHub'dadır."""

    __tablename__ = "pull_request"
    __table_args__ = (in_check("durum", enums.PR_DURUM, "pull_request_durum_ck"),)

    number: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    branch: Mapped[str]
    base: Mapped[str] = mapped_column(server_default="main", default="main")
    baslik: Mapped[str]
    govde: Mapped[str] = mapped_column(server_default="", default="")
    durum: Mapped[str] = mapped_column(server_default="open", default="open")
    head_sha: Mapped[str]
    merge_sha: Mapped[str | None]
    etiketler: Mapped[list[Any]] = mapped_column(JSONB, server_default=EMPTY_LIST, default=list)
    yorumlar: Mapped[list[Any]] = mapped_column(JSONB, server_default=EMPTY_LIST, default=list)
    acan: Mapped[str]
    merge_eden: Mapped[str | None]
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()


class Run(Base):
    """Test koşusu (yerel kontrol, CI, Sauce)."""

    __tablename__ = "run"
    __table_args__ = (
        in_check("kaynak", enums.RUN_KAYNAK, "run_kaynak_ck"),
        in_check("tetik", enums.RUN_TETIK, "run_tetik_ck"),
        in_check("sonuc", enums.RUN_SONUC, "run_sonuc_ck"),
        Index("run_olusturma_ix", "olusturma"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    script_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("script.id"))
    pr_no: Mapped[int | None] = mapped_column(Integer)
    commit: Mapped[str | None]
    github_run_id: Mapped[str | None]
    kaynak: Mapped[str] = mapped_column(server_default="local", default="local")
    tetik: Mapped[str]
    sonuc: Mapped[str] = mapped_column(server_default="queued", default="queued")
    ortam: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_OBJ, default=dict)
    artefaktlar: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=EMPTY_OBJ, default=dict
    )
    sure_ms: Mapped[int | None] = mapped_column(Integer)
    baslama: Mapped[datetime | None]
    bitis: Mapped[datetime | None]
    olusturma: Mapped[datetime] = olusturma_col()


class TestResult(Base):
    """JUnit XML'den ayrıştırılan test sonucu (§8.11). §7'deki `durum` burada `sonuc`."""

    __tablename__ = "test_result"
    __test__ = False
    __table_args__ = (
        in_check("sonuc", enums.TEST_SONUC, "test_result_sonuc_ck"),
        in_check("kaynak", enums.RUN_KAYNAK, "test_result_kaynak_ck"),
        in_check("tetik", enums.RUN_TETIK, "test_result_tetik_ck"),
        Index("test_result_run_ix", "run_id"),
        Index("test_result_ad_ix", "test_adi"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"))
    test_case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("test_case.id"))
    test_adi: Mapped[str]
    dosya: Mapped[str | None]
    sonuc: Mapped[str]
    sure_ms: Mapped[int | None] = mapped_column(Integer)
    retry: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    commit: Mapped[str | None]
    tetik: Mapped[str]
    kaynak: Mapped[str] = mapped_column(server_default="local", default="local")
    hata_mesaji: Mapped[str | None]
    olusturma: Mapped[datetime] = olusturma_col()


class Failure(Base):
    """Triage sonucu (§8.6): önce kural, sonra gerekirse LLM."""

    __tablename__ = "failure"
    __table_args__ = (
        in_check("sinif", enums.FAILURE_SINIF, "failure_sinif_ck"),
        in_check("karar_kaynagi", enums.KARAR_KAYNAGI, "failure_karar_kaynagi_ck"),
        in_check("oneri_turu", enums.ONERI_TURU, "failure_oneri_turu_ck"),
        in_check("oneri_durumu", enums.ONERI_DURUMU, "failure_oneri_durumu_ck"),
        in_check("uretim_modu", enums.URETIM_MODU, "failure_mod_ck", True),
        Index("failure_run_ix", "run_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"))
    test_result_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("test_result.id"))
    test_adi: Mapped[str]
    hata_imzasi: Mapped[str]
    sinif: Mapped[str]
    alt_tur: Mapped[str | None]
    eslesen_sinyaller: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=EMPTY_LIST, default=list
    )
    karar_kaynagi: Mapped[str] = mapped_column(server_default="rule", default="rule")
    gerekce: Mapped[str | None]
    oneri_turu: Mapped[str] = mapped_column(server_default="none", default="none")
    oneri_durumu: Mapped[str] = mapped_column(server_default="none", default="none")
    ai_call_id: Mapped[uuid.UUID | None]
    uretim_modu: Mapped[str | None]
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()


class BugDraft(Base):
    """Bug taslağı (§8.12): yalnızca testçi onayı ve onaylanan hash ile yayınlanır."""

    __tablename__ = "bug_draft"
    __table_args__ = (
        in_check("karar", enums.BUG_KARAR, "bug_draft_karar_ck", True),
        in_check("durum", enums.durumlar("bug_draft"), "bug_draft_durum_ck"),
        in_check("uretim_modu", enums.URETIM_MODU, "bug_draft_mod_ck", True),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    failure_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("failure.id"))
    finding_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("consistency_finding.id"))
    icerik: Mapped[dict[str, Any]] = mapped_column(JSONB)
    icerik_hash: Mapped[str]
    mukerrer_adaylari: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=EMPTY_LIST, default=list
    )
    karar: Mapped[str | None]
    link_key: Mapped[str | None]
    onaylayan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    onaylanan_hash: Mapped[str | None]
    jira_key: Mapped[str | None]
    durum: Mapped[str] = _durum("bug_draft")
    ai_call_id: Mapped[uuid.UUID | None]
    uretim_modu: Mapped[str | None]
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()


class ExternalRef(Base):
    """Dış etkili eylemlerin idempotency kaydı: önce `intent`, sonra `created` (§8.3)."""

    __tablename__ = "external_ref"
    __table_args__ = (
        in_check("sistem", enums.EXTERNAL_SISTEM, "external_ref_sistem_ck"),
        in_check("durum", enums.EXTERNAL_DURUM, "external_ref_durum_ck"),
        Index("external_ref_entity_ix", "entity_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    entity_turu: Mapped[str]
    entity_id: Mapped[uuid.UUID]
    sistem: Mapped[str]
    idempotency_key: Mapped[str] = mapped_column(unique=True)
    external_key: Mapped[str | None]
    url: Mapped[str | None]
    durum: Mapped[str] = mapped_column(server_default="intent", default="intent")
    hata: Mapped[str | None]
    olusturma: Mapped[datetime] = olusturma_col()
    guncelleme: Mapped[datetime] = guncelleme_col()
