"""Kontrol Kulesi uçları (MIMARI-SOZLESME §5): `GET /control-tower` ve
`GET /control-tower/case-quality` (specs/011 K21; herkes)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter

from tp_core.auth.deps import CurrentUser, DbSession
from tp_core.features.control_tower import case_kalitesi, service

router = APIRouter(tags=["control-tower"])


@router.get("/control-tower")
def control_tower(session: DbSession, _user: CurrentUser) -> dict[str, Any]:
    return service.control_tower(session)


@router.get("/control-tower/case-quality")
def case_quality(
    session: DbSession, _user: CurrentUser, requirement_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """Case kalitesi: `requirement_id` verilirse yalnız o gereksinim, yoksa proje geneli."""
    return case_kalitesi.case_kalitesi(session, requirement_id)
