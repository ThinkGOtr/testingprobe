"""Bug taslağı karar uçları (MIMARI-SOZLESME §5; TEKNIK-TASARIM §8.12).

| Yöntem | Yol | Rol |
|---|---|---|
| POST | `/bug-drafts/{id}/decision` `{karar, icerik_hash, icerik?, link_key?, gerekce?}` | tester |
| POST | `/bug-drafts/{id}/prepare` | tester — mükerrer aramasını ve AI taslağını yeniden hazırla |
| POST | `/bug-drafts/{id}/publish` | tester — onaylı taslağın yayınını yeniden dene |
| GET  | `/bug-drafts/{id}/detail` | herkes — Faz 4 ayrıntılı görünüm (hazırlık, adaylar, yayın) |

`karar`: `new` (yeni Bug) · `link` (`link_key` mevcut kayda bağla) · `edit` (içerik düzenle;
onay değildir) · `dismiss` (gerekçe zorunlu) · `reopen` (reddedilmişi taslağa al). Gövdedeki
`icerik_hash` ekranda görülen içeriğin hash'idir (eksikse 422, değiştiyse 409). `new`/`link`
yayın işini kuyruğa koyar (Jira yazma kimliği yalnızca worker'da) ve en çok `BEKLEME_S` bekler:
yanıt taslak görünümü + `yayin_sonucu` (iş bittiyse) ya da 202 + `job_id`.

Liste ve tekil GET (`/bug-drafts`, `/bug-drafts/{id}`) requirements şeridindedir (Faz 2);
`serialize.bug_draft_view` aynı alanların üst kümesidir.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from tp_core.api.deps import DbSession, Principal, current_user, require_role
from tp_core.db import get_engine
from tp_core.features.bugs import serialize, service
from tp_core.models import BugDraft, session_scope

router = APIRouter(tags=["bugs"])

Tester = Annotated[Principal, Depends(require_role("tester"))]
Herkes = Annotated[Principal, Depends(current_user)]
BEKLEME_S = 20.0


class BugKarari(BaseModel):
    karar: Literal["new", "link", "edit", "dismiss", "reopen"]
    icerik_hash: str | None = Field(default=None, max_length=128)
    icerik: dict[str, Any] | None = None
    link_key: str | None = Field(default=None, max_length=64)
    gerekce: str | None = Field(default=None, max_length=2000)


def _view(draft_id: uuid.UUID) -> dict[str, Any]:
    with session_scope() as s:
        b = s.get(BugDraft, draft_id)
        if b is None:
            raise HTTPException(404, "Bug taslağı bulunamadı")
        return serialize.bug_draft_view(s, b)


async def _bekle(job_id: uuid.UUID, response: Response) -> dict[str, Any]:
    """Yayın işini bekler: `{is_durumu: done|failed|queued|running|retry, job_id, sonuc, hata}`."""
    from tp_core.features.publish.service import await_job

    durum, sonuc, hata = await await_job(get_engine(), job_id, BEKLEME_S)
    out: dict[str, Any] = {"is_durumu": durum, "job_id": str(job_id), "sonuc": sonuc, "hata": hata}
    if durum not in ("done", "failed", "cancelled"):
        response.status_code = 202
        out["mesaj"] = "Jira yazımı kuyrukta; sonuç SSE 'bug.published' ile gelir."
    return out


@router.post("/bug-drafts/{draft_id}/decision")
async def decision(
    draft_id: uuid.UUID, body: BugKarari, user: Tester, response: Response
) -> dict[str, Any]:
    def karar_ver() -> uuid.UUID | None:
        with session_scope() as s:
            return service.decide(
                s,
                draft_id,
                user,
                body.karar,
                body.icerik_hash,
                icerik=body.icerik,
                link_key=body.link_key,
                gerekce=body.gerekce,
            )

    job_id = await run_in_threadpool(karar_ver)
    yayin = await _bekle(job_id, response) if job_id is not None else None
    out = await run_in_threadpool(_view, draft_id)
    out["yayin_sonucu"] = yayin
    return out


@router.post("/bug-drafts/{draft_id}/prepare", status_code=202)
def prepare(draft_id: uuid.UUID, session: DbSession, user: Tester) -> dict[str, Any]:
    job_id = service.request_prepare(session, draft_id, user)
    return {
        "job_id": str(job_id),
        "durum": "queued",
        "mesaj": "Mükerrer araması ve taslak hazırlanıyor",
    }


@router.post("/bug-drafts/{draft_id}/publish")
async def publish(draft_id: uuid.UUID, user: Tester, response: Response) -> dict[str, Any]:
    def kuyruga_al() -> uuid.UUID:
        with session_scope() as s:
            return service.retry_publish(s, draft_id, user)

    job_id = await run_in_threadpool(kuyruga_al)
    yayin = await _bekle(job_id, response)
    out = await run_in_threadpool(_view, draft_id)
    out["yayin_sonucu"] = yayin
    return out


@router.get("/bug-drafts/{draft_id}/detail")
def detail(draft_id: uuid.UUID, _u: Herkes) -> dict[str, Any]:
    return _view(draft_id)
