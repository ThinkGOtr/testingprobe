"""GitHub modu: elle ve gece dispatch'leri koşu adındaki `[<istek_id>]` ile eşlenir (QA bulgusu)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from tests.unit.conftest import *  # noqa: F403
from tests.unit.features.ci.helpers import artefakt_kok, ci_env, run_jobs  # noqa: F401
from tests.unit.features.ci.test_github import FakeGitHub, _run, gh  # noqa: F401
from tp_core.features.ci import service


def test_elle_dispatch_istek_id_gonderir(engine, gh: FakeGitHub) -> None:  # noqa: F811
    with Session(engine) as s, s.begin():
        rid = service.trigger_manual(s, "manual", "gelistirici")["run_id"]
    run_jobs(engine)
    assert gh.dispatchler == [
        ("workflow_dispatch", {"ref": "main", "inputs": {"tetik": "manual", "istek_id": str(rid)}})
    ]
    gh.wr(301, "workflow_dispatch", conclusion="success", name=f"ci manual [{rid}]")
    assert service.github_poll(engine, rid, 1)["durum"] == "passed"


def test_elle_ve_gece_ayni_anda_karismaz(engine, gh: FakeGitHub) -> None:  # noqa: F811
    with Session(engine) as s, s.begin():
        gece = service.trigger_manual(s, "nightly", "muhendis")["run_id"]
    with Session(engine) as s, s.begin():
        elle = service.trigger_manual(s, "manual", "gelistirici")["run_id"]
    run_jobs(engine)
    simdi = datetime.now(UTC)
    # Önce gece, sonra elle koşusu oluştu; gece önce yoklansa da en yeni adayı (elle) almaz.
    gh.wr(
        401,
        "workflow_dispatch",
        conclusion="failure",
        created_at=simdi.isoformat(),
        name=f"ci nightly [{gece}]",
    )
    gh.wr(
        402,
        "workflow_dispatch",
        conclusion="success",
        created_at=(simdi + timedelta(seconds=5)).isoformat(),
        name=f"ci manual [{elle}]",
    )
    service.github_poll(engine, gece, 1)
    service.github_poll(engine, elle, 1)
    assert _run(engine, gece).github_run_id == "401"
    assert _run(engine, elle).github_run_id == "402"


def test_dispatchli_kosu_isaretsiz_adaya_baglanmaz(engine, gh: FakeGitHub) -> None:  # noqa: F811
    """Kesin bağ: dispatch edilen koşu yalnız `[<run_id>]` işaretli GitHub koşusuna eşlenir;
    başka isteğin, `[elle]` ya da işaretsiz (eski cron) koşusu zamana göre bağlanmaz."""
    with Session(engine) as s, s.begin():
        rid = service.trigger_manual(s, "manual", "gelistirici")["run_id"]
    run_jobs(engine)
    gh.wr(500, "workflow_dispatch", conclusion="failure", name="ci manual [baska-istek]")
    gh.wr(501, "workflow_dispatch", conclusion="success", name="ci manual [elle]")
    gh.wr(502, "workflow_dispatch", conclusion="success", name="ci")
    assert service.github_poll(engine, rid, 1)["durum"] == "bekleniyor"
    assert _run(engine, rid).github_run_id is None
    gh.wr(503, "workflow_dispatch", conclusion="success", name=f"ci manual [{rid}]")
    assert service.github_poll(engine, rid, 2)["durum"] == "passed"
    assert _run(engine, rid).github_run_id == "503"


def test_dispatchsiz_kosuda_isaretsiz_aday_eski_eslemeyle_secilir(
    engine,
    gh: FakeGitHub,  # noqa: F811
) -> None:
    """Geriye dönük: dispatch'siz eski gece kaydı (cron'u bekleyen) olay + zamanla eşlenir."""
    with Session(engine) as s, s.begin():
        rid = service._enqueue(s, None, "nightly", anahtar="nightly:eski")["run_id"]
    run_jobs(engine)
    assert gh.dispatchler == []
    gh.wr(600, "schedule", conclusion="success", name="ci")
    assert service.github_poll(engine, rid, 1)["durum"] == "passed"
    assert _run(engine, rid).github_run_id == "600"
