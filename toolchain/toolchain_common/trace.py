"""Playwright `trace.zip`'ten güvenli, model-siz özet (TEKNIK-TASARIM §8.6 kanıt, §8.7 alternatif).

§8.7: aria snapshot `data-testid` taşımaz; testId çalışan uygulamada (`/locator-probe`) ya da
**trace.zip içindeki DOM snapshot'ından** okunur. Bu modül ikincisini yapar: koşu yeniden
çalıştırılmadan, başarısız eylemin anındaki DOM'dan `data-testid`'li elemanları, kapsayıcı
zincirlerini ve (yaklaşık) rol + adlarını çıkarır.

**Güvenlik:** trace, commit'ten gelen test kodunun ürettiği güvenilmeyen veridir.
- Zip diske açılmaz; yalnızca `*.trace` üyeleri bellekte, boyut sınırıyla okunur
  (üye sayısı, üye boyutu, sıkıştırma oranı, satır sayısı sınırlı; zip bombası reddedilir).
- DOM snapshot'ı Playwright'ın sıkıştırılmış biçimidir (`[[geri, düğüm]]` önceki snapshot'a
  başvurur); çözümleme derinlik ve düğüm bütçesiyle, döngüye karşı korumalı yapılır.
- Çıktıdaki tüm metinler kırpılır; HTML hiçbir zaman yorumlanmaz/çalıştırılmaz.

Rol + ad hesaplaması **yaklaşıktır** (örtük rol tablosu + aria-label/labelledby/label[for]/metin);
tarayıcının erişilebilirlik ağacı değildir. Karar core'undur; bu yalnızca girdi üretir.
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any

from toolchain_common.aria import AriaSourceError, resolve_artifact

MAX_ZIP_BYTES = 200 * 1024 * 1024
MAX_MEMBERS = 5_000
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_RATIO = 200  # açılmış / sıkıştırılmış
MAX_LINES = 200_000
MAX_ACTIONS = 200
MAX_ELEMENTS = 500
MAX_NODES = 100_000
MAX_DEPTH = 256
MAX_TEXT = 120

_TESTID_SEL_RE = re.compile(r"""internal:testid=\[([\w-]+)=\\?"((?:[^"\\]|\\.)*)\\?"[si]?\]""")
_WS = re.compile(r"\s+")


class TraceError(ValueError):
    """Trace okunamadı ya da güvenlik sınırını aştı."""


def _clip(text: Any, limit: int = MAX_TEXT) -> str:
    s = _WS.sub(" ", str(text or "")).strip()
    return s if len(s) <= limit else s[:limit] + "…"


# ------------------------------------------------------------------------------ zip okuma


def read_trace_members(path: Path) -> dict[str, list[dict[str, Any]]]:
    """`*.trace` üyelerini NDJSON olayları olarak döner (üye adı → olay listesi)."""
    try:
        size = path.lstat().st_size
    except OSError as exc:
        raise TraceError(f"trace okunamadı: {exc}") from exc
    if path.is_symlink() or not path.is_file():
        raise TraceError("trace düzenli bir dosya değil")
    if size > MAX_ZIP_BYTES:
        raise TraceError("trace çok büyük")
    out: dict[str, list[dict[str, Any]]] = {}
    lines_total = 0
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_MEMBERS:
                raise TraceError("trace'te çok fazla üye var")
            for info in infos:
                name = info.filename
                if info.is_dir() or not name.endswith(".trace") or "/" in name or "\\" in name:
                    continue
                if info.file_size > MAX_MEMBER_BYTES:
                    raise TraceError(f"trace üyesi çok büyük: {name[:80]}")
                if info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
                    raise TraceError("trace sıkıştırma oranı şüpheli (zip bombası?)")
                with zf.open(info) as fh:
                    data = fh.read(MAX_MEMBER_BYTES + 1)
                if len(data) > MAX_MEMBER_BYTES:
                    raise TraceError(f"trace üyesi çok büyük: {name[:80]}")
                events: list[dict[str, Any]] = []
                for raw in data.decode("utf-8", "replace").splitlines():
                    lines_total += 1
                    if lines_total > MAX_LINES:
                        raise TraceError("trace'te çok fazla olay var")
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        ev = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(ev, dict):
                        events.append(ev)
                out[name[:200]] = events
    except zipfile.BadZipFile as exc:
        raise TraceError("trace geçerli bir zip değil") from exc
    except (OSError, RuntimeError, NotImplementedError) as exc:
        raise TraceError(f"trace okunamadı: {exc}") from exc
    return out


