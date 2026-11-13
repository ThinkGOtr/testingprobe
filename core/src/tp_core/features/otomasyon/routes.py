"""Jira durum tetiği durum ucu (specs/013-sprint-otomasyonu §3.4).

`api.py` (otomasyon ayarları, Ş1) ile çakışmasın diye ayrı modül; registry paket başına hem
`api` hem `routes` modülünü yükler.

| Yöntem | Yol | İzin |
|---|---|---|
| GET | `/automation/jira-trigger` | `requirement.read` — ayar, son tur özeti, son tetiklenenler |
| GET | `/automation/codegen-jobs/{job_id}` | `code.read` — toplu onay kod işinin case sonuçları |
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from tp_core.auth.deps import DbSession
from tp_core.auth.yetki import izin
from tp_core.features.otomasyon import jira_tetik, otokod
from tp_core.workflow.service import Principal

router = APIRouter(tags=["otomasyon"])

Okur = Annotated[Principal, Depends(izin("requirement.read"))]
KodOkur = Annotated[Principal, Depends(izin("code.read"))]


@router.get("/automation/jira-trigger")
def jira_trigger(session: DbSession, _user: Okur) -> dict[str, Any]:
    return jira_tetik.durum_ozeti(session)


@router.get("/automation/codegen-jobs/{job_id}")
def codegen_job(job_id: uuid.UUID, session: DbSession, _user: KodOkur) -> dict[str, Any]:
    ozet = otokod.is_ozeti(session, job_id)
    if ozet is None:
        raise HTTPException(404, "Otomatik kod işi bulunamadı")
    return ozet
