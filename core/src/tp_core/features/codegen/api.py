"""Kod üretimi uçları (MIMARI-SOZLESME §5; TEKNIK-TASARIM §8.4, §8.10).

| Yöntem | Yol | Rol |
|---|---|---|
| POST | `/code/generate` `{case_ids[], platform?, dil?}` | engineer — CasesToCode (202) |
| GET  | `/code/languages?platform=` | engineer, presenter — algılanan dil + seçenekler (K-T8) |
| GET  | `/scripts` · `/scripts/{id}` | herkes — üretilen test, PR, adımlar, yerel kontrol |
| GET  | `/scripts/{id}/screenshots/{n}` | herkes — ajan adımının ekran görüntüsü (PNG) |
| POST | `/scripts/{id}/break-verify` | engineer — kırarak doğrula (202) |
| POST | `/prs/{number}/merge` `{icerik_hash, head_sha, onay_notu?}` | engineer — merge |
| POST | `/prs/{number}/update-branch` | engineer — dalı main ile güncelle (202) |
| POST | `/prs/{number}/review` `{karar, ret_nedeni, icerik_hash, head_sha, not?}` | engineer |

Merge, forge yazma kimliği yalnızca core-worker'da olduğu için işe (`codegen.merge`) gider; uç en
çok `MERGE_BEKLEME_S` bekler: bitti → 200 `PullRequest`, reddedildi → 409, sürüyor → 202. Aynı
head için ikinci istek aynı işi bekler (idempotent). Kırarak doğrulama `passed` değilse `onay_notu`
(açık insan kabulü) zorunludur; yoksa 409. `head_sha` yoksa 422; PR zaten merge edildiyse 409
"PR zaten merge edildi". Dal main'in gerisindeyse (başka PR merge edildi) merge onay kaydı
yazılmadan 409 döner; dal otomatik güncellenir (ya da `update-branch`).

Rol kısıtı (K-T8): Kod üretimi / Koşular ekranlarının rol bazlı görünürlüğü **arayüz düzenidir,
yetki sınırı değildir**; okuma uçları oturum açmış herkese açıktır. Tek istisna `GET
/code/languages`: her çağrı forge'u okur (GitHub hız sınırı), bu yüzden yalnız üretimi başlatan
(engineer) ve sunum yapan (presenter) rollere açıktır.

Review (`karar` ∈ {degisiklik_iste, reddet}, `ret_nedeni` sabit taksonomiden) script'i kapatır ve
`insan_review_sonucu`'nu yazar (Constitution X); PR worker'da kapatılır.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from tp_core.auth.deps import CurrentUser, DbSession, require_role
from tp_core.db import get_engine
from tp_core.features.codegen import service, views
from tp_core.models import session_scope
from tp_core.workflow.service import Principal

router = APIRouter(tags=["codegen"])

Engineer = Annotated[Principal, Depends(require_role("engineer"))]
EngineerPresenter = Annotated[Principal, Depends(require_role("engineer", "presenter"))]
MERGE_BEKLEME_S = 20.0  # portal nginx /api/ zaman aşımı 30 sn


class KodUretGirdisi(BaseModel):
    case_ids: list[uuid.UUID] = Field(min_length=1, max_length=service.MAX_CASE)
    # 009 §2.1: üretilecek testin platformu; yoksa web (geriye uyum). Bilinmeyen değer 422.
    platform: Literal["web", "android", "ios", "windows"] = "web"
    # 011 §2.3: üretim dili; yoksa hedef repodan algılanır. Geçersiz (platform, dil) çifti 422.
    dil: Literal["ts", "java", "csharp", "python"] | None = None


class MergeGirdisi(BaseModel):
    icerik_hash: str | None = Field(default=None, max_length=128)
    head_sha: str | None = Field(default=None, max_length=64)
    # Kırarak doğrulama `passed` değilse (zayıf / tamamlanamadı / yapılmadı) zorunlu insan kabulü.
    onay_notu: str | None = Field(default=None, max_length=500)


class ReviewGirdisi(BaseModel):
    karar: str = Field(max_length=32)
    ret_nedeni: str = Field(max_length=64)
    icerik_hash: str | None = Field(default=None, max_length=128)
    head_sha: str | None = Field(default=None, max_length=64)
    not_: str | None = Field(default=None, max_length=500, alias="not")


@router.post("/code/generate", status_code=202)
def generate(body: KodUretGirdisi, session: DbSession, user: Engineer) -> dict[str, Any]:
    return service.start_generation(session, body.case_ids, user, body.platform, body.dil)


@router.get("/code/languages")
def languages(
    _user: EngineerPresenter,
    platform: Literal["web", "android", "ios", "windows"] = "web",
) -> dict[str, Any]:
    """Algılanan dil, depodaki elle yazılmış test sayıları ve platformun dil seçenekleri."""
    return service.dil_secenekleri(platform)


@router.get("/scripts")
def list_scripts(
    session: DbSession, _user: CurrentUser, response: Response
) -> list[dict[str, Any]]:
    """En yeni 200 script (düz dizi). `X-Daha-Fazla: 1` → daha eski kayıtlar var (liste kesildi),
    `0` → liste tam (MİM-D5)."""
    liste, daha_fazla = views.list_scripts_sinirli(session)
    response.headers[views.DAHA_FAZLA_BASLIGI] = "1" if daha_fazla else "0"
    return liste


@router.get("/scripts/{script_id}")
def get_script(script_id: uuid.UUID, session: DbSession, _user: CurrentUser) -> dict[str, Any]:
    pair = views.get_pair(session, script_id)
    if pair is None:
        raise HTTPException(404, "Script bulunamadı")
    return views.detail(session, *pair)


@router.get("/scripts/{script_id}/screenshots/{sira}")
def screenshot(
    script_id: uuid.UUID, sira: int, session: DbSession, _user: CurrentUser
) -> FileResponse:
    if sira < 1 or sira > 10_000:
        raise HTTPException(404, "Ekran görüntüsü bulunamadı")
    yol = views.screenshot_path(session, script_id, sira)
    if yol is None:
        raise HTTPException(404, "Ekran görüntüsü bulunamadı")
    return FileResponse(
        yol,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/scripts/{script_id}/break-verify", status_code=202)
def break_verify(script_id: uuid.UUID, session: DbSession, user: Engineer) -> dict[str, Any]:
    return service.start_break_verify(session, script_id, user)


@router.post("/prs/{number}/update-branch", status_code=202)
def update_branch(number: int, session: DbSession, user: Engineer) -> dict[str, Any]:
    return service.request_update_branch(session, number, user)


@router.post("/prs/{number}/review")
def review(number: int, body: ReviewGirdisi, session: DbSession, user: Engineer) -> dict[str, Any]:
    return service.review_pr(
        session,
        number,
        user,
        body.karar,
        body.ret_nedeni,
        body.icerik_hash,
        body.head_sha,
        body.not_,
    )


@router.post("/prs/{number}/merge")
async def merge(
    number: int, body: MergeGirdisi, user: Engineer, response: Response
) -> dict[str, Any]:
    from tp_core.features.publish.service import await_job
    from tp_core.features.repair import service as repair_service
    from tp_core.features.repair import views as repair_views

    def kuyruga_al() -> uuid.UUID:
        with session_scope() as s:
            # Faz 4: locator onarım PR'ları (`tp/repair-*`) repair şeridinin merge yoluna gider.
            if repair_service.repair_script_for_pr(s, number) is not None:
                return repair_service.request_merge(
                    s, number, user, body.icerik_hash, body.head_sha
                )
            return service.request_merge(
                s, number, user, body.icerik_hash, body.head_sha, body.onay_notu
            )

    job_id = await run_in_threadpool(kuyruga_al)
    durum, _sonuc, hata = await await_job(get_engine(), job_id, MERGE_BEKLEME_S)
    if durum in ("failed", "cancelled"):
        raise HTTPException(409, hata or "Merge reddedildi")

    def pr() -> dict[str, Any] | None:
        with session_scope() as s:
            onarim_pr = repair_views.pr_response(s, number)
            if onarim_pr is not None:
                return onarim_pr
            sc = service.script_for_pr(s, number)
            return views.pr_response(s, number, [sc])

    yanit = await run_in_threadpool(pr) or {"number": number}
    if durum != "done":
        response.status_code = 202
        return {**yanit, "job_id": str(job_id), "is_durumu": durum}
    return {**yanit, "job_id": str(job_id)}
