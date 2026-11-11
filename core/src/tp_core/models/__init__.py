"""SQLAlchemy 2 ORM modelleri (TEKNIK-TASARIM §7, MIMARI-SOZLESME §4).

Şema değişikliği yalnızca `core/alembic/versions/` migrasyonlarıyla yapılır; modeller ile
migrasyonun eşitliği birim testinde (`compare_metadata`) doğrulanır. Durum makinesi olan
tablolarda `durum` yalnızca `tp_core.workflow.transition()` ile değişir (bkz. `guard`).
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from tp_core.models import asistan as asistan
from tp_core.models import baseline_feature as baseline_feature
from tp_core.models import bugs_feature as bugs_feature
from tp_core.models import ci_feature as ci_feature
from tp_core.models import codegen_feature as codegen_feature
from tp_core.models import guard as guard
from tp_core.models import requirements_feature as requirements_feature
from tp_core.models import triage_feature as triage_feature
from tp_core.models.base import Base
from tp_core.models.cases_feature import CaseGoruntuleme as CaseGoruntuleme
from tp_core.models.cases_feature import CaseUretim as CaseUretim
from tp_core.models.delivery import (
    BugDraft,
    ExternalRef,
    Failure,
    PullRequest,
    Run,
    Script,
    ScriptTestCase,
    StepMapping,
    TestResult,
)
from tp_core.models.guard import StateWriteForbidden
from tp_core.models.identity import ApiToken, AppUser, KimlikBagi, Oturum
from tp_core.models.requirements import (
    ConsistencyFinding,
    Requirement,
    RequirementReview,
    Review,
    TestCase,
    case_id,
)
from tp_core.models.system import AiCall, AuditEvent, Job, ToolCall, WorkflowInstance

# durum makinesi olan tablo adı → model sınıfı
STATEFUL: dict[str, type[Base]] = {
    "requirement": Requirement,
    "requirement_review": RequirementReview,
    "consistency_finding": ConsistencyFinding,
    "test_case": TestCase,
    "script": Script,
    "bug_draft": BugDraft,
    "workflow_instance": WorkflowInstance,
}


def new_session() -> Session:
    """Varsayılan motora bağlı yeni oturum (commit çağırana aittir)."""
    from tp_core.db import get_engine

    return Session(get_engine(), expire_on_commit=False)


def db_session() -> Iterator[Session]:
    """FastAPI bağımlılığı: istek başına oturum; başarıda commit, hatada rollback."""
    with new_session() as session:
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise


@contextmanager
def session_scope() -> Iterator[Session]:
    """İşlem kapsamı: başarıda commit, hatada rollback."""
    with new_session() as session, session.begin():
        yield session


__all__ = [
    "STATEFUL",
    "AiCall",
    "ApiToken",
    "AppUser",
    "AuditEvent",
    "Base",
    "BugDraft",
    "ConsistencyFinding",
    "ExternalRef",
    "Failure",
    "Job",
    "KimlikBagi",
    "Oturum",
    "PullRequest",
    "Requirement",
    "RequirementReview",
    "Review",
    "Run",
    "Script",
    "ScriptTestCase",
    "StateWriteForbidden",
    "StepMapping",
    "TestCase",
    "TestResult",
    "ToolCall",
    "WorkflowInstance",
    "case_id",
    "db_session",
    "new_session",
    "session_scope",
]
