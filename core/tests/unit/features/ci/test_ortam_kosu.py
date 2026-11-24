"""Koşunun test ortamı (0048): varsayılan ortam seçimi, elle seçim, gece koşusu, kayıt alanları,
liste/Kontrol Kulesi süzgeci, toolchain bloğu ve Canlı korumaları (API)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.unit.features.ci.helpers import SHA, FakeToolchain, login, run_jobs
from tp_core.features.ci import enqueue_ci
from tp_core.home_config import durum
from tp_core.proje import ortam

pytestmark = pytest.mark.usefixtures("ci_env")

STG = "a1a1a1a1a1a1"
CANLI = "c2c2c2c2c2c2"


@pytest.fixture
def ortamlar(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Home ortam listesi ve ortam düzeyi görünüm (env kipinde Home yok: sahtelenir)."""
    durumu: dict[str, Any] = {"varsayilan": STG}

    def liste(pid: str | None = None) -> list[ortam.Ortam]:
        p = ortam._pid(pid)
        return [
            ortam.Ortam(p, CANLI, "Canlı", "prod", durumu["varsayilan"] == CANLI),
            ortam.Ortam(p, STG, "Staging", "staging", durumu["varsayilan"] == STG),
        ]

    gorunumler = {
        STG: {"BASE_URL": "https://stg.example.test", "TP_PROBE_PASSWORD": "stg-parola"},
        CANLI: {"BASE_URL": "https://canli.example.test"},
    }
    monkeypatch.setattr(ortam, "ortamlar", liste)
    # Canlı Deployment parolasını A1/env_unset ile KALDIRIR (473de3ee: boş parola yalnız
    # açık kaldırmada gider; tanımsız ad runner'ın kendi parolasına bırakılır).
    kaldirilan = {STG: frozenset(), CANLI: frozenset({"TP_PROBE_PASSWORD"})}
    monkeypatch.setattr(
        durum, "ortam_gorunumu", lambda pid, eid: (gorunumler[eid], kaldirilan[eid])
    )
    return durumu


def _satir(engine: Engine, rid: Any) -> tuple[Any, ...]:
    with engine.connect() as c:
        return tuple(
            c.execute(
                text("SELECT ortam_eid, ortam_adi, ortam_turu FROM run WHERE id = :i"),
                {"i": str(rid)},
            ).one()
        )


def test_ortamsiz_projede_davranis_degismez(
    api: TestClient, make_user: Any, engine: Engine
) -> None:
    login(api, make_user("engineer"))
    assert api.get("/environments").json() == {"ortamlar": [], "varsayilan_eid": None}
    r = api.post("/ci/trigger", json={"tetik": "deploy"})
    assert r.status_code == 202, r.text
    assert r.json()["test_ortami"] is None
    assert _satir(engine, r.json()["run_id"]) == (None, None, None)


def test_ortam_listesi_ve_varsayilan(
    api: TestClient, make_user: Any, ortamlar: dict[str, Any]
) -> None:
    login(api, make_user("analyst"))
    b = api.get("/environments").json()
    assert b["varsayilan_eid"] == STG
    assert [(o["ad"], o["canli"], o["varsayilan"]) for o in b["ortamlar"]] == [
        ("Canlı", True, False),
        ("Staging", False, True),
    ]


