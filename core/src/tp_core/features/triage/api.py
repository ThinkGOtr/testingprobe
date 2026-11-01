"""Triage uçları (MIMARI-SOZLESME §5).

| Yöntem | Yol | Rol |
|---|---|---|
| GET | `/failures?run_id=&sinif=&karar_kaynagi=&oneri_turu=&oneri_durumu=&script_id=&kaynak=&limit=` | herkes |
| GET | `/failures/{id}` | herkes — triage sonucu (sınıf, eşleşen sinyaller, kanıt, öneri) |

`POST /failures/{id}/fix` (locator onarım PR'ı) repair şeridindedir.
"""  # noqa: E501

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query

from tp_core.auth.deps import CurrentUser, DbSession
from tp_core.features.triage import service

router = APIRouter(tags=["triage"])

SinifSec = Literal[
    "environment", "flaky", "test_maintenance", "product_defect", "test_data", "unknown"
]


@router.get("/failures")
def list_failures(
    session: DbSession,
    _user: CurrentUser,
    run_id: uuid.UUID | None = None,
    sinif: SinifSec | None = None,
    karar_kaynagi: Literal["rule", "llm"] | None = None,
    oneri_turu: Literal["locator_fix", "bug_draft", "none"] | None = None,
    oneri_durumu: Literal["none", "proposed", "pr_open", "merged", "rejected"] | None = None,
    script_id: uuid.UUID | None = None,
    kaynak: Literal["ci", "codegen", "kirma"] | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    return service.list_failures(
        session,
        run_id=run_id,
        sinif=sinif,
        karar_kaynagi=karar_kaynagi,
        oneri_turu=oneri_turu,
        oneri_durumu=oneri_durumu,
        script_id=script_id,
        kaynak=kaynak,
        limit=limit,
    )


@router.get("/failures/{failure_id}")
def get_failure(failure_id: uuid.UUID, session: DbSession, _user: CurrentUser) -> dict[str, Any]:
    detay = service.get_failure(session, failure_id)
    if detay is None:
        raise HTTPException(404, "Triage kaydı bulunamadı")
    return detay
