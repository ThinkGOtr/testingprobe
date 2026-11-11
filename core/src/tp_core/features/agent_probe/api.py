"""Agent Probe uçları (specs/011 §4.4, A şeridi; F6).

| Yöntem | Yol | Rol |
|---|---|---|
| GET | `/agent-probe/products` | herkes — Agent Probe'da hazır ajan ürünleri (simülasyon) |
| PUT | `/requirements/{id}/agent-product` (`{urun_kodu: str \\| null}`) | analyst — bağla/kaldır |
| POST | `/requirements/{id}/agent-test` | analyst — Agent Probe'da test başlat (202) |
| GET | `/requirements/{id}/agent-test` | herkes — bağlantı + talep; bitmemiş talep sorgulanır |
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from tp_core.auth.deps import CurrentUser, DbSession, require_role
from tp_core.features.agent_probe import service
from tp_core.workflow.service import Principal

router = APIRouter(tags=["agent-probe"])

Analyst = Annotated[Principal, Depends(require_role("analyst"))]


class UrunBaglamaGirdisi(BaseModel):
    urun_kodu: str | None = Field(default=None, max_length=100)


@router.get("/agent-probe/products")
def urunler(user: CurrentUser) -> dict[str, Any]:
    kip, liste = service.urunler()
    return {"kip": kip, "simulasyon": True, "urunler": [u.model_dump() for u in liste]}


@router.put("/requirements/{requirement_id}/agent-product")
def urun_bagla(
    requirement_id: uuid.UUID, girdi: UrunBaglamaGirdisi, session: DbSession, user: Analyst
) -> dict[str, Any]:
    service.urun_bagla(session, requirement_id, girdi.urun_kodu, user)
    return service.gorunum(session, requirement_id)


@router.post("/requirements/{requirement_id}/agent-test", status_code=202)
def test_baslat(requirement_id: uuid.UUID, session: DbSession, user: Analyst) -> dict[str, Any]:
    service.test_baslat(session, requirement_id, user)
    return service.gorunum(session, requirement_id)


@router.get("/requirements/{requirement_id}/agent-test")
def ajan_testi(requirement_id: uuid.UUID, session: DbSession, user: CurrentUser) -> dict[str, Any]:
    service.yenile(session, requirement_id)
    return service.gorunum(session, requirement_id)
