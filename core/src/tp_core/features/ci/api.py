"""CI ve koşu uçları (MIMARI-SOZLESME §5).

| Yöntem | Yol | Rol |
|---|---|---|
| POST | `/ci/trigger` `{tetik: deploy\\|nightly}` | presenter — 202 `{job_id, run_id, …}` |
| GET  | `/runs?tetik=&kaynak=&sonuc=&pr_no=&script_id=&limit=` | herkes |
| GET  | `/runs/{id}` | herkes — testler, süreler, artefakt bağlantıları |
| GET  | `/artifacts/runs/{run_id}/{yol}` | herkes — oturumlu, yolu doğrulanmış artefakt |
| GET  | `/artifacts/k/{imza}/runs/{run_id}/{yol}` | imzalı rapor bağlantısı (oturumsuz, süreli) |
"""

from __future__ import annotations

import time
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from tp_core.auth.deps import CurrentUser, DbSession, require_role
from tp_core.features.ci import artifacts, service
from tp_core.workflow.service import Principal

router = APIRouter(tags=["ci"])

Presenter = Annotated[Principal, Depends(require_role("presenter"))]
TetikSec = Literal["pr", "push", "nightly", "deploy", "break_verify", "local_check", "manual"]


class TetikGirdisi(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tetik: Literal["deploy", "nightly"]


class TetikYaniti(BaseModel):
    job_id: uuid.UUID | None
    run_id: uuid.UUID | None
    durum: str
    mesaj: str
    kaynak: str
    tetik: str


@router.post("/ci/trigger", response_model=TetikYaniti, status_code=202)
def ci_trigger(body: TetikGirdisi, session: DbSession, user: Presenter) -> dict[str, Any]:
    try:
        return service.trigger_manual(session, body.tetik, user.kullanici_adi)
    except service.CiError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/runs")
def list_runs(
    session: DbSession,
    _user: CurrentUser,
    tetik: TetikSec | None = None,
    kaynak: Literal["local", "github", "sauce"] | None = None,
    sonuc: Literal["queued", "running", "passed", "failed", "error"] | None = None,
    pr_no: int | None = None,
    script_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    return service.list_runs(
        session,
        tetik=tetik,
        kaynak=kaynak,
        sonuc=sonuc,
        pr_no=pr_no,
        script_id=script_id,
        limit=limit,
    )


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, session: DbSession, _user: CurrentUser) -> dict[str, Any]:
    detay = service.run_detail(session, run_id)
    if detay is None:
        raise HTTPException(404, "Koşu bulunamadı")
    return detay


@router.get("/artifacts/k/{token}/runs/{run_id}/{yol:path}", response_model=None)
def get_artifact_signed(
    token: str, run_id: uuid.UUID, yol: str, session: DbSession
) -> FileResponse | JSONResponse | Response:
    """İmzalı, kısa ömürlü rapor bağlantısı (sandbox'lı raporun çerezsiz alt istekleri için).

    Oturum yerine `serialize_runs`'ın ürettiği HMAC imzası (tek koşu, süreli) doğrulanır; yol
    kuralları ve izinli alt ağaç oturumlu uçla aynıdır.
    """
    if not artifacts.token_gecerli_mi(run_id, token, time.time()):
        raise HTTPException(
            403, "Rapor bağlantısının süresi dolmuş ya da geçersiz; koşuyu yenileyin"
        )
    return _sun(session, run_id, yol, imzali=True)


@router.get("/artifacts/runs/{run_id}/{yol:path}", response_model=None)
def get_artifact(
    run_id: uuid.UUID, yol: str, session: DbSession, _user: CurrentUser
) -> FileResponse | JSONResponse | Response:
    return _sun(session, run_id, yol, imzali=False)


def _sun(
    session: Any, run_id: uuid.UUID, yol: str, *, imzali: bool
) -> FileResponse | JSONResponse | Response:
    kok = service.artifact_dir(session, run_id)
    if kok is None:
        raise HTTPException(404, "Bu koşunun yerel artefaktı yok")
    try:
        hedef = artifacts.coz(kok, yol)
    except artifacts.YolHatasi as exc:
        raise HTTPException(400, f"Geçersiz artefakt yolu: {exc}") from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, "Artefakt bulunamadı") from exc
    if hedef.is_dir():
        return JSONResponse(
            {"yol": yol.strip("/"), "dosyalar": artifacts.listele(hedef, kok)},
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )
    if not hedef.is_file():
        raise HTTPException(404, "Artefakt bulunamadı")
    tur = artifacts.icerik_turu(hedef)
    if tur == "text/html" and artifacts.depo_simi_gerekir_mi(hedef):
        return Response(
            artifacts.depo_simi_ekle(hedef.read_bytes()),
            media_type=tur,
            headers=artifacts.basliklar(tur, hedef.name, imzali=imzali),
        )
    return FileResponse(
        hedef, media_type=tur, headers=artifacts.basliklar(tur, hedef.name, imzali=imzali)
    )
