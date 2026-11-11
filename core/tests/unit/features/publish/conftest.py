"""Gerçek Postgres (platform fikstürü) + süreç içi jira-sim + model geçidi fikstürleri."""

import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[4]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import pytest  # noqa: E402

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
from tp_core.features.cases import denetim_akisi  # noqa: E402


@pytest.fixture(autouse=True)
def _denetim_kapisi_kapali(monkeypatch: pytest.MonkeyPatch):
    """Yayın testleri denetim kapısından (011 K3) bağımsız yayın kurallarını sınar: kapı bağlıdır
    ama `TP_DENETIM_KAPISI=off`. Kapıyı sınayan testler ortamı `on` yapar
    (`features/cases/test_review_denetim.py`). Test kancayı değiştirse de sonra yeniden bağlanır."""
    monkeypatch.setenv("TP_DENETIM_KAPISI", "off")
    yield
    denetim_akisi.bind_gate()
