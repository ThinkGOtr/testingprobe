"""TP-GITHUB-404: `python -m tp_core.*` CLI'ları Home etkin config'ini tek seferlik yükler
(`durum.cli_yukle`); `CONFIG_SOURCE=home` iken eski env App'i (GH_APP_ID + özel anahtar) sessizce
devreye girmez, App kimliği / kurulum uyuşmazlığında açık hata verilir."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.unit.home_config.sahte_home import HOME, SahteHome, ornek_yanit
from tp_core.home_config import baglanti, durum
from tp_core.integrations.forge import ForgeValidationError
from tp_core.integrations.forge_github import AppAuth, GitHubForge
from tp_core.proje import proje_icinde

ESKI_ENV = {"GH_APP_ID": "5570812", "GH_APP_PRIVATE_KEY": "eski-anahtar"}


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[SahteHome]:
    sahte = SahteHome()
    for k in [*durum.CALISMA_ANINDA, "TP_BAGLANTI_TOKENI", "GH_APP_INSTALLATION_ID"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CONFIG_SOURCE", "home")
    monkeypatch.setenv("TP_HOME_PROJECT", "aaaabbbbcccc")
    monkeypatch.setenv("AIPROBE_HOME_RUN_URL", HOME)
    monkeypatch.setenv("TP_CONFIG_LKG_PATH", str(tmp_path / "lkg.json"))
    durum.reset()
    baglanti.configure(None)
    durum.configure(http=sahte, id_token=lambda aud: f"id:{aud}", temizle=lambda: None,
                    projeler=lambda: [])  # fmt: skip
    yield sahte
    durum.reset()
    baglanti.configure(None)


def _app_kipi(home: SahteHome, kurulum: str = "182319319") -> None:
    home.yanit = ornek_yanit(
        connections={"jira": {"mode": "token", "public": {}},
                     "github": {"mode": "app", "public": {"installation_id": kurulum}}}
    )  # fmt: skip
    home.erisim = {
        "github": {"mode": "app", "access_token": "gh-tok",
                   "expires_at": "2099-01-01T00:00:00Z", "base_url": None},
    }  # fmt: skip


# ------------------------------------------------------------------ durum.cli_yukle


def test_cli_yukle_env_kipinde_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    durum.reset()
    monkeypatch.delenv("CONFIG_SOURCE", raising=False)
    cagri: list[object] = []
    durum.configure(http=lambda *a: cagri.append(a))  # type: ignore[arg-type,return-value]
    d = durum.cli_yukle()
    assert cagri == [] and d.cfg is None and durum.ozet()["kaynak"] == "env"
    durum.reset()


def test_cli_yukle_tek_sefer_iplik_acmaz(home: SahteHome) -> None:
    _app_kipi(home)
    d = durum.cli_yukle("core-worker")
    assert d.kaynak == "home" and durum.baglanti_kipi("github") == "app"
    assert durum._IPLIK is None  # arka plan yenileyici yok
    assert home.sayi("/v1/config/effective") == 1


def test_cli_yukle_home_kapaliysa_lkg(home: SahteHome) -> None:
    _app_kipi(home)
    durum.cli_yukle()  # LKG yazılır
    durum.reset()
    durum.configure(http=SahteHome(kapali=True), id_token=lambda a: "x", temizle=lambda: None,
                    projeler=lambda: [])  # fmt: skip
    d = durum.cli_yukle()
    assert d.kaynak == "lkg" and durum.baglanti_kipi("github") == "app"


# ------------------------------------------------------------------ forge_demo CLI


def test_forge_demo_cli_home_config_yukler_ve_app_kipini_kullanir(
    home: SahteHome, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.integrations import forge_demo
    from tp_core.integrations.proje_ortami import ProjeGitHubAuth

    _app_kipi(home)
    monkeypatch.setenv("TP_BAGLANTI_TOKENI", "1")
    monkeypatch.setenv("GITHUB_REPO", "org/demo")
    monkeypatch.setenv("GH_APP_INSTALLATION_ID", "182319319")
    for k, v in ESKI_ENV.items():
        monkeypatch.setenv(k, v)
    gorulen: dict[str, Any] = {}

    def calistir(args: Any, **_kw: Any) -> int:
        gorulen["auth"] = GitHubForge.from_env()._auth
        return 0

    monkeypatch.setattr(forge_demo, "_calistir", calistir)
    assert forge_demo.main(["web-state"]) == 0
    assert isinstance(gorulen["auth"], ProjeGitHubAuth)
    assert not isinstance(gorulen["auth"], AppAuth)


def test_demo_ve_jira_seed_cli_home_config_yukler(
    home: SahteHome, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.features.demo import __main__ as demo_cli
    from tp_core.integrations import jira_seed

    _app_kipi(home)
    kipler: list[str] = []

    def kaydet(*_a: Any, **_kw: Any) -> int:
        kipler.append(durum.baglanti_kipi("github"))
        return 0

    monkeypatch.setattr(demo_cli, "_calistir", kaydet)
    monkeypatch.setattr(jira_seed, "_calistir", kaydet)
    assert demo_cli.main(["on-kosul"]) == 0
    durum.reset()
    durum.configure(http=home, id_token=lambda a: "x", temizle=lambda: None, projeler=lambda: [])
    assert jira_seed.main([]) == 0
    assert kipler == ["app", "app"]


# ------------------------------------------------------------------ eski App dalı koruması


def test_home_config_yuklenmemisse_eski_app_acik_hata(home: SahteHome) -> None:
    env = {"GITHUB_REPO": "org/demo", "GH_APP_INSTALLATION_ID": "182319319", **ESKI_ENV}
    with pytest.raises(ForgeValidationError, match="Home etkin config'i bu süreçte yüklenmedi"):
        GitHubForge.from_env(env)


def test_kurulum_home_dan_app_eski_env_den_uyusmazlik_hatasi(home: SahteHome) -> None:
    # Home bağlantısı `app` kipinde değil ama kurulum kimliği Home'dan (env görünümü) geliyor.
    home.yanit = ornek_yanit(
        connections={"jira": {"mode": "token", "public": {}},
                     "github": {"mode": "token", "public": {"installation_id": "182319319"}}}
    )  # fmt: skip
    durum.cli_yukle()
    env = {"GITHUB_REPO": "org/demo", "GH_APP_INSTALLATION_ID": "182319319", **ESKI_ENV}
    with (
        proje_icinde("aaaabbbbcccc", kaynak="cli"),
        pytest.raises(ForgeValidationError, match="uyuşmazlığı") as e,
    ):
        GitHubForge.from_env(env)
    assert "eski-anahtar" not in str(e.value)  # sır mesaja düşmez


def test_home_token_kipinde_env_kurulumuyla_eski_app_calisir(home: SahteHome) -> None:
    durum.cli_yukle()  # github: token kipi, Home'da kurulum kimliği yok
    env = {"GITHUB_REPO": "org/demo", "GH_APP_INSTALLATION_ID": "177618071", **ESKI_ENV}
    with proje_icinde("aaaabbbbcccc", kaynak="cli"):
        assert isinstance(GitHubForge.from_env(env)._auth, AppAuth)


def test_env_kipinde_eski_app_bugunku_gibi(monkeypatch: pytest.MonkeyPatch) -> None:
    durum.reset()
    monkeypatch.delenv("CONFIG_SOURCE", raising=False)
    env = {"GITHUB_REPO": "org/demo", "GH_APP_INSTALLATION_ID": "1", **ESKI_ENV}
    assert isinstance(GitHubForge.from_env(env)._auth, AppAuth)
