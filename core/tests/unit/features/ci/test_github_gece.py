"""GitHub kipi gece koşusu: çekirdek `workflow_dispatch` (`tetik=nightly`, `istek_id=<run_id>`)
gönderir, GitHub cron'unu beklemez; koşu yalnız `[<run_id>]` işaretiyle bağlanır."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.unit.conftest import *  # noqa: F403
from tests.unit.features.ci.helpers import artefakt_kok, ci_env, run_jobs  # noqa: F401
from tests.unit.features.ci.test_github import FakeGitHub, _run, gh  # noqa: F401
from tp_core.features.ci import service, services
from tp_core.models import ExternalRef

# 2026-11-02 02:00 TR = 2026-11-01 23:00 UTC
GECE = datetime(2026, 11, 1, 23, 0, 5, tzinfo=UTC)
KOK = Path(__file__).resolve().parents[5]


def _gece_kosusu(engine) -> uuid.UUID:
    with services.override(now=lambda: GECE):
        sonuc = service.nightly_job(engine, "2026-11-02")
    assert sonuc["yeni"] is True
    return uuid.UUID(sonuc["run_id"])


def test_gece_isi_workflow_dispatch_gonderir(
    engine,
    gh: FakeGitHub,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TP_CI_NIGHTLY_SAAT", raising=False)
    monkeypatch.delenv("TP_WEB_DILLERI", raising=False)
    rid = _gece_kosusu(engine)
    run = _run(engine, rid)
    assert (run.kaynak, run.tetik, run.ortam["dispatch"]) == ("github", "nightly", "nightly")
    assert run.ortam["isteyen"] == "system:gece"
    run_jobs(engine)  # ci.run → ci.github_poll(0) → _dispatch
    assert gh.dispatchler == [
        ("workflow_dispatch", {"ref": "main", "inputs": {"tetik": "nightly", "istek_id": str(rid)}})
    ]
    with Session(engine) as s:
        ref = s.scalar(select(ExternalRef).where(ExternalRef.entity_id == rid))
        assert (ref.durum, ref.external_key) == ("created", "workflow_dispatch:nightly")
    # GitHub'ın (eski) cron koşusu ve işaretsiz dispatch koşusu gece koşusuna bağlanmaz.
    gh.wr(700, "schedule", conclusion="success", name="ci")
    gh.wr(701, "workflow_dispatch", conclusion="success", name="ci nightly [elle]")
    assert service.github_poll(engine, rid, 1)["durum"] == "bekleniyor"
    gh.wr(702, "workflow_dispatch", conclusion="failure", name=f"ci nightly [{rid}]")
    assert service.github_poll(engine, rid, 2)["durum"] == "failed"
    assert _run(engine, rid).github_run_id == "702"
    assert len(gh.dispatchler) == 1  # yoklama turları dispatch'i tekrarlamaz


def test_gece_isi_ikinci_kez_kosarsa_tek_dispatch(
    engine,
    gh: FakeGitHub,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TP_CI_NIGHTLY_SAAT", raising=False)
    rid = _gece_kosusu(engine)
    with services.override(now=lambda: GECE):
        tekrar = service.nightly_job(engine, "2026-11-02")
    assert (tekrar["run_id"], tekrar["yeni"]) == (str(rid), False)
    run_jobs(engine)
    assert len(gh.dispatchler) == 1


def test_dispatch_sonrasi_bir_saatte_bulunamazsa_error(
    engine,
    gh: FakeGitHub,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TP_CI_NIGHTLY_SAAT", raising=False)
    monkeypatch.delenv("TP_CI_GITHUB_BULMA_S", raising=False)
    rid = _gece_kosusu(engine)
    run_jobs(engine)
    simdi = datetime.now(UTC)
    with services.override(now=lambda: simdi + timedelta(minutes=50)):
        assert service.github_poll(engine, rid, 3)["durum"] == "bekleniyor"
    with services.override(now=lambda: simdi + timedelta(minutes=65)):
        assert service.github_poll(engine, rid, 4)["durum"] == "error"
    run = _run(engine, rid)
    assert run.sonuc == "error"
    assert "bulunamadı" in run.artefaktlar["hata"] and str(rid) in run.artefaktlar["hata"]


def test_bulunan_kosu_bir_saatten_uzun_surebilir(
    engine,
    gh: FakeGitHub,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1 saat kuralı yalnız GitHub'da hiç görünmeyen koşu içindir; süren koşu genel sınırdadır."""
    monkeypatch.delenv("TP_CI_NIGHTLY_SAAT", raising=False)
    rid = _gece_kosusu(engine)
    run_jobs(engine)
    gh.wr(710, "workflow_dispatch", status="in_progress", name=f"ci nightly [{rid}]")
    simdi = datetime.now(UTC)
    with services.override(now=lambda: simdi + timedelta(minutes=70)):
        assert service.github_poll(engine, rid, 1)["durum"] == "bekleniyor"
    assert _run(engine, rid).sonuc == "running"


def test_local_kipte_gece_dispatch_isaretlemez(engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TP_CI_NIGHTLY_SAAT", raising=False)
    with services.override(mode=lambda: "local"):
        rid = _gece_kosusu(engine)
    run = _run(engine, rid)
    assert run.kaynak == "local" and run.ortam["dispatch"] is None


@pytest.mark.parametrize("dosya", ["ci.yml", "web-java.yml"])
def test_web_is_akislarinda_schedule_yok(dosya: str) -> None:
    """Gece koşusunu çekirdek dispatch eder: web iş akışlarında GitHub cron'u çift koşu açardı."""
    yol = KOK / ".github" / "workflows" / dosya
    if not yol.exists():
        pytest.skip(f"{dosya} bu çalışma kopyasında yok")
    wf = yaml.safe_load(yol.read_text(encoding="utf-8"))
    on = wf.get("on", wf.get(True))
    assert "schedule" not in on
    assert "tetik" in on["workflow_dispatch"]["inputs"]
    assert "istek_id" in on["workflow_dispatch"]["inputs"]
