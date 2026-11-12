"""Gerçek Postgres (platform fikstürü) + case fikstürleri (sahte/REPLAY geçit, jira-sim)."""

import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[4]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import tp_core.features.oracle.jobs  # noqa: E402, F401  (oracle.* iş işleyicileri)
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
