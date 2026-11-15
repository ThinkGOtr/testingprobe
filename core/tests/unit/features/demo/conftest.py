"""Şerit fikstürleri."""

from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _proje_baglami(proje: Any) -> Any:
    """Şeridin testleri varsayılan proje (`test-a`, `TP_HOME_PROJECT`) bağlamında koşar
    (TP-COK-PROJE-PLANI §2.1, §7 Şerit 5)."""
    return proje
