"""Core'un PR dal önekleri CI'daki AST koruması mod seçimiyle aynı olmalı."""

from pathlib import Path

import pytest
import yaml

from tp_core.integrations.forge import CASE_BRANCH_PREFIX, REPAIR_BRANCH_PREFIX

CI = Path(__file__).resolve().parents[4] / ".github" / "workflows" / "ci.yml"


@pytest.mark.skipif(not CI.exists(), reason="ci.yml yok (yalnızca core kopyalanmış)")
def test_dal_onekleri_ci_ile_ayni() -> None:
    env = yaml.safe_load(CI.read_text(encoding="utf-8"))["env"]
    assert env["REPAIR_BRANCH_PREFIX"] == REPAIR_BRANCH_PREFIX
    assert env["CASE_BRANCH_PREFIX"] == CASE_BRANCH_PREFIX
