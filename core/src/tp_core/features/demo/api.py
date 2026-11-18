"""Demo kontrolleri (MIMARI-SOZLESME §5; specs/012-rol-yetki §6).

| Yöntem | Yol | İzin |
|---|---|---|
| POST | `/demo/break-locator?zorla=` | `demo.manage` — locator kırılması (demo-admin bypass'ı) |
| POST | `/demo/reset` | `demo.manage` — main → baseline, tp/* PR kapat, uygulama, AI Bug silme |
| GET  | `/demo/status` | `dashboard.read` — forge main/testid, uygulama commit'i, `onarim_on_kosulu` |
| POST | `/demo/jira-status` | `demo.manage` — jira-sim'de story'yi duruma taşı (gerçek Jira'da 409) |

Yazan uçlar yalnız `TP_DEMO_MODE=1` iken çalışır; kapalıyken izinli rol de 403 (`demo_kapali`,
"Demo kipi kapalı (TP_DEMO_MODE=0)"; denetimde `authz.denied`, `neden: demo_kapali`) alır.
Worker işleri (`run_break`/`run_reset`) ve host CLI'ı da demo kipi kapalıyken çalışmaz.
`/demo/status` yanıtı `demo_modu` ve `ortam` (`TP_ORTAM`) alanlarını taşır.

Kırılmadan önce yeşil temel koşu yoksa kırılma 409 + yönerge döner (`zorla=true` bilerek atlar):
locator onarımı "son yeşil" kanıt ister. GitHub kipinde (TP_FORGE=github) kırılma/sıfırlama insan
kimliğiyle (`GITHUB_MERGE_TOKEN`, demo-admin bypass) PR olarak yapılır; token yoksa iş başarısız
olur ve 409 Türkçe neden döner (`/demo/status` → `locator_demo.kip`).

Demo uçları yalnız varsayılan projede (`TP_HOME_PROJECT`; demo-app) vardır; başka projede 404
(TP-COK-PROJE-PLANI §4.3). İstisna `/demo/status`: başka projede 200 `{demo_modu: false,
demo_projesi: false, ortam}` döner (portal demo öğelerini gizler; TP3-1).

Forge yazımı yalnızca core-worker'dadır: uçlar işi kuyruğa alır ve en çok `BEKLEME_S` bekler
(bitti → 200 sonuç, sürüyor → 202 `{job_id}`, başarısız → 409 Türkçe neden).
"""  # noqa: E501

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from tp_core.api.errors import KodluHata
from tp_core.auth.deps import DbSession
from tp_core.auth.yetki import denetle_red, izin
from tp_core.config import get_settings
from tp_core.db import get_engine
from tp_core.features.demo import service
from tp_core.models import session_scope
from tp_core.proje import varsa, varsayilan_pid
from tp_core.workflow.service import Principal

router = APIRouter(tags=["demo"])

DEMO_KAPALI = service.DEMO_KAPALI


def varsayilan_projede(user: Principal) -> None:
    """Demo (demo-app forge'u, kırma/sıfırlama) yalnız varsayılan projeye aittir: başka projede
    uç yokmuş gibi 404."""
    pid = getattr(user, "project_id", None)
    if pid is None:
        b = varsa()
        pid = b.pid if b is not None else None
    if pid is not None and pid != varsayilan_pid():
        raise HTTPException(404, "Not Found")


def demo_okuru(user: Annotated[Principal, Depends(izin("dashboard.read"))]) -> Principal:
    varsayilan_projede(user)
    return user


Okur = Annotated[Principal, Depends(demo_okuru)]


def demo_yoneticisi(
    request: Request,
    session: DbSession,
    user: Annotated[Principal, Depends(izin("demo.manage"))],
) -> Principal:
    """`demo.manage` + demo kipi (`TP_DEMO_MODE=1`); kapalıysa 403 ve `authz.denied`.
    Varsayılan proje dışında 404."""
    varsayilan_projede(user)
    if not get_settings().demo_mode:
        denetle_red(session, user, "demo.manage", "demo_kapali", request.url.path)
        raise KodluHata(403, "demo_kapali", DEMO_KAPALI)
    return user


def canli_degil(islem: str) -> None:
    """Demo kırma/sıfırlama uygulamanın verisini değiştirir: projenin varsayılan test ortamı
    Canlı ise 409 (`proje.ortam.canli_engelle`)."""
    from tp_core.proje.ortam import canli_engelle

    canli_engelle(islem)


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
    canli_degil("demo locator kırma")

    def istek(s: Any, u: Principal) -> dict[str, Any]:
        return service.request_break(s, u, zorla=zorla)

    return await _calistir(istek, user, response)


@router.post("/demo/reset")
async def reset(user: DemoYoneticisi, response: Response) -> dict[str, Any]:
    canli_degil("demo sıfırlama")
    return await _calistir(service.request_reset, user, response)


def _demo_projesi_mi(user: Principal) -> bool:
    try:
        varsayilan_projede(user)
    except HTTPException:
        return False
    return True


@router.get("/demo/status")
def status(user: Annotated[Principal, Depends(izin("dashboard.read"))]) -> dict[str, Any]:
    if not _demo_projesi_mi(user):
        # TP3-1: demo yalnız varsayılan projede; başka projede 404 yerine "demo yok" durumu (portal
        # her sayfada okur; konsol hatası ve demo menüsü/eylemleri çıkmaz). Yazan uçlar 404 kalır.
        return {"demo_modu": False, "demo_projesi": False, "ortam": get_settings().ortam}
    with session_scope() as s:
        ayar = get_settings()
        from tp_core.proje.ortam import islem_ortami

        o = islem_ortami()
        return {
            **service.durum(session=s),
            "demo_modu": ayar.demo_mode,
            "demo_projesi": True,
            "ortam": ayar.ortam,
            # 0048: varsayılan test ortamı (Canlı ise kırma/sıfırlama kapalı).
            "test_ortami": o.ozet() if o else None,
        }


class JiraDurumIstegi(BaseModel):
    jira_key: str = Field(min_length=3, max_length=40)
    durum: str = Field(min_length=1, max_length=100)


@router.post("/demo/jira-status")
def jira_status(body: JiraDurumIstegi, user: DemoYoneticisi) -> dict[str, Any]:
    """jira-sim'deki story'yi verilen duruma taşır (ör. "QA To Do": Jira durum tetiği provası)."""
    from tp_core.integrations.jira import JiraError

    try:
        return service.jira_durum_tasi(user, body.jira_key, body.durum)
    except JiraError as exc:
        raise HTTPException(502, f"Jira'ya erişilemedi: {exc}") from exc
