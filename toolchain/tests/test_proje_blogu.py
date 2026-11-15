"""İstek `proje` bloğu (TP-COK-PROJE-PLANI §4.4): ayar birleştirme, doğrulama, iletim."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from toolchain_common.proje import ProjeBlogu
from toolchain_common.settings import settings


@pytest.fixture
def kokler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_FORGE_PATH", "/forge/demo-app.git")
    monkeypatch.setenv("TP_FORGE_MIRROR_PATH", "/forge-mirror/demo-app.git")
    monkeypatch.setenv("BASE_URL", "http://demo-app-web:8080")
    monkeypatch.setenv("TP_PROBE_PASSWORD", "ortam-parola")
    monkeypatch.setenv("TP_RUN_DEALERS", "bayi1,bayi2")


TAM_BLOK: dict[str, Any] = {
    "pid": "proje-b",
    "forge_path": "/forge/proje-b/repo.git",
    "mirror_path": "/forge-mirror/proje-b.git",
    "remote_url": "https://github.com/ornek/b.git",
    "base_url": "https://b.example.invalid/",
    "demo_api_url": "https://b-api.example.invalid",
    "probe_user": "test1",
    "probe_password": "gizli-b",
    "run_dealers": ["t1", " t2 "],
    "e2e_root": "b-app/e2e",
    "app": {"android": {"app_id": "com.ornek.b", "activity": ".Ana"}},
}


def test_blok_yoksa_ayarlar_aynen(kokler: None) -> None:
    a, b = settings(), settings(None)
    assert a == b
    assert a.pid is None and a.app_ayarlari is None and a.proje_blogu is None


def test_tam_blok_birlestirme(kokler: None) -> None:
    cfg = settings(TAM_BLOK)
    assert cfg.pid == "proje-b"
    assert cfg.forge_path == Path("/forge/proje-b/repo.git")
    assert cfg.forge_mirror_path == Path("/forge-mirror/proje-b.git")
    assert cfg.forge_remote_url == "https://github.com/ornek/b.git"
    assert cfg.base_url == cfg.probe_base_url == "https://b.example.invalid"
    assert cfg.demo_api_url == "https://b-api.example.invalid"
    assert (cfg.probe_user, cfg.probe_password) == ("test1", "gizli-b")
    assert cfg.run_dealers == ("t1", "t2")
    assert cfg.e2e_root == "b-app/e2e"
    assert cfg.app_ayarlari == {"android": {"APP_ID": "com.ornek.b", "APP_ACTIVITY": ".Ana"}}
    # Ortamdan gelen kurulum değerleri (D) değişmez.
    assert cfg.artifacts_path == settings().artifacts_path
    assert cfg.run_lock_path == settings().run_lock_path


def test_kismi_blok_eksik_alanlar_ortamdan(kokler: None) -> None:
    cfg = settings({"pid": "p"})
    taban = settings()
    assert cfg.pid == "p"
    assert cfg.forge_path == taban.forge_path
    assert cfg.probe_password == "ortam-parola"
    assert cfg.run_dealers == ("bayi1", "bayi2")


def test_bos_remote_url_uzak_cekmeyi_kapatir(kokler: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_FORGE_REMOTE_URL", "https://github.com/ornek/a.git")
    assert settings({"pid": "p", "remote_url": ""}).forge_remote_url == ""


def test_parola_repr_ve_dokumda_yok(kokler: None) -> None:
    blok = ProjeBlogu.model_validate(TAM_BLOK)
    assert "gizli-b" not in repr(blok)
    # Ham blok (test-runner'a iletilen) Settings repr'ına girmez.
    assert "proje_blogu" not in repr(settings(blok))


@pytest.mark.parametrize(
    "degisiklik",
    [
        {"pid": "../x"},
        {"pid": "a..b"},
        {"pid": ""},
        {"pid": "a/b"},
        {"forge_path": "/baska/repo.git"},
        {"forge_path": "/forge/../etc/repo.git"},
        {"forge_path": "forge/b/repo.git"},
        {"forge_path": "/forge"},
        {"mirror_path": "/forge/b.git"},
        {"remote_url": "file:///etc/passwd"},
        {"base_url": "javascript:alert(1)"},
        {"e2e_root": "/mutlak"},
        {"e2e_root": "../yukari"},
        {"run_dealers": ["a,b"]},
        {"probe_password": "satir\nsonu"},
        {"app": {"symbian": {"app_id": "x"}}},
        {"app": {"windows": {"path": "C:\\a'; Remove-Item"}}},
        {"app": {"android": {"app_id": "x", "fazla": "y"}}},
        {"bilinmeyen": 1},
    ],
)
def test_gecersiz_blok_reddedilir(kokler: None, degisiklik: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ProjeBlogu.model_validate({**TAM_BLOK, **degisiklik})


def test_app_settings_blokla_yalniz_blok(kokler: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from runner import java_run

    monkeypatch.setenv("TP_APP_PATH_ANDROID", "/ortam/bayi.apk")
    monkeypatch.setenv("TP_APP_ID_IOS", "com.ortam.ios")
    monkeypatch.setenv("TP_DEVICE_UDID_ANDROID", "emulator-5554")
    cfg = settings(TAM_BLOK)
    # Android blokta: uygulama değerleri yalnız bloktan; cihaz ortamdan (K2).
    assert java_run.app_settings("android", cfg) == {
        "APP_ID": "com.ornek.b",
        "APP_ACTIVITY": ".Ana",
        "DEVICE_UDID": "emulator-5554",
    }
    # iOS blokta yok: bugünkü ortam davranışı.
    assert java_run.app_settings("ios", cfg) == java_run.app_settings("ios")
    assert java_run.app_settings("ios", cfg)["APP_ID"] == "com.ortam.ios"


def test_app_settings_bos_platform_blogu_varsayilan_sizdirmaz(kokler: None) -> None:
    from runner import java_run

    cfg = settings({"pid": "p", "app": {"android": {}}})
    assert "APP_ID" not in java_run.app_settings("android", cfg)
    assert java_run.app_settings("android")["APP_ID"] == java_run.DEFAULT_APP_ID["android"]


def _runner_istemcisi() -> tuple[httpx.Client, list[dict[str, Any]]]:
    cagrilar: list[dict[str, Any]] = []

    def isleyici(request: httpx.Request) -> httpx.Response:
        cagrilar.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "status": "passed"})

    return httpx.Client(transport=httpx.MockTransport(isleyici)), cagrilar


def test_check_blogu_test_runnera_iletir(kokler: None) -> None:
    from worker import check as checks

    istemci, cagrilar = _runner_istemcisi()
    checks._call_runner(settings(TAM_BLOK), {"sha": "a" * 40, "run_id": "r1"}, istemci)
    gonderilen = cagrilar[0]["proje"]
    assert gonderilen["pid"] == "proje-b"
    assert gonderilen["forge_path"] == "/forge/proje-b/repo.git"
    assert gonderilen["probe_password"] == "gizli-b"
    # test-runner gövdesi doğrulanabilir olmalı (RunBody extra=forbid).
    from runner.app import RunBody

    RunBody.model_validate({**cagrilar[0], "run_id": "r1"})


def test_check_blok_yoksa_proje_alani_yok(kokler: None) -> None:
    from worker import check as checks

    istemci, cagrilar = _runner_istemcisi()
    checks._call_runner(settings(), {"sha": "a" * 40, "run_id": "r1"}, istemci)
    assert "proje" not in cagrilar[0]


def test_runner_runbody_proje_kabul(kokler: None) -> None:
    from runner.app import RunBody

    body = RunBody.model_validate({"sha": "main", "run_id": "r1", "proje": TAM_BLOK})
    assert body.proje is not None and body.proje.pid == "proje-b"
    assert RunBody.model_validate({"sha": "main", "run_id": "r1"}).proje is None
    with pytest.raises(ValidationError):
        RunBody.model_validate({"sha": "main", "run_id": "r1", "proje": {"pid": "../x"}})


def test_worker_uclari_projenin_forgeunu_kullanir(
    env: Path, forge: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blokla gelen `forge_path` (aynı kök altında, ayrı depo) çözümde kullanılır; kök dışı 422."""
    from worker import app as worker_app

    monkeypatch.setenv("TP_FORGE_REMOTE_URL", "")
    worker_app._SYMBOL_CACHE.clear()
    istemci = TestClient(worker_app.app)
    baska = forge.bare.parent / "proje-b" / "repo.git"
    baska.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "--bare", str(baska)], check=True)
    proje = {"pid": "proje-b", "forge_path": str(baska), "remote_url": ""}
    r = istemci.post("/symbols", json={"sha": forge.main, "proje": proje})
    # Commit varsayılan projenin deposunda; B projesinin deposunda yok → bulunamaz.
    assert r.status_code == 404 and "bulunamad" in r.text, r.text
    r = istemci.post(
        "/symbols", json={"sha": forge.main, "proje": {"pid": "b", "forge_path": "/etc/x.git"}}
    )
    assert r.status_code == 422, r.text


