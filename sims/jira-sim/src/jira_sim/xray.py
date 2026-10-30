"""Xray Cloud REST v2 alt kümesi: kimlik doğrulama ve toplu test içe aktarımı.

Gerçek Xray'de içe aktarım asenkron bir iştir; simülatör işi hemen işler ama ilk durum sorgusunda
``working`` döner, böylece istemcinin bekleme döngüsü de sınanır.
"""

from __future__ import annotations

import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from jira_sim.adf import is_adf_doc, text_to_adf
from jira_sim.api import base_url, get_store, json_body
from jira_sim.ops import SimError, create_issue
from jira_sim.store import Store

router = APIRouter(prefix="/xray/api/v2")

XRAY_USER = "writer@sim.local"  # API anahtarının bağlı olduğu Jira kullanıcısı


class XrayError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def xray_error_response(exc: XrayError) -> JSONResponse:
    return JSONResponse({"error": exc.message}, status_code=exc.status)


def bearer(request: Request) -> str:
    store: Store = request.app.state.store
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or token not in store.xray_tokens:
        raise XrayError(401, "Authentication failed. Invalid or expired token.")
    return token


Token = Annotated[str, Depends(bearer)]
StoreDep = Annotated[Store, Depends(get_store)]


@router.post("/authenticate")
async def authenticate(request: Request, store: StoreDep) -> JSONResponse:
    body = await json_body(request)
    if not isinstance(body, dict):
        raise XrayError(400, "Invalid request body.")
    cid, secret = body.get("client_id"), body.get("client_secret")
    if not isinstance(cid, str) or not cid or not isinstance(secret, str) or not secret:
        raise XrayError(401, "Authentication failed. Invalid client credentials!")
    token = "simxray." + secrets.token_urlsafe(24)
    store.xray_tokens.add(token)
    return JSONResponse(token)  # gerçek Xray de yalnızca JSON string döner


def _import_one(store: Store, n: int, test: Any) -> dict[str, Any]:
    if not isinstance(test, dict) or not isinstance(test.get("fields"), dict):
        return {"elementNumber": n, "errors": {"fields": "Test must contain 'fields'."}}
    f = dict(test["fields"])
    steps = test.get("steps") or []
    if not isinstance(steps, list) or not all(
        isinstance(s, dict) and str(s.get("action") or "").strip() for s in steps
    ):
        return {"elementNumber": n, "errors": {"steps": "Each step must have an action."}}
    desc = f.get("description")
    if isinstance(desc, str):
        f["description"] = text_to_adf(desc)
    elif desc is not None and not is_adf_doc(desc):
        return {"elementNumber": n, "errors": {"description": "Invalid description."}}
    f["issuetype"] = {"name": "Test"}  # Xray Test türü her zaman vardır
    xray = {
        "testtype": test.get("testtype") or "Manual",
        "steps": [
            {
                "action": str(s.get("action") or ""),
                "data": str(s.get("data") or ""),
                "result": str(s.get("result") or ""),
            }
            for s in steps
        ],
    }
    try:
        it = create_issue(store, {"fields": f}, XRAY_USER, xray=xray)
    except SimError as exc:
        return {"elementNumber": n, "errors": exc.body["errors"] or exc.body["errorMessages"]}
    return {"elementNumber": n, "id": it["id"], "key": it["key"]}


@router.post("/import/test/bulk")
async def import_bulk(request: Request, store: StoreDep, token: Token) -> dict[str, Any]:
    body = await json_body(request)
    if not isinstance(body, list) or not body:
        raise XrayError(400, "Request body must be a non-empty JSON array of tests.")
    if len(body) > 1000:
        raise XrayError(400, "Maximum 1000 tests per import.")
    base = base_url(request)
    with store.lock:
        results = [_import_one(store, n, t) for n, t in enumerate(body)]
        issues = [
            {**r, "self": f"{base}/rest/api/3/issue/{r['id']}"} for r in results if "key" in r
        ]
        errors = [r for r in results if "errors" in r]
        final = "successful" if not errors else "failed" if not issues else "partially_successful"
        job_id = secrets.token_hex(12)
        with store.tx() as state:
            state["xray_jobs"][job_id] = {
                "status": final,
                "polls": 0,
                "result": {"errors": errors, "issues": issues, "warnings": []},
            }
    return {"jobId": job_id}


@router.get("/import/test/bulk/{job_id}/status")
def import_status(store: StoreDep, token: Token, job_id: str) -> dict[str, Any]:
    with store.tx() as state:
        job = state["xray_jobs"].get(job_id)
        if job is None:
            raise XrayError(404, "Job not found.")
        job["polls"] += 1
        if job["polls"] == 1:
            return {"status": "working", "progress": ["Test import in progress."]}
        return {
            "status": job["status"],
            "result": job["result"],
            "progress": ["Test import finished."],
        }
