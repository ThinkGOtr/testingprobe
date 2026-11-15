"""Uçtan uca kalite doğrulama (012) fikstürleri: gerçek Postgres, API, REPLAY golden'ları."""

import os
import sys
from pathlib import Path
from typing import Any

import pytest

# Oracle gereksinim kontrolü birleştirme gecikmesi (run_after): testlerde işler hemen koşar.
os.environ.setdefault("TP_ORACLE_BIRLESTIRME_S", "0")

CORE = Path(__file__).resolve().parents[4]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import tp_core.features.karar_tablosu.jobs  # noqa: E402  (karar_tablosu.draft)
import tp_core.features.oracle.jobs  # noqa: E402, F401  (oracle.*)
from tests.unit.features.cases.helpers import (  # noqa: E402, F401  (pytest fikstürleri)
    api,
    make_requirement,
)


@pytest.fixture(autouse=True)
def _proje_baglami(proje: Any) -> Any:
    """Şeridin testleri varsayılan proje (`test-a`, `TP_HOME_PROJECT`) bağlamında koşar
    (TP-COK-PROJE-PLANI §2.1, §7 Şerit 5)."""
    return proje
