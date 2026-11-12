"""Jira durum tetiği durum ucu (specs/013-sprint-otomasyonu §3.4).

`api.py` (otomasyon ayarları, Ş1) ile çakışmasın diye ayrı modül; registry paket başına hem
`api` hem `routes` modülünü yükler.

| Yöntem | Yol | Rol |
|---|---|---|
| GET | `/automation/jira-trigger` | herkes — ayar + son tur özeti + son tetiklenen story'ler |
| GET | `/automation/codegen-jobs/{job_id}` | herkes — toplu onay kod işinin case başına sonucu |
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from tp_core.auth.deps import CurrentUser, DbSession
from tp_core.features.otomasyon import jira_tetik, otokod

router = APIRouter(tags=["otomasyon"])


@router.get("/automation/jira-trigger")
def jira_trigger(session: DbSession, _user: CurrentUser) -> dict[str, Any]:
    return jira_tetik.durum_ozeti(session)


@router.get("/automation/codegen-jobs/{job_id}")
def codegen_job(job_id: uuid.UUID, session: DbSession, _user: CurrentUser) -> dict[str, Any]:
    ozet = otokod.is_ozeti(session, job_id)
    if ozet is None:
        raise HTTPException(404, "Otomatik kod işi bulunamadı")
    return ozet
