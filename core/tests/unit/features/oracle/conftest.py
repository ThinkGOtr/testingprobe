"""Gerçek Postgres (platform fikstürü) + case fikstürleri (sahte/REPLAY geçit, jira-sim)."""

import os
import sys
from pathlib import Path

# Oracle gereksinim kontrolü birleştirme gecikmesi (run_after): testlerde işler hemen koşar.
os.environ.setdefault("TP_ORACLE_BIRLESTIRME_S", "0")

CORE = Path(__file__).resolve().parents[4]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine  # noqa: E402

import tp_core.features.oracle.jobs  # noqa: E402, F401  (oracle.* iş işleyicileri)
from tests.unit.features.cases.helpers import (  # noqa: E402, F401  (pytest fikstürleri)  # noqa: E402
    api,
    fake_gateway,
    jira,
    login,
    make_requirement,
    replay_gateway,
    run_jobs,
    sim,
    sim_transport,
    targets,
    uretim_cikti,
    worker,
)
from tests.unit.features.oracle.helpers import BASIT, olgu_modeli, tablo_ekle  # noqa: E402
from tp_core.gateway.testing import text_response  # noqa: E402


@pytest.fixture
def kur(api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway):  # noqa: F811
    """Basit tablolu (AC1) gereksinim + sahte model; case'ler tablo onayından ÖNCE üretilir.

    API oturumu Testçidir (üretim, `accept`/`edit` kapısı, `oracle-check`)."""

    def _kur(cases: list[dict], *, tablo_once: bool = False, olgu_sayisi: int = 0):
        provider = fake_gateway(
            [text_response(uretim_cikti(cases))] + [olgu_modeli] * max(olgu_sayisi, 0)
        )
        rid = make_requirement()
        analist, po = make_user("analyst"), make_user("po")
        # 012 rol modeli: case üretimi ve kabulü (kapı) Testçide, son onay Analistte.
        testci = make_user("tester")
        tid = tablo_ekle(rid, BASIT, analist, po) if tablo_once else None
        login(api, testci)
        assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
        run_jobs(engine, limit=50)
        if tid is None:
            tid = tablo_ekle(rid, BASIT, analist, po)
        return {
            "rid": rid,
            "analist": analist,
            "po": po,
            "testci": testci,
            "tid": tid,
            "provider": provider,
        }

    return _kur
