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


# ------------------------------------------------------------- üretim dili (011 §2.8, Ş5)


def test_web_java_check_ve_is_akisi_adi() -> None:
    from tp_core.integrations.forge import WEB_JAVA_CHECK, WEB_JAVA_WORKFLOW

    assert (WEB_JAVA_CHECK, WEB_JAVA_WORKFLOW) == ("web-java", "web-java.yml")


def test_etkin_web_dilleri() -> None:
    from tp_core.integrations.forge import etkin_web_dilleri

    assert etkin_web_dilleri({}) == ("ts",)
    assert etkin_web_dilleri({"TP_WEB_DILLERI": " Java ,ts"}) == ("ts", "java")
    # Doğrulanmamış diller CI'a/PR'a girmez (K3).
    with pytest.raises(ForgeValidationError):
        etkin_web_dilleri({"TP_WEB_DILLERI": "ts,csharp"})


def test_github_required_checks_web_java() -> None:
    assert github_required_checks(("test-local",), (), ("ts",)) == ("test-local",)
    assert github_required_checks(("test-local",), ("android",), ("ts", "java")) == (
        "test-local",
        "mobil-android",
        "web-java",
    )
    f = GitHubForge.from_env(
        {"GITHUB_REPO": "o/r", "GITHUB_TOKEN": "t", "TP_WEB_DILLERI": "ts,java"}
    )
    assert f.required_checks == ("test-local", "ast-guard", "semgrep", "web-java")


def test_local_required_checks_web_java_yolu() -> None:
    from tp_core.integrations.forge import local_required_checks
    from tp_core.ports import CheckRun

    def c(ad: str) -> CheckRun:
        return CheckRun(name=ad, status="completed", conclusion="success")

    kimlikler = "e2e-java/src/test/java/com/antreklabs/bayi/ekranlar/Kimlikler.java"
    # Yalnız e2e-java/ değişen PR: web kontrolü `local-ci` zorunlu (dil ne olursa olsun).
    assert local_required_checks(("local-ci",), [], [kimlikler]) == (("local-ci",), None)
    # Yapılandırma local-ci'ı içermese de web testi değişen PR onu ister.
    zorunlu, neden = local_required_checks(("local-ci-android",), [], [kimlikler])
    assert zorunlu == ("local-ci", "local-ci-android") and neden is None
    # Uygulama kuralı değişmez: yalnız e2e-app/ değişen PR'da kayıtlı platform kontrolü yeterli.
    app = "e2e-app/src/test/java/com/antreklabs/bayi/ekranlar/Kimlikler.java"
    assert local_required_checks(("local-ci",), [c("local-ci-android")], [app]) == (
        ("local-ci-android",),
        None,
    )
    # e2e-java + e2e-app birlikte: ikisi de gerekir.
    zorunlu, _ = local_required_checks(("local-ci",), [c("local-ci-android")], [app, kimlikler])
    assert zorunlu == ("local-ci", "local-ci-android")
