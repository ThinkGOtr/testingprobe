"""POST /tokens (`token.issue`: Testçi, Developer) · GET /tokens · DELETE /tokens/{id}
(`token.read`, yalnız kendi token'ları) — MCP kanalı token'ları (specs/012-rol-yetki/ANALIZ.md §4).

`publish` kapsamlı token yalnız `case.publish` iznine sahip role (Testçi) üretilir; Developer
`submit` kapsamıyla `get_requirement` aracını kullanır (2026-11-14 kararı). Hiçbir rol başkasının
token'ını listeleyemez ya da iptal edemez.

`POST /tokens` yalnızca uygulamada `/mcp` ucu bağlıyken token üretir; değilse 501 döner (portal
olmayan bir sunucu için çalışan kimlik bilgisi ve `.mcp.json` parçası dağıtılmaz).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from tp_core.auth.deps import DbSession
from tp_core.auth.tokens import issue_token, revoke_token
from tp_core.auth.yetki import izin, izinli, reddet
from tp_core.config import get_settings
from tp_core.models import ApiToken
from tp_core.workflow.service import Principal

router = APIRouter(prefix="/tokens", tags=["tokens"])

Uretici = Annotated[Principal, Depends(izin("token.issue"))]
Sahip = Annotated[Principal, Depends(izin("token.read"))]


class TokenIn(BaseModel):
    kapsam: Literal["publish", "submit"]


class TokenOut(BaseModel):
    id: uuid.UUID
    kapsam: str
    son_kullanma: datetime
    iptal: bool
    son_kullanim: datetime | None
    olusturma: datetime


class TokenCreated(BaseModel):
    id: uuid.UUID
    kapsam: str
    son_kullanma: datetime
    token: str  # yalnızca bir kez gösterilir
    mcp_url: str  # IDE'nin .mcp.json'una yazılacak adres (TP_MCP_PUBLIC_URL)


MCP_YOLU = "/mcp"


def _yollar(routes: Iterable[Any], onek: str = "") -> Iterator[str]:
    """Tüm rota yolları; `include_router` sarmalayıcılarının (_IncludedRouter) içine de iner."""
    for route in routes:
        yield onek + (getattr(route, "path", "") or "")
        alt = getattr(route, "original_router", None)
        if alt is not None:
            ek = getattr(getattr(route, "include_context", None), "prefix", "") or ""
            yield from _yollar(alt.routes, onek + ek)


def mcp_mounted(request: Request) -> bool:
    """Uygulamada `/mcp` (veya altı) yolunda bir uç/mount var mı?"""
    return any(
        yol == MCP_YOLU or yol.startswith(MCP_YOLU + "/") for yol in _yollar(request.app.routes)
    )


@router.post("", response_model=TokenCreated, status_code=201)
def create(body: TokenIn, request: Request, session: DbSession, user: Uretici) -> TokenCreated:
    if body.kapsam == "publish" and not izinli(user.rol, "case.publish"):
        raise reddet(session, user, "case.publish", "rol", request.url.path)
    if not mcp_mounted(request):
        raise HTTPException(501, "IDE (MCP) kanalı henüz etkin değil; token üretilemez")
    # AI Probe oturumundan üretilen token oturumun `auth_time`/`acr`/`session_epoch_ms`'ini taşır
    # (deps.current_user → request.state.oturum_durumu; yerel oturumda hepsi boş).
    durum = getattr(request.state, "oturum_durumu", None)
    tok, raw = issue_token(
        session,
        user,
        body.kapsam,
        get_settings().api_token_ttl_s,
        auth_time=getattr(durum, "auth_time", None),
        acr=getattr(durum, "acr", None),
        session_epoch_ms=getattr(durum, "session_epoch_ms", None),
    )
    return TokenCreated(
        id=tok.id,
        kapsam=tok.kapsam,
        son_kullanma=tok.son_kullanma,
        token=raw,
        mcp_url=get_settings().mcp_public_url,
    )


@router.get("", response_model=list[TokenOut])
def list_tokens(session: DbSession, user: Sahip) -> list[TokenOut]:
    rows = session.scalars(
        select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.olusturma.desc())
    ).all()
    return [TokenOut.model_validate(t, from_attributes=True) for t in rows]


@router.delete("/{token_id}", status_code=204)
def revoke(token_id: uuid.UUID, session: DbSession, user: Sahip) -> Response:
    if not revoke_token(session, user, token_id):
        raise HTTPException(404, "Token bulunamadı")
    return Response(status_code=204)
