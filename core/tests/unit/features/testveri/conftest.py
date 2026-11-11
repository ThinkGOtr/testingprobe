"""Test verisi kataloğu testleri: gerçek Postgres + case/kod üretimi fikstürleri (013 §3.3)."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

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
from tests.unit.features.codegen.conftest import (  # noqa: E402, F401  (pytest fikstürleri)
    ci_cagrilari,
    codegen,
    demo_bare,
    forge_dirs,
)
from tp_core.features.cases import testdata  # noqa: E402
from tp_core.features.testveri import service  # noqa: E402
from tp_core.models import session_scope  # noqa: E402

DEMO_PAROLA = "Demo123!"

# demo-app seed'inin salt okuma sorgu sonuçları (DEMO-VERISI.md; bugs/helpers.SEED_ROWS ile aynı).
SEED_ROWS: dict[str, list[tuple[Any, ...]]] = {
    "urun": [
        ("P-001", "Portakal Gazozu 1L", Decimal("25.00")),
        ("P-002", "Limonata 330ml", Decimal("15.00")),
        ("P-003", "Maden Suyu 200ml", Decimal("8.00")),
        ("P-004", "Şeftalili Soğuk Çay 1L", Decimal("30.00")),
    ],
    "kampanya": [("K-6AL1", "6 al 1 bedava", "P-001")],
    "ayar": [("min_siparis_tutari", "750.00")],
    "bayi": [
        ("bayi1", "Merkez Bayi", Decimal("100000.00")),
        ("bayi2", "Sahil Bayi", Decimal("500.00")),
    ],
}


def seed_sorgu(sql: str) -> Sequence[Sequence[Any]]:
    ad = {v: k for k, v in testdata.SORGULAR.items()}[sql]
    return SEED_ROWS[ad]


@pytest.fixture
def parola_sirri(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(service.DEMO_PAROLA_SIRRI, DEMO_PAROLA)
    return DEMO_PAROLA


@pytest.fixture
def katalog(engine: Any, parola_sirri: str) -> int:
    """Demo DB satırlarından tohumlanmış katalog (parola sırrı ortamda tanımlı)."""
    with session_scope() as s:
        return service.tohumla(s, seed_sorgu)
