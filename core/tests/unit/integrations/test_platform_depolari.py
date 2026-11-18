"""Platform başına GitHub deposu (platform-depo ANALIZ §2.3–2.4, §3.2.1, §3.2.9; Şerit T1):
`ProjeOrtami(pid, platform)` kaplaması, depo kimliği, devralma kuralı, zorunlu check'ler, ayna
yolları, istemci önbelleği ve toolchain `proje` bloğu."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tp_core.integrations import forge_yollari, proje_ortami, toolchain_blogu
from tp_core.integrations.forge import (
    GecersizPlatformDeposu,
    etkin_platformlar,
    get_forge,
)
from tp_core.integrations.proje_ortami import ProjeOrtami, depo_anahtari
from tp_core.proje import istemciler, proje_icinde

B = "test-b"
MOBIL = "Org/Bayi-Mobil"


@pytest.fixture
def forge_kok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TP_FORGE_PATH", str(tmp_path / "forge" / "demo-app.git"))
    monkeypatch.setenv("TP_FORGE_PRS_PATH", str(tmp_path / "forge" / "tp-prs.json"))
    monkeypatch.setenv("TP_FORGE_MIRROR_PATH", str(tmp_path / "forge-mirror" / "demo-app.git"))
    return tmp_path


@pytest.fixture
def temiz() -> Iterator[None]:
    istemciler.sifirla()
    yield
    istemciler.sifirla()


@pytest.fixture
def github(proje: Any, proje_ayar: Any, forge_kok: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Varsayılan proje GitHub kipinde, token kimliği (Home bağlantısı yok)."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    proje_ayar(
        TP_FORGE="github",
        GITHUB_REPO="org/bayi",
        TP_FORGE_CHECK_REF="main",
        TP_E2E_APP_ROOT="demo-app/e2e-app",
        TP_FORGE_APP_ROOT="demo-app",
        TP_APP_PATHS="demo-app/web,demo-app/api",
        TP_REQUIRED_CHECKS="test-local,ast-guard,semgrep",
        TP_PLATFORMS="android,ios,windows",
        TP_WEB_DILLERI="ts,java",
        TP_FORGE_REMOTE_URL="https://github.com/org/bayi.git",
    )
    return proje_ayar


# ------------------------------------------------------------------ geriye uyum (ayrı depo yok)


def test_ayri_depo_yoksa_gorunum_birebir(github: Any) -> None:
    taban = ProjeOrtami()
    for p in (None, "web", "android", "ios", "windows", "ai_agent"):
        g = ProjeOrtami(platform=p)
        assert not g.ayri_depo and g.depo == "" and depo_anahtari(p) == ""
        for ad in (
            "GITHUB_REPO",
            "TP_FORGE_CHECK_REF",
            "TP_E2E_APP_ROOT",
            "TP_FORGE_APP_ROOT",
            "TP_APP_PATHS",
            "TP_REQUIRED_CHECKS",
            "TP_PLATFORMS",
            "TP_WEB_DILLERI",
            "TP_FORGE_REMOTE_URL",
        ):
            assert g.get(ad) == taban.get(ad), ad
    assert taban["TP_PLATFORMS"] == "android,ios,windows"
    assert proje_ortami.proje_depolari() == {"": ("android", "ios", "windows")}


def test_ayni_depo_yazilirsa_varsayilan(github: Any) -> None:
    github(GITHUB_REPO_ANDROID="ORG/Bayi")  # büyük/küçük harf duyarsız
    assert depo_anahtari("android") == ""
    assert not ProjeOrtami(platform="android").ayri_depo


def test_local_kipte_platform_deposu_yok_sayilir(
    proje: Any, proje_ayar: Any, forge_kok: Path, caplog: pytest.LogCaptureFixture
) -> None:
    proje_ayar(TP_FORGE="local", GITHUB_REPO_ANDROID=MOBIL)
    assert depo_anahtari("android") == ""
    assert not ProjeOrtami(platform="android").ayri_depo
    assert "TP_FORGE=local" in caplog.text


# ------------------------------------------------------------------------- platform kaplaması


def test_ayri_depo_kaplamasi_devralma_kurali(github: Any) -> None:
    github(GITHUB_REPO_ANDROID=MOBIL, TP_E2E_APP_ROOT_ANDROID="e2e-app")
    g = ProjeOrtami(platform="android")
    assert g.ayri_depo and g.depo == "org/bayi-mobil"
    assert g["GITHUB_REPO"] == MOBIL  # gösterim/yazım config'teki gibi
    assert g["TP_FORGE_CHECK_REF"] == "main"  # devralır
    assert g["TP_E2E_APP_ROOT"] == "e2e-app"  # platform değeri
    assert g["TP_FORGE_APP_ROOT"] == ""  # devralmaz (depo kökü)
    assert g["TP_APP_PATHS"] == ""  # devralmaz
    assert g["TP_REQUIRED_CHECKS"] == "mobil-android"  # devralmaz: taban web check'leri yok
    assert g["TP_PLATFORMS"] == "android"
    assert g["TP_WEB_DILLERI"] == ""
    assert g["TP_FORGE_REPO_NAME"] == "Bayi-Mobil"
    assert g["TP_FORGE_REMOTE_URL"] == f"https://github.com/{MOBIL}.git"
    assert "org/bayi-mobil" in repr(g)


def test_platform_degerleri_tabani_ezer(github: Any) -> None:
    github(
        GITHUB_REPO_WINDOWS="org/masaustu",
        TP_FORGE_CHECK_REF_WINDOWS="develop",
        TP_FORGE_APP_ROOT_WINDOWS="app",
        TP_APP_PATHS_WINDOWS="app/src",
        TP_REQUIRED_CHECKS_WINDOWS="build,masaustu-windows",
    )
    g = ProjeOrtami(platform="windows")
    assert g["TP_FORGE_CHECK_REF"] == "develop"
    assert g["TP_FORGE_APP_ROOT"] == "app"
    assert g["TP_APP_PATHS"] == "app/src"
    assert g["TP_REQUIRED_CHECKS"] == "build,masaustu-windows"


def test_varsayilan_depodan_tasinan_platform_cikar(github: Any) -> None:
    github(GITHUB_REPO_ANDROID=MOBIL)
    assert ProjeOrtami()["TP_PLATFORMS"] == "ios,windows"
    assert etkin_platformlar(ProjeOrtami()) == ("windows",)  # ios zorunlu olamaz (uyarı)
    assert ProjeOrtami(platform="web")["TP_PLATFORMS"] == "ios,windows"
    # Taban zorunlu check'leri ve web dilleri varsayılan depoda aynen kalır.
    assert ProjeOrtami()["TP_REQUIRED_CHECKS"] == "test-local,ast-guard,semgrep"
    assert ProjeOrtami()["TP_WEB_DILLERI"] == "ts,java"


def test_ayni_depoyu_paylasan_platformlar_tek_depo(github: Any) -> None:
    github(GITHUB_REPO_ANDROID=MOBIL, GITHUB_REPO_IOS="org/bayi-mobil")
    assert depo_anahtari("android") == depo_anahtari("ios") == "org/bayi-mobil"
    assert proje_ortami.depoya_dusen_platformlar("org/bayi-mobil") == ("android", "ios")
    a, i = ProjeOrtami(platform="android"), ProjeOrtami(platform="ios")
    assert a["TP_PLATFORMS"] == i["TP_PLATFORMS"] == "android,ios"
    assert a["TP_REQUIRED_CHECKS"] == "mobil-android,mobil-ios"
    assert a["TP_FORGE_MIRROR_PATH"] == i["TP_FORGE_MIRROR_PATH"]
    assert ProjeOrtami()["TP_PLATFORMS"] == "windows"


def test_ayna_kapaliysa_adres_turetilmez(github: Any) -> None:
    github(GITHUB_REPO_IOS="org/ios", TP_FORGE_REMOTE_URL=None)
    assert ProjeOrtami(platform="ios")["TP_FORGE_REMOTE_URL"] == ""


def test_ayna_adresi_web_url_den(github: Any) -> None:
    github(GITHUB_REPO_IOS="org/ios", TP_FORGE_WEB_URL="https://ghe.ornek.invalid/")
    assert ProjeOrtami(platform="ios")["TP_FORGE_REMOTE_URL"] == (
        "https://ghe.ornek.invalid/org/ios.git"
    )


@pytest.mark.parametrize("deger", ["org", "org/../x", "org/..", "a b/c", "-org/x", "org/x/y"])
def test_gecersiz_platform_deposu(github: Any, deger: str) -> None:
    github(GITHUB_REPO_ANDROID=deger)
    with pytest.raises(GecersizPlatformDeposu):
        depo_anahtari("android")
    with pytest.raises(GecersizPlatformDeposu):
        ProjeOrtami(platform="android")
    # Bozuk android deposu web'i ve diğer platformları düşürmez.
    assert ProjeOrtami()["TP_PLATFORMS"] == "android,ios,windows"
    assert ProjeOrtami(platform="ios").get("GITHUB_REPO") == "org/bayi"


# ------------------------------------------------------------------- kayıtlı depo kimliği


def test_kayitli_depo_config_te_yoksa_kayittaki_adla(github: Any) -> None:
    g = ProjeOrtami(platform="ios", depo="org/eski-ios")
    assert g.ayri_depo and g["GITHUB_REPO"] == "org/eski-ios"
    assert g["TP_REQUIRED_CHECKS"] == "mobil-ios"  # platform ipucu
    assert ProjeOrtami(depo="").depo == "" and ProjeOrtami(depo="ORG/bayi").depo == ""


# ---------------------------------------------------------------------------- forge yolları


def test_platform_ayna_yollari(github: Any, forge_kok: Path) -> None:
    ayna = forge_kok / "forge-mirror"
    assert (
        forge_yollari.ayna_yolu("test-a", "org/x") == ayna / "_depolar" / "test-a" / "org" / "x.git"
    )
    assert forge_yollari.ayna_yolu(B, "org/x") == ayna / "_depolar" / B / "org" / "x.git"
    assert forge_yollari.depo_yolu(B, "org/x") == (
        forge_kok / "forge" / "_depolar" / B / "org" / "x.git"
    )
    # depo='' = bugünkü yollar
    assert forge_yollari.ayna_yolu("test-a", "") == ayna / "demo-app.git"
    assert forge_yollari.ayna_yolu(B) == ayna / f"{B}.git"


@pytest.mark.parametrize("depo", ["org/..", "org/.", "../x", "org", "Org/x", "o/x/y", "o/a b"])
def test_platform_ayna_yolu_gecersiz(proje: Any, forge_kok: Path, depo: str) -> None:
    with pytest.raises(forge_yollari.GecersizProjeKimligi):
        forge_yollari.ayna_yolu("test-a", depo)


# ------------------------------------------------------------------------ istemci önbelleği


def test_forge_platforma_gore_ayri_istemci(github: Any, temiz: None) -> None:
    from tp_core.integrations.forge_github import GitHubForge

    github(GITHUB_REPO_ANDROID=MOBIL, GITHUB_REPO_IOS=MOBIL)
    web = istemciler.forge()
    android = istemciler.forge("android")
    ios = istemciler.forge("ios")
    windows = istemciler.forge("windows")
    assert isinstance(web, GitHubForge) and isinstance(android, GitHubForge)
    assert web.repo == "org/bayi" and windows is web  # ayrı depo yok = varsayılan istemci
    assert android.repo == MOBIL and ios is android  # aynı depo = aynı istemci
    assert istemciler.forge("web") is web
    assert istemciler.forge_depo("") is web
    assert istemciler.forge_depo("org/bayi-mobil") is android
    # Merge kapısı: mobil depoda web check'leri beklenmez.
    assert "test-local" not in android.required_checks
    assert set(android.required_checks) >= {"mobil-android", "mobil-ios"}
    assert "mobil-android" not in web.required_checks
    assert "test-local" in web.required_checks


def test_ci_platform_deposunun_forgeunu_kullanir(github: Any, temiz: None) -> None:
    github(GITHUB_REPO_WINDOWS="org/masaustu")
    ci_w = istemciler.ci("windows")
    ci_web = istemciler.ci()
    assert ci_w is not None and ci_web is not None and ci_w is not ci_web
    assert istemciler.ci_depo("org/masaustu") is ci_w


def test_get_forge_platform_parametresi(github: Any, temiz: None) -> None:
    github(GITHUB_REPO_ANDROID=MOBIL)
    assert get_forge(platform="android").repo == MOBIL  # type: ignore[attr-defined]
    assert get_forge().repo == "org/bayi"  # type: ignore[attr-defined]


def test_ci_okuyucu_platform_deposu(github: Any, temiz: None) -> None:
    from tp_core.features.ci.clients import GitHubCiOkuyucu

    github(GITHUB_REPO_ANDROID=MOBIL, GITHUB_READ_TOKEN="ghr_okuma")
    assert GitHubCiOkuyucu.kur(platform="android")._repo == MOBIL
    assert GitHubCiOkuyucu.kur()._repo == "org/bayi"


def test_diger_projenin_platform_deposu_sizmaz(github: Any, forge_kok: Path) -> None:
    github(GITHUB_REPO_ANDROID=MOBIL)
    with proje_icinde(B):
        assert depo_anahtari("android") == ""
        assert not ProjeOrtami(platform="android").ayri_depo


# ------------------------------------------------------------------------- toolchain bloğu


def test_toolchain_blogu_platform_deposu(github: Any, forge_kok: Path) -> None:
    github(GITHUB_REPO_ANDROID=MOBIL, TP_E2E_APP_ROOT_ANDROID="e2e-app")
    blok = istemciler.toolchain_proje_blogu("android")
    assert blok["pid"] == "test-a"
    assert blok["mirror_path"] == str(
        forge_kok / "forge-mirror" / "_depolar" / "test-a" / "org" / "bayi-mobil.git"
    )
    assert blok["forge_path"] == str(
        forge_kok / "forge" / "_depolar" / "test-a" / "org" / "bayi-mobil.git"
    )
    assert blok["remote_url"] == f"https://github.com/{MOBIL}.git"
    assert blok["e2e_app_root"] == "e2e-app"
    assert blok["app_paths"] == []  # devralmaz
    # Platform verilmezse ya da ayrı depo yoksa bugünkü blok.
    taban = istemciler.toolchain_proje_blogu()
    assert "mirror_path" not in taban and istemciler.toolchain_proje_blogu("ios") == taban


def test_toolchain_blogu_ayna_token_host_kurali(
    github: Any, forge_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    github(GITHUB_REPO_ANDROID=MOBIL, TP_FORGE_WEB_URL="https://kotu.invalid")
    monkeypatch.setattr(toolchain_blogu, "_uzak_token", lambda pid: "ghs_tok")
    blok = toolchain_blogu.proje_blogu(platform="android")
    assert blok["remote_url"] == f"https://kotu.invalid/{MOBIL}.git"
    assert "remote_token" not in blok  # izinli GitHub host'u değil
    github(TP_FORGE_WEB_URL=None)
    assert toolchain_blogu.proje_blogu(platform="android")["remote_token"] == "ghs_tok"


def test_toolchain_blogu_java_kokleri_ve_uygulama_yollari(
    proje: Any, proje_ayar: Any, forge_kok: Path
) -> None:
    with proje_icinde(B):
        proje_ayar(
            pid=B,
            TP_E2E_APP_ROOT="b/e2e-app",
            TP_E2E_JAVA_ROOT="b/e2e-java",
            TP_APP_PATHS="b/web, b/api",
        )
        blok = istemciler.toolchain_proje_blogu()
        assert blok["e2e_app_root"] == "b/e2e-app"
        assert blok["e2e_java_root"] == "b/e2e-java"
        assert blok["app_paths"] == ["b/web", "b/api"]
