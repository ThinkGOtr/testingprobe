"""Çok proje entegrasyonları (TP-COK-PROJE-PLANI §4, Şerit 3): forge yolları, proje config görünümü,
Jira ayarları, istemci fabrikası, toolchain `proje` bloğu ve bağlantı token'ı proje başına."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from tp_core.home_config import baglanti
from tp_core.integrations import forge_yollari, jira, proje_ortami, toolchain_blogu
from tp_core.integrations.proje_ortami import ProjeOrtami
from tp_core.proje import istemciler, proje_icinde

B = "test-b"


@pytest.fixture
def forge_kok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TP_FORGE_PATH", str(tmp_path / "forge" / "demo-app.git"))
    monkeypatch.setenv("TP_FORGE_PRS_PATH", str(tmp_path / "forge" / "tp-prs.json"))
    monkeypatch.setenv("TP_FORGE_MIRROR_PATH", str(tmp_path / "forge-mirror" / "demo-app.git"))
    return tmp_path


@pytest.fixture
def temiz() -> Iterator[None]:
    istemciler.sifirla()
    jira.get_jira_settings.cache_clear()
    yield
    istemciler.sifirla()
    jira.get_jira_settings.cache_clear()


# ------------------------------------------------------------------------------ forge yolları


def test_forge_yollari_varsayilan_eski_yollar(proje: Any, forge_kok: Path) -> None:
    assert forge_yollari.depo_yolu("test-a") == forge_kok / "forge" / "demo-app.git"
    assert forge_yollari.pr_dosyasi("test-a") == forge_kok / "forge" / "tp-prs.json"
    assert forge_yollari.pr_dizini("test-a") == forge_kok / "forge"
    assert forge_yollari.ayna_yolu("test-a") == forge_kok / "forge-mirror" / "demo-app.git"


def test_forge_yollari_diger_proje(proje: Any, forge_kok: Path) -> None:
    assert forge_yollari.depo_yolu(B) == forge_kok / "forge" / B / "repo.git"
    assert forge_yollari.pr_dizini(B) == forge_kok / "forge" / B / "prs"
    assert forge_yollari.pr_dosyasi(B) == forge_kok / "forge" / B / "prs" / "tp-prs.json"
    assert forge_yollari.ayna_yolu(B) == forge_kok / "forge-mirror" / f"{B}.git"


@pytest.mark.parametrize("pid", ["../x", "a/b", "", ".gizli", "a b", "x" * 65])
def test_forge_yollari_gecersiz_pid(proje: Any, pid: str) -> None:
    with pytest.raises(forge_yollari.GecersizProjeKimligi):
        forge_yollari.depo_yolu(pid)


# ---------------------------------------------------------------------------- ProjeOrtami


def test_proje_ortami_varsayilan_env_diger_sizdirmaz(
    proje: Any, proje_ayar: Any, forge_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JIRA_PROJECT", "TPD")
    monkeypatch.setenv("TP_GIT_TIMEOUT_S", "61")
    a = ProjeOrtami()
    assert a.pid == "test-a" and a["JIRA_PROJECT"] == "TPD"
    assert a["TP_FORGE_PATH"] == str(forge_kok / "forge" / "demo-app.git")
    with proje_icinde(B):
        b = ProjeOrtami()
        assert b.get("JIRA_PROJECT") is None  # Bayi'nin değeri B'ye sızmaz
        assert "JIRA_PROJECT" not in b
        assert b["TP_GIT_TIMEOUT_S"] == "61"  # kurulum (D) ayarı ortak
        assert b["TP_FORGE_PATH"] == str(forge_kok / "forge" / B / "repo.git")
        proje_ayar(pid=B, JIRA_PROJECT="BBB", TP_APP_ID_ANDROID="com.b")
        assert b["JIRA_PROJECT"] == "BBB" and b["TP_APP_ID_ANDROID"] == "com.b"
    assert "test-a" in repr(a) and "TPD" not in repr(a)


# ------------------------------------------------------------------------- Jira ayarları


def test_jira_ayarlari_proje_basina(
    proje: Any, proje_ayar: Any, monkeypatch: pytest.MonkeyPatch, temiz: None
) -> None:
    monkeypatch.setenv("JIRA_PROJECT", "TPD")
    monkeypatch.setenv("JIRA_PO_ACCOUNT_IDS", "po-a")
    a = jira.get_jira_settings()
    assert a.jira_project == "TPD" and a.pid == "test-a"
    assert jira.get_jira_settings() is a  # önbellek
    with proje_icinde(B):
        b = jira.get_jira_settings()
        assert b.pid == B
        assert b.jira_project == "TPD"  # alan varsayılanı (env'den değil)
        assert b.jira_po_account_ids == ""
        proje_ayar(pid=B, JIRA_PROJECT="BBB", JIRA_BASE_URL="http://jira-sim:8090")
        b2 = jira.get_jira_settings()
        assert b2 is not b and b2.jira_project == "BBB"  # sürüm değişti → yeniden kuruldu
    assert jira.get_jira_settings().jira_project == "TPD"
    assert jira.get_jira_settings(B).jira_project == "BBB"


def test_istemciler_jira_proje_basina(
    proje: Any, proje_ayar: Any, monkeypatch: pytest.MonkeyPatch, temiz: None
) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "http://jira-sim:8090")
    proje_ayar(pid=B, JIRA_BASE_URL="http://localhost:9999", JIRA_PROJECT="BBB")
    a = istemciler.jira()
    with proje_icinde(B):
        b = istemciler.jira()
    assert a is not b
    assert a.base_url.startswith("http://jira-sim") and b.base_url.startswith("http://localhost")


# ---------------------------------------------------------------------------------- forge


def test_istemciler_forge_proje_deposu(
    proje: Any, proje_ayar: Any, forge_kok: Path, temiz: None
) -> None:
    from tp_core.integrations.forge_local import LocalForge

    a = istemciler.forge()
    with proje_icinde(B):
        b = istemciler.forge()
    assert isinstance(a, LocalForge) and isinstance(b, LocalForge)
    assert a.path == forge_kok / "forge" / "demo-app.git"
    assert b.path == forge_kok / "forge" / B / "repo.git"
    assert b._prs.path == forge_kok / "forge" / B / "prs" / "tp-prs.json"


def test_github_forge_proje_ayari_ve_app_kimligi(
    proje: Any, proje_ayar: Any, monkeypatch: pytest.MonkeyPatch, temiz: None
) -> None:
    from tp_core.integrations.forge_github import GitHubForge

    monkeypatch.setenv("TP_BAGLANTI_TOKENI", "1")
    monkeypatch.setenv("GITHUB_REPO", "org/bayi")
    proje_ayar(pid=B, TP_FORGE="github", GITHUB_REPO="org/b")
    kipler: list[tuple[str, str | None]] = []

    def kip(tur: str, pid: str | None = None) -> str:
        kipler.append((tur, pid))
        return "app"

    monkeypatch.setattr(proje_ortami, "baglanti_kipi", kip)
    with proje_icinde(B):
        f = istemciler.forge()
    assert isinstance(f, GitHubForge) and f.repo == "org/b"
    assert isinstance(f._auth, proje_ortami.ProjeGitHubAuth) and f._auth.pid == B
    assert isinstance(f._auth, baglanti.HomeGitHubAuth)  # protokol uyumu
    assert ("github", B) in kipler


# ------------------------------------------------------------ bağlantı token'ı proje başına


def test_token_al_projeyi_gecirir(proje: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    tok = baglanti.ErisimTokeni("app", "ghs_a", 9e9, None)
    gorulen: list[tuple[str, str | None]] = []

    def yeni(tur: str, pid: str | None = None) -> baglanti.ErisimTokeni:
        gorulen.append((tur, pid))
        return tok

    monkeypatch.setattr(baglanti, "token_al", yeni)
    assert proje_ortami.token_al("github").access_token == "ghs_a"
    proje_ortami.token_al("jira", B)
    assert gorulen == [("github", proje.pid), ("jira", B)]


def test_jira_oauth_proje_jetonuyla(proje: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    taban = "https://api.atlassian.com/ex/jira/bulut-b"
    gorulen: list[str | None] = []

    def tok(tur: str, pid: str | None = None) -> baglanti.ErisimTokeni:
        gorulen.append(pid)
        return baglanti.ErisimTokeni("oauth", f"tok-{pid}", 9e9, taban)

    monkeypatch.setattr(proje_ortami, "baglanti_kipi", lambda tur, pid=None: "oauth")
    monkeypatch.setattr(proje_ortami, "baglanti_public", lambda tur, pid=None: {})
    monkeypatch.setattr(proje_ortami, "token_al", tok)
    istekler: list[httpx.Request] = []

    def h(req: httpx.Request) -> httpx.Response:
        istekler.append(req)
        return httpx.Response(200, json={"accountId": "x"})

    s = jira.JiraSettings.proje_icin(B)
    istemci = jira.get_jira(s, http=httpx.Client(transport=httpx.MockTransport(h)))
    assert istemci.oauth and istemci.base_url == taban
    istemci._http.get(taban + "/rest/api/3/myself", auth=istemci._read_auth)
    assert istekler[-1].headers["Authorization"] == f"Bearer tok-{B}"
    assert set(gorulen) == {B}


# ------------------------------------------------------------------------ toolchain bloğu


def test_toolchain_blogu_varsayilan_yalniz_pid(proje: Any, forge_kok: Path) -> None:
    assert istemciler.toolchain_proje_blogu() == {"pid": "test-a"}
    assert toolchain_blogu.app_mcp_basligi() == {}


def test_toolchain_blogu_varsayilan_home_farki_gider(
    proje: Any, proje_ayar: Any, forge_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BASE_URL", "http://demo-app-web:8080")
    proje_ayar(BASE_URL="http://demo-app-web:8080", DEMO_API_URL="https://api.a.invalid/")
    assert istemciler.toolchain_proje_blogu() == {
        "pid": "test-a",
        "demo_api_url": "https://api.a.invalid",
    }


def test_toolchain_blogu_diger_proje(
    proje: Any, proje_ayar: Any, forge_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_FORGE_REMOTE_URL", "https://github.com/org/bayi.git")
    monkeypatch.setenv("TP_APP_ID_ANDROID", "com.bayi")
    with proje_icinde(B):
        blok = istemciler.toolchain_proje_blogu()
        assert blok == {
            "pid": B,
            "forge_path": str(forge_kok / "forge" / B / "repo.git"),
            "mirror_path": str(forge_kok / "forge-mirror" / f"{B}.git"),
            "remote_url": "",  # Bayi'nin uzak deposu sızmaz
            "app": {"android": {}, "ios": {}, "windows": {}},  # Bayi uygulaması sızmaz
        }
        assert toolchain_blogu.eksik_alanlar(blok) == ["BASE_URL", "DEMO_API_URL"]
        proje_ayar(
            pid=B,
            BASE_URL="https://b.invalid/",
            DEMO_API_URL="https://b-api.invalid",
            TP_PROBE_USER="u",
            TP_PROBE_PASSWORD="p",
            TP_RUN_DEALERS="t1, t2",
            TP_E2E_ROOT="b/e2e",
            TP_FORGE_REMOTE_URL="https://github.com/org/b.git",
            TP_APP_ID_ANDROID="com.b",
            TP_APP_ACTIVITY_ANDROID=".Ana",
            TP_APP_PATH_WINDOWS="C:\\b\\B.exe",
        )
        blok = istemciler.toolchain_proje_blogu()
        assert toolchain_blogu.eksik_alanlar(blok) == []
        assert blok["base_url"] == "https://b.invalid"
        assert blok["remote_url"] == "https://github.com/org/b.git"
        assert blok["probe_user"] == "u" and blok["probe_password"] == "p"
        assert blok["run_dealers"] == ["t1", "t2"] and blok["e2e_root"] == "b/e2e"
        assert blok["app"] == {
            "android": {"app_id": "com.b", "activity": ".Ana"},
            "ios": {},
            "windows": {"path": "C:\\b\\B.exe"},
        }
        baslik = toolchain_blogu.app_mcp_basligi()["X-TP-App"]
        ham = base64.urlsafe_b64decode(baslik + "=" * (-len(baslik) % 4))
        assert json.loads(ham) == blok["app"]


def test_toolchain_blogu_github_app_ayna_tokeni(
    proje: Any, forge_kok: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GitHub App kipinde core-worker projenin kurulum token'ını blokta gönderir (ayna okuması);
    core-api'de (yetkisiz süreç) ve token kipinde gönderilmez."""
    kip = {"github": "app"}
    monkeypatch.setattr(proje_ortami, "baglanti_kipi", lambda tur, pid=None: kip.get(tur, "token"))
    monkeypatch.setattr(
        proje_ortami,
        "token_al",
        lambda tur, pid=None: baglanti.ErisimTokeni("app", f"ghs_{pid}", 9e9, None),
    )
    assert "remote_token" not in istemciler.toolchain_proje_blogu()  # core-api
    monkeypatch.setenv("TP_BAGLANTI_TOKENI", "1")
    assert istemciler.toolchain_proje_blogu()["remote_token"] == "ghs_test-a"
    with proje_icinde(B):
        assert istemciler.toolchain_proje_blogu()["remote_token"] == f"ghs_{B}"

    def hata(tur: str, pid: str | None = None) -> baglanti.ErisimTokeni:
        raise baglanti.BaglantiHatasi("Home erişilemedi")

    monkeypatch.setattr(proje_ortami, "token_al", hata)
    assert "remote_token" not in istemciler.toolchain_proje_blogu()
    kip["github"] = "token"
    monkeypatch.setattr(proje_ortami, "token_al", lambda *a, **k: pytest.fail("token kipi"))
    assert "remote_token" not in istemciler.toolchain_proje_blogu()


