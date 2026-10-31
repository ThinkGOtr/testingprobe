"""Playwright JSON raporunun (`results.json`) özeti: sayılar ve test bazında sonuç.

Rapor test kodunun çıktısıdır (güvenilmeyen veri): yalnızca bilinen alanlar okunur, metinler
kırpılır ve ANSI kaçışları silinir. Ek yolları yalnızca koşu dizini içindeyse döner.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
MAX_ERROR = 2000
MAX_TESTS = 500


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _clip(text: Any, limit: int = MAX_ERROR) -> str:
    s = strip_ansi(str(text or ""))
    return s if len(s) <= limit else s[:limit] + "…"


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _attachment_path(raw: Any, base: Path) -> str | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        p = Path(raw).resolve()
        b = base.resolve()
    except (OSError, RuntimeError):
        return None
    return str(p) if b in p.parents else None


def _walk(suite: dict[str, Any], titles: list[str], out: list[dict[str, Any]], base: Path) -> None:
    title = suite.get("title")
    here = [*titles, title] if isinstance(title, str) and title else titles
    for spec in suite.get("specs") or []:
        if not isinstance(spec, dict):
            continue
        for test in spec.get("tests") or []:
            if not isinstance(test, dict) or len(out) >= MAX_TESTS:
                continue
            results = [r for r in test.get("results") or [] if isinstance(r, dict)]
            failing = next(
                (r for r in results if r.get("status") not in ("passed", "skipped")), None
            )
            error = None
            if failing is not None:
                err = failing.get("error") or {}
                error = _clip(err.get("message") if isinstance(err, dict) else err)
            attachments = []
            for r in results:
                for a in r.get("attachments") or []:
                    if not isinstance(a, dict):
                        continue
                    path = _attachment_path(a.get("path"), base)
                    if path:
                        attachments.append(
                            {
                                "name": _clip(a.get("name"), 100),
                                "path": path,
                                "retry": r.get("retry"),
                            }
                        )
            out.append(
                {
                    "title": " › ".join([*here[1:], str(spec.get("title", ""))]) or "",
                    "file": str(spec.get("file") or suite.get("file") or ""),
                    "line": _int(spec.get("line")),
                    "project": str(test.get("projectName") or ""),
                    "status": str(test.get("status") or ""),  # expected|unexpected|flaky|skipped
                    "tags": [str(t) for t in spec.get("tags") or []][:20],
                    "attempts": len(results),
                    "duration_ms": sum(_int(r.get("duration")) for r in results),
                    "error": error,
                    "attachments": attachments[:20],
                }
            )
    for child in suite.get("suites") or []:
        if isinstance(child, dict):
            _walk(child, here, out, base)


def summarize(results_json: Path, attachments_base: Path) -> dict[str, Any]:
    """`results.json` → {stats, tests, errors}. Dosya yok/bozuksa `ValueError`."""
    try:
        data = json.loads(results_json.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("Playwright JSON raporu üretilmedi") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Playwright JSON raporu okunamadı: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Playwright JSON raporu nesne değil")
    raw_stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    stats = {
        k: _int(raw_stats.get(k))
        for k in ("expected", "unexpected", "flaky", "skipped", "duration")
    }
    stats["duration_ms"] = stats.pop("duration")
    tests: list[dict[str, Any]] = []
    for suite in data.get("suites") or []:
        if isinstance(suite, dict):
            _walk(suite, [], tests, attachments_base)
    errors = [
        _clip(e.get("message") if isinstance(e, dict) else e) for e in (data.get("errors") or [])
    ][:20]
    return {"stats": stats, "tests": tests, "errors": errors}


def decide_status(*, exit_code: int | None, timed_out: bool, summary: dict[str, Any] | None) -> str:
    """passed | failed | error.

    - süre aşımı, rapor yok, rapor düzeyinde hata veya hiç test koşmadıysa → error
    - beklenmeyen sonuç varsa → failed (assertion/locator; triage ayırır)
    - aksi halde çıkış kodu 0 → passed; 0 değilse → error
    """
    if timed_out or summary is None:
        return "error"
    stats = summary["stats"]
    if summary["errors"]:
        return "error"
    if stats["unexpected"] > 0:
        return "failed"
    if stats["expected"] + stats["flaky"] == 0:
        return "error"
    return "passed" if exit_code == 0 else "error"
