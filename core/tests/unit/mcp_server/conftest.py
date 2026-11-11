"""Gerçek Postgres (platform fikstürü) + süreç içi jira-sim + model geçidi fikstürleri."""

import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[3]
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


@pytest.fixture(autouse=True)
def _red_hiz_siniri_sifirla():
    """MCP kimlik reddi denetim kaydının hız sınırı süreç içi durumdur; her test temiz başlar."""
    from tp_core.mcp_server import server

    server._son_red.clear()
    yield
    server._son_red.clear()


@pytest.fixture(autouse=True)
def _denetim_kapisi_kapali(monkeypatch: pytest.MonkeyPatch):
    """MCP yayın testleri onay/hash kapısını sınar; denetim kapısı (011 K3) bağlı ama kapalı.
    Kapının kendisi `features/cases/test_review_denetim.py`'de sınanır."""
    from tp_core.features.cases import denetim_akisi

    monkeypatch.setenv("TP_DENETIM_KAPISI", "off")
    yield
    denetim_akisi.bind_gate()
