from datetime import date

import pytest

from tp_core.gateway import (
    Budget,
    BudgetExceeded,
    GatewaySettings,
    InMemorySpendLedger,
    ProviderNotConfigured,
    build_gateway,
    load_model_table,
    resolve_mode,
)
from tp_core.gateway.providers.azure_openai_provider import AzureOpenAIProvider
from tp_core.gateway.providers.base import Usage
from tp_core.gateway.testing import InMemoryCallRecorder

from .conftest import REAL_RULES


def settings(**env) -> GatewaySettings:
    return GatewaySettings.model_validate(env)


@pytest.mark.parametrize(
    ("env", "mode"),
    [
        ({}, "replay"),
        ({"ANTHROPIC_API_KEY": "sk-test"}, "live"),
        ({"ANTHROPIC_API_KEY": ""}, "replay"),
        ({"TP_MODEL_MODE": "replay", "ANTHROPIC_API_KEY": "sk-test"}, "replay"),
        ({"TP_MODEL_MODE": "record", "ANTHROPIC_API_KEY": "sk-test"}, "record"),
        ({"TP_MODEL_MODE": "live"}, "live"),
    ],
)
def test_resolve_mode(env, mode) -> None:
    assert resolve_mode(settings(**env)) == mode


def test_settings_defaults(monkeypatch) -> None:
    for var in ("TP_MODEL_MODE", "TP_DAILY_BUDGET_USD", "TP_WORKFLOW_BUDGET_USD", "TP_PII_MASKING"):
        monkeypatch.delenv(var, raising=False)
    s = GatewaySettings()
    assert (s.daily_budget_usd, s.workflow_budget_usd, s.pii_masking) == (30.0, 2.0, False)
    monkeypatch.setenv("TP_PII_MASKING", "1")
    monkeypatch.setenv("TP_WORKFLOW_BUDGET_USD", "0.5")
    s = GatewaySettings()
    assert s.pii_masking is True and s.workflow_budget_usd == 0.5


def test_build_gateway_without_key_is_replay() -> None:
    gw = build_gateway(InMemoryCallRecorder(), settings=settings(TP_RULES_DIR=str(REAL_RULES)))
    assert gw.mode == "replay"
    assert gw.provider is None
    assert gw.masker.enabled is False
    assert "writer@sim.local" in gw.masker.allowlist


def test_build_gateway_live_needs_key() -> None:
    with pytest.raises(ProviderNotConfigured):
        build_gateway(
            InMemoryCallRecorder(),
            settings=settings(TP_MODEL_MODE="live", TP_RULES_DIR=str(REAL_RULES)),
        )


def test_build_gateway_live_with_key_uses_anthropic() -> None:
    gw = build_gateway(
        InMemoryCallRecorder(),
        settings=settings(ANTHROPIC_API_KEY="sk-test", TP_RULES_DIR=str(REAL_RULES)),
    )
    assert gw.mode == "live" and gw.provider_name == "anthropic"


def test_azure_not_configured(monkeypatch) -> None:
    for var in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ProviderNotConfigured, match="AZURE_OPENAI_ENDPOINT"):
        AzureOpenAIProvider()


def test_cost_table() -> None:
    table = load_model_table(REAL_RULES)
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000, cache_read_tokens=1_000_000)
    assert table.cost("claude-sonnet-5-5", usage) == pytest.approx(2.0 + 10.0 + 0.2)
    assert table.cost("claude-haiku-5-5", usage) == pytest.approx(0.1 + 0.5 + 0.01)


def test_daily_ledger_resets_by_day() -> None:
    today = [date(2026, 10, 30)]
    ledger = InMemorySpendLedger(today=lambda: today[0])
    budget = Budget(workflow_cap_usd=100, daily_cap_usd=1.0, ledger=ledger)
    budget.charge(None, 1.5)
    with pytest.raises(BudgetExceeded):
        budget.check(None)
    today[0] = date(2026, 10, 31)
    budget.check(None)
