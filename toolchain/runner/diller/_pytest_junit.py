"""pytest JUnit XML (xunit2) özeti — Python hattı (Ş1; TASARIM §3.1).

Çıktı `runner.results.summarize` / `runner.surefire.summarize` ile AYNI biçimdedir
(`{stats, tests, errors}`; test girdisi ve `failure` alanları aynı adlarla). Rapor test kodunun
çıktısıdır (güvenilmeyen veri): ayrıştırma `surefire.parse_xml` ile (DTD/varlık yok, boyut sınırı),
metinler kırpılır, kanıt yolları yalnız kanıt dizini içindeyse döner.

**Hata türü** (`failure.type`, `results.FAILURE_TYPES` kümesi; sıra önemlidir):

- `other` + ortam sinyali — Appium/HTTP bağlantısı (ConnectionError, URLError, MaxRetryError,
  "Could not start a new session", SessionNotCreatedException)
- `test_data` — hazırlık (`/test/reset|break`, giriş, sepet boşaltma, token) ya da pytest
  `<error message="failed on setup …">` (fikstür hazırlığı)
- `navigation` — net::ERR_…, `Page.goto:`
- `locator_ambiguous` — strict mode violation
- `locator_not_found` — "element(s) not found", Selenium/Appium `NoSuchElementException`,
  `TimeoutException` + "öğe görünmedi"
- `locator_timeout` — Playwright `TimeoutError` + "waiting for", diğer `TimeoutException`
- `assertion` — `AssertionError` (Playwright `expect` dahil: "Locator expected to …"); kırarak
  doğrulamada kırmızı SAYILAN tek tür
- `other`

Kanıt: `<kanit>/<test işlevi>/{ekran.png, sayfa.html, sayfa-kaynagi.xml, trace.zip}` (demo
`conftest.py` `TP_KANIT_DIZINI`'ne yazar); yoksa pytest-playwright `--output` dizinindeki
`<nodeid-slug>/trace.zip` ve `test-failed-*.png`.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runner.results import (
    _NAV_RE,
    _TEST_DATA_RE,
    MAX_ERROR,
    MAX_FIELD,
    MAX_TESTS,
    _clip,
)
from runner.surefire import (
    _DOGRULA_RE,
    _KIMLIK_RE,
    _KURULUM_EK_RE,
    _KURULUM_RE,
    MAX_XML_FILES,
    parse_xml,
)

JUNIT_NAME = "TEST-pytest.xml"
# "E   playwright._impl._errors.TimeoutError: Locator.click: Timeout 30000ms exceeded."
_EXC_LINE_RE = re.compile(r"^E\s+([A-Za-z_][\w.]*(?:Error|Exception|Exit|Failure|Warning)):", re.M)
_EXC_HEAD_RE = re.compile(r"\A\s*([A-Za-z_][\w.]*(?:Error|Exception|Exit|Failure)):")
_PY_TESTID_RE = re.compile(r"""get_by_test_id\(\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')""")
_PW_ATTR_TESTID_RE = re.compile(r"""internal:testid=\[data-testid=\\?["']([^"'\\\]]+)""")
_PY_ROLE_RE = re.compile(
    r"""get_by_role\(\s*["'](\w+)["'](?:\s*,\s*name\s*=\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'))?"""
)
_PY_WAITING_RE = re.compile(
    r"waiting for ((?:get_by|locator\(|frame_locator\(|internal:)\S.*?)\s*$", re.M
)
_PY_EXPECTED_RE = re.compile(
    r"expected to (?:have|contain|be)(?: \w+)*? (?:text|value|count|title|URL|url|attribute)?"
    r"\s*'(.*?)'\s*$",
    re.M,
)
_PY_ACTUAL_RE = re.compile(r"^\s*Actual value:\s*(.*?)\s*$", re.M)
_PW_TIMEOUT_RE = re.compile(r"Timeout (\d+)\s*ms exceeded|with timeout (\d+)\s*ms")
_PY_ACTION_RE = re.compile(r"\b((?:Locator|Page|Frame)\.[a-z_]+):")
_ENV_RE = re.compile(
    r"ConnectionError|ConnectionRefused|URLError|MaxRetryError|NewConnectionError"
    r"|Could not start a new session|SessionNotCreated|Connection refused|Name or service not known"
)
_SETUP_RE = re.compile(r"\Afailed on setup\b|\Aerror at setup\b", re.I)
# pytest izi: "tests/generated/test_x.py:12: in test_x" / "pages/cart_page.py:30: AssertionError"
_PY_FRAME_RE = re.compile(r"^((?:[\w.-]+/)*[\w.-]+\.py):(\d+):", re.M)
_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")
EVIDENCE_FILES = (
    ("screenshot", "ekran.png"),
    ("page_html", "sayfa.html"),
    ("page_source", "sayfa-kaynagi.xml"),
    ("trace", "trace.zip"),
)


@dataclass(frozen=True)
class Repeat:
    """Bir tekrarın JUnit dizini (`TEST-pytest.xml`), kanıt dizini ve pytest-playwright çıktısı."""

    index: int
    reports_dir: Path
    kanit_dir: Path
    pw_output: Path | None = None


def exception_of(message: str, body: str) -> str:
    m = _EXC_HEAD_RE.match(message) or _EXC_LINE_RE.search(body)
    if m:
        return m.group(1)
    if message.lstrip().startswith("assert ") or "\nE       assert " in body:
        return "AssertionError"
    return ""


def _locator_ids(text: str) -> dict[str, Any]:
    ids = [a or b for a, b in _PY_TESTID_RE.findall(text)][:10]
    if not ids:
        ids = _PW_ATTR_TESTID_RE.findall(text)[:10]
    role = _PY_ROLE_RE.search(text)
    return {
        "locator_test_ids": ids,
        "locator_test_id": ids[-1] if ids else None,
        "locator_scope_test_id": ids[-2] if len(ids) > 1 else None,
        "locator_role": role.group(1).lower() if role else None,
        "locator_name": (role.group(2) or role.group(3) or None) if role else None,
    }


def classify(tag: str, message: str, body: str) -> dict[str, Any]:
    """Tek `<failure|error>` → biçimsel tür + çıkarılan alanlar (bkz. modül belgesi)."""
    text = f"{message}\n{body}"
    exc = exception_of(message, body)
    simple = exc.rsplit(".", 1)[-1]
    signals: list[str] = []
    waiting = _PY_WAITING_RE.search(text)
    locator = waiting.group(1) if waiting else None
    ids = _locator_ids(locator or text)
    kimlik = _KIMLIK_RE.search(text)
    if kimlik and ids["locator_test_id"] is None:
        k, scope = (
            (kimlik.group(2), kimlik.group(1)) if kimlik.group(2) else (kimlik.group(1), None)
        )
        ids.update(
            locator_test_ids=[x for x in (scope, k) if x], locator_test_id=k,
            locator_scope_test_id=scope,
        )  # fmt: skip
        locator = locator or kimlik.group(0)
    expected = received = None
    d = _DOGRULA_RE.search(text)
    if d:
        expected, received = d.group(1), d.group(2)
    else:
        e = _PY_EXPECTED_RE.search(text)
        a = _PY_ACTUAL_RE.search(text)
        expected = e.group(1) if e else None
        received = a.group(1) if a else None
    tm = _PW_TIMEOUT_RE.search(text)
    timeout_ms = int(next(g for g in tm.groups() if g)) if tm else None
    act = _PY_ACTION_RE.search(message) or _PY_ACTION_RE.search(body)
    action = act.group(1) if act else None
    setup = tag == "error" and bool(_SETUP_RE.match(message))
    is_assertion = simple == "AssertionError"
    if _ENV_RE.search(text):
        kind = "other"
        signals.append("ortam: bağlantı kurulamadı (Appium/demo API)")
    elif (
        _TEST_DATA_RE.search(text)
        or _KURULUM_RE.search(message)
        or _KURULUM_EK_RE.search(text)
        or setup
    ):
        kind = "test_data"
        signals.append("veri hazırlığı (/test/*, giriş, fikstür) başarısız")
    elif _NAV_RE.search(text) or "Page.goto:" in text:
        kind = "navigation"
        signals.append("sayfa yüklenemedi / gezinme hatası")
    elif "strict mode violation" in text:
        kind = "locator_ambiguous"
        signals.append("strict mode: locator birden çok elemana çözüldü")
    elif (
        "element(s) not found" in text
        or simple == "NoSuchElementException"
        or (simple == "TimeoutException" and "öğe görünmedi" in text)
    ):
        kind = "locator_not_found"
        signals.append("öğe bulunamadı")
    elif (simple == "TimeoutError" and waiting) or simple == "TimeoutException":
        kind = "locator_timeout"
        signals.append(f"{action or 'eylem'}: locator beklenirken zaman aşımı")
    elif is_assertion:
        kind = "assertion"
        signals.append("beklenen ≠ gerçekleşen")
    else:
        kind = "other"
    first = next((ln.strip() for ln in message.splitlines() if ln.strip()), "") or simple
    return {
        "type": kind,
        "first_line": _clip(first, MAX_FIELD),
        "matcher": None,
        "action": action,
        "exception": _clip(exc, 200) or None,
        "locator": _clip(locator, MAX_FIELD) if locator else None,
        **ids,
        "expected": _clip(expected, MAX_FIELD) if expected is not None else None,
        "received": _clip(received, MAX_FIELD) if received is not None else None,
        "timeout_ms": timeout_ms,
        "signals": signals,
    }


def src_file(classname: str) -> str:
    """`tests.generated.test_x` → `tests/generated/test_x.py` (nodeid'den türetilmiş)."""
    if not re.fullmatch(r"[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*", classname or ""):
        return _clip(classname, MAX_FIELD)
    return classname.replace(".", "/") + ".py"


def _frames(body: str) -> list[dict[str, Any]]:
    return [
        {"file": m.group(1), "line": int(m.group(2)), "column": 0}
        for m in _PY_FRAME_RE.finditer(body)
        if not m.group(1).startswith("/") and ".." not in m.group(1)
    ]


def _safe_file(base: Path, p: Path, rel_root: Path | None) -> dict[str, Any] | None:
    try:
        ok = (
            p.is_file()
            and not p.is_symlink()
            and not base.is_symlink()
            and base.resolve() in p.resolve().parents
        )
    except OSError:
        return None
    if not ok:
        return None
    rel = None
    if rel_root is not None:
        try:
            rel = str(p.resolve().relative_to(rel_root.resolve()))
        except ValueError:
            return None
    return {"path": str(p), "rel": rel, "exists": True}


def evidence(rep: Repeat, func: str, rel_root: Path | None) -> dict[str, Any]:
    out: dict[str, Any] = {"trace": None, "error_context": None, "screenshot": None,
                           "video": None, "page_source": None, "page_html": None}  # fmt: skip
    base = rep.kanit_dir / _SAFE_RE.sub("_", func)
    for key, name in EVIDENCE_FILES:
        out[key] = _safe_file(rep.kanit_dir, base / name, rel_root)
    if rep.pw_output is not None and rep.pw_output.is_dir() and not rep.pw_output.is_symlink():
        slug = func.replace("_", "-").lower()
        for d in sorted(rep.pw_output.iterdir()):
            if not d.is_dir() or d.is_symlink() or slug not in d.name.lower():
                continue
            if out["trace"] is None:
                out["trace"] = _safe_file(rep.pw_output, d / "trace.zip", rel_root)
            if out["screenshot"] is None:
                shots = sorted(d.glob("test-failed-*.png"))
                if shots:
                    out["screenshot"] = _safe_file(rep.pw_output, shots[0], rel_root)
            break
    return out


def _result_child(tc: ET.Element) -> ET.Element | None:
    found = None
    for child in tc:
        if child.tag in ("failure", "error"):
            return child  # çağrı hatası kurulum/teardown hatasından önce gelir
        if child.tag == "skipped":
            found = child
    return found


def _testcases(reports_dir: Path) -> tuple[list[ET.Element], list[str]]:
    if not reports_dir.is_dir() or reports_dir.is_symlink():
        return [], ["pytest rapor dizini yok"]
    files = sorted(reports_dir.glob("TEST-*.xml"))[:MAX_XML_FILES]
    if not files:
        return [], ["pytest JUnit XML'i üretilmedi"]
    cases: list[ET.Element] = []
    errors: list[str] = []
    for f in files:
        try:
            root = parse_xml(f)
        except (OSError, ValueError) as exc:
            errors.append(_clip(f"{f.name}: {exc}", MAX_ERROR))
            continue
        cases.extend(root.iter("testcase"))
    return cases, errors


def summarize(
    repeats: list[Repeat], *, project: str, rel_root: Path | None = None
) -> dict[str, Any]:
    tests: list[dict[str, Any]] = []
    errors: list[str] = []
    stats = {"expected": 0, "unexpected": 0, "flaky": 0, "skipped": 0, "duration_ms": 0}
    for rep in repeats:
        cases, errs = _testcases(rep.reports_dir)
        errors += [f"tekrar {rep.index + 1}: {e}" if len(repeats) > 1 else e for e in errs]
        seen: dict[str, int] = {}
        for tc in cases:
            if len(tests) >= MAX_TESTS:
                break
            classname = _clip(tc.get("classname"), MAX_FIELD)
            name = _clip(tc.get("name"), MAX_FIELD)
            func = name.split("[", 1)[0]
            try:
                duration = int(float(tc.get("time") or 0) * 1000)
            except ValueError:
                duration = 0
            file = src_file(classname)
            child = _result_child(tc)
            status, error, failure, kind = "expected", None, None, None
            if child is not None and child.tag == "skipped":
                status = "skipped"
            elif child is not None:
                status = "unexpected"
                message = _clip(child.get("message"), MAX_ERROR)
                body = _clip((child.text or "").strip(), 8000)
                info = classify(child.tag, message, body)
                frames = _frames(body)
                test_loc = next((f for f in frames if f["file"] == file), None)
                page_loc = next(
                    (f for f in reversed(frames)
                     if f["file"].startswith(("pages/", "ekranlar/"))), None,
                )  # fmt: skip
                ev = evidence(rep, func, rel_root)
                error = message or info["exception"] or child.tag
                kind = info["type"]
                failure = {
                    **info,
                    "message": _clip(message or body[:MAX_ERROR]),
                    "messages": [],
                    "location": page_loc or test_loc,
                    "test_location": test_loc,
                    "step": None,
                    "attempt": 0,
                    "status": "failed",
                    "evidence": ev,
                    "aria_snapshot": None,
                    "aria_snapshot_scope": None,
                    "aria_snapshot_rel": None,
                    "page_source_rel": (ev.get("page_source") or {}).get("rel"),
                    "page_html_rel": (ev.get("page_html") or {}).get("rel"),
                    "trace_rel": (ev.get("trace") or {}).get("rel"),
                    "page_location": page_loc,
                }
            stats[status] += 1
            stats["duration_ms"] += duration
            base_id = f"{classname}.{name}#{rep.index}"
            n = seen.get(base_id, 0)
            seen[base_id] = n + 1
            tests.append(
                {
                    "id": _clip(base_id + (f".{n}" if n else ""), 200),
                    "title": f"{classname.rsplit('.', 1)[-1]} › {name}",
                    "file": file,
                    "line": 0,
                    "column": 0,
                    "project": project,
                    "status": status,
                    "tags": [],
                    "attempts": 1,
                    "attempt_results": [
                        {
                            "retry": 0,
                            "status": {"expected": "passed", "unexpected": "failed"}.get(
                                status, status
                            ),
                            "duration_ms": duration,
                            "type": kind,
                        }
                    ],
                    "duration_ms": duration,
                    "error": error,
                    "failure": failure,
                    "attachments": [],
                    "repeat_index": rep.index,
                }
            )
    return {"stats": stats, "tests": tests, "errors": errors[:20]}
