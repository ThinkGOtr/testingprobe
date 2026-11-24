"""S2 (03-api-kimlik-taramasi): GitHub App kipinde core-api forge/GitHub Actions istemcisi
kuramaz (kurulum token'ı yalnız core-worker'da). Script detayındaki müşteri CI özeti
`codegen.musteri_ci_durum` işiyle (anlık şerit) worker'da hesaplanır; okuma hatası yutulmaz,
portal "durum okunamadı" gösterir.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, text

from tests.unit.features.cases.helpers import run_jobs
from tp_core.features.codegen import jobs as _codegen_jobs  # noqa: F401 — iş kaydı
from tp_core.features.codegen import service, views
from tp_core.workflow.jobs import ANLIK_SERIT, REGISTRY

SHA = "a" * 40
OZET = {"check_adi": "mobil-android-kotlin", "durum": "gecti", "artefakt": "alindi"}


def _script(**kw: Any) -> Any:
    v = dict(platform="android", dil="kotlin", head_sha=SHA, pr_no=7, depo="", id=1)
    v.update(kw)
    return SimpleNamespace(**v)


@pytest.fixture(autouse=True)
def _github_kipi(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(views, "get_settings", lambda: SimpleNamespace(forge="github"))
    views._MCI_ONBELLEK.clear()
    yield
    views._MCI_ONBELLEK.clear()


def test_is_anlik_seritte_kayitli() -> None:
    assert REGISTRY[views.MCI_JOB].serit == ANLIK_SERIT


def test_app_kipinde_core_api_forge_kurmaz_worker_hesaplar(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "_worker_algilamali", lambda: True)
    api_surecinde = [True]

    def dogrudan(depo: str, p: str, d: str, sha: str) -> dict[str, Any]:
        assert not api_surecinde[0], "core-api App kipinde forge kurmamalı"
        assert (p, d, sha) == ("android", "kotlin", SHA)
        return dict(OZET)

    monkeypatch.setattr(views, "_musteri_ci_dogrudan", dogrudan)
    ilk = views._musteri_ci_ozeti(_script(), 0.0)
    # Worker henüz koşmadı: dürüst "okunuyor" (önbelleğe yazılmaz).
    assert ilk and ilk["okunuyor"] is True and ilk["okuma_hatasi"] == views.MCI_OKUNUYOR
    assert ilk["check_adi"] and ilk["durum"] == "bilinmiyor"
    assert views._MCI_ONBELLEK == {}

    api_surecinde[0] = False
    sonuclar = run_jobs(engine)
    assert any(getattr(s, "durum", None) == "done" for s in sonuclar), sonuclar
    api_surecinde[0] = True
    assert views._musteri_ci_ozeti(_script(), 0.0) == OZET
    with engine.connect() as c:
        assert c.execute(
            text("SELECT count(*) FROM job WHERE tur = :t"), {"t": views.MCI_JOB}
        ).scalar_one() == 1  # fmt: skip


def test_worker_hatasi_portala_okunamadi_olarak_gelir(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "_worker_algilamali", lambda: True)

    def patla(*_a: Any) -> dict[str, Any]:
        raise RuntimeError("check'ler okunamadı")

    monkeypatch.setattr(views, "_musteri_ci_dogrudan", patla)
    views._musteri_ci_ozeti(_script(), 0.0)
    run_jobs(engine)
    ozet = views._musteri_ci_ozeti(_script(), 0.0)
    assert ozet and ozet["okunuyor"] is False
    assert "okunamadı" in ozet["okuma_hatasi"] and "RuntimeError" in ozet["okuma_hatasi"]


def test_token_kipinde_hata_yutulmaz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "_worker_algilamali", lambda: False)

    def patla(*_a: Any) -> dict[str, Any]:
        raise RuntimeError("x")

    monkeypatch.setattr(views, "_musteri_ci_dogrudan", patla)
    ozet = views._musteri_ci_ozeti(_script())
    assert ozet and ozet["durum"] == "bilinmiyor" and "okunamadı" in ozet["okuma_hatasi"]


def test_worker_isi_gecersiz_yuku_reddeder() -> None:
    assert views.run_musteri_ci_durum({"platform": "web", "dil": "ts", "head_sha": SHA}) == {
        "hata": "geçersiz istek"
    }
    assert "hata" in views.run_musteri_ci_durum(
        {"platform": "android", "dil": "kotlin", "head_sha": "zz"}
    )
