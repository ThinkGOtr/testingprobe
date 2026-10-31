"""test-runner (Faz 3/4): başarısız test girdileri, rapor bloğu, `.keep`, eski koşu temizliği."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from runner import run as runner
from tests.conftest import Forge
from tests.test_runner import DemoApi, _run, client, demo_api, fake_playwright  # noqa: F401
from toolchain_common.settings import settings


def _report_with_failure(e2e_marker: str = "{CWD}") -> dict[str, Any]:
    """Bir kırmızı (assertion) ve bir yeşil test; ek yolları koşu dizini içinde."""
    msg = (
        "Error: expect(locator).toHaveText(expected) failed\n\n"
        'Locator:  getByTestId(\'cart-line-free-P-001\')\nExpected: "0"\nReceived: "1"\n'
        "Timeout:  5000ms\n"
    )
    att = f"{e2e_marker}/results/artifacts/t/trace.zip"
    return {
        "suites": [
            {
                "title": "generated/tpd-1-c2.spec.ts",
                "file": "generated/tpd-1-c2.spec.ts",
                "specs": [
                    {
                        "id": "abc-1",
                        "title": "6 adet → bedava yok",
                        "file": "generated/tpd-1-c2.spec.ts",
                        "line": 4,
                        "tags": ["TPD-1"],
                        "tests": [
                            {
                                "projectName": "chromium",
                                "status": "unexpected",
                                "results": [
                                    {
                                        "status": "failed",
                                        "duration": 50,
                                        "retry": 0,
                                        "error": {"message": msg},
                                        "errors": [{"message": msg}],
                                        "errorLocation": {
                                            "file": f"{e2e_marker}/pages/cart/cart.page.ts",
                                            "line": 40,
                                            "column": 5,
                                        },
                                        "attachments": [
                                            {"name": "trace", "path": att},
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "id": "abc-2",
                        "title": "7 adet → 1 bedava",
                        "file": "generated/tpd-1-c2.spec.ts",
                        "line": 12,
                        "tests": [
                            {
                                "projectName": "chromium",
                                "status": "expected",
                                "results": [{"status": "passed", "duration": 40, "retry": 0}],
                            }
                        ],
                    },
                ],
            }
        ],
        "errors": [],
        "stats": {"expected": 1, "unexpected": 1, "flaky": 0, "skipped": 0, "duration": 90},
    }


def _fake_with_cwd_paths(tmp_path: Path, report: dict[str, Any], exit_code: int) -> Path:
    """Sahte Playwright: rapordaki `{CWD}`'yi koşu dizinindeki e2e yolu yapar, eki yazar."""
    from tests.conftest import make_fake_node

    return make_fake_node(
        tmp_path,
        f"""
        cwd = pathlib.Path.cwd()
        res = cwd / "results"
        (res / "artifacts" / "t").mkdir(parents=True, exist_ok=True)
        (res / "artifacts" / "t" / "trace.zip").write_bytes(b"zip")
        (res / "html").mkdir(exist_ok=True)
        (res / "html" / "index.html").write_text("<html/>")
        (res / "allure-results").mkdir(exist_ok=True)
        (res / "junit.xml").write_text("<testsuites/>")
        report = {json.dumps(report)!r}.replace("{{CWD}}", str(cwd))
        (res / "results.json").write_text(report)
        sys.exit({exit_code})
        """,
        name="fake-pw-cwd",
    )


