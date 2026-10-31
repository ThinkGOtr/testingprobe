"""Kontrol Kulesi ucu (MIMARI-SOZLESME §5): `GET /control-tower` (herkes)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from tp_core.auth.deps import CurrentUser, DbSession
from tp_core.features.control_tower import service

router = APIRouter(tags=["control-tower"])


@router.get("/control-tower")
def control_tower(session: DbSession, _user: CurrentUser) -> dict[str, Any]:
    return service.control_tower(session)
