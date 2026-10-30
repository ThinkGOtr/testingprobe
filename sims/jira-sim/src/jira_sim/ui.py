"""Sunucu tarafında çizilen basit Türkçe arayüz.

Demo sırasında PO bu ekrandan ``po@sim.local`` olarak yorum yazar, etiket ekler/kaldırır ve
gerekirse açıklamayı (kabul kriterleriyle) günceller. Bu işlemler insan onayıdır (anayasa I):
yazma uçları PO girişi (imzalı çerez), formda CSRF belirteci ve aynı köken ister
(bkz. ``jira_sim.security``).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from jira_sim import jql
from jira_sim.adf import adf_to_html, adf_to_text, text_to_adf
from jira_sim.api import get_store
from jira_sim.ops import SimError, add_comment, issue_links, update_issue
from jira_sim.security import SESSION_COOKIE, SimSecurity
from jira_sim.seed import USERS
from jira_sim.store import Store

PO_USER = "po@sim.local"

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
StoreDep = Annotated[Store, Depends(get_store)]


def _local_tz() -> tzinfo:
    """Simülatör kullanıcılarının saat dilimi (``timeZone: Europe/Istanbul``)."""
    try:
        return ZoneInfo("Europe/Istanbul")
    except ZoneInfoNotFoundError:  # tzdata olmayan imaj: İstanbul 2016'dan beri sabit UTC+3
        return timezone(timedelta(hours=3), "+03")


LOCAL_TZ = _local_tz()


def _fmt_time(value: str | None) -> str:
    """Jira zamanını (UTC, ``...+0000``) İstanbul yerel saatiyle ``GG.AA.YYYY SS:DD`` yazar."""
    if not value:
        return ""
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        return value
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(LOCAL_TZ).strftime("%d.%m.%Y %H:%M")


def _display_name(email: str | None) -> str:
    if not email:
        return "—"
    return USERS.get(email, {}).get("displayName", email)


templates.env.filters["zaman"] = _fmt_time
templates.env.filters["kisi"] = _display_name
templates.env.filters["adf"] = adf_to_html


# ------------------------------------------------------------ Türkçe hata metinleri

_FIELD_TR = {"labels": "Etiket", "comment": "Yorum", "description": "Açıklama", "summary": "Özet"}

_SIM_ERRORS_TR: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^Comment body can not be empty!$"), "Yorum boş olamaz."),
    (re.compile(r"^Issue does not exist"), "Kayıt bulunamadı ya da görme yetkiniz yok."),
    (re.compile(r"^The label '(.*)' contains spaces"), "Etiket boşluk içeremez: '{0}'."),
    (re.compile(r"^Labels must be non-empty strings\.$"), "Etiket boş olamaz."),
    (re.compile(r"^The label must not exceed 255"), "Etiket en fazla 255 karakter olabilir."),
    (re.compile(r"Atlassian Document"), "Metin biçimi geçersiz."),
    (re.compile(r"^You must specify a summary"), "Özet boş olamaz."),
]

_JQL_ERRORS_TR: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"the query is incomplete"), "JQL sorgusu eksik."),
    (re.compile(r"unexpected character at position (\d+)"), "{0}. konumda beklenmeyen karakter."),
    (re.compile(r"expecting 'by' after 'order'"), "'order' sonrasında 'by' bekleniyordu."),
    (
        re.compile(r"expecting EMPTY or NULL after 'is'"),
        "'is' sonrasında EMPTY ya da NULL bekleniyordu.",
    ),
    (re.compile(r"expecting a value but got '(.*)'"), "Değer bekleniyordu, '{0}' geldi."),
    (re.compile(r"expecting '(.*)' but got '(.*)'"), "'{0}' bekleniyordu, '{1}' geldi."),
    (re.compile(r"unsupported operator '(.*)'"), "Desteklenmeyen operatör: '{0}'."),
    (re.compile(r"unexpected '(.*)'"), "Beklenmeyen ifade: '{0}'."),
    (re.compile(r"^Field '(.*)' does not support sorting"), "'{0}' alanına göre sıralanamaz."),
    (re.compile(r"^Field '(.*)' does not exist"), "'{0}' alanı yok ya da görme yetkiniz yok."),
    (re.compile(r"^Unable to find JQL function '(.*)'"), "JQL fonksiyonu bulunamadı: '{0}'."),
    (
        re.compile(r"^The operator '(.*)' is not supported by the '(.*)' field"),
        "'{0}' operatörü '{1}' alanında kullanılamaz.",
    ),
]


def _translate(message: str, table: list[tuple[re.Pattern[str], str]], fallback: str) -> str:
    for pattern, text in table:
        if m := pattern.search(message):
            return text.format(*m.groups())
    return fallback


def jql_error_text(message: str) -> str:
    """JQL hata iletisinin Türkçesi (REST API İngilizce iletiyi Jira uyumu için korur)."""
    return _translate(message, _JQL_ERRORS_TR, "JQL sorgusu geçersiz.")


def _error_text(exc: SimError) -> str:
    parts = [_translate(m, _SIM_ERRORS_TR, "İşlem başarısız.") for m in exc.body["errorMessages"]]
    for field, msg in exc.body["errors"].items():
        name = _FIELD_TR.get(field, field)
        parts.append(_translate(msg, _SIM_ERRORS_TR, f"{name} alanı geçersiz."))
    return " ".join(dict.fromkeys(parts)) or "İşlem başarısız."


# ------------------------------------------------------------------- PO oturumu


def _security(request: Request) -> SimSecurity:
    return request.app.state.security


def _base(request: Request) -> str:
    return request.app.state.base_url


def _logged_in(request: Request) -> bool:
    return _security(request).session_nonce(request) is not None


def _page_ctx(request: Request) -> dict[str, Any]:
    return {"po_logged_in": _logged_in(request), "csrf": _security(request).csrf_token(request)}


def _refuse(request: Request, status: int, message: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "refused.html",
        {**_page_ctx(request), "message": message, "title": "İstek reddedildi"},
        status_code=status,
    )


class Refused(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _check_origin(request: Request) -> None:
    sec = _security(request)
    if not sec.host_allowed(request, _base(request)) or not sec.same_origin(
        request, _base(request)
    ):
        raise Refused(403, "İstek reddedildi: başka bir siteden gönderilen form kabul edilmez.")


def require_po(request: Request, csrf: Annotated[str, Form()] = "") -> str:
    """Arayüz yazma uçları: aynı köken + PO oturumu + geçerli CSRF belirteci."""
    _check_origin(request)
    sec = _security(request)
    if sec.session_nonce(request) is None:
        raise Refused(401, "Bu işlem için PO olarak giriş yapmalısınız.")
    if not sec.check_csrf(request, csrf):
        raise Refused(403, "Form süresi dolmuş ya da geçersiz. Sayfayı yenileyip tekrar deneyin.")
    return PO_USER


PoUser = Annotated[str, Depends(require_po)]


def _safe_next(target: str | None) -> str:
    """Girişten sonra yalnızca simülatör içi bir yola dönülür (açık yönlendirme yok)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/"