def test_toolchain_client_check_blok_ekler(proje: Any, forge_kok: Path, proje_ayar: Any) -> None:
    from tp_core.api.errors import ProjeAyariEksik
    from tp_core.features.ci.clients import ToolchainClient

    govdeler: list[dict[str, Any]] = []

    def h(req: httpx.Request) -> httpx.Response:
        govdeler.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True})

    c = ToolchainClient("http://tc", transport=httpx.MockTransport(h), timeout=5)
    # Varsayılan dışı projede ortam ayarı yoksa koşu başlamaz (toolchain env'e düşerdi).
    with proje_icinde(B), pytest.raises(ProjeAyariEksik):
        c.check({"sha": "a" * 40})
    assert govdeler == []
    proje_ayar(pid=B, BASE_URL="http://b.test", DEMO_API_URL="http://b-api.test")
    with proje_icinde(B):
        c.check({"sha": "a" * 40})
    c.check({"sha": "a" * 40, "proje": {"pid": "verilen"}})
    assert govdeler[0]["proje"]["pid"] == B
    assert govdeler[0]["proje"]["forge_path"].endswith(f"{B}/repo.git")
    assert govdeler[1]["proje"] == {"pid": "verilen"}  # çağıranın bloğu korunur


def test_forge_yolu_varsayilan_adla_cakisan_pid_reddedilir(monkeypatch):
    import pytest

    from tp_core.integrations import forge_yollari as fy

    monkeypatch.setenv("TP_FORGE_PATH", "/forge/demo-app.git")
    monkeypatch.setenv("TP_FORGE_MIRROR_PATH", "/forge-mirror/demo-app.git")
    for kotu in ("demo-app", "demo-app.git", "x.git"):
        with pytest.raises(fy.GecersizProjeKimligi):
            fy._dogrula(kotu)
    assert fy._dogrula("ea7383844744") == "ea7383844744"
