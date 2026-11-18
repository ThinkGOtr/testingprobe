"""T2-1 (deploy sonrası): GitHub App kipinde core-api forge kuramaz (kurulum token'ı yalnız
core-worker'da); `/code/languages` dil algılamasını `codegen.dil_algila` işiyle worker'a devreder.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.unit.features.cases.helpers import run_jobs
from tp_core.features.codegen import dil_algila, service


@pytest.fixture
def muhendis(api: TestClient, make_user: Any) -> Any:
    from .conftest import login

    u = make_user("engineer")
    login(api, u)
    return u


def test_alg_json_gidis_donus() -> None:
    alg = dil_algila.Algilama(
        "java", "algilandi", {"ts": 3, "java": 7}, {"ts": True, "java": True}, en_az=("java",)
    )
    geri = service._alg_coz("web", service._alg_json(alg))
    assert geri.dil == "java" and geri.kaynak == "algilandi"
    assert geri.sayilar["java"] == 7 and geri.sayilar["ts"] == 3 and geri.sayilar["python"] == 0
    assert geri.projeler == {"ts": True, "java": True}
    assert geri.en_az == ("java",) and geri.hata is None


@pytest.mark.parametrize("veri", [None, "x", {}, {"dil": "go"}, {"dil": "kotlin"}])
def test_alg_coz_bicim_disi_varsayilan(veri: Any) -> None:
    alg = service._alg_coz("web", veri)
    assert alg.dil == "ts" and alg.kaynak == "varsayilan" and alg.hata


def test_worker_algilamali_kosullari(monkeypatch: pytest.MonkeyPatch) -> None:
    from tp_core.integrations import proje_ortami

    service.reset_factories()
    monkeypatch.setattr(proje_ortami, "baglanti_kipi", lambda tur, pid=None: "app")
    monkeypatch.delenv("TP_BAGLANTI_TOKENI", raising=False)
    assert service._worker_algilamali() is True  # core-api + App kipi
    monkeypatch.setenv("TP_BAGLANTI_TOKENI", "1")
    assert service._worker_algilamali() is False  # core-worker kendisi okur
    monkeypatch.delenv("TP_BAGLANTI_TOKENI")
    monkeypatch.setattr(proje_ortami, "baglanti_kipi", lambda tur, pid=None: "token")
    assert service._worker_algilamali() is False  # token kipi: GITHUB_READ_TOKEN yolu
    monkeypatch.setattr(proje_ortami, "baglanti_kipi", lambda tur, pid=None: "app")
    service.set_factories(forge=lambda: None)
    try:
        assert service._worker_algilamali() is False  # test fabrikası: doğrudan yol
    finally:
        service.reset_factories()


def test_code_languages_app_kipinde_worker_algilar(
    api: TestClient,
    codegen: Any,
    muhendis: Any,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # API süreci forge kuramıyor (App kipi); worker yolu (`_algila_dogrudan`) sahte forge'u okur.
    monkeypatch.setattr(service, "_worker_algilamali", lambda: True)
    monkeypatch.setattr(service, "DIL_ALGILA_BEKLEME_S", 0.0)

    ilk = api.get("/code/languages", params={"platform": "android"})
    assert ilk.status_code == 200, ilk.text
    d = ilk.json()
    # Worker henüz koşmadı: dürüst "sürüyor" nedeni; seçim engellenmez.
    assert d["kaynak"] == "varsayilan" and service.DIL_ALGILA_SURUYOR in d["neden"]
    with engine.connect() as c:
        isler = c.execute(
            text("SELECT yuk FROM job WHERE tur = :t"), {"t": service.DIL_ALGILA_JOB}
        ).all()
    assert [r.yuk for r in isler] == [{"platform": "android"}]

    # Aynı dilimde ikinci istek yeni iş açmaz (idempotent).
    api.get("/code/languages", params={"platform": "android"})
    with engine.connect() as c:
        assert (
            c.execute(
                text("SELECT count(*) FROM job WHERE tur = :t"), {"t": service.DIL_ALGILA_JOB}
            ).scalar_one()
            == 1
        )

    sonuclar = run_jobs(engine)
    assert any(getattr(s, "durum", None) == "done" for s in sonuclar), sonuclar
    with engine.connect() as c:
        sonuc = c.execute(
            text("SELECT sonuc FROM job WHERE tur = :t"), {"t": service.DIL_ALGILA_JOB}
        ).scalar_one()
    assert sonuc["platform"] == "android" and "kotlin" in sonuc["kurulum"]
    assert "token" not in str(sonuc).lower()

    d = api.get("/code/languages", params={"platform": "android"}).json()
    assert d["neden"] is None, d
    secenek = {x["dil"]: x for x in d["secenekler"]}
    assert secenek["java"]["neden"] != service.DEPO_OKUNAMADI


def test_worker_isi_basarisizsa_varsayilan(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    from tp_core.features.publish import service as yayin
    from tp_core.proje import varsayilan_pid
    from tp_core.proje.baglam import proje_icinde

    monkeypatch.setattr(yayin, "job_status", lambda _e, _j: ("failed", None, "x"))
    with proje_icinde(varsayilan_pid()):
        alg, kurulum = service._worker_algilama("web")
    assert alg.kaynak == "varsayilan" and "başarısız" in (alg.hata or "") and kurulum is None
