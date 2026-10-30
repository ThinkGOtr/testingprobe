"""Model geçidi (TEKNIK-TASARIM §8.8–§8.9): sağlayıcıdan bağımsız `ports.ModelGateway`.

Kullanım (core-worker):

    from tp_core.gateway import build_gateway, load_schema, wrap_untrusted
    gw = build_gateway(recorder, engine=engine)     # TP_MODEL_MODE'a göre live / replay
    schema = load_schema(gw.rules_dir, "requirement_review")
    msg = ModelMessage(role="user", content=wrap_untrusted(text, source="jira:TPD-1", kind="jira"))
    result = gw.call("requirement_review", "requirement-review", [msg], schema,
                     replay_key={"name": golden_name("TPD-1"), "jira_key": "TPD-1"},
                     workflow_id=wf, call_id=deterministic_call_id(job_id, "requirement_review"))
    result.mode  # "live" | "replay" | "replay_miss" → portalda REPLAY / REPLAY-MISS rozeti
"""

from tp_core.gateway.budget import Budget, InMemorySpendLedger, SpendLedger
from tp_core.gateway.bundle import Bundle, load_bundle, load_schema
from tp_core.gateway.config import (
    GatewaySettings,
    ModelTable,
    find_rules_dir,
    load_model_table,
    resolve_mode,
)
from tp_core.gateway.core import (
    ALLOWED_AGENT_TOOLS,
    FINAL_TOOL,
    FORBIDDEN_TOOLS,
    UNGRANTED_MCP_TOOLS,
    CallLookup,
    Gateway,
    ReplayKeyInfo,
    RetryPolicy,
    default_is_snapshot,
    deterministic_call_id,
)
from tp_core.gateway.errors import (
    AgentTurnLimit,
    BudgetExceeded,
    GatewayConfigError,
    GatewayError,
    ProviderNotConfigured,
    ProviderPermanentError,
    ProviderRefusal,
    ProviderTransientError,
    ReplayMiss,
    ReplayNotFound,
    SchemaValidationFailed,
)
from tp_core.gateway.factory import build_gateway
from tp_core.gateway.masking import MaskingSession, PiiMasker
from tp_core.gateway.replay import ReplayStore, golden_name
from tp_core.gateway.untrusted import wrap_untrusted

__all__ = [
    "ALLOWED_AGENT_TOOLS",
    "FINAL_TOOL",
    "FORBIDDEN_TOOLS",
    "UNGRANTED_MCP_TOOLS",
    "AgentTurnLimit",
    "Budget",
    "BudgetExceeded",
    "Bundle",
    "CallLookup",
    "Gateway",
    "GatewayConfigError",
    "GatewayError",
    "GatewaySettings",
    "InMemorySpendLedger",
    "MaskingSession",
    "ModelTable",
    "PiiMasker",
    "ProviderNotConfigured",
    "ProviderPermanentError",
    "ProviderRefusal",
    "ProviderTransientError",
    "ReplayKeyInfo",
    "ReplayMiss",
    "ReplayNotFound",
    "ReplayStore",
    "RetryPolicy",
    "SchemaValidationFailed",
    "SpendLedger",
    "build_gateway",
    "default_is_snapshot",
    "deterministic_call_id",
    "find_rules_dir",
    "golden_name",
    "load_bundle",
    "load_model_table",
    "load_schema",
    "resolve_mode",
    "wrap_untrusted",
]
