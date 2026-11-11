"""Jira işlemleri: REST uçları ve HTML arayüzü aynı fonksiyonları kullanır.

Hatalar Jira Cloud gövde biçimiyle ``SimError`` olarak yükseltilir.
"""

from __future__ import annotations

from typing import Any

from jira_sim.adf import adf_to_text, is_adf_doc, resolve_mentions
from jira_sim.seed import ISSUE_TYPES, LINK_TYPES, PROJECT, STATUSES, USERS
from jira_sim.store import Store, now_jira


class SimError(Exception):
    def __init__(
        self,
        status: int,
        messages: list[str] | None = None,
        errors: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(messages or errors)
        self.status = status
        self.body = {"errorMessages": messages or [], "errors": errors or {}}
        self.headers = headers


NOT_FOUND = "Issue does not exist or you do not have permission to see it."


# ------------------------------------------------------------------- serileştirme


def user_json(email: str | None, base: str) -> dict[str, Any] | None:
    if not email or email not in USERS:
        return None
    u = USERS[email]
    return {
        "self": f"{base}/rest/api/3/user?accountId={u['accountId']}",
        "accountId": u["accountId"],
        "emailAddress": email,
        "displayName": u["displayName"],
        "active": True,
        "timeZone": "Europe/Istanbul",
        "accountType": "atlassian",
    }


def status_json(name: str, base: str) -> dict[str, Any]:
    st = STATUSES.get(name, STATUSES["To Do"])
    cat_id = {"new": 2, "indeterminate": 4, "done": 3}[st["key"]]
    return {
        "self": f"{base}/rest/api/3/status/{st['id']}",
        "id": st["id"],
        "name": st["name"],
        "statusCategory": {
            "self": f"{base}/rest/api/3/statuscategory/{cat_id}",
            "id": cat_id,
            "key": st["key"],
            "name": st["name"],
        },
    }


def issuetype_json(name: str, base: str) -> dict[str, Any]:
    t = next((t for t in ISSUE_TYPES if t["name"] == name), ISSUE_TYPES[1])
    return {"self": f"{base}/rest/api/3/issuetype/{t['id']}", **t}


def project_json(base: str) -> dict[str, Any]:
    return {"self": f"{base}/rest/api/3/project/{PROJECT['id']}", **PROJECT}


def link_type_json(name: str, base: str) -> dict[str, Any]:
    t = next(t for t in LINK_TYPES if t["name"] == name)
    return {"self": f"{base}/rest/api/3/issueLinkType/{t['id']}", **t}


def _brief(it: dict[str, Any], base: str) -> dict[str, Any]:
    return {
        "id": it["id"],
        "key": it["key"],
        "self": f"{base}/rest/api/3/issue/{it['id']}",
        "fields": {
            "summary": it["summary"],
            "status": status_json(it["status"], base),
            "issuetype": issuetype_json(it["issuetype"], base),
        },
    }


def issue_links(store: Store, it: dict[str, Any], base: str) -> list[dict[str, Any]]:
    out = []
    for link in store.state["links"]:
        if it["key"] not in (link["inward"], link["outward"]):
            continue
        entry: dict[str, Any] = {
            "id": link["id"],
            "self": f"{base}/rest/api/3/issueLink/{link['id']}",
            "type": link_type_json(link["type"], base),
        }
        if link["inward"] == it["key"]:
            other = store.issue(link["outward"])
            if other:
                entry["outwardIssue"] = _brief(other, base)
        else:
            other = store.issue(link["inward"])
            if other:
                entry["inwardIssue"] = _brief(other, base)
        out.append(entry)
    return out


def comment_json(c: dict[str, Any], key: str, issue_id: str, base: str) -> dict[str, Any]:
    author = user_json(c["author"], base)
    return {
        "self": f"{base}/rest/api/3/issue/{issue_id}/comment/{c['id']}",
        "id": c["id"],
        "author": author,
        "body": c["body"],
        "updateAuthor": author,
        "created": c["created"],
        "updated": c["created"],
        # Kısıtlı yorum provası (asistanın kısıtlı yorum filtresi): saklanmışsa aynen döner.
        "jsdPublic": c.get("jsdPublic", True) is not False,
        **({"visibility": c["visibility"]} if c.get("visibility") else {}),
    }


def history_json(h: dict[str, Any], base: str) -> dict[str, Any]:
    return {
        "id": h["id"],
        "author": user_json(h["author"], base),
        "created": h["created"],
        "items": h["items"],
    }


ALL_FIELDS = (
    "summary",
    "description",
    "labels",
    "status",
    "issuetype",
    "project",
    "reporter",
    "creator",
    "created",
    "updated",
    "issuelinks",
    "comment",
)
NAVIGABLE = tuple(f for f in ALL_FIELDS if f != "comment")


def select_fields(requested: list[str] | None, default: tuple[str, ...]) -> list[str]:
    if not requested:
        return list(default)
    chosen: list[str] = []
    excluded: set[str] = set()
    for raw in requested:
        for f in (p.strip() for p in raw.split(",")):
            if not f:
                continue
            if f == "*all":
                chosen.extend(ALL_FIELDS)
            elif f == "*navigable":
                chosen.extend(NAVIGABLE)
            elif f.startswith("-"):
                excluded.add(f[1:])
            elif f in ALL_FIELDS:
                chosen.append(f)
    return [f for f in dict.fromkeys(chosen) if f not in excluded]


def issue_json(
    store: Store,
    it: dict[str, Any],
    base: str,
    fields: list[str],
    changelog: bool = False,
) -> dict[str, Any]:
    full: dict[str, Any] = {
        "summary": lambda: it["summary"],
        "description": lambda: it.get("description"),
        "labels": lambda: list(it.get("labels", [])),
        "status": lambda: status_json(it["status"], base),
        "issuetype": lambda: issuetype_json(it["issuetype"], base),
        "project": lambda: project_json(base),
        "reporter": lambda: user_json(it.get("reporter"), base),
        "creator": lambda: user_json(it.get("reporter"), base),
        "created": lambda: it["created"],
        "updated": lambda: it["updated"],
        "issuelinks": lambda: issue_links(store, it, base),
        "comment": lambda: {
            "comments": [comment_json(c, it["key"], it["id"], base) for c in it["comments"]],
            "maxResults": len(it["comments"]),
            "total": len(it["comments"]),
            "startAt": 0,
        },
    }
    out: dict[str, Any] = {
        "expand": "renderedFields,names,schema,operations,editmeta,changelog",
        "id": it["id"],
        "self": f"{base}/rest/api/3/issue/{it['id']}",
        "key": it["key"],
        "fields": {f: full[f]() for f in fields if f in full},
    }
    if changelog:
        hs = [history_json(h, base) for h in it["changelog"]]
        out["changelog"] = {"startAt": 0, "maxResults": len(hs), "total": len(hs), "histories": hs}
    return out


# ----------------------------------------------------------------------- işlemler


def require_issue(store: Store, key: str) -> dict[str, Any]:
    it = store.issue(key)
    if it is None:
        raise SimError(404, [NOT_FOUND])
    return it


def _check_labels(labels: list[Any]) -> list[str]:
    out = []
    for lb in labels:
        if not isinstance(lb, str) or not lb:
            raise SimError(400, errors={"labels": "Labels must be non-empty strings."})
        if any(ch.isspace() for ch in lb):
            raise SimError(
                400, errors={"labels": f"The label '{lb}' contains spaces which is invalid."}
            )
        if len(lb) > 255:
            raise SimError(400, errors={"labels": "The label must not exceed 255 characters."})
        out.append(lb)
    return out


def _check_description(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not is_adf_doc(value):
        raise SimError(400, errors={"description": "Operation value must be an Atlassian Document"})
    return resolve_mentions(value, mention_names())


def mention_names() -> dict[str, str]:
    """Simülatör kullanıcılarının accountId → görünen ad eşlemesi (bahsetme çizimi için)."""
    return {u["accountId"]: u["displayName"] for u in USERS.values()}


def _record(store: Store, it: dict[str, Any], author: str, items: list[dict[str, Any]]) -> None:
    if not items:
        return
    ts = now_jira()
    it["changelog"].append({"id": store.next_id(), "author": author, "created": ts, "items": items})
    it["updated"] = ts


def _label_item(before: list[str], after: list[str]) -> dict[str, Any]:
    return {
        "field": "labels",
        "fieldtype": "jira",
        "fieldId": "labels",
        "from": None,
        "fromString": " ".join(before),
        "to": None,
        "toString": " ".join(after),
    }


def _text_item(field: str, before: str, after: str) -> dict[str, Any]:
    return {
        "field": field,
        "fieldtype": "jira",
        "fieldId": field,
        "from": None,
        "fromString": before,
        "to": None,
        "toString": after,
    }


EDITABLE = {"summary", "description", "labels"}


def update_issue(store: Store, key: str, body: dict[str, Any], author: str) -> None:
    fields = body.get("fields") or {}
    update = body.get("update") or {}
    if not isinstance(fields, dict) or not isinstance(update, dict):
        raise SimError(400, ["Request body is invalid."])
    for name in set(fields) | set(update):
        if name not in EDITABLE:
            raise SimError(
                400,
                errors={
                    name: f"Field '{name}' cannot be set. It is not on the appropriate screen, "
                    "or unknown."
                },
            )
    with store.tx():
        it = require_issue(store, key)
        items: list[dict[str, Any]] = []

        new_summary = fields.get("summary")
        for op in update.get("summary", []):
            if "set" in op:
                new_summary = op["set"]
        if new_summary is not None:
            if not isinstance(new_summary, str) or not new_summary.strip():
                raise SimError(400, errors={"summary": "You must specify a summary of the issue."})
            if new_summary != it["summary"]:
                items.append(_text_item("summary", it["summary"], new_summary))
                it["summary"] = new_summary

        desc_set = "description" in fields
        new_desc = fields.get("description")
        for op in update.get("description", []):
            if "set" in op:
                desc_set, new_desc = True, op["set"]
        if desc_set:
            new_desc = _check_description(new_desc)
            if new_desc != it.get("description"):
                items.append(
                    _text_item(
                        "description",
                        adf_to_text(it.get("description")),
                        adf_to_text(new_desc),
                    )
                )
                it["description"] = new_desc

        before = list(it.get("labels", []))
        labels = list(before)
        if "labels" in fields:
            if not isinstance(fields["labels"], list):
                raise SimError(400, errors={"labels": "Labels must be a list."})
            labels = _check_labels(fields["labels"])
        for op in update.get("labels", []):
            if not isinstance(op, dict):
                raise SimError(400, errors={"labels": "Invalid label operation."})
            if "set" in op:
                labels = _check_labels(list(op["set"] or []))
            if "add" in op:
                (lb,) = _check_labels([op["add"]])
                if lb not in labels:
                    labels.append(lb)
            if "remove" in op and op["remove"] in labels:
                labels.remove(op["remove"])
        labels = list(dict.fromkeys(labels))
        if sorted(labels) != sorted(before):
            items.append(_label_item(sorted(before), sorted(labels)))
            it["labels"] = labels

        _record(store, it, author, items)


def create_issue(
    store: Store, body: dict[str, Any], author: str, xray: dict[str, Any] | None = None
) -> dict[str, Any]:
    fields = body.get("fields")
    if not isinstance(fields, dict):
        raise SimError(400, ["Request body is invalid."])
    errors: dict[str, str] = {}
    allowed = {"project", "issuetype", "summary", "description", "labels", "reporter"}
    for name in fields:
        if name not in allowed:
            errors[name] = (
                f"Field '{name}' cannot be set. It is not on the appropriate screen, or unknown."
            )
    proj = fields.get("project") or {}
    if proj.get("key") != PROJECT["key"] and proj.get("id") != PROJECT["id"]:
        errors["project"] = "Specify a valid project ID or key"
    itype = fields.get("issuetype") or {}
    enabled = store.state["config"]["issue_types"]
    if xray is not None:  # Xray kurulu sitede Test türü her zaman vardır
        enabled = [*enabled, "Test"]
    type_name = itype.get("name") or next(
        (t["name"] for t in ISSUE_TYPES if t["id"] == itype.get("id")), None
    )
    if type_name not in enabled:
        errors["issuetype"] = "Specify a valid issue type"
    summary = fields.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        errors["summary"] = "You must specify a summary of the issue."
    elif len(summary) > 255:
        errors["summary"] = "Summary must be less than 255 characters."
    if errors:
        raise SimError(400, errors=errors)
    desc = _check_description(fields.get("description"))
    labels = _check_labels(list(fields.get("labels") or []))
    with store.tx() as state:
        key = store.next_key(PROJECT["key"])
        ts = now_jira()
        it = {
            "id": store.next_id(),
            "key": key,
            "project": PROJECT["key"],
            "issuetype": type_name,
            "summary": summary,
            "description": desc,
            "labels": list(dict.fromkeys(labels)),
            "status": "To Do",
            "reporter": author,
            "created": ts,
            "updated": ts,
            "changelog": [],
            "comments": [],
            "xray": xray,
        }
        state["issues"][key] = it
    return it


# Basit iş akışı: her durumdan diğer durumlara geçiş vardır (Jira'nın "Simplified workflow"u).
TRANSITIONS = [
    {"id": "11", "name": "To Do", "to": "To Do"},
    {"id": "21", "name": "In Progress", "to": "In Progress"},
    {"id": "41", "name": "QA To Do", "to": "QA To Do"},
    {"id": "31", "name": "Done", "to": "Done"},
]


def transitions_json(it: dict[str, Any], base: str) -> list[dict[str, Any]]:
    """``GET /issue/{key}/transitions`` gövdesindeki ``transitions`` (mevcut durum hariç)."""
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "to": status_json(t["to"], base),
            "hasScreen": False,
            "isGlobal": True,
            "isInitial": False,
            "isAvailable": True,
            "isConditional": False,
        }
        for t in TRANSITIONS
        if t["to"] != it["status"]
    ]


