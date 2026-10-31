"""Faz 3 inceleme düzeltmeleri (toolchain):

1. toolchain-worker uçları paylaşılan belirteçle korunur (test-runner'daki commit kodu `/check`'i
   çağırıp merge kapısını yazdıramaz) ve kapsamlı (test_files/grep) kontrol asla kapıya yazılmaz.
2. CI / test-runner imajında Playwright MCP sunucusu yoktur (anayasa II): yalnızca `mcp` hedefi.
3. `.keep` işaretli kanıt koşularının da saklama sınırı vardır; core işareti kaldırabilir.
4. Konteynerde elle başlatılan koşular (`make e2e-smoke`) test-runner'ın koşu kilidini paylaşır.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from runner import run as runner
from runner.app import app as runner_app
from tests.conftest import TOOLCHAIN, Forge
from tests.test_check import fake_tools, runner_client
from tests.test_runner import REPORT_PASSED, DemoApi, demo_api, fake_playwright  # noqa: F401
from tests.test_runner_phase3 import _old_run
from toolchain_common import runlock
from toolchain_common.settings import settings
from worker import check as checks
from worker.app import app as worker_app

TOKEN = "gizli-toolchain-belirteci"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

# ======================================================================= 1a. kimlik doğrulaması


def _bodies(sha: str) -> dict[str, dict[str, Any]]:
    return {
        "/check": {"sha": sha, "record_check": True},
        "/symbols": {"sha": sha},
        "/ast-guard": {"base_sha": sha, "head_sha": sha},
        "/locator-probe": {"sha": sha, "role": "button", "name": "Sepete ekle", "url_path": "/"},
        "/runs/release": {"run_ids": ["r1"]},
    }


@pytest.mark.parametrize(
    "path", ["/check", "/symbols", "/ast-guard", "/locator-probe", "/runs/release"]
)
def test_endpoints_require_bearer_token(
    path: str, env: Path, forge: Forge, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_TOOLCHAIN_TOKEN", TOKEN)
    client = TestClient(worker_app)
    body = _bodies(forge.main)[path]
    for headers in ({}, {"Authorization": "Bearer yanlis"}, {"Authorization": TOKEN}):
        resp = client.post(path, json=body, headers=headers)
        assert resp.status_code == 401, (path, headers, resp.text)
        assert resp.headers["www-authenticate"] == "Bearer"
        assert "Kimlik doğrulaması gerekli" in resp.json()["detail"]
    # Geçersiz gövde de önce 401 alır (doğrulama ayrıntısı sızmaz).
    assert client.post(path, json={"x": 1}).status_code == 401
    # Merge kapısına hiçbir şey yazılmadı.
    assert not (env / "checks").exists()


def test_valid_token_passes_through(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_TOOLCHAIN_TOKEN", TOKEN)
    client = TestClient(worker_app)
    # Belirteçle istek doğrulamaya ulaşır (kimlik değil, gövde reddedilir).
    resp = client.post("/check", json={"sha": forge.main, "test_files": ["../x"]}, headers=AUTH)
    assert resp.status_code == 422
    resp = client.post("/runs/release", json={"run_ids": ["r1"]}, headers=AUTH)
    assert resp.status_code == 200 and resp.json() == {"released": []}


def test_health_open_and_reports_auth_mode(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(worker_app)
    monkeypatch.setenv("TP_TOOLCHAIN_TOKEN", TOKEN)
    checks_ = client.get("/health").json()["checks"]
    assert checks_["auth"] == "ok (belirteç zorunlu)"

    monkeypatch.delenv("TP_TOOLCHAIN_TOKEN")
    auth = client.get("/health").json()["checks"]["auth"]
    assert auth.startswith("ok (uyarı:") and "TP_TOOLCHAIN_TOKEN" in auth


def test_require_token_without_token_fails_closed(
    env: Path, forge: Forge, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_TOOLCHAIN_REQUIRE_TOKEN", "1")
    client = TestClient(worker_app)
    resp = client.post("/check", json={"sha": forge.main})
    assert resp.status_code == 503 and "TP_TOOLCHAIN_TOKEN" in resp.json()["detail"]
    health = client.get("/health")
    assert health.status_code == 503
    assert health.json()["checks"]["auth"].startswith("error:")


# ============================================================ 1b. kapsamlı kontrol kapıya yazılmaz


@pytest.mark.parametrize(
    "extra",
    [
        {"test_files": ["tests/cart.spec.ts"]},
        {"grep": "@TPD-1"},
        {"test_files": ["tests/cart.spec.ts"], "repeat_each": 1},
    ],
)
def test_api_rejects_scoped_record_check(extra: dict[str, Any], env: Path, forge: Forge) -> None:
    """Saldırı: test-runner'daki kod başka bir head için kapsamlı + record_check:true ister."""
    resp = TestClient(worker_app).post(
        "/check", json={"sha": forge.main, "record_check": True, **extra}
    )
    assert resp.status_code == 422, resp.text
    assert "kapsamlı kontrol" in resp.json()["detail"]
    assert not (env / "checks").exists()