# -------------------------------------------------------------------- DOM snapshot çözümü


def _is_element(n: Any) -> bool:
    return isinstance(n, list) and bool(n) and isinstance(n[0], str)


def _is_ref(n: Any) -> bool:
    return (
        isinstance(n, list)
        and len(n) == 1
        and isinstance(n[0], list)
        and len(n[0]) == 2
        and all(isinstance(x, int) for x in n[0])
    )


class _FrameSnapshots:
    """Bir çerçevenin snapshot dizisi ve Playwright başvuru çözümü (snapshotRenderer ile aynı)."""

    def __init__(self, snapshots: list[dict[str, Any]]) -> None:
        self.snapshots = snapshots
        self._nodes: dict[int, list[Any]] = {}
        self.budget = MAX_NODES
        self.partial = False

    def nodes(self, idx: int) -> list[Any]:
        """Snapshot'ın düğümleri, post-order (metin + eleman; başvurular sayılmaz)."""
        if idx in self._nodes:
            return self._nodes[idx]
        out: list[Any] = []
        stack: list[tuple[Any, bool]] = [(self.snapshots[idx].get("html"), False)]
        while stack:
            n, done = stack.pop()
            if isinstance(n, str):
                out.append(n)
            elif _is_element(n):
                if done:
                    out.append(n)
                else:
                    stack.append((n, True))
                    kids = n[2:] if len(n) > 2 and isinstance(n[1], dict) else n[1:]
                    for child in reversed(kids):
                        stack.append((child, False))
            if len(out) > MAX_NODES:
                self.partial = True
                break
        self._nodes[idx] = out
        return out

    def resolve(self, n: Any, idx: int, depth: int = 0) -> Any:
        """Başvuruları açılmış ağaç: str | [TAG, attrs, *children] (bütçe/derinlik sınırlı)."""
        self.budget -= 1
        if self.budget < 0 or depth > MAX_DEPTH:
            self.partial = True
            return None
        if isinstance(n, str):
            return n
        if _is_ref(n):
            back, node_idx = n[0]
            ref = idx - back
            if back < 1 or ref < 0:  # aynı snapshot'a başvuru → döngü olabilir; yok say
                self.partial = True
                return None
            nodes = self.nodes(ref)
            if not 0 <= node_idx < len(nodes):
                self.partial = True
                return None
            return self.resolve(nodes[node_idx], ref, depth + 1)
        if _is_element(n):
            attrs = n[1] if len(n) > 1 and isinstance(n[1], dict) else {}
            kids = n[2:] if len(n) > 1 and isinstance(n[1], dict) else n[1:]
            out = [n[0], attrs]
            for child in kids:
                r = self.resolve(child, idx, depth + 1)
                if r is not None:
                    out.append(r)
            return out
        return None


# ------------------------------------------------------------------------- rol + ad (yaklaşık)

_INPUT_ROLES = {
    "number": "spinbutton",
    "checkbox": "checkbox",
    "radio": "radio",
    "range": "slider",
    "button": "button",
    "submit": "button",
    "reset": "button",
    "image": "button",
    "search": "searchbox",
}
_TAG_ROLES = {
    "BUTTON": "button",
    "ARTICLE": "article",
    "ASIDE": "complementary",
    "DIALOG": "dialog",
    "FORM": "form",
    "H1": "heading",
    "H2": "heading",
    "H3": "heading",
    "H4": "heading",
    "H5": "heading",
    "H6": "heading",
    "HR": "separator",
    "IMG": "img",
    "LI": "listitem",
    "MAIN": "main",
    "NAV": "navigation",
    "OL": "list",
    "UL": "list",
    "OPTION": "option",
    "P": "paragraph",
    "PROGRESS": "progressbar",
    "SECTION": "region",
    "SELECT": "combobox",
    "TABLE": "table",
    "TBODY": "rowgroup",
    "THEAD": "rowgroup",
    "TD": "cell",
    "TH": "columnheader",
    "TR": "row",
    "TEXTAREA": "textbox",
    "HEADER": "banner",
    "FOOTER": "contentinfo",
}
_NAME_FROM_CONTENT = {
    "button",
    "link",
    "heading",
    "cell",
    "columnheader",
    "row",
    "option",
    "listitem",
    "tab",
    "menuitem",
    "checkbox",
    "radio",
    "status",
    "alert",
    "paragraph",
}


