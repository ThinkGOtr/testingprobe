"""toolchain-worker `/check`: adım sırası, rapor birleştirme, LocalForge'un okuduğu dosya."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.conftest import (
    Forge,
    make_fake_node,
    requires_ast_guard,
    requires_e2e_node_modules,
    requires_node,
)
from toolchain_common.settings import settings
from worker import check as checks

RUN_OK = {
    "run_id": "x",
    "status": "passed",
    "junit": "/artifacts/runs/x/src/e2e/results/junit.xml",
    "json": "/artifacts/runs/x/src/e2e/results/results.json",
    "artifacts_dir": "/artifacts/runs/x",
    "duration_ms": 10,
}

AST_OK = {"tool": "ast-guard", "ok": True, "noop": True, "violations": [], "summary": "no-op"}


def runner_client(
    response: dict[str, Any] | None = None, status: int = 200
) -> tuple[httpx.Client, list]:
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"url": str(request.url), "body": json.loads(request.content)})
        return httpx.Response(status, json=response if response is not None else RUN_OK)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def fake_tools(
    tmp_path: Path,
    *,
    tsc_exit: int = 0,
    eslint_out: str = "[]",
    eslint_exit: int = 0,
    ast: dict[str, Any] | None = None,
    ast_exit: int = 0,
) -> Path:
    return make_fake_node(
        tmp_path,
        f"""
        script = sys.argv[1]
        log = pathlib.Path({str(tmp_path / "calls.log")!r})
        with log.open("a") as fh:
            fh.write(json.dumps(sys.argv[1:]) + "\\n")
        if script.endswith("typescript/bin/tsc"):
            if {tsc_exit}:
                print("tests/x.spec.ts(3,7): error TS2345: "
                      "Argument of type 'number' is not assignable.")
            sys.exit({tsc_exit})
        if script.endswith("eslint/bin/eslint.js"):
            print({eslint_out!r})
            sys.exit({eslint_exit})
        if script.endswith("ast-guard/dist/src/cli.js"):
            print({json.dumps(ast or AST_OK)!r})
            sys.exit({ast_exit})
        sys.exit(99)
        """,
    )


def _calls(tmp_path: Path) -> list[list[str]]:
    log = tmp_path / "calls.log"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def _localforge_parse(path: Path) -> list[dict[str, Any]]:
    """LocalForge.checks() ile aynı kurallar (tp_core.integrations.forge_local + ports.CheckRun)."""
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("checks", [data] if "name" in data else [])
    assert isinstance(data, list)
    for item in data:
        assert isinstance(item["name"], str)
        assert item["status"] in ("queued", "in_progress", "completed")
        assert item.get("conclusion") in (None, "success", "failure", "cancelled", "skipped")
        assert item.get("url") is None or isinstance(item["url"], str)
    return data


def test_success_writes_local_ci_success(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path)))
    head = forge.commit("tp/case-1", {"e2e/tests/yeni.spec.ts": "// yeni\n"})
    client, calls = runner_client()
    report = checks.execute(
        settings(),
        checks.CheckRequest(sha=head[:12], test_files=["tests/yeni.spec.ts"], repeat_each=3),
        runner_client=client,
    )
    assert report["conclusion"] == "success"
    assert report["sha"] == head
    assert [report[s]["ok"] for s in checks.STEPS] == [True] * 5
    assert report["run"]["junit_path"] == RUN_OK["junit"]
    path = env / "checks" / f"{head}.json"
    assert report["checks_path"] == str(path)
    assert _localforge_parse(path) == [
        {"name": "local-ci", "status": "completed", "conclusion": "success", "url": None}
    ]
    # Sıra: tsc → eslint → ast-guard (pr, merge-base = main) → test-runner
    tools = [c[0].rsplit("/", 3)[-3:] for c in _calls(tmp_path)]
    assert [t[-1] for t in tools] == ["tsc", "eslint.js", "cli.js"]
    ast_argv = _calls(tmp_path)[2]
    assert ast_argv[ast_argv.index("--base") + 1] == forge.main
    assert ast_argv[ast_argv.index("--head") + 1] == head
    assert ast_argv[ast_argv.index("--mode") + 1] == "pr"
    assert ast_argv[ast_argv.index("--root") + 1] == "e2e"
    (call,) = calls
    assert call["url"].endswith("/run")
    assert call["body"]["sha"] == head
    assert call["body"]["test_files"] == ["tests/yeni.spec.ts"]
    assert call["body"]["repeat_each"] == 3
    assert call["body"]["env"] == {}
    assert call["body"]["run_id"].startswith(f"check-{head[:12]}-")


def test_tsc_failure_stops_and_records_failure(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path, tsc_exit=2)))
    client, calls = runner_client()
    report = checks.execute(settings(), checks.CheckRequest(sha=forge.main), runner_client=client)
    assert report["conclusion"] == "failure"
    assert report["failed_steps"] == ["tsc"]
    assert report["tsc"]["diagnostics"] == [
        {
            "file": "tests/x.spec.ts",
            "line": 3,
            "column": 7,
            "severity": "error",
            "code": "TS2345",
            "message": "Argument of type 'number' is not assignable.",
        }
    ]
    assert report["eslint"]["skipped"] and report["run"]["skipped"]
    assert calls == []
    assert _localforge_parse(env / "checks" / f"{forge.main}.json")[0]["conclusion"] == "failure"


def test_ast_guard_violation_blocks_run(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = {**AST_OK, "ok": False, "violations": [{"code": "field_changed", "file": "x"}]}
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path, ast=bad, ast_exit=1)))
    client, calls = runner_client()
    report = checks.execute(settings(), checks.CheckRequest(sha=forge.main), runner_client=client)
    assert report["failed_steps"] == ["ast_guard"]
    assert report["ast_guard"]["report"]["violations"][0]["code"] == "field_changed"
    assert calls == []


def test_runner_failure_and_unreachable(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path)))
    client, _ = runner_client({**RUN_OK, "status": "failed"})
    report = checks.execute(settings(), checks.CheckRequest(sha=forge.main), runner_client=client)
    assert report["conclusion"] == "failure" and report["failed_steps"] == ["run"]

    client, _ = runner_client({"detail": "Başka bir test koşusu sürüyor"}, status=409)
    report = checks.execute(settings(), checks.CheckRequest(sha=forge.main), runner_client=client)
    assert "HTTP 409" in report["run"]["error"]
    assert report["conclusion"] == "failure"

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("bağlantı reddedildi", request=request)

    report = checks.execute(
        settings(),
        checks.CheckRequest(sha=forge.main),
        runner_client=httpx.Client(transport=httpx.MockTransport(boom)),
    )
    assert "ulaşılamadı" in report["run"]["error"]


def test_lockfile_mismatch_fails_closed(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path)))
    lock = json.loads((forge.work / "e2e" / "package-lock.json").read_text())
    lock["packages"][""]["devDependencies"]["left-pad"] = "1.3.0"
    head = forge.commit("tp/case-dep", {"e2e/package-lock.json": json.dumps(lock)})
    client, calls = runner_client()
    report = checks.execute(settings(), checks.CheckRequest(sha=head), runner_client=client)
    assert report["failed_steps"] == ["deps"]
    assert "çevrimdışı" in report["deps"]["error"]
    assert _calls(tmp_path) == [] and calls == []


def test_tampered_eslint_config_is_not_loaded(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path)))
    head = forge.commit(
        "tp/case-eslint",
        {"e2e/eslint.config.js": "require('child_process').execSync('id');\nexport default [];\n"},
    )
    client, calls = runner_client()
    report = checks.execute(settings(), checks.CheckRequest(sha=head), runner_client=client)
    assert report["failed_steps"] == ["eslint"]
    assert "güvenilir kopyadan farklı" in report["eslint"]["error"]
    # Yalnızca tsc koştu; eslint süreci hiç başlatılmadı.
    assert [c[0].rsplit("/", 1)[-1] for c in _calls(tmp_path)] == ["tsc"]
    assert calls == []


def test_break_campaign_check_does_not_touch_checks_file(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path)))
    client, calls = runner_client({**RUN_OK, "status": "failed"})
    report = checks.execute(
        settings(), checks.CheckRequest(sha=forge.main, break_campaign=True), runner_client=client
    )
    assert calls[0]["body"]["env"] == {"BREAK_CAMPAIGN": "1"}
    assert report["checks_path"] is None
    assert not (env / "checks").exists()


def test_unexpected_exception_still_closes_checks_file(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path)))

    def explode(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise RuntimeError("beklenmedik")

    monkeypatch.setattr(checks.static, "run_eslint", explode)
    with pytest.raises(RuntimeError):
        checks.execute(settings(), checks.CheckRequest(sha=forge.main))
    doc = json.loads((env / "checks" / f"{forge.main}.json").read_text())
    assert doc["checks"][0] == {
        "name": "local-ci",
        "status": "completed",
        "conclusion": "failure",
        "url": None,
    }
    assert "beklenmeyen hata" in doc["report"]["summary"]


def test_aggregate_requires_every_step() -> None:
    ok = {"ok": True}
    full = {
        "deps": ok,
        "tsc": ok,
        "eslint": ok,
        "ast_guard": ok,
        "run": {"ok": True, "status": "passed"},
    }
    assert checks.aggregate("a" * 40, full)["conclusion"] == "success"
    partial = {k: v for k, v in full.items() if k != "run"}
    agg = checks.aggregate("a" * 40, partial)
    assert agg["conclusion"] == "failure"
    assert agg["run"]["skipped"] is True
    flaky_status = {**full, "run": {"ok": True, "status": "error"}}
    assert checks.aggregate("a" * 40, flaky_status)["conclusion"] == "failure"


@requires_node
@requires_e2e_node_modules
@requires_ast_guard
def test_real_tsc_eslint_ast_guard_on_demo_e2e(
    env: Path, forge: Forge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gerçek araçlar (yerel demo-app/e2e/node_modules + derlenmiş ast-guard), sahte test-runner."""
    monkeypatch.setenv("TP_NODE", "node")
    client, _ = runner_client()
    report = checks.execute(settings(), checks.CheckRequest(sha=forge.main), runner_client=client)
    assert report["tsc"]["ok"], report["tsc"]
    assert report["eslint"]["ok"], report["eslint"]
    assert report["ast_guard"]["ok"] and report["ast_guard"]["report"]["noop"] is True
    assert report["conclusion"] == "success"

    broken = forge.commit(
        "tp/case-tur",
        {
            "e2e/tests/tur.spec.ts": (
                'import { test } from "./fixtures";\n\n'
                'test("tür hatası", async ({ catalogPage }) => {\n'
                "  await catalogPage.addToCart(42, 6);\n"
                "});\n"
            )
        },
    )
    report = checks.execute(settings(), checks.CheckRequest(sha=broken), runner_client=client)
    assert report["failed_steps"] == ["tsc"]
    assert any(
        d["file"] == "tests/tur.spec.ts" and d["code"] == "TS2345"
        for d in report["tsc"]["diagnostics"]
    )