def test_scoped_request_never_records_even_if_forced(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Savunma derinliği: API'yi atlayan bir çağrıda da kapsamlı kontrol yazılmaz."""
    assert checks.CheckRequest(sha="a" * 40, test_files=["tests/x.spec.ts"], record_check=True)
    assert not checks.CheckRequest(
        sha="a" * 40, test_files=["tests/x.spec.ts"], record_check=True
    ).records_check()
    assert not checks.CheckRequest(sha="a" * 40, grep="x", record_check=True).records_check()
    assert checks.CheckRequest(sha="a" * 40).records_check()
    assert checks.CheckRequest(sha="a" * 40, record_check=True).records_check()
    assert not checks.CheckRequest(sha="a" * 40, record_check=False).records_check()

    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path)))
    client, _ = runner_client()
    report = checks.execute(
        settings(),
        checks.CheckRequest(sha=forge.main, test_files=["tests/cart.spec.ts"], record_check=True),
        runner_client=client,
    )
    assert report["conclusion"] == "success"
    assert report["check_recorded"] is False and report["checks_path"] is None
    assert not (env / "checks").exists()


def test_recorded_check_run_carries_full_scope_flag(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path)))
    client, _ = runner_client()
    report = checks.execute(settings(), checks.CheckRequest(sha=forge.main), runner_client=client)
    assert report["check_recorded"] is True
    doc = json.loads((env / "checks" / f"{forge.main}.json").read_text())
    assert doc["checks"] == [
        {
            "name": "local-ci",
            "status": "completed",
            "conclusion": "success",
            "url": None,
            "tam": True,
        }
    ]
    assert doc["report"]["kapsam"]["tam"] is True


def test_isolation_script_probes_worker_from_test_runner() -> None:
    """make security-check maddesi: test-runner'dan /check denemesi ve belirteç sızıntısı."""
    script = (TOOLCHAIN / "security" / "checks-isolation.sh").read_text()
    subprocess.run(["bash", "-n", str(TOOLCHAIN / "security" / "checks-isolation.sh")], check=True)
    assert "toolchain-worker:8100/check" in script
    assert "TP_TOOLCHAIN_TOKEN" in script
    assert '"record_check":true' in script and '"test_files"' in script


# ========================================================================= 2. MCP CI imajında yok


def test_ci_npm_manifest_has_no_mcp() -> None:
    pkg = json.loads((TOOLCHAIN / "package.json").read_text())
    lock = json.loads((TOOLCHAIN / "package-lock.json").read_text())
    assert "@playwright/mcp" not in pkg["dependencies"]
    assert not any("@playwright/mcp" in k for k in lock["packages"])
    mcp = json.loads((TOOLCHAIN / "mcp" / "package.json").read_text())
    mcp_lock = json.loads((TOOLCHAIN / "mcp" / "package-lock.json").read_text())
    assert (
        mcp["dependencies"]["@playwright/mcp"]
        == mcp_lock["packages"][""]["dependencies"]["@playwright/mcp"]
    )
    # MCP de imajdaki tarayıcılarla aynı playwright-core'u kullanır.
    assert mcp["overrides"] == pkg["overrides"]
    assert (
        mcp_lock["packages"]["node_modules/playwright-core"]["version"]
        == (pkg["overrides"]["playwright-core"])
    )


def _stages(dockerfile: str) -> dict[str, str]:
    """Dockerfile aşamaları: ad → gövde (son, adsız aşama `__default__`)."""
    out: dict[str, str] = {}
    parts = re.split(r"(?m)^FROM\s+", dockerfile)[1:]
    for part in parts:
        header, _, body = part.partition("\n")
        m = re.search(r"\bAS\s+(\S+)", header, re.I)
        out[m.group(1) if m else "__default__"] = header + "\n" + body
    return out


