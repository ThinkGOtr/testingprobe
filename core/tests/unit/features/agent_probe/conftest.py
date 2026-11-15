"""Gerçek Postgres (platform fikstürü) + case şeridinin gereksinim/API fikstürleri."""

from typing import Any

import pytest

from tests.unit.features.cases.helpers import (  # noqa: F401  (pytest fikstürleri)
    api,
    make_requirement,
)


@pytest.fixture(autouse=True)
def _proje_baglami(proje: Any) -> Any:
    """Şeridin testleri varsayılan proje (`test-a`, `TP_HOME_PROJECT`) bağlamında koşar
    (TP-COK-PROJE-PLANI §2.1, §7 Şerit 5)."""
    return proje
