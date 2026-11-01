"""toolchain_common.mirror_export: GitHub kipinde demo-app-web arşivi aynadan (salt okuma)."""

from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path

import pytest

from tests.conftest import Forge, git
from toolchain_common import mirror_export
from toolchain_common.settings import settings


@pytest.fixture
def remote(forge: Forge, tmp_path: Path) -> dict[str, str]:
    """Sahte GitHub: yerel forge'da olmayan main commit'i (demo-app/web altında)."""
    bare = tmp_path / "github" / "demo-app.git"
    bare.parent.mkdir()
    subprocess.run(["git", "clone", "-q", "--bare", str(forge.bare), str(bare)], check=True)
    work = tmp_path / "gh-work"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], check=True)
    web = work / "demo-app" / "web"
    (web / "src").mkdir(parents=True)
    (web / "Dockerfile").write_text("FROM scratch\n")
    (web / "src" / "Catalog.tsx").write_text('<button data-testid="cart-add" />\n')
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "github main")
    git(work, "push", "-q", "origin", "main")
    return {
        "url": f"file://{bare}",
        "main": git(work, "rev-parse", "HEAD"),
        "tree": git(work, "rev-parse", "HEAD:demo-app/web"),
    }


def _run(capfdbinary: pytest.CaptureFixture[bytes], *args: str) -> tuple[int, bytes, bytes]:
    rc = mirror_export.main(list(args), cfg=settings())
    cap = capfdbinary.readouterr()
    return rc, cap.out, cap.err


def test_arsiv_ve_agac_aynadan(
    env: Path,
    remote: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capfdbinary: pytest.CaptureFixture[bytes],
) -> None:
    sha = remote["main"]
    monkeypatch.delenv("TP_FORGE_REMOTE_URL", raising=False)
    rc, _out, err = _run(capfdbinary, "tree", "--ref", sha, "--path", "demo-app/web")
    assert rc == 3 and b"TP_FORGE_REMOTE_URL" in err  # ayna yok, uzak depo yok

    monkeypatch.setenv("TP_FORGE_REMOTE_URL", remote["url"])
    rc, out, _ = _run(capfdbinary, "tree", "--ref", sha, "--path", "demo-app/web")
    assert rc == 0 and out.decode().strip() == remote["tree"]
    rc, out, _ = _run(capfdbinary, "archive", "--ref", sha, "--path", "demo-app/web")
    assert rc == 0
    with tarfile.open(fileobj=io.BytesIO(out)) as t:
        names = set(t.getnames())
    assert "Dockerfile" in names and "src/Catalog.tsx" in names  # kök = demo-app/web

    rc, _out, err = _run(capfdbinary, "archive", "--ref", sha, "--path", "demo-app/yok")
    assert rc == 3 and b"yok" in err


@pytest.mark.parametrize(
    ("ref", "path"),
    [
        ("main", "demo-app/web"),  # ad çözülmez: tam sha
        ("a" * 12, "demo-app/web"),
        ("a" * 40, "../etc"),
        ("a" * 40, "/abs"),
        ("a" * 40, "-x"),  # --path=-x biçiminde (seçenek enjeksiyonu)
        ("a" * 40, "demo-app/../web"),
    ],
)
def test_girdi_dogrulama(
    env: Path, ref: str, path: str, capfdbinary: pytest.CaptureFixture[bytes]
) -> None:
    rc, out, _err = _run(capfdbinary, "archive", f"--ref={ref}", f"--path={path}")
    assert rc == 2 and out == b""
