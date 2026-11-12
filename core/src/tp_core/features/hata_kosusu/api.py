"""Ekilmiş hata koşusu uçları (ANALIZ §4.6, §6).

| Yöntem | Yol | Rol |
|---|---|---|
| POST | `/fault-runs` `{platformlar, hatalar?}` | engineer, presenter — 202 `{id, durum}` |
| GET  | `/fault-runs?limit=` | herkes — son koşular (yeniden eskiye) |
| GET  | `/fault-runs/catalog` | herkes — hata kataloğu |
| GET  | `/fault-runs/{id}` | herkes — koşu + adımlar |
| POST | `/fault-runs/{id}/cancel` | engineer, presenter — iptal |

Süren koşu varken başlatma 409 `hata_kosusu_suruyor`. İptal: kuyruktaki koşu hemen, süren koşu
adım arasında durur (koşmakta olan `/check` bitene kadar beklenir).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from tp_core.auth.deps import CurrentUser, DbSession, require_role
from tp_core.features.hata_kosusu import katalog as kat
from tp_core.features.hata_kosusu import service
from tp_core.workflow.service import Principal

router = APIRouter(tags=["hata_kosusu"])

Baslatan = Annotated[Principal, Depends(require_role("engineer", "presenter"))]
KOD = r"^[a-z0-9_]{1,40}$"


class KosuGirdisi(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platformlar: list[str] = Field(min_length=1, max_length=4)
    hatalar: list[Annotated[str, Field(pattern=KOD)]] | None = Field(default=None, max_length=50)


@router.post("/fault-runs", status_code=202)
def baslat(body: KosuGirdisi, session: DbSession, user: Baslatan) -> dict[str, Any]:
    try:
        return service.baslat(session, body.platformlar, body.hatalar, user)
    except service.GecersizIstek as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/fault-runs")
def liste(
    session: DbSession,
    _user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[dict[str, Any]]:
    return service.liste(session, limit)


@router.get("/fault-runs/catalog")
def katalog(_user: CurrentUser) -> list[dict[str, Any]]:
    return kat.katalog()


@router.get("/fault-runs/{kosu_id}")
def detay(kosu_id: uuid.UUID, session: DbSession, _user: CurrentUser) -> dict[str, Any]:
    d = service.detay(session, kosu_id)
    if d is None:
        raise HTTPException(404, "Ekilmiş hata koşusu bulunamadı")
    return d


@router.post("/fault-runs/{kosu_id}/cancel")
def iptal(kosu_id: uuid.UUID, session: DbSession, user: Baslatan) -> dict[str, Any]:
    d = service.iptal(session, kosu_id, user)
    if d is None:
        raise HTTPException(404, "Ekilmiş hata koşusu bulunamadı")
    return d
