"""Metamorfik türetme uçları (ANALIZ §6).

| Yöntem | Yol | Rol |
|---|---|---|
| POST | `/requirements/{id}/metamorphic-cases` `{iliski_id, case_ids?}` | analyst |
| GET  | `/requirements/{id}/metamorphic-derivations` | herkes |

POST yanıtı: `{turetilen: [{case_id, kaynak_case_id, baslik}], atlanan: [{kaynak_case_id, sonuc,
neden}]}`. `atlanan[].sonuc`: `iliski_gecersiz | belirsiz_alinti | olgu_yok | zaten_turetildi`.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from tp_core.auth.deps import CurrentUser, DbSession, require_role
from tp_core.features.metamorfik import service
from tp_core.workflow.service import Principal

router = APIRouter(tags=["metamorfik"])

Analyst = Annotated[Principal, Depends(require_role("analyst"))]


class TuretmeGirdisi(BaseModel):
    iliski_id: uuid.UUID
    # Verilmezse ilişkinin AC'lerine atıf yapan bütün güncel case'ler kaynak olur.
    case_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=200)


class Turetilen(BaseModel):
    case_id: str
    kaynak_case_id: str
    baslik: str


class Atlanan(BaseModel):
    kaynak_case_id: str
    sonuc: str
    neden: str | None


class TuretmeYaniti(BaseModel):
    turetilen: list[Turetilen]
    atlanan: list[Atlanan]


@router.post("/requirements/{requirement_id}/metamorphic-cases", response_model=TuretmeYaniti)
def metamorphic_cases(
    requirement_id: uuid.UUID, body: TuretmeGirdisi, session: DbSession, user: Analyst
) -> dict[str, Any]:
    return service.turet(session, requirement_id, body.iliski_id, body.case_ids, user)


@router.get("/requirements/{requirement_id}/metamorphic-derivations")
def metamorphic_derivations(
    requirement_id: uuid.UUID, session: DbSession, _user: CurrentUser
) -> list[dict[str, Any]]:
    return service.turetmeler(session, requirement_id)
