"""GitHub forge kipinde platform → iş akışı check'i (009 §2.7, Ş6b). GitHub'a gidilmez."""

from __future__ import annotations

import pytest

from tp_core.integrations.forge import (
    GITHUB_PLATFORM_CHECKS,
    GITHUB_PLATFORM_WORKFLOWS,
    ForgeValidationError,
    etkin_platformlar,
    github_required_checks,
)
from tp_core.integrations.forge_github import GitHubForge


def test_etkin_platformlar() -> None:
    assert etkin_platformlar({}) == ()
    assert etkin_platformlar({"TP_PLATFORMS": ""}) == ()
    assert etkin_platformlar({"TP_PLATFORMS": " Android ,web,windows,android"}) == (
        "android",
        "windows",
    )
    with pytest.raises(ForgeValidationError):
        etkin_platformlar({"TP_PLATFORMS": "android,symbian"})
    # mobil-ios.yml paths süzgeçli / push'suz: zorunlu yapılırsa ilgisiz PR süresiz bekler.
    with pytest.raises(ForgeValidationError, match="no-op"):
        etkin_platformlar({"TP_PLATFORMS": "ios"})


def test_platform_check_ve_is_akisi_adlari_ci_md_ile_ayni() -> None:
    assert GITHUB_PLATFORM_CHECKS == {
        "android": "mobil-android",
        "ios": "mobil-ios",
        "windows": "masaustu-windows",
    }
    assert GITHUB_PLATFORM_WORKFLOWS["android"] == "mobil-android.yml"
    from pathlib import Path

    kok = Path(__file__).resolve().parents[4] / ".github" / "workflows"
    if kok.is_dir():
        for dosya in GITHUB_PLATFORM_WORKFLOWS.values():
            assert (kok / dosya).is_file(), dosya


def test_github_required_checks_birlesir_ve_tekrarsiz() -> None:
    assert github_required_checks(("test-local", "semgrep"), ()) == ("test-local", "semgrep")
    assert github_required_checks(("test-local", "mobil-android"), ("android", "ios")) == (
        "test-local",
        "mobil-android",
        "mobil-ios",
    )


def test_github_forge_from_env_platform_checkleri() -> None:
    f = GitHubForge.from_env(
        {"GITHUB_REPO": "o/r", "GITHUB_TOKEN": "t", "TP_PLATFORMS": "android,windows"}
    )
    assert f.required_checks == (
        "test-local",
        "ast-guard",
        "semgrep",
        "mobil-android",
        "masaustu-windows",
    )
    # Platform yoksa varsayılan değişmez.
    assert GitHubForge.from_env({"GITHUB_REPO": "o/r", "GITHUB_TOKEN": "t"}).required_checks == (
        "test-local",
        "ast-guard",
        "semgrep",
    )
    with pytest.raises(ForgeValidationError):
        GitHubForge.from_env({"GITHUB_REPO": "o/r", "GITHUB_TOKEN": "t", "TP_PLATFORMS": "x"})