def _attrs(el: list[Any]) -> dict[str, str]:
    a = el[1] if len(el) > 1 and isinstance(el[1], dict) else {}
    return {str(k): str(v) for k, v in a.items() if isinstance(k, str)}


def _children(el: list[Any]) -> list[Any]:
    return el[2:]


def _text(el: Any) -> str:
    if isinstance(el, str):
        return el
    if not _is_element(el):
        return ""
    tag = el[0].upper()
    if tag in ("SCRIPT", "STYLE", "TEMPLATE", "NOSCRIPT"):
        return ""
    if _attrs(el).get("aria-hidden") == "true":
        return ""
    return " ".join(_text(c) for c in _children(el))


def _role(el: list[Any]) -> str | None:
    a = _attrs(el)
    if a.get("role"):
        return a["role"].split()[0].lower()
    tag = el[0].upper()
    if tag == "A":
        return "link" if "href" in a else None
    if tag == "INPUT":
        t = a.get("type", "text").lower()
        if t == "hidden":
            return None
        return _INPUT_ROLES.get(t, "textbox")
    return _TAG_ROLES.get(tag)


# ------------------------------------------------------------------------------- özet


def _selector_test_ids(selector: str) -> list[str]:
    return [m.group(2) for m in _TESTID_SEL_RE.finditer(selector or "")][:10]


