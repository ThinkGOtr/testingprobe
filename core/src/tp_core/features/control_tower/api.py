"""Kontrol Kulesi ucu (MIMARI-SOZLESME §5): `GET /control-tower` (`dashboard.read`, tüm roller)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from tp_core.auth.deps import DbSession
from tp_core.auth.yetki import izin
from tp_core.features.control_tower import service
from tp_core.workflow.service import Principal

router = APIRouter(tags=["control-tower"])

Okur = Annotated[Principal, Depends(izin("dashboard.read"))]


@router.get("/control-tower")
def control_tower(session: DbSession, _user: Okur) -> dict[str, Any]:
    return service.control_tower(session)