def transition_issue(store: Store, key: str, body: dict[str, Any], author: str) -> None:
    ref = body.get("transition")
    tid = str(ref.get("id") or "") if isinstance(ref, dict) else ""
    with store.tx():
        it = require_issue(store, key)
        target = next((t for t in TRANSITIONS if t["id"] == tid and t["to"] != it["status"]), None)
        if target is None:
            raise SimError(
                400,
                [
                    f"Transition id '{tid}' is not valid for this issue."
                    if tid
                    else "Transition id must be specified."
                ],
            )
        before = it["status"]
        it["status"] = target["to"]
        _record(store, it, author, [_text_item("status", before, target["to"])])


def delete_issue(store: Store, key: str) -> None:
    with store.tx() as state:
        it = require_issue(store, key)
        del state["issues"][it["key"]]
        state["links"] = [
            lk for lk in state["links"] if it["key"] not in (lk["inward"], lk["outward"])
        ]


def add_comment(
    store: Store,
    key: str,
    body: Any,
    author: str,
    *,
    visibility: Any = None,
    jsd_public: Any = None,
) -> dict[str, Any]:
    """Yorum ekler. ``visibility`` (``{"type": "role"|"group", "value": ...}``) ve
    ``jsdPublic=false`` (iç not) gerçek Jira'daki kısıtlı yorumları taklit eder."""
    if visibility is not None and (
        not isinstance(visibility, dict)
        or visibility.get("type") not in ("role", "group")
        or not isinstance(visibility.get("value"), str)
    ):
        raise SimError(400, errors={"visibility": "Invalid visibility."})
    if jsd_public is not None and not isinstance(jsd_public, bool):
        raise SimError(400, errors={"jsdPublic": "jsdPublic must be a boolean."})
    if not is_adf_doc(body):
        raise SimError(400, errors={"comment": "Comment body must be an Atlassian Document"})
    if not adf_to_text(body).strip():
        raise SimError(400, errors={"comment": "Comment body can not be empty!"})
    with store.tx():
        it = require_issue(store, key)
        body = resolve_mentions(body, mention_names())
        c = {"id": store.next_id(), "author": author, "body": body, "created": now_jira()}
        if visibility is not None:
            c["visibility"] = {"type": visibility["type"], "value": visibility["value"]}
        if jsd_public is False:
            c["jsdPublic"] = False
        it["comments"].append(c)
        it["updated"] = c["created"]
    return c