def adf_to_editable(doc: Any) -> str:
    """ADF → arayüzdeki düzenleme kutusunun metni (``### başlık``, ``- madde``)."""
    blocks: list[str] = []
    for node in (doc or {}).get("content", []) if isinstance(doc, dict) else []:
        kind = node.get("type")
        if kind == "heading":
            level = (node.get("attrs") or {}).get("level", 3)
            blocks.append("#" * int(level) + " " + adf_to_text(node).strip())
        elif kind in ("bulletList", "orderedList"):
            lines = []
            start = (node.get("attrs") or {}).get("order", 1)
            start = start if isinstance(start, int) and start >= 0 else 1
            for i, item in enumerate(node.get("content") or [], start=start):
                text = adf_to_text({"type": "doc", "content": item.get("content") or []})
                prefix = "- " if kind == "bulletList" else f"{i}. "
                lines.append(prefix + " ".join(text.split("\n")).strip())
            blocks.append("\n".join(lines))
        else:
            blocks.append(adf_to_text(node).strip())
    return "\n\n".join(b for b in blocks if b)


FIELD_NAMES = {"labels": "Etiketler", "description": "Açıklama", "summary": "Özet"}


def history_rows(changelog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Değişiklik geçmişi, en yeni önce; etiketler eklenen/kaldırılan olarak gösterilir."""
    rows = []
    for h in reversed(changelog):
        changes = []
        for item in h["items"]:
            if item["field"] == "labels":
                before = set((item.get("fromString") or "").split())
                after = set((item.get("toString") or "").split())
                changes += [f"Etiket eklendi: {lb}" for lb in sorted(after - before)]
                changes += [f"Etiket kaldırıldı: {lb}" for lb in sorted(before - after)]
            else:
                changes.append(f"{FIELD_NAMES.get(item['field'], item['field'])} güncellendi")
        rows.append({"author": h["author"], "created": h["created"], "changes": changes})
    return rows


PO_APPROVED_LABEL = "tp-po-approved"
CONTENT_FIELDS = {"summary", "description"}


def approval_is_stale(changelog: list[dict[str, Any]], label: str = PO_APPROVED_LABEL) -> bool:
    """Onay etiketi son eklendikten *sonra* özet/açıklama değişti mi?

    Çekirdekteki ``RestJira.po_approvals`` ile aynı kural: changelog sırası belirleyicidir;
    etiketin eklendiği düzenlemenin kendisindeki içerik değişikliği onaydan önce sayılır.
    Etiket hiç eklenmediyse ``False`` döner (çağıran etiketin şu an üzerinde olduğunu denetler).
    """
    last_add = -1
    last_content = -1
    for i, h in enumerate(changelog):
        for item in h.get("items") or []:
            field = item.get("field")
            if field == "labels":
                before = set((item.get("fromString") or "").split())
                after = set((item.get("toString") or "").split())
                if label in after and label not in before:
                    last_add = i
            elif field in CONTENT_FIELDS:
                last_content = i
    return last_add >= 0 and last_content > last_add


def _redirect(key: str, anchor: str = "", error: str | None = None) -> RedirectResponse:
    url = f"/browse/{quote(key)}"
    if error:
        url += "?hata=" + quote(error)
    return RedirectResponse(url + (f"#{anchor}" if anchor else ""), status_code=303)


DEFAULT_JQL = "project = TPD ORDER BY key ASC"


async def refused_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, Refused)
    return _refuse(request, exc.status, exc.message)


@router.get("/", response_class=HTMLResponse)
def issue_list(request: Request, store: StoreDep) -> HTMLResponse:
    query = request.query_params.get("jql") or DEFAULT_JQL
    error = None
    rows: list[dict[str, Any]] = []
    try:
        q = jql.parse(query)
        with store.lock:
            docs = [store.search_doc(it) for it in store.state["issues"].values()]
            rows = [
                d["_issue"] for d in jql.sort_docs([d for d in docs if q.predicate(d)], q.order)
            ]
    except jql.JqlError as exc:
        error = jql_error_text(str(exc))
    ctx = {**_page_ctx(request), "rows": rows, "jql": query, "error": error, "title": "Kayıtlar"}
    return templates.TemplateResponse(request, "list.html", ctx)


@router.get("/browse/{key}", response_class=HTMLResponse)
def issue_detail(request: Request, store: StoreDep, key: str) -> HTMLResponse:
    with store.lock:
        it = store.issue(key)
        if it is None:
            return templates.TemplateResponse(
                request,
                "not_found.html",
                {**_page_ctx(request), "key": key, "title": "Kayıt bulunamadı"},
                status_code=404,
            )
        links = issue_links(store, it, "")
        link_rows = []
        for lk in links:
            if "outwardIssue" in lk:
                link_rows.append((lk["type"]["outward"], lk["outwardIssue"]))
            else:
                link_rows.append((lk["type"]["inward"], lk["inwardIssue"]))
        ctx = {
            **_page_ctx(request),
            "it": it,
            "links": link_rows,
            "editable": adf_to_editable(it.get("description")),
            "error": request.query_params.get("hata"),
            "po": PO_USER,
            "title": f"{it['key']} {it['summary']}",
            "history": history_rows(it["changelog"]),
            "approval_stale": PO_APPROVED_LABEL in it.get("labels", [])
            and approval_is_stale(it["changelog"]),
            "here": f"/browse/{quote(it['key'])}",
        }
        return templates.TemplateResponse(request, "issue.html", ctx)


# ------------------------------------------------------------------- giriş / çıkış


@router.get("/giris", response_class=HTMLResponse)
def login_form(request: Request) -> HTMLResponse:
    ctx = {
        **_page_ctx(request),
        "po": PO_USER,
        "sonra": _safe_next(request.query_params.get("sonra")),
        "error": None,
        "title": "PO girişi",
    }
    return templates.TemplateResponse(request, "login.html", ctx)


@router.post("/giris", response_model=None)
def login(
    request: Request,
    password: Annotated[str, Form()] = "",
    sonra: Annotated[str, Form()] = "/",
) -> Response:
    _check_origin(request)
    target = _safe_next(sonra)
    if not _security(request).check_po_password(password):
        ctx = {
            **_page_ctx(request),
            "po": PO_USER,
            "sonra": target,
            "error": "Parola hatalı.",
            "title": "PO girişi",
        }
        return templates.TemplateResponse(request, "login.html", ctx, status_code=401)
    resp = RedirectResponse(target, status_code=303)
    resp.set_cookie(
        SESSION_COOKIE,
        _security(request).new_session(),
        httponly=True,
        samesite="strict",
        path="/",
        max_age=int(_security(request).session_ttl_s),
    )
    return resp


@router.post("/cikis")
def logout(request: Request, _: PoUser) -> RedirectResponse:
    _security(request).end_session(request)
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


# ------------------------------------------------------------------ PO işlemleri


@router.post("/browse/{key}/comment")
def ui_comment(
    store: StoreDep, key: str, po: PoUser, body: Annotated[str, Form()] = ""
) -> RedirectResponse:
    try:
        add_comment(store, key, text_to_adf(body), po)
    except SimError as exc:
        return _redirect(key, "yorumlar", _error_text(exc))
    return _redirect(key, "yorumlar")


@router.post("/browse/{key}/labels")
def ui_labels(
    store: StoreDep,
    key: str,
    po: PoUser,
    action: Annotated[str, Form()] = "add",
    label: Annotated[str, Form()] = "",
) -> RedirectResponse:
    label = label.strip()
    if not label:
        return _redirect(key, "etiketler", "Etiket boş olamaz.")
    op = "remove" if action == "remove" else "add"
    try:
        update_issue(store, key, {"update": {"labels": [{op: label}]}}, po)
    except SimError as exc:
        return _redirect(key, "etiketler", _error_text(exc))
    return _redirect(key, "etiketler")


@router.post("/browse/{key}/reapprove")
def ui_reapprove(store: StoreDep, key: str, po: PoUser) -> RedirectResponse:
    """Bayat onayı yenile: etiketi kaldırıp yeniden ekler (iki changelog kaydı, PO adına).

    Kaldırma + ekleme tek ``update`` içinde etiket kümesini değiştirmez (changelog kaydı
    oluşmaz); bu yüzden iki ayrı düzenleme yazılır ve yeni ekleme içerik değişikliğinden
    sonra gelir. Dış işlem ikisini birlikte uygular ya da hiçbirini (araya yazma giremez).
    """
    try:
        with store.tx():
            update_issue(store, key, {"update": {"labels": [{"remove": PO_APPROVED_LABEL}]}}, po)
            update_issue(store, key, {"update": {"labels": [{"add": PO_APPROVED_LABEL}]}}, po)
    except SimError as exc:
        return _redirect(key, "po", _error_text(exc))
    return _redirect(key, "po")


@router.post("/browse/{key}/description")
def ui_description(
    store: StoreDep, key: str, po: PoUser, text: Annotated[str, Form()] = ""
) -> RedirectResponse:
    try:
        update_issue(store, key, {"fields": {"description": text_to_adf(text)}}, po)
    except SimError as exc:
        return _redirect(key, "aciklama", _error_text(exc))
    return _redirect(key, "aciklama")
