"""Sunucu demo kontrolleri (MIMARI-SOZLESME §5).

| Yöntem | Yol | Rol |
|---|---|---|
| POST | `/demo/break-locator?zorla=` | presenter — locator kırılması (demo-admin bypass'ı) |
| POST | `/demo/reset` | presenter — main → baseline, tp/* PR kapat, uygulama, AI Bug silme |
| GET  | `/demo/status` | herkes — forge main/testid, uygulama commit'i, `onarim_on_kosulu` |

Kırılmadan önce yeşil temel koşu yoksa kırılma 409 + yönerge döner (`zorla=true` bilerek atlar):
locator onarımı "son yeşil" kanıt ister. GitHub kipinde (TP_FORGE=github) kırılma her zaman 409:
locator demosu yalnızca yerel forge'dadır (`/demo/status` → `locator_demo`).

Forge yazımı yalnızca core-worker'dadır: uçlar işi kuyruğa alır ve en çok `BEKLEME_S` bekler
(bitti → 200 sonuç, sürüyor → 202 `{job_id}`, başarısız → 409 Türkçe neden).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.concurrency import run_in_threadpool

from tp_core.auth.deps import CurrentUser, require_role
from tp_core.db import get_engine
from tp_core.features.demo import service
from tp_core.models import session_scope
from tp_core.workflow.service import Principal

router = APIRouter(tags=["demo"])

Presenter = Annotated[Principal, Depends(require_role("presenter"))]
BEKLEME_S = 20.0  # portal nginx /api/ zaman aşımı 30 sn


async def _calistir(istek: Any, user: Principal, response: Response) -> dict[str, Any]:
    from tp_core.features.publish.service import await_job

    def kuyruga_al() -> dict[str, Any]:
        with session_scope() as s:
            return istek(s, user)

    out = await run_in_threadpool(kuyruga_al)
    durum, sonuc, hata = await await_job(get_engine(), uuid.UUID(out["job_id"]), BEKLEME_S)
    if durum in ("failed", "cancelled"):
        raise HTTPException(409, hata or "Demo işlemi başarısız")
    if durum != "done":
        response.status_code = 202
        return {**out, "is_durumu": durum}
    return {**out, "durum": "done", "sonuc": sonuc}


@router.post("/demo/break-locator")
async def break_locator(user: Presenter, response: Response, zorla: bool = False) -> dict[str, Any]:
    def istek(s: Any, u: Principal) -> dict[str, Any]:
        return service.request_break(s, u, zorla=zorla)

    return await _calistir(istek, user, response)


@router.post("/demo/reset")
async def reset(user: Presenter, response: Response) -> dict[str, Any]:
    return await _calistir(service.request_reset, user, response)


@router.get("/demo/status")
def status(_user: CurrentUser) -> dict[str, Any]:
    with session_scope() as s:
        return service.durum(session=s)
