"""TP_TEST_TEK_HESAP: yalnız test için ürünün Jira hesabı PO onaylayanı olabilir."""

from __future__ import annotations

import pytest

from tp_core.config import get_settings
from tp_core.workflow.service import ApprovalNotAllowed, check_jira_approver


@pytest.fixture(autouse=True)
def _ayar(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TP_DATABASE_URL", "postgresql+psycopg://u:p@localhost:1/x")
    monkeypatch.setenv("TP_SESSION_SECRET", "s" * 32)
    monkeypatch.setenv("JIRA_WRITE_EMAIL", "bot@ornek.test")
    monkeypatch.setenv("TP_PO_JIRA_USERS", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_varsayilan_kapali_bot_onaylayamaz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TP_TEST_TEK_HESAP", raising=False)
    get_settings.cache_clear()
    assert get_settings().test_tek_hesap is False
    with pytest.raises(ApprovalNotAllowed):
        check_jira_approver("bot@ornek.test")


def test_acikken_bot_hesabi_onaylayabilir_sim_botlari_yine_ayrik(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TP_TEST_TEK_HESAP", "1")
    get_settings.cache_clear()
    assert check_jira_approver("bot@ornek.test") == "bot@ornek.test"
    with pytest.raises(ApprovalNotAllowed):
        check_jira_approver("writer@sim.local")
