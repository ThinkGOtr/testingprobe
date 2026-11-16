"""Gerçek Postgres (platform fikstürü) + süreç içi jira-sim + model geçidi fikstürleri."""

import os
import sys
from pathlib import Path

import pytest

# Oracle gereksinim kontrolü birleştirme gecikmesi (run_after): testlerde işler hemen koşar.
os.environ.setdefault("TP_ORACLE_BIRLESTIRME_S", "0")

CORE = Path(__file__).resolve().parents[4]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from tests.unit.features.cases.helpers import (  # noqa: E402, F401  (pytest fikstürleri)
    api,
    fake_gateway,
    jira,
    make_requirement,
    replay_gateway,
    sim,
    sim_transport,
    targets,
    worker,
)


@pytest.fixture(autouse=True)
def _proje_baglami(proje: object) -> object:
    """Çok proje (TP-COK-PROJE-PLANI §2.4): bu dizinin testleri `test-a` projesinin bağlamında
    koşar; DB'li testlerde `sql_denetimi` proje kapsamlı ham SQL'i denetler. Bağlamsız davranışı
    sınayan test kodu `contextvars.Context().run(...)` ile koşturur."""
    return proje
