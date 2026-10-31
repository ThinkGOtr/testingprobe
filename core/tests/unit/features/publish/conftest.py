"""Gerçek Postgres (platform fikstürü) + süreç içi jira-sim + model geçidi fikstürleri."""

import sys
from pathlib import Path

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