# ------------------------------------------- GitHub App kipi: ayna token'ı bloktan (remote_token)


def test_remote_token_ortamin_yerine_gecer_ve_gizli(
    kokler: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_FORGE_REMOTE_TOKEN", "ortam-pat")
    assert settings().forge_remote_token == "ortam-pat"  # token kipi: bugünkü gibi
    cfg = settings({**TAM_BLOK, "remote_token": "ghs_kurulum"})
    assert cfg.forge_remote_token == "ghs_kurulum"
    assert "ghs_kurulum" not in repr(
        ProjeBlogu.model_validate({**TAM_BLOK, "remote_token": "ghs_kurulum"})
    )
    # Blokta token yoksa ortamınki kalır.
    assert settings(TAM_BLOK).forge_remote_token == "ortam-pat"


def test_remote_token_test_runnera_gitmez(kokler: None) -> None:
    from runner.app import RunBody
    from worker import check as checks

    istemci, cagrilar = _runner_istemcisi()
    cfg = settings({**TAM_BLOK, "remote_token": "ghs_kurulum"})
    checks._call_runner(cfg, {"sha": "a" * 40, "run_id": "r1"}, istemci)
    assert "remote_token" not in cagrilar[0]["proje"]
    assert "ghs_kurulum" not in json.dumps(cagrilar[0])
    with pytest.raises(ValidationError, match="remote_token"):
        RunBody.model_validate(
            {"sha": "main", "run_id": "r1", "proje": {"pid": "p", "remote_token": "x"}}
        )


def test_remote_token_ayna_cekmesinde_kullanilir(
    kokler: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from toolchain_common import gitforge, repos

    gorulen: list[str] = []
    monkeypatch.setattr(gitforge, "init_mirror", lambda *a, **k: None)
    monkeypatch.setattr(
        gitforge, "fetch", lambda repo, url, refspecs, token, timeout: gorulen.append(token) or True
    )
    cfg = settings({**TAM_BLOK, "remote_token": "ghs_kurulum"})
    repos._fetch(cfg, "a" * 40)
    assert gorulen == ["ghs_kurulum"]
