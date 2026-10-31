"""Ortam değişkenleri (her çağrıda okunur; testler ortamı değiştirebilir)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    forge_path: Path
    artifacts_path: Path
    e2e_root: str
    e2e_deps: Path
    toolchain_home: Path
    node: str
    test_runner_url: str
    base_url: str
    demo_api_url: str
    demoapp_test_token: str
    probe_base_url: str
    probe_app_sha: str
    probe_user: str
    probe_password: str
    run_dealers: tuple[str, ...]
    git_timeout_s: float
    tsc_timeout_s: float
    eslint_timeout_s: float
    ast_guard_timeout_s: float
    symbols_timeout_s: float
    probe_timeout_s: float
    run_timeout_s: float
    run_queue_wait_s: float
    check_queue_wait_s: float

    @property
    def ast_guard_cli(self) -> Path:
        return self.toolchain_home / "ast-guard" / "dist" / "src" / "cli.js"

    @property
    def symbols_cli(self) -> Path:
        return self.toolchain_home / "symbols" / "dist" / "src" / "cli.js"

    @property
    def probe_script(self) -> Path:
        return self.toolchain_home / "probe" / "locator-probe.mjs"

    @property
    def e2e_node_modules(self) -> Path:
        return self.e2e_deps / "node_modules"


def settings() -> Settings:
    env = os.environ.get
    return Settings(
        forge_path=Path(env("TP_FORGE_PATH", "/forge/demo-app.git")),
        artifacts_path=Path(env("TP_ARTIFACTS_PATH", "/artifacts")),
        e2e_root=env("TP_E2E_ROOT", "e2e"),
        e2e_deps=Path(env("TP_E2E_DEPS", "/opt/e2e")),
        toolchain_home=Path(env("TOOLCHAIN_HOME", "/opt/toolchain")),
        node=env("TP_NODE", "node"),
        test_runner_url=env("TEST_RUNNER_URL", "http://test-runner:8200").rstrip("/"),
        base_url=env("BASE_URL", "http://demo-app-web:8080").rstrip("/"),
        demo_api_url=env("DEMO_API_URL", "http://demo-app-api:8000").rstrip("/"),
        demoapp_test_token=env("DEMOAPP_TEST_TOKEN", ""),
        probe_base_url=env("DEMO_WEB_URL", "http://demo-app-web:8080").rstrip("/"),
        # Çalışan demo uygulamasının derlendiği commit (biliniyorsa). Boşsa /locator-probe
        # ölçümün istenen sha'ya ait olduğunu doğrulayamaz ve bunu yanıtında açıkça belirtir.
        probe_app_sha=env("DEMO_APP_BUILD_SHA", "").strip(),
        # DEMO-VERISI.md: bayi1 / Demo123! (sentetik demo kullanıcısı; yoklama salt okunur gezinir).
        probe_user=env("TP_PROBE_USER", "bayi1"),
        probe_password=env("TP_PROBE_PASSWORD", "Demo123!"),
        run_dealers=tuple(
            d.strip() for d in env("TP_RUN_DEALERS", "bayi1,bayi2").split(",") if d.strip()
        ),
        git_timeout_s=_float("TP_GIT_TIMEOUT_S", 60),
        tsc_timeout_s=_float("TP_TSC_TIMEOUT_S", 180),
        eslint_timeout_s=_float("TP_ESLINT_TIMEOUT_S", 240),
        ast_guard_timeout_s=_float("TP_AST_GUARD_TIMEOUT_S", 60),
        symbols_timeout_s=_float("TP_SYMBOLS_TIMEOUT_S", 60),
        probe_timeout_s=_float("TP_PROBE_TIMEOUT_S", 60),
        run_timeout_s=_float("TP_RUN_TIMEOUT_S", 900),
        run_queue_wait_s=_float("TP_RUN_QUEUE_WAIT_S", 600),
        check_queue_wait_s=_float("TP_CHECK_QUEUE_WAIT_S", 900),
    )
