"""Shared /health helpers for toolchain-worker and test-runner (contracts/health.md)."""

import json
import os
import subprocess
from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

NODE_MODULES = Path(os.environ.get("TOOLCHAIN_NODE_MODULES", "/opt/toolchain/node_modules"))
APP_VERSION = version("testingprobe-toolchain")


def check_playwright() -> str:
    """Installed playwright-core must equal PLAYWRIGHT_VERSION (.playwright-version)."""
    expected = os.environ.get("PLAYWRIGHT_VERSION")
    if not expected:
        return "error: PLAYWRIGHT_VERSION not set"
    try:
        pkg = json.loads((NODE_MODULES / "playwright-core" / "package.json").read_text())
    except (OSError, ValueError) as exc:
        return f"error: playwright-core not found ({exc})"
    installed = pkg.get("version")
    if installed != expected:
        return f"error: installed {installed}, expected {expected}"
    return "ok"


def check_node() -> str:
    try:
        out = subprocess.run(
            ["node", "--version"], capture_output=True, text=True, timeout=3, check=True
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"error: {exc}"
    return f"ok ({out.stdout.strip()})"


def check_artifacts() -> str:
    """TP_ARTIFACTS_PATH yazılabilir mi (checks/ ve runs/ buraya yazılır)."""
    from toolchain_common.artifacts import check_writable
    from toolchain_common.settings import settings

    return check_writable(settings().artifacts_path)


def create_app(service: str, checks: dict) -> FastAPI:
    app = FastAPI(
        title=service, version=APP_VERSION, docs_url=None, redoc_url=None, openapi_url=None
    )

    @app.get("/health")
    def health() -> JSONResponse:
        results = {name: fn() for name, fn in checks.items()}
        healthy = all(r.startswith("ok") for r in results.values())
        body = {
            "service": service,
            "status": "ok" if healthy else "degraded",
            "version": APP_VERSION,
            "checks": results,
        }
        return JSONResponse(body, status_code=200 if healthy else 503)

    return app
