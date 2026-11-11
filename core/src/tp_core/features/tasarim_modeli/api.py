"""Test tasarım modeli uçları (specs/011 F3, §4.4).

| Yöntem | Yol | Rol |
|---|---|---|
| GET  | `/requirements/{id}/design-model` | herkes — son model + geçmiş özeti |
| POST | `/requirements/{id}/design-model` | analyst — modeli (yeniden) üret (202) |
| POST | `/design-models/{id}/decision` (`ModelKararGirdisi`) | analyst — approve / edit / reject |

İki turun başlangıcı ve onaylı modelden case üretimi `POST /requirements/{id}/generate-cases`
(`{kip: "iki_tur"}`) ucundadır (`features.cases.api`).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from tp_core.auth.deps import CurrentUser, DbSession, require_role
from tp_core.features.cases import model_service
from tp_core.features.cases.api import IsYaniti
from tp_core.workflow.service import Principal

router = APIRouter(tags=["design-model"])

Analyst = Annotated[Principal, Depends(require_role("analyst"))]


class ModelKararGirdisi(BaseModel):
    karar: Literal["approve", "edit", "reject"]
    # Ekranda görülen modelin hash'i (edit'te düzeltme ÖNCESİ). Zorunlu.
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


@router.get("/requirements/{requirement_id}/design-model")
def get_design_model(
    requirement_id: uuid.UUID, session: DbSession, _user: CurrentUser
) -> dict[str, Any]:
    return model_service.design_model_view(session, requirement_id)


@router.post(
    "/requirements/{requirement_id}/design-model", response_model=IsYaniti, status_code=202
)
def regenerate_design_model(
    requirement_id: uuid.UUID, session: DbSession, user: Analyst
) -> IsYaniti:
    sonuc = model_service.start_model_generation(session, requirement_id, user)
    return IsYaniti(
        job_id=sonuc["job_id"],
        workflow_id=sonuc["workflow_id"],
        durum="started",
        mesaj="Test tasarım modeli üretimi başlatıldı (iki tur).",
        kip="iki_tur",
        asama="model",
    )


@router.post("/design-models/{model_id}/decision")
def decide_design_model(
    model_id: uuid.UUID, body: ModelKararGirdisi, session: DbSession, user: Analyst
) -> dict[str, Any]:
    m = model_service.decide_model(
        session,
        model_id,
        user,
        karar=body.karar,
        icerik_hash=body.icerik_hash,
        icerik=body.icerik,
        ret_nedeni=body.ret_nedeni,
        gerekce=body.gerekce,
    )
    session.flush()
    req = model_service.get_requirement(session, m.requirement_id)
    return model_service.serialize_model(session, m, req)
