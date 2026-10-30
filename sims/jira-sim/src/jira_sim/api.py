"""Jira Cloud REST v3 alt kümesi (yanıt biçimleri gerçek Jira ile aynı)."""

from __future__ import annotations

import base64
import binascii
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response

from jira_sim import jql
from jira_sim.ops import (
    ALL_FIELDS,
    SimError,
    add_comment,
    comment_json,
    create_issue,
    create_link,
    delete_issue,
    history_json,
    issue_json,
    issuetype_json,
    link_type_json,
    require_issue,
    select_fields,
    update_issue,
    user_json,
)
from jira_sim.seed import ISSUE_TYPES, PROJECT, USERS
from jira_sim.store import Store

router = APIRouter(prefix="/rest/api/3")


def get_store(request: Request) -> Store:
    return request.app.state.store


def base_url(request: Request) -> str:
    configured = request.app.state.base_url
    return configured or str(request.base_url).rstrip("/")


PO_EMAIL = "po@sim.local"


def current_user(request: Request) -> str:
    """Basic auth; bilinmeyen kullanıcı → 401.

    Okuma ve yazma (bot) kullanıcıları için her token kabul edilir. PO kullanıcısının token'ı PO
    parolası olmalıdır: PO adına yazmak (ör. ``tp-po-approved``) insan onayıdır.
    """
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "basic" or not value:
        raise SimError(
            401,
            ["You are not authenticated. Authentication required to perform this operation."],
        )
    try:
        email, _, token = base64.b64decode(value).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise SimError(401, ["Basic authentication header is malformed."]) from exc
    if email not in USERS or not token:
        raise SimError(401, ["Client must be authenticated to access this resource."])
    if email == PO_EMAIL and not request.app.state.security.check_po_password(token):
        raise SimError(401, ["Client must be authenticated to access this resource."])
    return email


def writer(user: Annotated[str, Depends(current_user)]) -> str:
    if not USERS[user]["can_write"]:
        raise SimError(403, ["You do not have permission to perform this operation."])
    return user


Reader = Annotated[str, Depends(current_user)]
Writer = Annotated[str, Depends(writer)]
StoreDep = Annotated[Store, Depends(get_store)]


async def json_body(request: Request) -> Any:
    try:
        return await request.json()
    except ValueError as exc:
        raise SimError(400, ["Unexpected character in request body (invalid JSON)."]) from exc


