from __future__ import annotations

from pathlib import Path

import pytest

from toolchain_common.artifacts import checks_file, ensure_inside, run_dir
from toolchain_common.validation import (
    validate_grep,
    validate_ref,
    validate_role,
    validate_run_id,
    validate_test_file,
    validate_test_files,
    validate_test_id,
    validate_url_path,
)


@pytest.mark.parametrize(
    "value",
    ["a" * 40, "0123abc", "main", "tp/case-1234", "demo-baseline", "release/1.2"],
)
def test_ref_accepts(value: str) -> None:
    assert validate_ref(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "-n",
        "--output=/etc/x",
        "main..evil",
        "a//b",
        "x.lock",
        "HEAD@{1}",
        "main\n",
        "../x",
        "a b",
        "x/",
        "ref;rm -rf",
    ],
)
def test_ref_rejects(value: str) -> None:
    with pytest.raises(ValueError):
        validate_ref(value)


@pytest.mark.parametrize("value", ["run-1", "check-abc.20261031T1200", "R_1"])
def test_run_id_accepts(value: str) -> None:
    assert validate_run_id(value) == value


@pytest.mark.parametrize(
    "value", ["", "../x", "a/b", ".hidden", "-x", "a..b", "x" * 101, "a b", "r1\n"]
)
def test_run_id_rejects(value: str) -> None:
    with pytest.raises(ValueError):
        validate_run_id(value)


@pytest.mark.parametrize(
    "value", ["tests/cart.spec.ts", "tests/generated/tpd-1-case-2.spec.ts", "tests/a_b.spec.ts"]
)
def test_test_file_accepts(value: str) -> None:
    assert validate_test_file(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "cart.spec.ts",
        "/abs/tests/x.spec.ts",
        "tests/../../etc/passwd.spec.ts",
        "tests/x.ts",
        "tests/-x.spec.ts",
        "tests/x.spec.ts --grep",
        "tests//x.spec.ts",
        "pages/catalog/locators.ts",
        "tests/x.spec.ts\n",
    ],
)
def test_test_file_rejects(value: str) -> None:
    with pytest.raises(ValueError):
        validate_test_file(value)


def test_test_files_dedupes_and_limits() -> None:
    assert validate_test_files(["tests/a.spec.ts", "tests/a.spec.ts"]) == ["tests/a.spec.ts"]
    with pytest.raises(ValueError):
        validate_test_files([f"tests/t{i}.spec.ts" for i in range(201)])


def test_grep() -> None:
    assert validate_grep(None) is None
    assert validate_grep("") is None
    assert validate_grep("-kampanya") == "-kampanya"  # `--grep=` biçimiyle geçer
    with pytest.raises(ValueError):
        validate_grep("a\nb")
    with pytest.raises(ValueError):
        validate_grep("x" * 301)


def test_probe_fields() -> None:
    assert validate_role("button") == "button"
    for bad in ("Button", "button;", "", "a" * 41):
        with pytest.raises(ValueError):
            validate_role(bad)
    assert validate_test_id("product-card-P-001") == "product-card-P-001"
    with pytest.raises(ValueError):
        validate_test_id('x"]')
    assert validate_url_path("/katalog") == "/katalog"
    for bad in ("katalog", "//evil.example/x", "http://x/", "/a/../b", "/a b", "/x\n"):
        with pytest.raises(ValueError):
            validate_url_path(bad)


def test_artifact_paths_stay_inside(tmp_path: Path) -> None:
    assert run_dir(tmp_path, "run-1") == tmp_path / "runs" / "run-1"
    with pytest.raises(ValueError):
        run_dir(tmp_path, "../x")
    sha = "a" * 40
    assert checks_file(tmp_path, sha) == tmp_path / "checks" / f"{sha}.json"
    with pytest.raises(ValueError):
        checks_file(tmp_path, "abc1234")  # kısa sha: LocalForge tam sha ile okur
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "link").symlink_to("/etc", target_is_directory=True)
    with pytest.raises(ValueError):
        ensure_inside(tmp_path, tmp_path / "runs" / "link")
