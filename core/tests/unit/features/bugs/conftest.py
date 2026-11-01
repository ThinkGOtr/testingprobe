"""Gerçek Postgres (platform fikstürü) + süreç içi jira-sim + model geçidi fikstürleri."""

import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[4]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from tests.unit.features.bugs.helpers import (  # noqa: E402, F401  (pytest fikstürleri)
    bug_fake_gateway,
    bug_replay_gateway,
    bug_services,
)
from tests.unit.features.cases.helpers import (  # noqa: E402, F401  (pytest fikstürleri)
    api,
    jira,
    sim,
    sim_transport,
    worker,
)