def delete_comment(store: Store, key: str, comment_id: str) -> None:
    with store.tx():
        it = require_issue(store, key)
        kept = [c for c in it["comments"] if str(c["id"]) != comment_id]
        if len(kept) == len(it["comments"]):
            raise SimError(404, [f"Can not find a comment for the id: {comment_id}."])
        it["comments"] = kept


def create_link(store: Store, body: dict[str, Any]) -> None:
    ltype = body.get("type") or {}
    enabled = store.state["config"]["link_types"]
    name = ltype.get("name") or next(
        (t["name"] for t in LINK_TYPES if t["id"] == ltype.get("id")), None
    )
    if name not in enabled:
        shown = ltype.get("name") or ltype.get("id")
        raise SimError(404, [f"No issue link type with name '{shown}' found."])

    def ref(side: str) -> str:
        v = body.get(side) or {}
        it = store.issue(str(v.get("key") or v.get("id") or ""))
        if it is None:
            raise SimError(404, [f"Issue Does Not Exist: {side}"])
        return it["key"]

    with store.tx() as state:
        inward, outward = ref("inwardIssue"), ref("outwardIssue")
        for lk in state["links"]:
            if (lk["type"], lk["inward"], lk["outward"]) == (name, inward, outward):
                return
        state["links"].append(
            {"id": store.next_id(), "type": name, "inward": inward, "outward": outward}
        )
        for k in (inward, outward):
            state["issues"][k]["updated"] = now_jira()
