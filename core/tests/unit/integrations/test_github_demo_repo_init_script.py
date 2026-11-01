"""scripts/github-demo-repo-init.sh — kuru çalışma: GitHub demo deposu ağacı (ağ yok, sır yok)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "scripts" / "github-demo-repo-init.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None
    or shutil.which("git") is None
    or not (REPO / ".git").exists()
    or not SCRIPT.exists(),
    reason="bash / git / ürün git deposu yok",
)


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GITHUB_", "GH_"))}
    env.update(TP_BOOTSTRAP_AUTHOR_NAME="t", TP_BOOTSTRAP_AUTHOR_EMAIL="t@example.invalid")
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=cwd or REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _git(d: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(d), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture(scope="module")
def agac(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, subprocess.CompletedProcess[str]]:
    out = tmp_path_factory.mktemp("demo-repo") / "agac"
    r = _run("--out", str(out))
    assert r.returncode == 0, r.stderr
    return out, r


def test_kuru_calisma_duzen_ve_cikti(agac: tuple[Path, subprocess.CompletedProcess[str]]) -> None:
    out, r = agac
    assert "KURU ÇALIŞMA" in r.stdout and "ThinkGOtr/testingprobe-demo-app" in r.stdout
    for yol in (
        "demo-app/web/Dockerfile",
        "demo-app/web/src/pages/CatalogPage.tsx",
        "demo-app/e2e/pages/catalog/locators.ts",
        "demo-app/ci/run-checks.sh",
        ".github/workflows/ci.yml",
        ".github/workflows/break-verify.yml",
        ".github/CODEOWNERS",
        "scripts/github-ast-guard-mode.sh",
        "scripts/github-ci-results.sh",
        "scripts/github-demo-serve.sh",
        "toolchain/ast-guard/src/guard.ts",
        "toolchain/security/no-mcp-in-image.sh",
        ".playwright-version",
        "README.md",
        ".gitignore",
    ):
        assert (out / yol).is_file(), yol
    # Ürün içi dosyalar ve sırlar gönderilmez.
    for yok in ("rules", "core", "docs", ".env", "toolchain/ast-guard/test/ci-workflow.test.ts",
                ".github/workflows/build-toolchain.yml", "scripts/lib.sh"):  # fmt: skip
        assert not (out / yok).exists(), yok
    assert not [p for p in out.rglob(".env*") if ".git" not in p.parts]
    assert not [p for p in out.rglob("node_modules")]


def test_ci_zorunlu_checkler_ve_golden_drift_yok(
    agac: tuple[Path, subprocess.CompletedProcess[str]],
) -> None:
    out, _ = agac
    metin = (out / ".github/workflows/ci.yml").read_text()
    jobs = yaml.safe_load(metin)["jobs"]
    assert {"changes", "test-local", "ast-guard", "semgrep"} <= set(jobs)
    assert "golden-drift" not in jobs
    for ad in ("test-local", "ast-guard", "semgrep"):
        assert jobs[ad]["name"] == ad  # ruleset zorunlu check adları
        assert jobs[ad]["runs-on"].startswith("ubuntu-")  # GitHub-hosted runner
    assert "github-demo-repo-init.sh ile üretildi" in metin.splitlines()[1]
    for ad in ("ANTHROPIC", "anthropic_api_key", "mcp-server"):
        assert ad not in metin
    if shutil.which("actionlint"):
        r = subprocess.run(["actionlint", "-no-color"], cwd=out, capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr


def test_codeowners_ve_git(agac: tuple[Path, subprocess.CompletedProcess[str]]) -> None:
    out, _ = agac
    co = (out / ".github/CODEOWNERS").read_text()
    assert "/demo-app/e2e/pages/        @gokhansipahi" in co
    assert "/.github/                   @gokhansipahi" in co
    assert _git(out, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert _git(out, "rev-parse", "demo-baseline^{commit}") == _git(out, "rev-parse", "HEAD")
    assert _git(out, "remote") == ""  # kuru çalışma uzak depo tanımlamaz
    assert _git(out, "status", "--porcelain") == ""
    assert int(_git(out, "rev-list", "--count", "HEAD")) == 1


def test_codeowner_secenegi_ve_hatalar(tmp_path: Path) -> None:
    r = _run("--out", str(tmp_path / "a"), "--codeowner", "ThinkGOtr/demo-admin")
    assert r.returncode == 0, r.stderr
    co = (tmp_path / "a" / ".github/CODEOWNERS").read_text()
    assert "@ThinkGOtr/demo-admin" in co and "@gokhansipahi" not in co

    dolu = tmp_path / "dolu"
    dolu.mkdir()
    (dolu / "x").write_text("x")
    r = _run("--out", str(dolu))
    assert r.returncode != 0 and "boş değil" in r.stderr
    r = _run("--update")
    assert r.returncode != 0 and "--push" in r.stderr
    r = _run("--repo", "kötü repo")
    assert r.returncode != 0 and "geçersiz --repo" in r.stderr


def test_goreli_out_cagiranin_dizinine_gore(tmp_path: Path) -> None:
    r = _run("--out", "goreli", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "goreli" / "demo-app" / "web" / "Dockerfile").is_file()