def _dict_body(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise SimError(400, ["Request body must be a JSON object."])
    return body


# ---------------------------------------------------------------------- kimlik


@router.get("/myself")
def myself(request: Request, user: Reader) -> dict[str, Any]:
    return user_json(user, base_url(request)) or {}


# ----------------------------------------------------------------------- arama


def _search(
    request: Request,
    store: Store,
    query: str,
    fields: list[str] | None,
    max_results: int,
    token: str | None,
    expand: str | None,
) -> dict[str, Any]:
    try:
        q = jql.parse(query)
    except jql.JqlError as exc:
        raise SimError(400, [str(exc)]) from exc
    base = base_url(request)
    chosen = select_fields(fields, ())
    with store.lock:
        docs = [store.search_doc(it) for it in store.state["issues"].values()]
        hits = jql.sort_docs([d for d in docs if q.predicate(d)], q.order)
        start = 0
        if token:
            try:
                start = int(base64.urlsafe_b64decode(token.encode()).decode())
            except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
                raise SimError(400, ["The provided next page token is invalid."]) from exc
        max_results = max(1, min(max_results, 5000))
        page = hits[start : start + max_results]
        changelog = bool(expand and "changelog" in expand)
        issues = []
        for d in page:
            body = issue_json(store, d["_issue"], base, chosen, changelog)
            if not chosen:
                body.pop("fields")
            body.pop("expand", None)
            issues.append(body)
    out: dict[str, Any] = {"issues": issues, "isLast": start + len(page) >= len(hits)}
    if not out["isLast"]:
        out["nextPageToken"] = base64.urlsafe_b64encode(str(start + len(page)).encode()).decode()
    return out


@router.get("/search/jql")
def search_get(
    request: Request,
    store: StoreDep,
    user: Reader,
    jql_: Annotated[str, Query(alias="jql")] = "",
    fields: Annotated[list[str] | None, Query()] = None,
    max_results: Annotated[int, Query(alias="maxResults")] = 50,
    next_page_token: Annotated[str | None, Query(alias="nextPageToken")] = None,
    expand: str | None = None,
) -> dict[str, Any]:
    return _search(request, store, jql_, fields, max_results, next_page_token, expand)


@router.post("/search/jql")
async def search_post(request: Request, store: StoreDep, user: Reader) -> dict[str, Any]:
    body = _dict_body(await json_body(request))
    fields = body.get("fields")
    if fields is not None and not isinstance(fields, list):
        raise SimError(400, ["'fields' must be a list."])
    expand = body.get("expand")
    if isinstance(expand, list):
        expand = ",".join(expand)
    return _search(
        request,
        store,
        str(body.get("jql") or ""),
        fields,
        int(body.get("maxResults") or 50),
        body.get("nextPageToken"),
        expand,
    )


# ------------------------------------------------------------- tür meta verisi


def _issue_types(store: Store, base: str) -> list[dict[str, Any]]:
    enabled = store.state["config"]["issue_types"]
    return [issuetype_json(t["name"], base) for t in ISSUE_TYPES if t["name"] in enabled]


def _check_project(key: str) -> None:
    if key not in (PROJECT["key"], PROJECT["id"]):
        raise SimError(404, [f"No project could be found with key '{key}'."])


@router.get("/issue/createmeta/{project}/issuetypes")
def createmeta_types(request: Request, store: StoreDep, user: Reader, project: str) -> dict:
    _check_project(project)
    types = _issue_types(store, base_url(request))
    return {"maxResults": 50, "startAt": 0, "total": len(types), "issueTypes": types}


@router.get("/issue/createmeta")
def createmeta(
    request: Request,
    store: StoreDep,
    user: Reader,
    project_keys: Annotated[str | None, Query(alias="projectKeys")] = None,
) -> dict:
    keys = [k.strip() for k in (project_keys or PROJECT["key"]).split(",") if k.strip()]
    projects = []
    if PROJECT["key"] in keys:
        base = base_url(request)
        projects.append(
            {
                "self": f"{base}/rest/api/3/project/{PROJECT['id']}",
                **PROJECT,
                "issuetypes": _issue_types(store, base),
            }
        )
    return {"expand": "projects", "projects": projects}


@router.get("/project/{project}")
def project(request: Request, store: StoreDep, user: Reader, project: str) -> dict:
    _check_project(project)
    base = base_url(request)
    return {
        "self": f"{base}/rest/api/3/project/{PROJECT['id']}",
        **PROJECT,
        "issueTypes": _issue_types(store, base),
    }


@router.get("/issueLinkType")
def link_types(request: Request, store: StoreDep, user: Reader) -> dict:
    base = base_url(request)
    enabled = store.state["config"]["link_types"]
    return {"issueLinkTypes": [link_type_json(n, base) for n in enabled]}


# ----------------------------------------------------------------------- issue


@router.post("/issue", status_code=201)
async def issue_create(request: Request, store: StoreDep, user: Writer) -> dict:
    body = _dict_body(await json_body(request))
    it = create_issue(store, body, user)
    return {
        "id": it["id"],
        "key": it["key"],
        "self": f"{base_url(request)}/rest/api/3/issue/{it['id']}",
    }


@router.get("/issue/{key}")
def issue_get(
    request: Request,
    store: StoreDep,
    user: Reader,
    key: str,
    fields: Annotated[list[str] | None, Query()] = None,
    expand: str | None = None,
) -> dict:
    with store.lock:
        it = require_issue(store, key)
        chosen = select_fields(fields, ALL_FIELDS)
        return issue_json(
            store, it, base_url(request), chosen, bool(expand and "changelog" in expand)
        )


@router.put("/issue/{key}", status_code=204)
async def issue_put(request: Request, store: StoreDep, user: Writer, key: str) -> Response:
    body = _dict_body(await json_body(request))
    update_issue(store, key, body, user)
    return Response(status_code=204)


@router.delete("/issue/{key}", status_code=204)
def issue_delete(store: StoreDep, user: Writer, key: str) -> Response:
    delete_issue(store, key)
    return Response(status_code=204)


@router.get("/issue/{key}/changelog")
def changelog(
    request: Request,
    store: StoreDep,
    user: Reader,
    key: str,
    start_at: Annotated[int, Query(alias="startAt", ge=0)] = 0,
    max_results: Annotated[int, Query(alias="maxResults", ge=1, le=100)] = 100,
) -> dict:
    base = base_url(request)
    with store.lock:
        it = require_issue(store, key)
        hs = it["changelog"]
        page = hs[start_at : start_at + max_results]
        return {
            "self": f"{base}/rest/api/3/issue/{key}/changelog?maxResults={max_results}"
            f"&startAt={start_at}",
            "maxResults": max_results,
            "startAt": start_at,
            "total": len(hs),
            "isLast": start_at + len(page) >= len(hs),
            "values": [history_json(h, base) for h in page],
        }


@router.get("/issue/{key}/comment")
def comments(
    request: Request,
    store: StoreDep,
    user: Reader,
    key: str,
    start_at: Annotated[int, Query(alias="startAt", ge=0)] = 0,
    max_results: Annotated[int, Query(alias="maxResults", ge=1, le=5000)] = 5000,
) -> dict:
    base = base_url(request)
    with store.lock:
        it = require_issue(store, key)
        cs = it["comments"]
        page = cs[start_at : start_at + max_results]
        return {
            "startAt": start_at,
            "maxResults": max_results,
            "total": len(cs),
            "comments": [comment_json(c, it["key"], it["id"], base) for c in page],
        }


@router.post("/issue/{key}/comment", status_code=201)
async def comment_add(request: Request, store: StoreDep, user: Writer, key: str) -> dict:
    body = _dict_body(await json_body(request))
    c = add_comment(store, key, body.get("body"), user)
    it = require_issue(store, key)
    return comment_json(c, it["key"], it["id"], base_url(request))


@router.post("/issueLink", status_code=201)
async def issue_link(request: Request, store: StoreDep, user: Writer) -> Response:
    body = _dict_body(await json_body(request))
    create_link(store, body)
    return Response(status_code=201)


def error_response(exc: SimError) -> JSONResponse:
    return JSONResponse(exc.body, status_code=exc.status, headers=exc.headers)
