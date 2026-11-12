"""Oracle uçları (012 ANALIZ §6).

| Yöntem | Yol | Rol |
|---|---|---|
| GET  | `/cases/{id}/oracle?icerik_hash=` | herkes — güncel ya da önerilen içeriğin sonucu |
| POST | `/cases/{id}/oracle-check` `{icerik?}` | analyst — 202 `{job_id, icerik_hash}`) |

`POST` önerilen içeriği case içerik doğrulamasıyla (şema + AC atıfları) denetler; içerik case'e
yazılmaz. Sonuç `oracle.checked` olayıyla duyurulur, `GET` ile okunur.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from tp_core.audit import content_hash
from tp_core.auth.deps import CurrentUser, DbSession, require_role
from tp_core.features.cases import service as cases_service
from tp_core.features.cases.schema import content_errors
from tp_core.features.oracle import service
from tp_core.workflow.service import Principal

router = APIRouter(tags=["oracle"])

Analyst = Annotated[Principal, Depends(require_role("analyst"))]


class KontrolIstegi(BaseModel):
    # Düzeltme formundaki önerilen içerik; verilmezse case'in güncel içeriği kontrol edilir.
    icerik: dict[str, Any] | None = None


class KontrolYaniti(BaseModel):
    job_id: uuid.UUID
    icerik_hash: str


@router.get("/cases/{case_id}/oracle")
def get_oracle(
    case_id: uuid.UUID, session: DbSession, _user: CurrentUser, icerik_hash: str | None = None
) -> dict[str, Any]:
    tc = cases_service.get_case(session, case_id)
    return service.case_oracle(session, tc, icerik_hash)


@router.post("/cases/{case_id}/oracle-check", response_model=KontrolYaniti, status_code=202)
def oracle_check(
    case_id: uuid.UUID, session: DbSession, _user: Analyst, body: KontrolIstegi | None = None
) -> KontrolYaniti:
    tc = cases_service.get_case(session, case_id)
    icerik = body.icerik if body is not None else None
    if icerik is not None:
        req = cases_service.get_requirement(session, tc.requirement_id)
        hatalar = content_errors(icerik, req.kabul_kriterleri)
        if hatalar:
            raise cases_service.InvalidCaseContent("Önerilen case içeriği şemaya uymuyor", hatalar)
        h = content_hash(dict(icerik))
    else:
        h = tc.icerik_hash
    job_id = service.kontrol_kuyruga_al(session, tc.id, h, icerik if h != tc.icerik_hash else None)
    return KontrolYaniti(job_id=job_id, icerik_hash=h)
