"""GET /audit?verify=true — denetim kaydı (yeniden eskiye) ve doğrulama.

Doğrulama iki parçadır: hash zinciri (`verify_chain`) ve zincire sabitlenmiş `ai_call`/`tool_call`
satır çapaları (`verify_call_anchors`). `verify.ok` ikisi de sağlamsa True'dur.

Kapsam (specs/012-rol-yetki §4.2): `audit.read_all` (admin, auditor) tüm kaydı; `audit.read_own`
(iş rolleri) yalnız `aktor` = kendi kullanıcı adı olan olayları görür. `verify=true`
`audit.verify` ister (zincir doğrulaması tüm kaydı okur). İkisi de yoksa 403.

Denetçi (auditor) görünümünde `ozet` PII maskeleyicisinden geçer (`features/assistant/maskeleme`,
`TP_PII_MASKING`'den bağımsız her zaman açık; yanıt başına tek oturum, yer tutucular tutarlı):
denetçi olayları ve zinciri inceler, kişisel veriyi görmez. `hash`/`prev_hash` ham kayda aittir.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import text

from tp_core.audit import chain_tip, verify_call_anchors, verify_chain
from tp_core.auth import yetki
from tp_core.auth.deps import DbSession
from tp_core.workflow.service import Principal

router = APIRouter(tags=["audit"])

Okur = Annotated[Principal, Depends(yetki.izinlerden_biri("audit.read_all", "audit.read_own"))]


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


# Oturum kimliği (`sid`) çerezle birlikte oturumu temsil eder; denetim görünümünde tam değer
# gerekmez (canlı: Denetçi auth.login / auth.role_switch özetlerinde tam UUID görüyordu). Yalnız
# gösterim: kayıt ve hash zinciri değişmez.
SID_ALANLARI = frozenset({"sid", "onceki_sid", "session_id"})


def sid_kisalt(ozet: Any) -> Any:
    def _k(x: Any) -> Any:
        if isinstance(x, dict):
            return {k: _sid(v) if k in SID_ALANLARI else _k(v) for k, v in x.items()}
        if isinstance(x, list):
            return [_k(v) for v in x]
        return x

    return _k(ozet)


def _sid(v: Any) -> Any:
    return f"{v[:8]}…" if isinstance(v, str) and len(v) > 8 else v


@router.get("/audit", response_model=AuditOut)
def audit(
    request: Request,
    session: DbSession,
    user: Okur,
    verify: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    before_id: Annotated[int | None, Query(ge=1)] = None,
    nesne: Annotated[str | None, Query(max_length=200)] = None,
) -> AuditOut:
    if verify and not yetki.izinli(user.rol, "audit.verify"):
        raise yetki.reddet(session, user, "audit.verify", "rol", request.url.path)
    kosul = ["(CAST(:before AS bigint) IS NULL OR id < CAST(:before AS bigint))"]
    if nesne:
        kosul.append("nesne = :nesne")
    if not yetki.izinli(user.rol, "audit.read_all"):
        kosul.append("aktor = :aktor")
    conn = session.connection()
    rows = conn.execute(
        text(
            "SELECT id, zaman, aktor, eylem, nesne, ozet, prev_hash, hash FROM audit_event "
            f"WHERE {' AND '.join(kosul)} ORDER BY id DESC LIMIT :limit"
        ),
        {"before": before_id, "limit": limit, "nesne": nesne, "aktor": user.kullanici_adi},
    ).all()
    events = [AuditEventOut.model_validate(r._asdict()) for r in rows]
    for e in events:
        e.ozet = sid_kisalt(e.ozet)
    if yetki.normalize_rol(user.rol) == yetki.AUDITOR:
        from tp_core.features.assistant.maskeleme import maskeleyici

        oturum = maskeleyici(enabled=True).new_session()
        for e in events:
            e.ozet = oturum.mask(e.ozet)[0]
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
