"""CI ve koşu uçları (MIMARI-SOZLESME §5).

| Yöntem | Yol | Rol |
|---|---|---|
| POST | `/ci/trigger` `{tetik: deploy\\|nightly}` | `run.trigger_scheduled` — 202 `{job_id, run_id, …}` |
| POST | `/ci/trigger` `{tetik: manual}` | `run.trigger_manual` — developer `TP_ORTAM=prod` iken 403 |
| GET  | `/environments` | `run.read` — projenin Home test ortamları ve varsayılanı (0048) |
| GET  | `/runs?tetik=&kaynak=&sonuc=&pr_no=&script_id=&depo=&ortam=&limit=` | `run.read` |
| GET  | `/runs/{id}` | `run.read` — testler, süreler, artefakt bağlantıları |
| GET  | `/artifacts/runs/{run_id}/{yol}` | `run.artifacts` — oturumlu, yolu doğrulanmış artefakt |
| GET  | `/artifacts/k/{imza}/runs/{run_id}/{yol}` | imzalı rapor bağlantısı (oturumsuz, süreli) |

Test ortamı (0048): `/ci/trigger` gövdesinde `ortam` (Home ortam kimliği) verilmezse projenin
varsayılan ortamı (yoksa ortamsız) seçilir; gece koşusu yalnız varsayılan ortamda koşar (`ortam`
verilirse 422). Bilinmeyen ortam 422. Koşu kayıtları `test_ortami` taşır; `/runs?ortam=<eid>`
(`-` = ortamsız) süzer.

Maskeli görünüm (specs/012-rol-yetki §2): `run.artifacts` izni olmayan roller (auditor, viewer)
koşu özetini görür; artefakt bağlantıları (imzalı rapor bağlantısı dahil) yanıttan çıkarılır. İmzalı
bağlantı yalnız `run.artifacts` sahibine verildiği için oturumsuz uç izin dışı kalabilir.
"""  # noqa: E501

from __future__ import annotations

import time
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from tp_core.auth import yetki
from tp_core.auth.deps import DbSession
from tp_core.auth.yetki import izin, izinlerden_biri
from tp_core.config import get_settings
from tp_core.features.ci import artifacts, service
from tp_core.integrations.toolchain_blogu import ortam_gerekli
from tp_core.proje import ortam as ortamlar
from tp_core.proje import proje_icinde
from tp_core.workflow.service import Principal

router = APIRouter(tags=["ci"])

KosuOkur = Annotated[Principal, Depends(izin("run.read"))]
ArtefaktOkur = Annotated[Principal, Depends(izin("run.artifacts"))]
Tetikler = Annotated[
    Principal, Depends(izinlerden_biri("run.trigger_scheduled", "run.trigger_manual"))
]

TetikSec = Literal["pr", "push", "nightly", "deploy", "break_verify", "local_check", "manual"]


