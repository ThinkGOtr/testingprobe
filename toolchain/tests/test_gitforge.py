from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from tests.conftest import Forge
from toolchain_common import gitforge


def test_resolve_full_short_and_branch(forge: Forge) -> None:
    assert gitforge.resolve_commit(forge.bare, forge.main) == forge.main
    assert gitforge.resolve_commit(forge.bare, forge.main[:10]) == forge.main
    assert gitforge.resolve_commit(forge.bare, "main") == forge.main
    head = forge.commit("tp/case-1", {"e2e/tests/yeni.spec.ts": "// yeni\n"})
    assert gitforge.resolve_commit(forge.bare, "tp/case-1") == head


def test_resolve_unknown_and_invalid(forge: Forge) -> None:
    with pytest.raises(gitforge.CommitNotFound):
        gitforge.resolve_commit(forge.bare, "f" * 40)
    with pytest.raises(gitforge.CommitNotFound):
        gitforge.resolve_commit(forge.bare, "yok-boyle-dal")
    with pytest.raises(ValueError):
        gitforge.resolve_commit(forge.bare, "--all")


def test_missing_repo(tmp_path: Path) -> None:
    with pytest.raises(gitforge.ForgeError):
        gitforge.resolve_commit(tmp_path / "yok.git", "main")


def test_checkout_extracts_commit_tree_and_cleans_up(forge: Forge) -> None:
    head = forge.commit("tp/case-2", {"e2e/tests/yeni.spec.ts": "// yeni\n"})
    with gitforge.checkout(forge.bare, head, "e2e") as e2e:
        assert (e2e / "pages" / "catalog" / "locators.ts").is_file()
        assert (e2e / "tests" / "yeni.spec.ts").read_text() == "// yeni\n"
        assert not (e2e.parent / "README.md").exists()  # yalnızca istenen alt ağaç
        tmp = e2e.parent
    assert not tmp.exists()
    with gitforge.checkout(forge.bare, forge.main, "e2e") as e2e:
        assert not (e2e / "tests" / "yeni.spec.ts").exists()


def test_checkout_missing_subdir(forge: Forge) -> None:
    with pytest.raises(gitforge.ForgeError), gitforge.checkout(forge.bare, forge.main, "yok"):
        pass


def _tar(members: list[tarfile.TarInfo], data: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for m in members:
            payload = data.get(m.name)
            if payload is not None:
                m.size = len(payload)
                tar.addfile(m, io.BytesIO(payload))
            else:
                tar.addfile(m)
    return buf.getvalue()


def test_extract_rejects_path_traversal_and_outside_links(tmp_path: Path) -> None:
    evil = tarfile.TarInfo("e2e/../../kacis.txt")
    with pytest.raises(tarfile.FilterError):
        gitforge.extract_archive(_tar([evil], {"e2e/../../kacis.txt": b"x"}), tmp_path / "d")
    assert not (tmp_path / "kacis.txt").exists()
    link = tarfile.TarInfo("e2e/passwd")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    with pytest.raises(tarfile.FilterError):
        gitforge.extract_archive(_tar([link], {}), tmp_path / "d2")


def test_link_node_modules_replaces_committed_dir(tmp_path: Path) -> None:
    e2e = tmp_path / "e2e"
    fake = e2e / "node_modules" / "typescript" / "bin"
    fake.mkdir(parents=True)
    (fake / "tsc").write_text("kötü kod")
    image_nm = tmp_path / "image-nm"
    image_nm.mkdir()
    gitforge.link_node_modules(e2e, image_nm)
    assert (e2e / "node_modules").is_symlink()
    assert (e2e / "node_modules").resolve() == image_nm.resolve()
    gitforge.link_node_modules(e2e, image_nm)  # idempotent
    assert (e2e / "node_modules").resolve() == image_nm.resolve()
