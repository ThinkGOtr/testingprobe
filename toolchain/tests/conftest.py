"""Ortak fikstürler: geçici bare forge deposu (demo-app/e2e), artefakt kökü, sahte node."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

TOOLCHAIN = Path(__file__).resolve().parents[1]
REPO = TOOLCHAIN.parent
DEMO_E2E = REPO / "demo-app" / "e2e"
E2E_FILES_EXCLUDE = {"node_modules", "results", "test-results", "playwright-report"}

GIT_ENV = {
    "GIT_AUTHOR_NAME": "tp-test",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "tp-test",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
}


def git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


@dataclass
class Forge:
    bare: Path
    work: Path
    main: str

    def commit(self, branch: str, files: dict[str, str | None], message: str = "değişiklik") -> str:
        """`branch` (yoksa main'den) üzerine dosya yazar/siler, push eder; commit sha'sı."""
        branches = git(self.work, "branch", "--list", branch)
        git(
            self.work,
            "checkout",
            "-q",
            branch if branches else "-b",
            *([] if branches else [branch]),
        )
        for rel, text in files.items():
            p = self.work / rel
            if text is None:
                p.unlink()
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")
        git(self.work, "add", "-A", "-f", *files)  # -f: .gitignore'lı yollar da (ör. results/)
        git(self.work, "commit", "-q", "-m", message)
        git(self.work, "push", "-q", "origin", branch)
        sha = git(self.work, "rev-parse", "HEAD")
        git(self.work, "checkout", "-q", "main")
        return sha


def _copy_e2e(dest: Path) -> None:
    def ignore(_dir: str, names: list[str]) -> set[str]:
        return {n for n in names if n in E2E_FILES_EXCLUDE}

    shutil.copytree(DEMO_E2E, dest / "e2e", ignore=ignore)


@pytest.fixture
def forge(tmp_path: Path) -> Forge:
    work = tmp_path / "work"
    bare = tmp_path / "forge" / "demo-app.git"
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    _copy_e2e(work)
    (work / "README.md").write_text("demo\n", encoding="utf-8")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "başlangıç")
    bare.parent.mkdir(parents=True)
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(bare)], check=True)
    git(work, "remote", "add", "origin", str(bare))
    return Forge(bare=bare, work=work, main=git(work, "rev-parse", "HEAD"))


@pytest.fixture
def e2e_deps(tmp_path: Path) -> Path:
    """İmajdaki /opt/e2e'nin yerel karşılığı: kilit, eslint yapılandırması, node_modules."""
    deps = tmp_path / "e2e-deps"
    deps.mkdir()
    for name in ("package.json", "package-lock.json", "eslint.config.js"):
        shutil.copy(TOOLCHAIN / "e2e-deps" / name, deps / name)
    nm = DEMO_E2E / "node_modules"
    if nm.is_dir():
        (deps / "node_modules").symlink_to(nm, target_is_directory=True)
    else:
        (deps / "node_modules").mkdir()
    return deps


@pytest.fixture
def env(
    forge: Forge, e2e_deps: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("TP_FORGE_PATH", str(forge.bare))
    monkeypatch.setenv("TP_ARTIFACTS_PATH", str(artifacts))
    monkeypatch.setenv("TP_E2E_DEPS", str(e2e_deps))
    monkeypatch.setenv("TOOLCHAIN_HOME", str(TOOLCHAIN))
    monkeypatch.setenv("DEMO_API_URL", "http://demo-api.invalid")
    monkeypatch.setenv("DEMOAPP_TEST_TOKEN", "test-belirteci")
    monkeypatch.setenv("TP_RUN_QUEUE_WAIT_S", "5")
    monkeypatch.setenv("TP_CHECK_QUEUE_WAIT_S", "5")
    # Ana makinedeki olası /forge, /opt/allure vb. testlere sızmasın.
    monkeypatch.setenv("TP_FORGE_MIRROR_PATH", str(tmp_path / "forge-mirror" / "demo-app.git"))
    monkeypatch.setenv("TP_APP_BUILD_SHA_FILE", str(tmp_path / "yok" / "demo-app-web.sha"))
    monkeypatch.setenv("TP_ALLURE_CLI", str(tmp_path / "yok" / "allure-cli.js"))
    monkeypatch.setenv("TP_ALLURE_CONFIG", str(tmp_path / "yok" / "allurerc.mjs"))
    # Süreçler arası koşu kilidi testler arasında paylaşılmasın.
    monkeypatch.setenv("TP_RUN_LOCK_PATH", str(tmp_path / "run.lock"))
    for name in (
        "DEMO_APP_BUILD_SHA",
        "TP_FORGE_REMOTE_URL",
        "TP_FORGE_REMOTE_TOKEN",
        "TP_CHECKS_PATH",
        "TP_CHECKS_REQUIRE_MOUNT",
        "TP_CHECK_REQUIRE_APP_SHA",
        "TP_TOOLCHAIN_TOKEN",
        "TP_TOOLCHAIN_REQUIRE_TOKEN",
        "TP_RUNS_KEEP_EVIDENCE_DAYS",
        "TP_RUNS_KEEP_EVIDENCE_MAX",
    ):
        monkeypatch.delenv(name, raising=False)
    yield artifacts


def make_fake_node(tmp_path: Path, body: str, name: str = "fake-node") -> Path:
    """`node` yerine geçen Python betiği; `body` argv'ye (sys.argv) göre davranır."""
    path = tmp_path / name
    path.write_text(
        f"#!{sys.executable}\nimport json, os, sys, time, pathlib\n" + textwrap.dedent(body),
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def have_node() -> bool:
    return shutil.which("node") is not None


requires_node = pytest.mark.skipif(not have_node(), reason="node yok")
requires_ast_guard = pytest.mark.skipif(
    not (TOOLCHAIN / "ast-guard" / "dist" / "src" / "cli.js").is_file()
    or not (TOOLCHAIN / "ast-guard" / "node_modules").is_dir(),
    reason="ast-guard derlenmemiş (cd toolchain/ast-guard && npm ci && npm run build)",
)
requires_symbols = pytest.mark.skipif(
    not (TOOLCHAIN / "symbols" / "dist" / "src" / "cli.js").is_file()
    or not (TOOLCHAIN / "symbols" / "node_modules").is_dir(),
    reason="symbols derlenmemiş (cd toolchain/symbols && npm ci && npm run build)",
)
requires_e2e_node_modules = pytest.mark.skipif(
    not (DEMO_E2E / "node_modules" / "typescript").is_dir()
    or not (DEMO_E2E / "node_modules" / "eslint").is_dir(),
    reason="demo-app/e2e/node_modules yok (cd demo-app/e2e && npm ci --ignore-scripts)",
)
