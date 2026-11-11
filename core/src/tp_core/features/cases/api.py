"""Case uçları (MIMARI-SOZLESME §5; TEKNIK-TASARIM §9).

| Yöntem | Yol | Rol |
|---|---|---|
| POST | `/requirements/{id}/generate-cases` | analyst — yalnızca PO onaylı gereksinim |
| GET  | `/cases?requirement_id=` | herkes |
| GET  | `/cases/{id}` | herkes |
| POST | `/cases/{id}/viewed` | analyst — ilk görüntüleme (review süresinin başlangıcı) |
| POST | `/cases/{id}/decision` (aşağıda `CaseKararGirdisi`) | analyst |
| GET  | `/requirements/{id}/case-metrics` | herkes — kabul oranı ve süreler (§12) |
| GET  | `/requirements/{id}/case-summary` | herkes — üretim özetleri + kapsam matrisi (011 §4.4) |
| POST | `/requirements/{id}/review-complete` | analyst |
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from tp_core.auth.deps import CurrentUser, DbSession, require_role
from tp_core.features.cases import service
from tp_core.workflow.service import Principal

router = APIRouter(tags=["cases"])

Analyst = Annotated[Principal, Depends(require_role("analyst"))]


class IsYaniti(BaseModel):
    job_id: uuid.UUID | None
    durum: str
    mesaj: str | None = None
    workflow_id: uuid.UUID | None = None
    uretim_no: int | None = None


class CaseKararGirdisi(BaseModel):
    karar: Literal["approve", "edit", "reject", "reopen"]
    # Kullanıcının ekranda gördüğü içeriğin hash'i (edit'te düzeltme ÖNCESİ). Portalda zorunlu.
    icerik_hash: str | None = None
    icerik: dict[str, Any] | None = None
    ret_nedeni: (
        Literal[
            "hallucinated_step",
            "missing_ac",
            "wrong_test_data",
            "out_of_scope",
            "duplicate",
            "wrong_element",
        ]
        | None
    ) = None
    gerekce: str | None = Field(default=None, max_length=2000)
    # §12 "beklenen sonuç anlamca değişmedi" insan yargısı (verilmezse metin karşılaştırması).
    beklenen_anlam_degisti: bool | None = None


@router.post(
    "/requirements/{requirement_id}/generate-cases", response_model=IsYaniti, status_code=202
)
def generate_cases(requirement_id: uuid.UUID, session: DbSession, user: Analyst) -> IsYaniti:
    sonuc = service.start_generation(session, requirement_id, user)
    return IsYaniti(
        job_id=sonuc["job_id"],
        workflow_id=sonuc["workflow_id"],
        uretim_no=sonuc["uretim_no"],
        durum="started",
        mesaj="Case üretimi başlatıldı.",
    )


@router.get("/cases")
def list_cases(
    session: DbSession, _user: CurrentUser, requirement_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    return service.list_cases(session, requirement_id)


@router.get("/cases/{case_id}")
def get_case(case_id: uuid.UUID, session: DbSession, _user: CurrentUser) -> dict[str, Any]:
    return service.serialize_cases(session, [service.get_case(session, case_id)])[0]


@router.post("/cases/{case_id}/viewed")
def mark_viewed(case_id: uuid.UUID, session: DbSession, user: Analyst) -> dict[str, Any]:
    return service.mark_viewed(session, case_id, user)


@router.post("/cases/{case_id}/decision")
def decide(
    case_id: uuid.UUID, body: CaseKararGirdisi, session: DbSession, user: Analyst
) -> dict[str, Any]:
    tc = service.decide(
        session,
        case_id,
        user,
        karar=body.karar,
        icerik_hash=body.icerik_hash,
        icerik=body.icerik,
        ret_nedeni=body.ret_nedeni,
        gerekce=body.gerekce,
        beklenen_anlam_degisti=body.beklenen_anlam_degisti,
    )
    session.flush()
    return service.serialize_cases(session, [tc])[0]


@router.get("/requirements/{requirement_id}/case-metrics")
def case_metrics(
    requirement_id: uuid.UUID, session: DbSession, _user: CurrentUser
) -> dict[str, Any]:
    return service.requirement_metrics(session, requirement_id)


@router.get("/requirements/{requirement_id}/case-summary")
def case_summary(
    requirement_id: uuid.UUID, session: DbSession, _user: CurrentUser
) -> dict[str, Any]:
    return service.case_summary(session, requirement_id)


@router.post("/requirements/{requirement_id}/review-complete")
def review_complete(requirement_id: uuid.UUID, session: DbSession, user: Analyst) -> dict[str, Any]:
    return service.review_complete(session, requirement_id, user)
