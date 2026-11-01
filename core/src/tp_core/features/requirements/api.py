"""Gereksinim ve bulgu uçları (MIMARI-SOZLESME §5). `registry` bu `router`'ı otomatik bağlar.

Yanıt biçimleri review-portal'ın `src/api/types.ts` sözleşmesini izler. Karar gövdeleri,
kullanıcının ekranda gördüğü içeriğin `icerik_hash`'ini taşır (eksikse 422, eskiyse 409).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from tp_core.api.deps import DbSession, Principal, current_user, require_role
from tp_core.features.requirements import flow, serialize, services
from tp_core.models import BugDraft, ConsistencyFinding, Requirement

router = APIRouter(tags=["requirements"])

Analyst = Annotated[Principal, Depends(require_role("analyst"))]
Po = Annotated[Principal, Depends(require_role("po"))]
Herkes = Annotated[Principal, Depends(current_user)]

ELENEN_BASLIGI = "X-Elenen-Bulgu-Sayisi"


class SerbestMetin(BaseModel):
    baslik: str = Field(max_length=200)
    aciklama: str = Field(default="", max_length=10000)
    ac: list[Annotated[str, Field(max_length=2000)]] = Field(default_factory=list, max_length=30)


class BulguKarari(BaseModel):
    karar: Literal["fix_doc", "code_defect", "accept_difference"]
    icerik_hash: str | None = Field(default=None, max_length=128)
    metin: str | None = Field(default=None, max_length=4000)
    gerekce: str | None = Field(default=None, max_length=2000)


class DuzeltmeUygulama(BaseModel):
    # Düzeltme, aynı döngüdeki 'bilinçli fark' kararıyla çelişiyorsa (409) bilinçli uygulama.
    cakismayi_onayla: bool = False


class PoOnayi(BaseModel):
    icerik_hash: str | None = Field(default=None, max_length=128)


def _req(session: DbSession, req_id: uuid.UUID, kilit: bool = False) -> Requirement:
    req = session.get(Requirement, req_id, with_for_update=kilit)
    if req is None:
        raise HTTPException(404, "Gereksinim bulunamadı")
    return req


def _is(started: flow.Started | flow.Finalized | None, mesaj: str | None = None) -> dict[str, Any]:
    if isinstance(started, flow.Finalized):
        return {
            "job_id": None,
            "workflow_id": None,
            "durum": "done",
            "mesaj": started.mesaj,
            "kabul_edilen_uyarilar": started.kabul_edilen,
        }
    if started is None:
        return {"job_id": None, "workflow_id": None, "durum": "done", "mesaj": mesaj}
    return {
        "job_id": str(started.job_id),
        "workflow_id": str(started.workflow_id),
        "durum": "started",
        "mesaj": started.mesaj,
    }


@router.get("/requirements")
def list_requirements(session: DbSession, _u: Herkes) -> list[dict[str, Any]]:
    return serialize.list_requirements(session)


@router.post("/requirements/sync")
def sync(session: DbSession, user: Analyst) -> dict[str, Any]:
    from tp_core.integrations.jira import JiraError

    try:
        jira = services.jira()
        rapor = flow.sync_from_jira(session, jira, user)
    except JiraError as exc:
        raise HTTPException(502, f"Jira'ya erişilemedi: {exc}") from exc
    return {
        "job_id": None,
        "durum": "done",
        "mesaj": rapor.mesaj(),
        "proje": rapor.proje,
        "sonuc": rapor.sonuc,
    }


@router.post("/requirements/free-text", status_code=201)
def free_text(body: SerbestMetin, session: DbSession, user: Analyst) -> dict[str, Any]:
    req = flow.create_free_text(session, user, body.baslik, body.aciklama, body.ac)
    return serialize.requirement_detail(session, req)


@router.get("/requirements/{req_id}")
def detail(req_id: uuid.UUID, session: DbSession, _u: Herkes) -> dict[str, Any]:
    return serialize.requirement_detail(session, _req(session, req_id))


@router.post("/requirements/{req_id}/review", status_code=202)
def review(req_id: uuid.UUID, session: DbSession, user: Analyst) -> dict[str, Any]:
    return _is(flow.start_review(session, _req(session, req_id, kilit=True), user))


@router.get("/requirements/{req_id}/findings")
def findings(
    req_id: uuid.UUID,
    session: DbSession,
    response: Response,
    _u: Herkes,
    tumu: Annotated[bool, Query(description="Bayatlamış (stale) bulguları da getir")] = False,
) -> list[dict[str, Any]]:
    _req(session, req_id)
    bulgular, elenen = serialize.findings_for(session, req_id, tumu=tumu)
    response.headers[ELENEN_BASLIGI] = str(elenen)
    return bulgular


@router.post("/findings/{finding_id}/decision")
def decision(
    finding_id: uuid.UUID, body: BulguKarari, session: DbSession, user: Analyst
) -> dict[str, Any]:
    f = session.get(ConsistencyFinding, finding_id)
    if f is None or not f.kanit_dogrulandi:
        raise HTTPException(404, "Bulgu bulunamadı")
    flow.decide_finding(
        session, f, user, body.karar, body.icerik_hash, metin=body.metin, gerekce=body.gerekce
    )
    session.flush()
    return serialize.one_finding(session, f)


@router.post("/requirements/{req_id}/apply-doc-fixes", status_code=202)
def apply_doc_fixes(
    req_id: uuid.UUID,
    session: DbSession,
    user: Analyst,
    body: DuzeltmeUygulama | None = None,
) -> dict[str, Any]:
    started = flow.start_apply(
        session,
        _req(session, req_id, kilit=True),
        user,
        cakismayi_onayla=bool(body and body.cakismayi_onayla),
    )
    return _is(started)


@router.post("/requirements/{req_id}/po-approve")
def po_approve(req_id: uuid.UUID, body: PoOnayi, session: DbSession, user: Po) -> dict[str, Any]:
    req = _req(session, req_id, kilit=True)
    flow.po_approve_portal(session, req, user, body.icerik_hash)
    session.flush()
    return serialize.requirement_detail(session, req)


# ----------------------------------------------------------- bug taslakları (salt okuma)
# Tutarlılık bulgusundaki "kod/veri hatalı" kararı bug taslağı açar; portaldaki "Bug taslağına
# git" bağlantısı bu uçlara gelir (MIMARI-SOZLESME §5: GET /bug-drafts · /bug-drafts/{id}).
# Karar/yayın (`POST /bug-drafts/{id}/decision`, publish_bug) Faz 4 özelliğindedir.


@router.get("/bug-drafts")
def bug_drafts(
    session: DbSession,
    _u: Herkes,
    requirement_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[dict[str, Any]]:
    from tp_core.features.bugs import serialize as bugs_serialize

    # Faz 4: `bug_draft_view` Faz 2 `bug_draft_out`'un üst kümesidir; triage kaynaklı
    # taslaklar da gereksinim süzgecine girer.
    return bugs_serialize.bug_draft_list(session, requirement_id)


@router.get("/bug-drafts/{draft_id}")
def bug_draft(draft_id: uuid.UUID, session: DbSession, _u: Herkes) -> dict[str, Any]:
    b = session.get(BugDraft, draft_id)
    if b is None:
        raise HTTPException(404, "Bug taslağı bulunamadı")
    from tp_core.features.bugs import serialize as bugs_serialize

    return bugs_serialize.bug_draft_view(session, b)