def test_dockerfile_default_target_is_ci_without_mcp() -> None:
    stages = _stages((TOOLCHAIN / "Dockerfile").read_text())
    assert stages["__default__"].split("\n", 1)[0].strip() == "ci"
    assert (
        "mcp/" not in stages["ci"]
        and "/opt/mcp" not in stages["ci"].replace("# ", "").split("COPY bin")[0]
    )
    assert "COPY mcp/package.json mcp/package-lock.json" in stages["mcp"]
    assert stages["mcp"].split("\n", 1)[0].startswith("ci AS mcp")
    wrapper = (TOOLCHAIN / "bin" / "playwright-mcp").read_text()
    assert "/opt/mcp/node_modules/@playwright/mcp/cli.js" in wrapper
    assert "/opt/toolchain/node_modules/@playwright/mcp" not in wrapper


def test_no_mcp_guard_script_is_valid() -> None:
    path = TOOLCHAIN / "security" / "no-mcp-in-image.sh"
    subprocess.run(["bash", "-n", str(path)], check=True)
    assert os.access(path, os.X_OK)
    res = subprocess.run([str(path)], capture_output=True, text=True)
    assert res.returncode == 2 and "kullanım" in res.stderr
    text = path.read_text()
    assert "require.resolve" in text and "@playwright/mcp" in text


# ===================================================================== 3. kanıt koşusu saklama


