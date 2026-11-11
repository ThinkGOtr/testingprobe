"""Jira durum tetiği durum ucu (specs/013-sprint-otomasyonu §3.4).

`api.py` (otomasyon ayarları, Ş1) ile çakışmasın diye ayrı modül; registry paket başına hem
`api` hem `routes` modülünü yükler.

| Yöntem | Yol | Rol |
|---|---|---|
| GET | `/automation/jira-trigger` | herkes — ayar + son tur özeti + son tetiklenen story'ler |
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from tp_core.auth.deps import CurrentUser, DbSession
from tp_core.features.otomasyon import jira_tetik

router = APIRouter(tags=["otomasyon"])


@router.get("/automation/jira-trigger")
def jira_trigger(session: DbSession, _user: CurrentUser) -> dict[str, Any]:
    return jira_tetik.durum_ozeti(session)
