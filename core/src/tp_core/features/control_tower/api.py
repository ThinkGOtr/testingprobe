"""Kontrol Kulesi uçları (MIMARI-SOZLESME §5): `GET /control-tower` ve
`GET /control-tower/case-quality` (specs/011 K21); ikisi de `dashboard.read` (tüm roller).

Case kalitesi yalnız toplu sayılar döner (case içeriği yok), bu yüzden Kontrol Kulesi'nin geri
kalanıyla aynı izinle okunur."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from tp_core.auth.deps import DbSession
from tp_core.auth.yetki import izin, izinli
from tp_core.features.control_tower import case_kalitesi, service
from tp_core.workflow.service import Principal

router = APIRouter(tags=["control-tower"])

Okur = Annotated[Principal, Depends(izin("dashboard.read"))]


@router.get("/control-tower")
def control_tower(
    session: DbSession,
    user: Okur,
    ortam: Annotated[str | None, Query(pattern=r"^(-|[0-9a-f]{12})$")] = None,
) -> dict[str, Any]:
    # Son koşulardaki artefakt/imzalı rapor bağlantıları yalnız `run.artifacts` sahibine döner.
    # `ortam` (0048): koşu tabanlı göstergeler o test ortamının koşularından (`-` = ortamsız).
    return service.control_tower(
        session, artefakt=izinli(user.rol, "run.artifacts"), ortam=ortam
    )


@router.get("/control-tower/case-quality")
def case_quality(
    session: DbSession, _user: Okur, requirement_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """Case kalitesi: `requirement_id` verilirse yalnız o gereksinim, yoksa proje geneli. Sonuç
    kısa süre önbellekte tutulur (`case_kalitesi_onbellekli`: TTL + DB parmak izi)."""
    return case_kalitesi.case_kalitesi_onbellekli(session, requirement_id)
