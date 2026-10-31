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

Şeritlere açık yardımcılar:
- `requirement_block(...)`: story/serbest metin → kanonik `<untrusted>` blok (golden eşleşmesi ve
  replay anahtarı kararlılığı için önerilen tek biçim); `FREE_TEXT_KEY` serbest metin golden kökü.
- `wrap_tool_result(tool, text)`: ajan araç sonucu → türüne uygun `<untrusted>` blok.
- `result_digest(rows)` / `digest_matches(claimed, rows)`: veri kanıtı özeti (§8.2b adım 4);
  `db_query` aracı, golden'lar ve doğrulayıcı aynı fonksiyonu kullanır.
- `normalize_text` / `input_hash`: replay anahtarının girdi normu (zaman damgası, UUID, sha …).
- `input_mismatches(spec, messages)`: golden girdi beyanı denetimi (REPLAY ↔ REPLAY-MISS).
- `mode_label(mode, model)`: Jira yorumu/portal için dürüst üretim modu etiketi; `model`
  `ai_call.model`'dir (`HAND_PREPARED_MODEL` = elle hazırlanmış örnek çıktı, model kaydı değil).
"""

from tp_core.gateway.budget import Budget, InMemorySpendLedger, SpendLedger
from tp_core.gateway.bundle import Bundle, load_bundle, load_schema
from tp_core.gateway.canonical import input_hash, normalize_text
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
    ReplayNoOutput,
    ReplayNotFound,
    SchemaValidationFailed,
)
from tp_core.gateway.evidence import digest_matches, result_digest
from tp_core.gateway.factory import build_gateway
from tp_core.gateway.inputs import (
    FREE_TEXT_KEY,
    numbered_acceptance_criteria,
    requirement_block,
    wrap_tool_result,
)
from tp_core.gateway.masking import MaskingSession, PiiMasker
from tp_core.gateway.matching import MATCHED, input_mismatches
from tp_core.gateway.replay import (
    HAND_PREPARED_MODEL,
    MISS_NEUTRAL,
    ReplayStore,
    golden_name,
    mode_label,
    output_origin,
)
from tp_core.gateway.untrusted import wrap_untrusted

__all__ = [
    "ALLOWED_AGENT_TOOLS",
    "FINAL_TOOL",
    "FORBIDDEN_TOOLS",
    "FREE_TEXT_KEY",
    "HAND_PREPARED_MODEL",
    "MATCHED",
    "MISS_NEUTRAL",
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
    "ReplayNoOutput",
    "ReplayNotFound",
    "ReplayStore",
    "RetryPolicy",
    "SchemaValidationFailed",
    "SpendLedger",
    "build_gateway",
    "default_is_snapshot",
    "deterministic_call_id",
    "digest_matches",
    "find_rules_dir",
    "golden_name",
    "input_hash",
    "input_mismatches",
    "load_bundle",
    "load_model_table",
    "load_schema",
    "mode_label",
    "normalize_text",
    "numbered_acceptance_criteria",
    "output_origin",
    "requirement_block",
    "resolve_mode",
    "result_digest",
    "wrap_tool_result",
    "wrap_untrusted",
]