def _dom_elements(root: Any, testid_attr: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(testId'li elemanlar, rol taşıyan tüm elemanlar) — kapsayıcı testId zinciriyle."""
    by_id: dict[str, list[Any]] = {}
    labels: dict[str, str] = {}

    def index(n: Any) -> None:
        if not _is_element(n):
            return
        a = _attrs(n)
        if a.get("id"):
            by_id.setdefault(a["id"], n)
        if n[0].upper() == "LABEL" and a.get("for"):
            labels.setdefault(a["for"], _clip(_text(n)))
        for c in _children(n):
            index(c)

    index(root)

    def name_of(el: list[Any], role: str | None) -> str:
        a = _attrs(el)
        if a.get("aria-label"):
            return _clip(a["aria-label"])
        if a.get("aria-labelledby"):
            parts = [_text(by_id[i]) for i in a["aria-labelledby"].split() if i in by_id]
            if parts:
                return _clip(" ".join(parts))
        if el[0].upper() in ("INPUT", "SELECT", "TEXTAREA") and a.get("id") in labels:
            return labels[a["id"]]
        if role in _NAME_FROM_CONTENT:
            return _clip(_text(el))
        if el[0].upper() == "IMG" and a.get("alt"):
            return _clip(a["alt"])
        return _clip(a.get("title", ""))

    with_testid: list[dict[str, Any]] = []
    with_role: list[dict[str, Any]] = []

    def walk(n: Any, scopes: list[str], hidden: bool) -> None:
        if not _is_element(n):
            return
        a = _attrs(n)
        hidden = hidden or a.get("aria-hidden") == "true" or "hidden" in a
        tid = a.get(testid_attr)
        role = None if hidden else _role(n)
        entry = None
        if tid is not None or role is not None:
            entry = {
                "test_id": _clip(tid, 200) if tid is not None else None,
                "tag": n[0].lower()[:20],
                "rol": role,
                "ad": name_of(n, role) if role else None,
                "kapsam_test_ids": list(scopes[-5:]),
            }
        if entry is not None and tid is not None and len(with_testid) < MAX_ELEMENTS:
            with_testid.append(entry)
        if entry is not None and role is not None and len(with_role) < MAX_ELEMENTS * 4:
            with_role.append(entry)
        child_scopes = [*scopes, _clip(tid, 200)] if tid is not None else scopes
        for c in _children(n):
            walk(c, child_scopes, hidden)

    walk(root, [], False)
    return with_testid, with_role


def _name_match(have: str | None, want: str) -> bool:
    return _clip(want, 10_000).casefold() in _clip(have or "", 10_000).casefold()


def summarize_trace(
    path: Path,
    *,
    role: str | None = None,
    name: str | None = None,
    scope_test_id: str | None = None,
) -> dict[str, Any]:
    """Eylemler, başarısız eylem ve o anki DOM'dan testId'li elemanlar (+ rol/ad araması)."""
    members = read_trace_members(path)
    testid_attr = "data-testid"
    actions: list[dict[str, Any]] = []
    failed: dict[str, Any] | None = None
    frames: dict[str, list[dict[str, Any]]] = {}
    snap_pos: dict[str, tuple[str, int, str]] = {}  # callId → (frameId, index, phase)
    logs: dict[str, list[str]] = {}
    for member, events in sorted(members.items()):
        before: dict[str, dict[str, Any]] = {}
        for ev in events:
            t = ev.get("type")
            if t == "context-options" and isinstance(ev.get("testIdAttributeName"), str):
                testid_attr = ev["testIdAttributeName"][:50]
            elif t == "before":
                cid = str(ev.get("callId") or "")
                params = ev.get("params") if isinstance(ev.get("params"), dict) else {}
                sel = params.get("selector") if isinstance(params.get("selector"), str) else None
                before[cid] = {
                    "call_id": cid[:60],
                    "uye": member,
                    "sinif": _clip(ev.get("class"), 40),
                    "metot": _clip(ev.get("method") or ev.get("apiName"), 60),
                    "secici": _clip(sel, 400) if sel else None,
                    "secici_test_ids": _selector_test_ids(sel or ""),
                    "hata": None,
                }
                if len(actions) < MAX_ACTIONS:
                    actions.append(before[cid])
            elif t == "after":
                cid = str(ev.get("callId") or "")
                err = ev.get("error")
                if cid in before and isinstance(err, dict):
                    before[cid]["hata"] = _clip(err.get("message"), 300)
                    if failed is None or before[cid]["secici"]:
                        failed = before[cid]
            elif t == "log":
                cid = str(ev.get("callId") or "")
                lst = logs.setdefault(cid, [])
                if len(lst) < 20:
                    lst.append(_clip(ev.get("message"), 300))
            elif t == "frame-snapshot" and isinstance(ev.get("snapshot"), dict):
                snap = ev["snapshot"]
                fid = f"{member}:{snap.get('frameId')}"
                lst = frames.setdefault(fid, [])
                lst.append(snap)
                cid = str(snap.get("callId") or "")
                if cid and snap.get("isMainFrame", True):
                    # Aynı eylemin son snapshot'ı (after > action > before) kalır.
                    snap_pos[cid] = (fid, len(lst) - 1, str(snap.get("phase") or ""))

    out: dict[str, Any] = {
        "test_id_ozniteligi": testid_attr,
        "uyeler": sorted(members)[:20],
        "eylemler": actions,
        "basarisiz_eylem": None,
        "dom": None,
        "rol_ad": None,
    }
    if failed is not None:
        out["basarisiz_eylem"] = {**failed, "log": logs.get(failed["call_id"], [])}

    target_cid = failed["call_id"] if failed else (actions[-1]["call_id"] if actions else None)
    pos = snap_pos.get(target_cid or "")
    if pos is None and frames:
        # Başarısız eylemin snapshot'ı yoksa son ana çerçeve snapshot'ı.
        fid = next(reversed(frames))
        pos = (fid, len(frames[fid]) - 1, str(frames[fid][-1].get("phase") or ""))
    if pos is None:
        return out
    fid, idx, phase = pos
    fs = _FrameSnapshots(frames[fid])
    root = fs.resolve(frames[fid][idx].get("html"), idx)
    with_testid, with_role = _dom_elements(root, testid_attr) if root is not None else ([], [])
    snap = frames[fid][idx]
    out["dom"] = {
        "call_id": _clip(snap.get("callId"), 60),
        "faz": phase,
        "cerceve_url": _clip(snap.get("frameUrl"), 300),
        "kismi": fs.partial,
        "elemanlar": with_testid,
        "yaklasik": True,
    }
    if role:
        hits = [
            e
            for e in with_role
            if e["rol"] == role
            and (name is None or _name_match(e["ad"], name))
            and (scope_test_id is None or scope_test_id in e["kapsam_test_ids"])
        ]
        ids = [e["test_id"] for e in hits]
        out["rol_ad"] = {
            "rol": role,
            "ad": name,
            "scope_test_id": scope_test_id,
            "eslesen": len(hits),
            "test_ids": ids[:20],
            "test_id": ids[0] if len(hits) == 1 else None,
            "yaklasik": True,
        }
    return out


def load_and_summarize(
    artifacts: Path,
    rel: str,
    *,
    role: str | None = None,
    name: str | None = None,
    scope_test_id: str | None = None,
) -> dict[str, Any]:
    try:
        p = resolve_artifact(artifacts, rel, suffixes=(".zip",))
    except AriaSourceError as exc:
        raise TraceError(str(exc)) from exc
    if not p.exists():
        raise TraceError("trace dosyası yok")
    return {
        "trace_rel": rel,
        **summarize_trace(p, role=role, name=name, scope_test_id=scope_test_id),
    }