def test_tetik_varsayilan_ve_secilen_ortam(
    api: TestClient,
    make_user: Any,
    engine: Engine,
    toolchain: FakeToolchain,
    ortamlar: dict[str, Any],
) -> None:
    login(api, make_user("engineer"))
    r = api.post("/ci/trigger", json={"tetik": "deploy"})
    assert r.status_code == 202, r.text
    assert r.json()["test_ortami"]["eid"] == STG
    assert _satir(engine, r.json()["run_id"]) == (STG, "Staging", "staging")
    # Aynı tetik başka ortamda ayrı koşu (Staging koşusu Canlı'yı yutmaz).
    r2 = api.post("/ci/trigger", json={"tetik": "deploy", "ortam": CANLI})
    assert r2.status_code == 202, r2.text
    assert r2.json()["run_id"] != r.json()["run_id"]
    assert r2.json()["test_ortami"]["canli"] is True
    for kotu in ("ffffffffffff", "x"):
        r3 = api.post("/ci/trigger", json={"tetik": "deploy", "ortam": kotu})
        assert r3.status_code == 422
    # Gece koşusu yalnız varsayılan ortamda.
    assert api.post("/ci/trigger", json={"tetik": "nightly", "ortam": CANLI}).status_code == 422
    run_jobs(engine)
    bloklar = {b["proje"]["ortam"]["eid"]: b["proje"] for b in toolchain.istekler}
    assert bloklar[STG]["base_url"] == "https://stg.example.test"
    assert bloklar[STG]["probe_password"] == "stg-parola"
    assert bloklar[CANLI]["base_url"] == "https://canli.example.test"
    assert bloklar[CANLI]["probe_password"] == ""
    assert bloklar[CANLI]["ortam"]["tur"] == "prod"
    # Liste: rozet alanı ve süzgeç.
    liste = api.get("/runs").json()
    assert {k["test_ortami"]["eid"] for k in liste if k["test_ortami"]} == {STG, CANLI}
    yalniz = api.get("/runs", params={"ortam": CANLI}).json()
    assert [k["test_ortami"]["ad"] for k in yalniz] == ["Canlı"]
    assert api.get("/runs", params={"ortam": "-"}).json() == []
    assert api.get("/runs", params={"ortam": "bozuk"}).status_code == 422
    detay = api.get(f"/runs/{r2.json()['run_id']}").json()
    assert detay["test_ortami"] == {"eid": CANLI, "ad": "Canlı", "tur": "prod", "canli": True}
    # Kontrol Kulesi süzgeci.
    kk = api.get("/control-tower", params={"ortam": STG}).json()
    assert kk["ortam_suzgeci"] == STG
    assert {k["test_ortami"]["eid"] for k in kk["son_kosular"]} == {STG}
    assert api.get("/control-tower").json()["ortam_suzgeci"] is None


def test_gece_ve_otomatik_kosular_varsayilan_ortamda(
    engine: Engine, ortamlar: dict[str, Any]
) -> None:
    from tp_core.proje import proje_icinde, varsayilan_pid

    with proje_icinde(varsayilan_pid()), Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "pr", 7)
        gece = enqueue_ci(s, None, "nightly", anahtar="nightly:2026-11-18")
        ortamsiz = enqueue_ci(s, SHA, "push", ortam=None)
    assert _satir(engine, rid)[0] == STG
    assert _satir(engine, gece)[0] == STG
    assert _satir(engine, ortamsiz) == (None, None, None)


def test_canli_varsayilan_ortamda_kirma_islemleri_engellenir(
    api: TestClient, make_user: Any, engine: Engine, ortamlar: dict[str, Any]
) -> None:
    from tp_core.api.errors import CanliOrtamEngeli
    from tp_core.features.codegen import service as cg
    from tp_core.proje import proje_icinde, varsayilan_pid

    ortamlar["varsayilan"] = CANLI
    with proje_icinde(varsayilan_pid()):
        with pytest.raises(CanliOrtamEngeli, match="kırarak doğrulama"):
            ortam.canli_engelle("kırarak doğrulama")
        with pytest.raises(CanliOrtamEngeli, match="sepet"):
            cg._sepeti_sifirla()
    # Koşu (okuma) Canlı'da serbest; kayıt Canlı ortamı taşır.
    login(api, make_user("engineer"))
    r = api.post("/ci/trigger", json={"tetik": "manual"})
    assert r.status_code == 202, r.text
    assert _satir(engine, r.json()["run_id"]) == (CANLI, "Canlı", "prod")
