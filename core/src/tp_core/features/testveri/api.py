"""Test verisi kataloğu uçları (specs/013-sprint-otomasyonu §3.3).

| Yöntem | Yol | İzin |
|---|---|---|
| GET | `/test-data` | `case.read` |
| POST | `/test-data` | `testdata.manage` |
| PUT | `/test-data/{id}` | `testdata.manage` — `beklenen_surum` zorunlu (iyimser kilit, 409) |
| DELETE | `/test-data/{id}?beklenen_surum=` | `testdata.manage` — atıf yapan etkin case varsa 409 |
| GET | `/test-data/{id}/history` | `case.read` |

Gizli kayıtta değer hiçbir yanıtta dönmez; `sir_tanimli` döner. PUT'ta `aciklama: ""` (ya da
açıkça `null`) açıklamayı temizler. DELETE 409 gövdesi: `{detail, kod: "cakisma", kullanan:
[{case_id, case_ref, requirement_id, baslik, durum}]}`.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from tp_core.auth.deps import DbSession
from tp_core.auth.yetki import izin
from tp_core.features.testveri import service
from tp_core.workflow.service import Principal

router = APIRouter(tags=["test-data"])

Okur = Annotated[Principal, Depends(izin("case.read"))]
Duzenleyen = Annotated[Principal, Depends(izin("testdata.manage"))]


class TestVerisiGirdisi(BaseModel):
    __test__ = False
    anahtar: str = Field(max_length=200)
    grup: str | None = Field(default=None, max_length=100)
    aciklama: str | None = Field(default=None, max_length=500)
    deger: str | None = Field(default=None, max_length=service.MAX_DEGER)
    gizli: bool = False
    sir_adi: str | None = Field(default=None, max_length=100)


class TestVerisiGuncelleme(BaseModel):
    __test__ = False
    deger: str | None = Field(default=None, max_length=service.MAX_DEGER)
    aciklama: str | None = Field(default=None, max_length=500)
    grup: str | None = Field(default=None, max_length=100)
    sir_adi: str | None = Field(default=None, max_length=100)
    beklenen_surum: int


@router.get("/test-data")
def listele(session: DbSession, _user: Okur) -> list[dict[str, Any]]:
    return service.listele(session)


@router.post("/test-data", status_code=201)
def olustur(body: TestVerisiGirdisi, session: DbSession, user: Duzenleyen) -> dict[str, Any]:
    k = service.olustur(session, body.model_dump(), user.kullanici_adi)
    return service.serialize(k)


@router.put("/test-data/{kid}")
def guncelle(
    kid: uuid.UUID, body: TestVerisiGuncelleme, session: DbSession, user: Duzenleyen
) -> dict[str, Any]:
    girdi = body.model_dump(exclude={"beklenen_surum"}, exclude_unset=True)
    k = service.guncelle(session, kid, girdi, body.beklenen_surum, user.kullanici_adi)
    return service.serialize(k)


@router.delete("/test-data/{kid}", response_model=None)
def sil(
    kid: uuid.UUID,
    session: DbSession,
    user: Duzenleyen,
    beklenen_surum: Annotated[int, Query()],
) -> dict[str, Any] | JSONResponse:
    try:
        k = service.sil(session, kid, beklenen_surum, user.kullanici_adi)
    except service.TestVerisiKullanimda as exc:
        return JSONResponse(
            {"detail": str(exc), "kod": "cakisma", "kullanan": exc.kullanan}, status_code=409
        )
    return {"id": str(k.id), "anahtar": k.anahtar, "silindi": True, "surum": k.surum}


@router.get("/test-data/{kid}/history")
def gecmis(kid: uuid.UUID, session: DbSession, _user: Okur) -> list[dict[str, Any]]:
    return service.gecmis(session, kid)
