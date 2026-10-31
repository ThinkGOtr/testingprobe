from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner.results import decide_status, summarize


def _write(tmp_path: Path, data: object) -> Path:
    p = tmp_path / "results.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_summarize_nested_suites_flaky_and_attachments(tmp_path: Path) -> None:
    base = tmp_path / "run"
    trace = base / "src" / "e2e" / "results" / "artifacts" / "t" / "trace.zip"
    trace.parent.mkdir(parents=True)
    trace.write_bytes(b"zip")
    report = {
        "suites": [
            {
                "title": "order.spec.ts",
                "file": "order.spec.ts",
                "specs": [],
                "suites": [
                    {
                        "title": "Sipariş",
                        "specs": [
                            {
                                "title": "onay",
                                "file": "order.spec.ts",
                                "line": 12,
                                "tests": [
                                    {
                                        "projectName": "chromium",
                                        "status": "flaky",
                                        "results": [
                                            {
                                                "status": "failed",
                                                "duration": 10,
                                                "retry": 0,
                                                "error": {"message": "zaman aşımı"},
                                                "attachments": [
                                                    {"name": "trace", "path": str(trace)},
                                                    {"name": "dışarı", "path": "/etc/passwd"},
                                                ],
                                            },
                                            {"status": "passed", "duration": 20, "retry": 1},
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
        "errors": [],
        "stats": {"expected": 0, "unexpected": 0, "flaky": 1, "skipped": 0, "duration": 30},
    }
    s = summarize(_write(tmp_path, report), base)
    (t,) = s["tests"]
    assert t["title"] == "Sipariş › onay"
    assert t["status"] == "flaky"
    assert t["attempts"] == 2
    assert t["duration_ms"] == 30
    assert t["error"] == "zaman aşımı"
    # Koşu dizini dışındaki ek yolları dönmez.
    assert [a["path"] for a in t["attachments"]] == [str(trace.resolve())]
    assert decide_status(exit_code=0, timed_out=False, summary=s) == "passed"


def test_summarize_missing_and_corrupt(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="üretilmedi"):
        summarize(tmp_path / "yok.json", tmp_path)
    p = tmp_path / "bozuk.json"
    p.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="okunamadı"):
        summarize(p, tmp_path)


def _summary(
    expected: int = 0, unexpected: int = 0, flaky: int = 0, errors: list[str] | None = None
):
    return {
        "stats": {"expected": expected, "unexpected": unexpected, "flaky": flaky, "skipped": 0},
        "tests": [],
        "errors": errors or [],
    }


@pytest.mark.parametrize(
    ("kwargs", "status"),
    [
        ({"exit_code": 0, "timed_out": False, "summary": _summary(expected=3)}, "passed"),
        (
            {"exit_code": 1, "timed_out": False, "summary": _summary(expected=2, unexpected=1)},
            "failed",
        ),
        ({"exit_code": None, "timed_out": True, "summary": _summary(expected=3)}, "error"),
        ({"exit_code": 1, "timed_out": False, "summary": None}, "error"),
        ({"exit_code": 1, "timed_out": False, "summary": _summary(errors=["config"])}, "error"),
        ({"exit_code": 0, "timed_out": False, "summary": _summary()}, "error"),
        ({"exit_code": 1, "timed_out": False, "summary": _summary(expected=3)}, "error"),
    ],
)
def test_decide_status(kwargs: dict, status: str) -> None:
    assert decide_status(**kwargs) == status
