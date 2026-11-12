"""Demo kontrolleri (MIMARI-SOZLESME §5; specs/012-rol-yetki §6).

| Yöntem | Yol | İzin |
|---|---|---|
| POST | `/demo/break-locator?zorla=` | `demo.manage` — locator kırılması (demo-admin bypass'ı) |
| POST | `/demo/reset` | `demo.manage` — main → baseline, tp/* PR kapat, uygulama, AI Bug silme |
| GET  | `/demo/status` | `dashboard.read` — forge main/testid, uygulama commit'i, `onarim_on_kosulu` |

Yazan uçlar yalnız `TP_DEMO_MODE=1` iken çalışır; kapalıyken izinli rol de 403 (`demo_kapali`,
"Demo kipi kapalı (TP_DEMO_MODE=0)"; denetimde `authz.denied`, `neden: demo_kapali`) alır.
Worker işleri (`run_break`/`run_reset`) ve host CLI'ı da demo kipi kapalıyken çalışmaz.
`/demo/status` yanıtı `demo_modu` ve `ortam` (`TP_ORTAM`) alanlarını taşır.

Kırılmadan önce yeşil temel koşu yoksa kırılma 409 + yönerge döner (`zorla=true` bilerek atlar):
locator onarımı "son yeşil" kanıt ister. GitHub kipinde (TP_FORGE=github) kırılma/sıfırlama insan
kimliğiyle (`GITHUB_MERGE_TOKEN`, demo-admin bypass) PR olarak yapılır; token yoksa iş başarısız
olur ve 409 Türkçe neden döner (`/demo/status` → `locator_demo.kip`).

Forge yazımı yalnızca core-worker'dadır: uçlar işi kuyruğa alır ve en çok `BEKLEME_S` bekler
(bitti → 200 sonuç, sürüyor → 202 `{job_id}`, başarısız → 409 Türkçe neden).
"""  # noqa: E501

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool

from tp_core.api.errors import KodluHata
from tp_core.auth.deps import DbSession
from tp_core.auth.yetki import denetle_red, izin
from tp_core.config import get_settings
from tp_core.db import get_engine
from tp_core.features.demo import service
from tp_core.models import session_scope
from tp_core.workflow.service import Principal

router = APIRouter(tags=["demo"])

Okur = Annotated[Principal, Depends(izin("dashboard.read"))]
DEMO_KAPALI = service.DEMO_KAPALI


def demo_yoneticisi(
    request: Request,
    session: DbSession,
    user: Annotated[Principal, Depends(izin("demo.manage"))],
) -> Principal:
    """`demo.manage` + demo kipi (`TP_DEMO_MODE=1`); kapalıysa 403 ve `authz.denied`."""
    if not get_settings().demo_mode:
        denetle_red(session, user, "demo.manage", "demo_kapali", request.url.path)
        raise KodluHata(403, "demo_kapali", DEMO_KAPALI)
    return user


DemoYoneticisi = Annotated[Principal, Depends(demo_yoneticisi)]
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
async def break_locator(
    user: DemoYoneticisi, response: Response, zorla: bool = False
) -> dict[str, Any]:
    def istek(s: Any, u: Principal) -> dict[str, Any]:
        return service.request_break(s, u, zorla=zorla)

    return await _calistir(istek, user, response)


@router.post("/demo/reset")
async def reset(user: DemoYoneticisi, response: Response) -> dict[str, Any]:
    return await _calistir(service.request_reset, user, response)


@router.get("/demo/status")
def status(_user: Okur) -> dict[str, Any]:
    with session_scope() as s:
        ayar = get_settings()
        return {**service.durum(session=s), "demo_modu": ayar.demo_mode, "ortam": ayar.ortam}