class TetikGirdisi(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tetik: Literal["deploy", "nightly", "manual"]
    # 0048: Home ortam kimliği (12 hex); verilmezse projenin varsayılan ortamı.
    ortam: str | None = Field(default=None, pattern=r"^[0-9a-f]{12}$")


class TetikYaniti(BaseModel):
    job_id: uuid.UUID | None
    run_id: uuid.UUID | None
    durum: str
    mesaj: str
    kaynak: str
    tetik: str
    test_ortami: dict[str, Any] | None = None


def tetik_izni(tetik: str) -> str:
    return "run.trigger_manual" if tetik == "manual" else "run.trigger_scheduled"


@router.post("/ci/trigger", response_model=TetikYaniti, status_code=202)
def ci_trigger(
    body: TetikGirdisi, request: Request, session: DbSession, user: Tetikler
) -> dict[str, Any]:
    # Kesin izin tetiğe göre (gövdeden) seçilir; developer üretim ortamında koşu başlatamaz.
    izin_adi = tetik_izni(body.tetik)
    if not yetki.izinli(user.rol, izin_adi):
        raise yetki.reddet(session, user, izin_adi, "rol", request.url.path)
    if yetki.normalize_rol(user.rol) == yetki.DEVELOPER and get_settings().ortam == "prod":
        raise yetki.reddet(session, user, izin_adi, "prod_ortam", request.url.path)
    if body.tetik == "nightly" and body.ortam:
        raise HTTPException(422, "Gece koşusu yalnız projenin varsayılan ortamında koşar")
    try:
        test_ortami = ortamlar.sec(body.ortam)
    except ortamlar.OrtamBulunamadi as exc:
        raise HTTPException(422, str(exc)) from exc
    with ortamlar.ortam_icinde(test_ortami):
        # Ortamın adresleri (varsayılan dışı projede) ortam bağlamında denetlenir.
        ortam_gerekli()
    try:
        return service.trigger_manual(session, body.tetik, user.kullanici_adi, test_ortami)
    except service.CiError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/environments")
def list_environments(_user: KosuOkur) -> dict[str, Any]:
    """Projenin Home test ortamları (ada göre) ve varsayılan ortam. Home config'i yoksa boş."""
    try:
        liste = ortamlar.ortamlar()
    except Exception:  # Home'suz/bağlamsız kurulum: ortam yok (bugünkü davranış)
        liste = []
    varsayilan = next((o for o in liste if o.varsayilan), None)
    return {
        "ortamlar": [{**o.ozet(), "varsayilan": o.varsayilan} for o in liste],
        "varsayilan_eid": varsayilan.eid if varsayilan else None,
    }


@router.get("/runs")
def list_runs(
    session: DbSession,
    user: KosuOkur,
    tetik: TetikSec | None = None,
    kaynak: Literal["local", "github", "sauce"] | None = None,
    sonuc: Literal["queued", "running", "passed", "failed", "error"] | None = None,
    pr_no: int | None = None,
    script_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    # 0046: koşunun deposu (`''` = varsayılan depo; ayrı platform deposunda `sahip/ad`).
    depo: Annotated[str | None, Query(max_length=201)] = None,
    # 0048: test ortamı kimliği; `-` = ortamsız koşular.
    ortam: Annotated[str | None, Query(pattern=r"^(-|[0-9a-f]{12})$")] = None,
) -> list[dict[str, Any]]:
    from tp_core.features.codegen import depo as depolar

    if depo is not None and not depolar.gecerli_mi(depolar.normalize(depo)):
        raise HTTPException(422, "depo 'sahip/ad' biçiminde olmalı (boş = varsayılan depo)")
    kosular = service.list_runs(
        session,
        tetik=tetik,
        kaynak=kaynak,
        sonuc=sonuc,
        pr_no=pr_no,
        script_id=script_id,
        depo=depo,
        ortam=ortam,
        limit=limit,
        artefakt=yetki.izinli(user.rol, "run.artifacts"),
    )
    return kosular


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, session: DbSession, user: KosuOkur) -> dict[str, Any]:
    detay = service.run_detail(session, run_id, artefakt=yetki.izinli(user.rol, "run.artifacts"))
    if detay is None:
        raise HTTPException(404, "Koşu bulunamadı")
    return detay


def maskele(kosu: dict[str, Any]) -> dict[str, Any]:
    """Geriye dönük ad: `service.maskele_kosu`."""
    return service.maskele_kosu(kosu)


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
    # Oturum yok: imza koşuyu yetkilendirir, proje bağlamı koşunun projesidir.
    pid = service.kosu_projesi(session, run_id)
    if pid is None:
        raise HTTPException(404, "Bu koşunun yerel artefaktı yok")
    with proje_icinde(pid, kaynak="token"):
        return _sun(session, run_id, yol, imzali=True)


@router.get("/artifacts/runs/{run_id}/{yol:path}", response_model=None)
def get_artifact(
    run_id: uuid.UUID, yol: str, session: DbSession, _user: ArtefaktOkur
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
