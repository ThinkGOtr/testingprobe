"""GET /audit?verify=true — denetim kaydı (yeniden eskiye) ve doğrulama.

Doğrulama iki parçadır: hash zinciri (`verify_chain`) ve zincire sabitlenmiş `ai_call`/`tool_call`
satır çapaları (`verify_call_anchors`). `verify.ok` ikisi de sağlamsa True'dur.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import text

from tp_core.audit import chain_tip, verify_call_anchors, verify_chain
from tp_core.auth.deps import CurrentUser, DbSession

router = APIRouter(tags=["audit"])


class AuditEventOut(BaseModel):
    id: int
    zaman: datetime
    aktor: str
    eylem: str
    nesne: str | None
    ozet: Any
    prev_hash: str
    hash: str


class AnchorBrokenOut(BaseModel):
    nesne: str
    reason: str


class AnchorsOut(BaseModel):
    ok: bool
    checked: int
    eski: int
    sabitsiz: int
    broken: list[AnchorBrokenOut]


class ChainOut(BaseModel):
    ok: bool
    count: int
    tip_hash: str
    broken_at: int | None
    reason: str | None
    anchors: AnchorsOut | None = None


class AuditOut(BaseModel):
    events: list[AuditEventOut]
    tip_hash: str
    next_before_id: int | None
    verify: ChainOut | None = None


@router.get("/audit", response_model=AuditOut)
def audit(
    session: DbSession,
    _user: CurrentUser,
    verify: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    before_id: Annotated[int | None, Query(ge=1)] = None,
    nesne: Annotated[str | None, Query(max_length=200)] = None,
) -> AuditOut:
    kosul = ["(CAST(:before AS bigint) IS NULL OR id < CAST(:before AS bigint))"]
    if nesne:
        kosul.append("nesne = :nesne")
    conn = session.connection()
    rows = conn.execute(
        text(
            "SELECT id, zaman, aktor, eylem, nesne, ozet, prev_hash, hash FROM audit_event "
            f"WHERE {' AND '.join(kosul)} ORDER BY id DESC LIMIT :limit"
        ),
        {"before": before_id, "limit": limit, "nesne": nesne},
    ).all()
    events = [AuditEventOut.model_validate(r._asdict()) for r in rows]
    sonuc = AuditOut(
        events=events,
        tip_hash=chain_tip(conn),
        next_before_id=events[-1].id if len(events) == limit else None,
    )
    if verify:
        zincir = ChainOut(**verify_chain(conn).as_dict())
        capalar = verify_call_anchors(conn)
        zincir.anchors = AnchorsOut.model_validate(capalar.as_dict())
        if not capalar.ok:
            zincir.ok = False
            zincir.reason = zincir.reason or "ai_call/tool_call satırı çapasıyla uyuşmuyor"
        sonuc.verify = zincir
    return sonuc
