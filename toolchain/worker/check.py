"""`POST /check`: yerel CI (`local-ci`) — CI ile aynı sıra, AI yok (TEKNIK-TASARIM §8.5).

  bağımlılık kilidi → tsc --noEmit → eslint --no-inline-config → ast-guard (pr) → test-runner /run

İlk başarısız adımda durulur (`run-checks.sh` gibi `set -e`); atlanan adımlar `skipped` olur.
Başta `checks/<sha>.json`'a `in_progress`, sonda `completed` + `success|failure` yazılır
(LocalForge.checks() bu dosyayı okur; merge kapısı `local-ci`'ı ister). Beklenmeyen bir hatada
da dosya `failure` ile kapatılır: yarım kalmış kontrol asla başarı sayılmaz.

Kırılma istenen kontrol ("kırarak doğrula", BREAK_CAMPAIGN) bilerek kırmızı beklenen bir
denemedir; commit'in CI sonucu değildir, bu yüzden `checks/<sha>.json`'a yazılmaz.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from toolchain_common import gitforge
from toolchain_common.artifacts import atomic_write_json, checks_file
from toolchain_common.settings import Settings
from worker import static
from worker.astguard import AstGuardError, run_ast_guard

CHECK_NAME = "local-ci"
CHECK_LOCK = threading.Lock()
STEPS = ("deps", "tsc", "eslint", "ast_guard", "run")


class CheckBusy(RuntimeError):
    """Başka bir kontrol sürüyor ve bekleme süresi doldu."""


@dataclass(frozen=True)
class CheckRequest:
    sha: str
    test_files: list[str] = field(default_factory=list)
    repeat_each: int = 3
    retries: int = 0
    break_campaign: bool = False
    grep: str | None = None
    base_sha: str | None = None
    ast_guard_mode: str = "pr"
    run_id: str | None = None


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def default_run_id(sha: str) -> str:
    return f"check-{sha[:12]}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}"


def skipped(reason: str) -> dict[str, Any]:
    return {"ok": False, "skipped": True, "reason": reason}


def aggregate(sha: str, steps: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Adım sonuçlarından tek rapor: hepsi tamam ve koşu `passed` ise `success`."""
    failed = [
        name
        for name in STEPS
        if name in steps and not steps[name].get("skipped") and not steps[name].get("ok")
    ]
    run = steps.get("run") or {}
    complete = all(name in steps and not steps[name].get("skipped") for name in STEPS)
    success = complete and not failed and run.get("status") == "passed"
    if success:
        summary = "Yerel CI geçti: bağımlılıklar, tsc, eslint, AST koruması ve testler yeşil."
    elif failed:
        summary = "Yerel CI başarısız: " + ", ".join(failed)
    else:
        summary = "Yerel CI tamamlanamadı."
    return {
        "sha": sha,
        "conclusion": "success" if success else "failure",
        "ok": success,
        "failed_steps": failed,
        "summary": summary,
        **{name: steps.get(name, skipped("önceki adım başarısız")) for name in STEPS},
    }


def checks_document(sha: str, status: str, report: dict[str, Any] | None) -> dict[str, Any]:
    """LocalForge.checks() biçimi: {"checks": [CheckRun…]} (+ rapor, ek alanlar yok sayılır)."""
    conclusion = None if report is None else report["conclusion"]
    return {
        "schema_version": 1,
        "sha": sha,
        "guncelleme": now_iso(),
        "checks": [{"name": CHECK_NAME, "status": status, "conclusion": conclusion, "url": None}],
        "report": report,
    }


def _call_runner(
    cfg: Settings, body: dict[str, Any], client: httpx.Client | None
) -> dict[str, Any]:
    timeout = cfg.run_timeout_s + cfg.run_queue_wait_s + 60
    http = client or httpx.Client(timeout=timeout)
    try:
        resp = http.post(f"{cfg.test_runner_url}/run", json=body, timeout=timeout)
    except httpx.HTTPError as exc:
        return {"ok": False, "status": "error", "error": f"test-runner'a ulaşılamadı: {exc}"}
    finally:
        if client is None:
            http.close()
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if not resp.is_success:
        detail = data.get("detail") if isinstance(data, dict) else None
        return {
            "ok": False,
            "status": "error",
            "error": f"test-runner HTTP {resp.status_code}: {detail or resp.text[:300]}",
        }
    return {
        **data,
        "ok": data.get("status") == "passed",
        # /check sözleşmesindeki adlar (MIMARI-SOZLESME §2)
        "junit_path": data.get("junit"),
        "json_path": data.get("json"),
    }


