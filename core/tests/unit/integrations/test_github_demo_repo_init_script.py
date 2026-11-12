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
        # Java web hattı (011, OPS-Y1): e2e-java ile iş akışı, guard aracı ve güvenilir pom.
        "demo-app/e2e-java/pom.xml",
        "demo-app/ci/run-java-checks.sh",
        ".github/workflows/web-java.yml",
        "toolchain/java-araclar/pom.xml",
        "toolchain/java-araclar/mvnw",
        "toolchain/java-araclar/src/main/java/com/antreklabs/tp/javaaraclar/Main.java",
        "toolchain/e2e-java-deps/pom.xml",
        "README.md",
        ".gitignore",
    ):
        assert (out / yol).is_file(), yol
    # Ürün içi dosyalar ve sırlar gönderilmez.
    for yok in ("rules", "core", "docs", ".env", "toolchain/ast-guard/test/ci-workflow.test.ts",
                ".github/workflows/build-toolchain.yml", "scripts/lib.sh"):  # fmt: skip
        assert not (out / yok).exists(), yok
    assert not [p for p in out.rglob(".env*") if ".git" not in p.parts]
    # pom kilidi: gönderilen hedef pom güvenilir pom ile bayt eşit.
    assert (out / "demo-app/e2e-java/pom.xml").read_bytes() == (
        out / "toolchain/e2e-java-deps/pom.xml"
    ).read_bytes()
    assert os.access(out / "toolchain/java-araclar/mvnw", os.X_OK)
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
    wj = yaml.safe_load((out / ".github/workflows/web-java.yml").read_text())["jobs"]
    assert wj["web-java"]["name"] == "web-java"
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


def test_update_uretilen_testleri_uzak_mainde_birakir(tmp_path: Path) -> None:
    """K-T14: `--push --update` güncelleme dalı merge edilmiş üretilen testleri silmez, ürün
    deposundaki örnekleri eklemez; diğer değişiklikler (ör. güvenilir pom) gider. Uzak depo yerel
    bare depodur (url.insteadOf); ağ yok."""
    uzak = tmp_path / "uzak" / "o" / "r.git"
    uzak.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(uzak)], check=True)
    gcfg = tmp_path / "gitconfig"
    gcfg.write_text(
        f'[url "file://{tmp_path / "uzak"}/"]\n\tinsteadOf = https://github.com/\n'
        "[user]\n\tname = t\n\temail = t@example.invalid\n"
    )
    env_ek = {"GIT_CONFIG_GLOBAL": str(gcfg), "GIT_CONFIG_NOSYSTEM": "1"}

    def kos(*a: str) -> subprocess.CompletedProcess[str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GITHUB_", "GH_"))}
        env.update(TP_BOOTSTRAP_AUTHOR_NAME="t", TP_BOOTSTRAP_AUTHOR_EMAIL="t@example.invalid")
        env.update(env_ek)
        return subprocess.run(
            ["bash", str(SCRIPT), "--repo", "o/r", *a],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )

    r = kos("--push", "--out", str(tmp_path / "ilk"))
    assert r.returncode == 0, r.stderr + r.stdout

    # Uzak main: merge edilmiş üretilen testler + eski pom; ürün örneği uzakta yok.
    w = tmp_path / "w"
    genv = {**os.environ, **env_ek}
    subprocess.run(["git", "clone", "-q", str(uzak), str(w)], check=True, env=genv)
    ure = "demo-app/e2e-java/src/test/java/com/antreklabs/bayi/uretilen"
    ornek = sorted((w / ure).glob("TP*Test.java"))
    assert ornek, "ürün deposunda uretilen/ örneği bekleniyordu"
    ornek[0].unlink()
    (w / ure / "MergeTest.java").write_text("class MergeTest {}\n")
    (w / "demo-app/e2e/tests/generated").mkdir(parents=True, exist_ok=True)
    (w / "demo-app/e2e/tests/generated/merged.spec.ts").write_text("m\n")
    pom = w / "demo-app/e2e-app/pom.xml"
    pom.write_text(pom.read_text().replace("<project", "<!-- eski -->\n<project", 1))
    for c in (["add", "-A"], ["commit", "-q", "-m", "merge"], ["push", "-q", "origin", "main"]):
        subprocess.run(["git", "-C", str(w), *c], check=True, env=genv)
    uzak_main = _git(w, "rev-parse", "HEAD")

    r = kos("--push", "--update", "--out", str(tmp_path / "iki"))
    assert r.returncode == 0, r.stderr + r.stdout
    assert "korundu" in r.stdout
    dal = next(s.split()[1] for s in r.stdout.splitlines() if s.startswith("Gönderildi:"))
    subprocess.run(["git", "-C", str(w), "fetch", "-q", "origin", dal], check=True, env=genv)
    fark = _git(w, "diff", "--name-status", uzak_main, "FETCH_HEAD").splitlines()
    assert fark == ["M\tdemo-app/e2e-app/pom.xml"]
