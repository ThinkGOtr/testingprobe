"""Test ortamı (core 0048): proje bloğunun `ortam` alanı, Canlı koruması ve test süreci env'i."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from runner import run as runmod
from toolchain_common.proje import ProjeBlogu
from toolchain_common.settings import ortam_env, settings
from worker import check as checks


@pytest.fixture
def ortam_env_kur(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_FORGE_PATH", "/forge/demo-app.git")
    monkeypatch.setenv("TP_FORGE_MIRROR_PATH", "/forge-mirror/demo-app.git")
    monkeypatch.setenv("DEMOAPP_TEST_TOKEN", "test-belirteci")


def _blok(tur: str) -> dict[str, object]:
    return {
        "pid": "varsayilan",
        "base_url": "https://staging.example.invalid",
        "ortam": {"eid": "a1b2c3d4e5f6", "ad": "Staging", "tur": tur},
    }


def test_ortamsiz_blok_davranisi_degismez(ortam_env_kur: None) -> None:
    cfg = settings({"pid": "varsayilan"})
    assert cfg.ortam_eid == "" and not cfg.canli
    assert cfg.demoapp_test_token == "test-belirteci"
    assert cfg.ortam_env() == {}


def test_staging_ortami_token_korunur_env_bilgisi_gider(ortam_env_kur: None) -> None:
    cfg = settings(_blok("staging"))
    assert cfg.base_url == "https://staging.example.invalid"
    assert cfg.demoapp_test_token == "test-belirteci"
    assert not cfg.canli
    assert ortam_env(cfg) == {
        "TP_TEST_ORTAMI": "a1b2c3d4e5f6",
        "TP_TEST_ORTAMI_ADI": "Staging",
        "TP_TEST_ORTAMI_TURU": "staging",
        "TP_CANLI": "",
    }


def test_canli_ortamda_test_verisi_belirteci_verilmez(ortam_env_kur: None) -> None:
    cfg = settings(_blok("prod"))
    assert cfg.canli
    assert cfg.demoapp_test_token == ""
    assert ortam_env(cfg)["TP_CANLI"] == "1"


@pytest.mark.parametrize(
    "ortam",
    [
        {"eid": "KISA", "tur": "test"},
        {"eid": "a1b2c3d4e5f6", "tur": "uretim"},
        {"eid": "a1b2c3d4e5f6", "tur": "test", "fazla": 1},
        {"eid": "a1b2c3d4e5f6", "ad": "a\nb"},
    ],
)
def test_gecersiz_ortam_reddedilir(ortam: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ProjeBlogu.model_validate({"pid": "p", "ortam": ortam})


def test_ortam_env_sahte_ayarda_bos() -> None:
    class Sahte:
        pass

    assert ortam_env(Sahte()) == {}


@pytest.mark.parametrize("fault,kampanya", [(None, True), ("F1", False)])
def test_canli_ortamda_kirma_kontrolu_reddedilir(
    ortam_env_kur: None, fault: str | None, kampanya: bool
) -> None:
    cfg = settings(_blok("prod"))
    req = checks.CheckRequest(sha="a" * 40, break_campaign=kampanya, fault=fault)
    with pytest.raises(checks.CanliOrtamReddi, match="Canlı ortamda"):
        checks.execute(cfg, req)


def test_canli_ortamda_runner_kirma_kosusunu_reddeder(ortam_env_kur: None) -> None:
    cfg = settings(_blok("prod"))
    req = runmod.RunRequest(sha="a" * 40, run_id="r1", break_campaign=True)
    with pytest.raises(runmod.RunRejected, match="Canlı ortamda"):
        runmod.execute(cfg, req)


def test_playwright_env_ortam_bilgisini_tasir(ortam_env_kur: None) -> None:
    cfg = settings(_blok("staging"))
    req = runmod.RunRequest(sha="a" * 40, run_id="r1")
    env = runmod.playwright_env(cfg, req)
    assert env["TP_TEST_ORTAMI_ADI"] == "Staging"
    assert env["BASE_URL"] == "https://staging.example.invalid"
