"""Gerçek Postgres (platform fikstürü) + sahte toolchain-worker / forge / GitHub fikstürleri."""

import sys
from pathlib import Path
from typing import Any

import pytest

CORE = Path(__file__).resolve().parents[4]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from tests.unit.features.ci.helpers import (  # noqa: E402, F401  (pytest fikstürleri)
    api,
    artefakt_kok,
    ci_env,
    fake_forge,
    make_requirement_case,
    toolchain,
)


@pytest.fixture(autouse=True)
def _proje_baglami(proje: Any) -> Any:
    """Şeridin testleri varsayılan proje (`test-a`, `TP_HOME_PROJECT`) bağlamında koşar
    (TP-COK-PROJE-PLANI §2.1, §7 Şerit 5)."""
    return proje