def execute(
    cfg: Settings, req: CheckRequest, *, runner_client: httpx.Client | None = None
) -> dict[str, Any]:
    full = gitforge.resolve_commit(cfg.forge_path, req.sha, cfg.git_timeout_s)
    base = (
        gitforge.resolve_commit(cfg.forge_path, req.base_sha, cfg.git_timeout_s)
        if req.base_sha
        else None
    )
    if not CHECK_LOCK.acquire(timeout=cfg.check_queue_wait_s):
        raise CheckBusy("Başka bir yerel CI kontrolü sürüyor; daha sonra yeniden deneyin.")
    try:
        return _execute_locked(cfg, req, full, base, runner_client)
    finally:
        CHECK_LOCK.release()


def _execute_locked(
    cfg: Settings,
    req: CheckRequest,
    full: str,
    base: str | None,
    runner_client: httpx.Client | None,
) -> dict[str, Any]:
    path = None if req.break_campaign else checks_file(cfg.artifacts_path, full)
    if path is not None:
        atomic_write_json(path, checks_document(full, "in_progress", None))
    started = time.monotonic()
    steps: dict[str, dict[str, Any]] = {}
    report: dict[str, Any] | None = None
    try:
        steps = _run_steps(cfg, req, full, base, runner_client)
        report = aggregate(full, steps)
    except Exception as exc:  # dosya her durumda failure ile kapanır
        report = aggregate(full, steps)
        report.update(
            conclusion="failure",
            ok=False,
            summary=f"Yerel CI beklenmeyen hata: {type(exc).__name__}: {exc}",
        )
        raise
    finally:
        if report is not None:
            report["duration_ms"] = int((time.monotonic() - started) * 1000)
            report["checks_path"] = str(path) if path is not None else None
            report["break_campaign"] = req.break_campaign
            if path is not None:
                atomic_write_json(path, checks_document(full, "completed", report))
    return report


def _run_steps(
    cfg: Settings,
    req: CheckRequest,
    full: str,
    base: str | None,
    runner_client: httpx.Client | None,
) -> dict[str, dict[str, Any]]:
    steps: dict[str, dict[str, Any]] = {}
    with gitforge.checkout(cfg.forge_path, full, cfg.e2e_root, cfg.git_timeout_s) as e2e:
        steps["deps"] = static.check_deps(cfg, e2e)
        if not steps["deps"]["ok"]:
            return steps
        gitforge.link_node_modules(e2e, cfg.e2e_node_modules)
        steps["tsc"] = static.run_tsc(cfg, e2e)
        if not steps["tsc"]["ok"]:
            return steps
        steps["eslint"] = static.run_eslint(cfg, e2e)
        if not steps["eslint"]["ok"]:
            return steps

    base_sha = base or gitforge.merge_base(cfg.forge_path, full, "main", cfg.git_timeout_s) or full
    try:
        guard = run_ast_guard(cfg, base_sha, full, req.ast_guard_mode)
        steps["ast_guard"] = {
            "ok": bool(guard.get("ok")),
            "mode": req.ast_guard_mode,
            "base_sha": base_sha,
            "report": guard,
        }
    except AstGuardError as exc:
        steps["ast_guard"] = {"ok": False, "mode": req.ast_guard_mode, "error": str(exc)}
    if not steps["ast_guard"]["ok"]:
        return steps

    body: dict[str, Any] = {
        "sha": full,
        "run_id": req.run_id or default_run_id(full),
        "repeat_each": req.repeat_each,
        "retries": req.retries,
        "test_files": req.test_files,
        "env": {"BREAK_CAMPAIGN": "1"} if req.break_campaign else {},
    }
    if req.grep:
        body["grep"] = req.grep
    steps["run"] = _call_runner(cfg, body, runner_client)
    return steps