def test_old_evidence_runs_are_pruned_by_age_and_cap(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_RUNS_KEEP", "50")
    monkeypatch.setenv("TP_RUNS_KEEP_EVIDENCE_DAYS", "30")
    monkeypatch.setenv("TP_RUNS_KEEP_EVIDENCE_MAX", "3")
    day = 86_400
    _old_run(env, "kanit-yeni-0", age_s=1 * day, keep=True)
    _old_run(env, "kanit-yeni-1", age_s=2 * day, keep=True)
    _old_run(env, "kanit-yeni-2", age_s=3 * day, keep=True)
    _old_run(env, "kanit-fazla", age_s=4 * day, keep=True)  # sayı sınırı (3) dışı
    _old_run(env, "kanit-eski", age_s=31 * day, keep=True)  # yaş sınırı dışı
    _old_run(env, "kanit-suruyor", age_s=60, status="running", keep=True)
    _old_run(env, "isaretsiz", age_s=40 * day)  # TP_RUNS_KEEP=50 içinde → kalır
    out = runner.prune_runs(settings(), "yok")
    assert sorted(out["deleted_evidence"]) == ["kanit-eski", "kanit-fazla"]
    assert out["deleted"] == [] and out["errors"] == []
    left = sorted(p.name for p in (env / "runs").iterdir())
    assert left == sorted(
        ["kanit-yeni-0", "kanit-yeni-1", "kanit-yeni-2", "kanit-suruyor", "isaretsiz"]
    )
    assert out["keep_evidence_days"] == 30 and out["keep_evidence_max"] == 3


def test_evidence_defaults_bound_growth(env: Path) -> None:
    cfg = settings()
    assert cfg.runs_keep_evidence_days == 30 and cfg.runs_keep_evidence_max == 200
    _old_run(env, "kanit-cok-eski", age_s=45 * 86_400, keep=True)
    out = runner.prune_runs(cfg, "yok")
    assert out["deleted_evidence"] == ["kanit-cok-eski"]


def test_release_endpoint_removes_keep_marker(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_TOOLCHAIN_TOKEN", TOKEN)
    monkeypatch.setenv("TP_RUNS_KEEP", "1")
    _old_run(env, "kanit-a", age_s=5000, keep=True)
    _old_run(env, "kanit-b", age_s=6000, keep=True)
    client = TestClient(worker_app)
    resp = client.post(
        "/runs/release", json={"run_ids": ["kanit-a", "yok", "kanit-a"]}, headers=AUTH
    )
    assert resp.status_code == 200 and resp.json() == {"released": ["kanit-a"]}
    assert not (env / "runs" / "kanit-a" / ".keep").exists()
    assert (env / "runs" / "kanit-b" / ".keep").is_file()
    # Serbest kalan koşu artık işaretsiz havuzda: sıradaki temizlik onu eler.
    out = runner.prune_runs(settings(), "yeni")
    assert out["deleted"] == ["kanit-a"] and out["deleted_evidence"] == []
    for bad in (["../x"], [], ["a b"]):
        assert client.post("/runs/release", json={"run_ids": bad}, headers=AUTH).status_code == 422


# ======================================================================== 4. koşu kilidi (flock)


@pytest.fixture
def run_client(env: Path, demo_api: DemoApi) -> TestClient:  # noqa: F811
    return TestClient(runner_app)


def test_run_waits_for_external_lock_holder(
    run_client: TestClient, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`make e2e-smoke` (tp-run-lock) koşarken /run beklemeli, süre dolunca 409 dönmeli."""
    monkeypatch.setenv("TP_NODE", str(fake_playwright(tmp_path, report=REPORT_PASSED)))
    monkeypatch.setenv("TP_RUN_QUEUE_WAIT_S", "0.5")
    fd = runlock.acquire(settings().run_lock_path, 1)
    try:
        resp = run_client.post("/run", json={"run_id": "r-kilit", "sha": forge.main})
        assert resp.status_code == 409, resp.text
        assert "make e2e-smoke" in resp.json()["detail"]
    finally:
        runlock.release(fd)
    # Kilit bırakılınca koşu yürür ve kilidi kendisi de bırakır.
    monkeypatch.setenv("TP_RUN_QUEUE_WAIT_S", "5")
    resp = run_client.post("/run", json={"run_id": "r-kilit", "sha": forge.main})
    assert resp.status_code == 200 and resp.json()["status"] == "passed"
    runlock.release(runlock.acquire(settings().run_lock_path, 0))


def _tp_run_lock(*args: str, wait: str = "0.5") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOLCHAIN / "bin" / "tp-run-lock"), "--wait", wait, "--", *args],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=30,
    )


def test_tp_run_lock_refuses_while_run_in_progress(env: Path) -> None:
    fd = runlock.acquire(settings().run_lock_path, 1)
    try:
        res = _tp_run_lock(sys.executable, "-c", "print('koştu')")
    finally:
        runlock.release(fd)
    assert res.returncode == 75, res.stderr
    assert "koştu" not in res.stdout and "başka bir test koşusu" in res.stderr


def test_tp_run_lock_holds_lock_for_command_lifetime(env: Path) -> None:
    lock = settings().run_lock_path
    probe = (
        "import fcntl, os, sys\n"
        f"fd = os.open({str(lock)!r}, os.O_RDWR)\n"
        "try:\n"
        "    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "    print('KILITSIZ')\n"
        "except BlockingIOError:\n"
        "    print('KILITLI', os.environ.get('TP_RUN_LOCK_HELD'))\n"
        "sys.exit(3)\n"
    )
    # Komutun kendi alt süreci kilidi alamaz (komut kilidi tutuyor); çıkış kodu aktarılır.
    res = _tp_run_lock(
        sys.executable,
        "-c",
        f"import subprocess, sys; sys.exit(subprocess.call([sys.executable, '-c', {probe!r}]))",
    )
    assert res.returncode == 3, res.stderr
    assert res.stdout.strip() == "KILITLI 1"
    # Komut bitince kilit düşer.
    runlock.release(runlock.acquire(lock, 0))


def test_tp_run_lock_blocks_concurrent_run(
    run_client: TestClient, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Elle başlatılan uzun koşu sürerken /run beklemez-geçmez: sıraya girer."""
    monkeypatch.setenv("TP_NODE", str(fake_playwright(tmp_path, report=REPORT_PASSED)))
    monkeypatch.setenv("TP_RUN_QUEUE_WAIT_S", "10")
    started = tmp_path / "basladi"
    proc = subprocess.Popen(
        [
            sys.executable,
            str(TOOLCHAIN / "bin" / "tp-run-lock"),
            "--",
            sys.executable,
            "-c",
            f"import pathlib, time; pathlib.Path({str(started)!r}).touch(); time.sleep(1.5)",
        ],
        env=os.environ.copy(),
    )
    try:
        deadline = time.monotonic() + 10
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert started.exists()
        t0 = time.monotonic()
        result: dict[str, Any] = {}

        def call() -> None:
            result["resp"] = run_client.post("/run", json={"run_id": "r-sira", "sha": forge.main})

        th = threading.Thread(target=call)
        th.start()
        th.join(30)
        waited = time.monotonic() - t0
    finally:
        proc.wait(10)
    assert result["resp"].status_code == 200
    assert proc.returncode == 0
    assert waited >= 0.8  # e2e-smoke bitene dek bekledi
