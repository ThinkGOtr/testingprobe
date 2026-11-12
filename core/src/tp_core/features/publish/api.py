"""Yayın uçları (MIMARI-SOZLESME §5) ve IDE (MCP) kanalının bağlantı noktası.

| Yöntem | Yol | Rol |
|---|---|---|
| GET  | `/publish/preview?requirement_id=` | `publish.preview` — hedef başına gövde (dry-run) |
| POST | `/publish` `{case_ids[]}` | `case.publish` (Testçi) — yayın işini başlatır, sonucu bekler |
| MCP  | `/mcp` | `Authorization: Bearer tpt_…` — `tp_core.mcp_server` (çerez kullanılmaz) |

`POST /publish` işi kuyruğa koyar (Jira/Xray yazma kimliği yalnızca core-worker'da) ve en fazla
`BEKLEME_S` saniye bekler: iş bittiyse `YayinSonucu` (200), bitmediyse
`{job_id, durum, sonuclar: []}` (202), iş çöktüyse 502.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from tp_core.auth.deps import DbSession
from tp_core.auth.yetki import izin
from tp_core.db import get_engine
from tp_core.features.publish import service
from tp_core.integrations.jira import get_jira_settings
from tp_core.mcp_server import MCP_METHODS, MCP_PATH, mcp_asgi_app
from tp_core.models import session_scope
from tp_core.workflow.service import Principal

router = APIRouter(tags=["publish"])

Yayinci = Annotated[Principal, Depends(izin("case.publish"))]
Onizleyici = Annotated[Principal, Depends(izin("publish.preview"))]


class PublishIn(BaseModel):
    case_ids: list[uuid.UUID] = Field(min_length=1, max_length=service.MAX_CASE)


@router.get("/publish/preview")
def preview(requirement_id: uuid.UUID, session: DbSession, _user: Onizleyici) -> dict[str, Any]:
    return service.preview(session, requirement_id)


@router.post("/publish")
async def publish(body: PublishIn, user: Yayinci, response: Response) -> dict[str, Any]:
    def kuyruga_al() -> uuid.UUID:
        with session_scope() as s:
            return service.request_publish(s, body.case_ids, user)

    job_id = await run_in_threadpool(kuyruga_al)
    durum, sonuc, hata = await service.await_job(get_engine(), job_id)
    if durum == "done":
        return {**(sonuc or {}), "job_id": str(job_id)}
    if durum in ("failed", "cancelled"):
        raise HTTPException(502, f"Yayın işi başarısız: {hata or durum}")
    response.status_code = 202
    return {
        "hedef": get_jira_settings().test_mgmt,
        "job_id": str(job_id),
        "durum": durum,
        "sonuclar": [],
        "mesaj": "Yayın kuyrukta; sonuç iş tamamlanınca case durumlarında görünür.",
    }


# IDE (Claude Code) kanalı: streamable HTTP MCP uç noktası (bearer token, yalnızca localhost).
router.add_route(MCP_PATH, mcp_asgi_app, methods=list(MCP_METHODS), include_in_schema=False)
