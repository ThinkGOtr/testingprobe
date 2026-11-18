"""Koşu hesabı başına parola (`TP_RUN_DEALER_PASSWORDS`, Home `tp.test_users.run_pool_passwords`):
blok/ortam çözümü ve test sürecine iletim (ts, java, python, csharp)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from runner import java_run
from runner import run as runner
from runner.diller import csharp_run, python_run
from toolchain_common.proje import ProjeBlogu
from toolchain_common.settings import kosu_parola_adi, kosu_parola_env, settings

GIZLI = "Kosu-Parola-9f8e7d"


def test_ortamdan_ve_bloktan(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("TP_RUN_DEALERS", "bayi1,bayi2")
    monkeypatch.delenv("TP_RUN_DEALER_PASSWORDS", raising=False)
    assert settings().run_dealer_passwords == {}
    monkeypatch.setenv("TP_RUN_DEALER_PASSWORDS", json.dumps({" bayi2 ": GIZLI}))
    cfg = settings()
    assert cfg.run_dealer_passwords == {"bayi2": GIZLI}
    assert GIZLI not in repr(cfg)
    # bozuk değer: yok sayılır, uyarıda değer yok
    with caplog.at_level(logging.WARNING):
        monkeypatch.setenv("TP_RUN_DEALER_PASSWORDS", '{"bayi1": "' + GIZLI + '"')
        assert settings().run_dealer_passwords == {}
        monkeypatch.setenv("TP_RUN_DEALER_PASSWORDS", json.dumps({"bayi1": ""}))
        assert settings().run_dealer_passwords == {}
    assert GIZLI not in caplog.text and "TP_RUN_DEALER_PASSWORDS" in caplog.text
    # proje bloğu ortamın üstüne yazar ve test-runner'a iletilir
    monkeypatch.setenv("TP_RUN_DEALER_PASSWORDS", json.dumps({"bayi1": "ortam"}))
    cfg = settings({"pid": "p", "run_dealers": ["t1"], "run_dealer_passwords": {"t1": GIZLI}})
    assert cfg.run_dealer_passwords == {"t1": GIZLI}
    assert cfg.proje_blogu["run_dealer_passwords"] == {"t1": GIZLI}
    assert settings({"pid": "p"}).run_dealer_passwords == {"bayi1": "ortam"}


@pytest.mark.parametrize(
    "deger",
    [
        [1],
        {"": "x"},
        {"a": ""},
        {"a": "x\ny"},
        {"a,b": "x"},
        {"a": 1},
        {f"u{i}": "p" for i in range(101)},
    ],
)
def test_blok_dogrulama(deger: object) -> None:
    with pytest.raises(ValidationError) as exc:
        ProjeBlogu.model_validate({"pid": "p", "run_dealer_passwords": deger})
    assert GIZLI not in str(exc.value)
    blok = ProjeBlogu.model_validate({"pid": "p", "run_dealer_passwords": {"a": GIZLI}})
    assert GIZLI not in repr(blok)


def test_test_surecine_yalniz_kosu_hesaplari() -> None:
    cfg = SimpleNamespace(
        run_dealers=("bayi1", "bayi2"), run_dealer_passwords={"bayi2": GIZLI, "baska": "x"}
    )
    assert kosu_parola_env(cfg) == {  # type: ignore[arg-type]
        "TP_RUN_DEALER_PASSWORDS": json.dumps({"bayi2": GIZLI}),
        "TP_TESTVERI_KOSU_BAYI2": GIZLI,
    }
    bos = SimpleNamespace(run_dealers=("bayi1",), run_dealer_passwords={})
    assert kosu_parola_env(bos) == {}  # type: ignore[arg-type]
    assert kosu_parola_env(SimpleNamespace()) == {}  # type: ignore[arg-type]
    # Java: seed yedeği (koşu parolası önce), adı çakışan kullanıcılar atlanır.
    seed = {"bayi1": "seed1", "bayi2": "seed2", "a.b": "s", "a_b": "s"}
    env = kosu_parola_env(cfg, seed)  # type: ignore[arg-type]
    assert env["TP_TESTVERI_KOSU_BAYI1"] == "seed1" and env["TP_TESTVERI_KOSU_BAYI2"] == GIZLI
    assert "TP_TESTVERI_KOSU_A_B" not in env
    assert (
        kosu_parola_adi("x" * 60) is None and kosu_parola_adi("t.k-2") == "TP_TESTVERI_KOSU_T_K_2"
    )


def test_java_seed_bayileri(tmp_path: Path) -> None:
    yol = tmp_path / java_run.BAYILER_YOLU
    assert java_run.seed_bayiler(tmp_path) == {}
    yol.parent.mkdir(parents=True)
    yol.write_text(
        'List.of(\n new BayiBilgisi("bayi1", "Demo123!", "Merkez"),\n'
        '   new BayiBilgisi( "bayi2" ,"P\\"x", "S"), new BayiBilgisi("bos", "", "B"));',
        encoding="utf-8",
    )
    assert java_run.seed_bayiler(tmp_path) == {"bayi1": "Demo123!"}


def test_tum_dil_ortamlarinda(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_PYTHON_E2E", "/v/bin/python")
    cfg = SimpleNamespace(
        base_url="http://w",
        demo_api_url="http://a",
        demoapp_test_token="t",
        app_ayarlari=None,
        run_dealers=("bayi1", "bayi2"),
        run_dealer_passwords={"bayi1": GIZLI},
    )
    beklenen = json.dumps({"bayi1": GIZLI})
    req = runner.RunRequest(sha="a" * 40, run_id="r1")
    ortamlar = {
        "ts": runner.playwright_env(cfg, req),  # type: ignore[arg-type]
        "java-web": java_run.maven_env(cfg, req, "web"),  # type: ignore[arg-type]
        "java-android": java_run.maven_env(cfg, req, "android"),  # type: ignore[arg-type]
        "python": python_run.pytest_env(cfg, req, "web", None, tmp_path / "k"),  # type: ignore[arg-type]
        "csharp": csharp_run.test_env(
            cfg, req, "web", tmp_path / "k", tmp_path / "a", tmp_path, tmp_path
        ),  # type: ignore[arg-type]
    }
    for dil, env in ortamlar.items():
        assert env.get("TP_RUN_DEALER_PASSWORDS") == beklenen, dil
        assert env.get("TP_TESTVERI_KOSU_BAYI1") == GIZLI, dil