def test_failed_run_carries_failure_inputs_and_reports(
    client: TestClient,  # noqa: F811
    forge: Forge,
    env: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _fake_with_cwd_paths(tmp_path, _report_with_failure(), exit_code=1)
    monkeypatch.setenv("TP_NODE", str(fake))
    resp = _run(client, sha=forge.main, repeat_each=3, test_files=["tests/generated/x.spec.ts"])
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "failed"
    (fail,) = data["failures"]
    assert fail["title"] == "6 adet → bedava yok" and fail["id"] == "abc-1"
    f = fail["failure"]
    assert f["type"] == "assertion"
    assert (f["expected"], f["received"]) == ('"0"', '"1"')
    assert f["location"] == {"file": "pages/cart/cart.page.ts", "line": 40, "column": 5}
    trace = f["evidence"]["trace"]
    assert trace["exists"] is True
    assert trace["rel"] == "runs/r1/src/e2e/results/artifacts/t/trace.zip"
    # Yeşil test failures'ta yok ama tests'te var (failure=None).
    assert [t["failure"] is None for t in data["tests"]] == [False, True]
    reports = data["reports"]
    assert {k: v["exists"] for k, v in reports.items()} == {
        "html": True,
        "junit": True,
        "json": True,
        "allure": True,
        # Sahte koşu boş allure-results bırakır: HTML raporu üretilmez, koşu sonucu değişmez.
        "allure_html": False,
    }
    assert data["allure_report"]["ok"] is False and data["allure_report"]["error"]
    assert reports["html"]["rel"] == "runs/r1/src/e2e/results/html"
    stored = json.loads((env / "runs" / "r1" / "run.json").read_text())
    assert stored["failures"] == data["failures"]


def test_reports_absent_when_health_fails(
    client: TestClient,  # noqa: F811
    forge: Forge,
    demo_api: DemoApi,  # noqa: F811
) -> None:
    demo_api.get_status["/health"] = 503
    data = _run(client, sha=forge.main).json()
    assert data["status"] == "error" and data["failures"] == []
    assert not any(r["exists"] for r in data["reports"].values())


def _old_run(root: Path, name: str, age_s: float, status: str = "passed", keep: bool = False):
    d = root / "runs" / name
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps({"run_id": name, "status": status}))
    if keep:
        (d / ".keep").write_text("x")
    t = time.time() - age_s
    os.utime(d / "run.json", (t, t))
    return d


def test_prune_keeps_newest_marked_and_running(
    client: TestClient,  # noqa: F811
    forge: Forge,
    env: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_runner import REPORT_PASSED

    monkeypatch.setenv("TP_NODE", str(fake_playwright(tmp_path, report=REPORT_PASSED)))
    monkeypatch.setenv("TP_RUNS_KEEP", "3")
    for i in range(5):
        _old_run(env, f"eski-{i}", age_s=1000 + i * 100)  # eski-0 en yeni
    _old_run(env, "kanit", age_s=99_999, keep=True)
    _old_run(env, "suruyor", age_s=10, status="running")
    _old_run(env, "cokmus", age_s=999_999, status="running")
    (env / "runs" / "garip ad").mkdir()
    data = _run(client, sha=forge.main, keep=True).json()
    assert data["status"] == "passed"
    left = sorted(p.name for p in (env / "runs").iterdir())
    # Bu koşu (r1) + en yeni 2 işaretsiz = 3; .keep, süren koşu ve geçersiz ad dokunulmaz.
    assert left == sorted(["r1", "eski-0", "eski-1", "kanit", "suruyor", "garip ad"])
    assert sorted(data["cleanup"]["deleted"]) == ["cokmus", "eski-2", "eski-3", "eski-4"]
    assert (env / "runs" / "r1" / ".keep").is_file()


def test_prune_disabled_with_zero(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_RUNS_KEEP", "0")
    monkeypatch.setenv("TP_RUNS_KEEP_EVIDENCE_DAYS", "0")
    monkeypatch.setenv("TP_RUNS_KEEP_EVIDENCE_MAX", "0")
    for i in range(3):
        _old_run(env, f"eski-{i}", age_s=1000)
    _old_run(env, "kanit", age_s=400 * 86_400, keep=True)
    out = runner.prune_runs(settings(), "yok")
    assert out["deleted"] == [] and out["deleted_evidence"] == [] and out["errors"] == []
    assert len(list((env / "runs").iterdir())) == 4


def test_prune_does_not_follow_symlinks(
    env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_RUNS_KEEP", "1")
    outside = tmp_path / "disari"
    outside.mkdir()
    (outside / "run.json").write_text("{}")
    (env / "runs").mkdir()
    (env / "runs" / "baglanti").symlink_to(outside, target_is_directory=True)
    _old_run(env, "eski", age_s=5000)
    out = runner.prune_runs(settings(), "yeni")
    assert out["deleted"] == ["eski"]
    assert (outside / "run.json").is_file()
