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
- Kod üretimi (verify_and_map): `approved_case_text` (golden `input_match.case_text` beyanı),
  doğrulama bayisi `VERIFY_AGENT_DEALER`; araç kaydı sırları `mask_tool_args` / `scrub_secrets`;
  rules/replay/README.md.
- `result_digest(rows)` / `digest_matches(claimed, rows)`: veri kanıtı özeti (§8.2b adım 4);
  `db_query` aracı, golden'lar ve doğrulayıcı aynı fonksiyonu kullanır.
- `normalize_text` / `input_hash`: replay anahtarının girdi normu (zaman damgası, UUID, sha …).
- `input_mismatches(spec, messages)`: golden girdi beyanı denetimi (REPLAY ↔ REPLAY-MISS).
- `mode_label(mode, model)`: Jira yorumu/portal için dürüst üretim modu etiketi; `model`
  `ai_call.model`'dir (`HAND_PREPARED_MODEL` = elle hazırlanmış örnek çıktı, model kaydı değil).
- Faz 4 (triage / bug taslağı / mükerrer): girdiyi YALNIZCA `tp_core.gateway.defects`
  kurucularıyla kurun (`failure_block`, `case_block`, `finding_block`, `triage_messages`,
  `bug_draft_messages`, `dup_rank_messages`) ve `replay_key=defect_replay_key(story_key)` verin;
  çıktıdaki `kanit:<ad>` yer tutucularını `resolve_evidence` çözer, `invented_dup_keys` aramada
  olmayan anahtarı, `dup_rank_problems` sıralama değişmezlerinin (her aday tam bir kez, sıra
  1..n, gerekçe ≤ 200, `link` yalnızca `high` adaya) tüm aykırılıklarını yakalar.
  rules/replay/README.md "Faz 4".
- `evaluation_summary(rules_dir, bundle_id)` / `Gateway.evaluation_of(bundle_id)`: paketin canlı
  değerlendirme durumu (constitution X); geçit her `ai_call.ek.degerlendirme`'ye yazar
  (`etiket` = "canlı değerlendirme bekliyor").
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
    FORBIDDEN_TOOL_ARGS,
    FORBIDDEN_TOOLS,
    RESTRICTED_TOOL_ARGS,
    UNGRANTED_MCP_TOOLS,
    CallLookup,
    Gateway,
    ReplayKeyInfo,
    RetryPolicy,
    default_is_snapshot,
    deterministic_call_id,
    narrow_tool,
    restricted_args,
)
from tp_core.gateway.defects import (
    DEFECT_GOLDEN_KEY,
    EVIDENCE_PREFIX,
    bug_draft_messages,
    candidates_text,
    canonical_test_file,
    canonical_test_title,
    case_block,
    defect_replay_key,
    dup_rank_messages,
    dup_rank_problems,
    failure_block,
    failure_text,
    finding_block,
    finding_text,
    invented_dup_keys,
    literal_evidence_refs,
    resolve_evidence,
    triage_messages,
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
from tp_core.gateway.evaluation import PENDING_LABEL, evaluation_summary
from tp_core.gateway.evidence import digest_matches, result_digest
from tp_core.gateway.factory import build_gateway
from tp_core.gateway.inputs import (
    FREE_TEXT_KEY,
    VERIFY_AGENT_DEALER,
    VERIFY_AGENT_DEALER_NAME,
    VERIFY_BASE_URL,
    approved_case_text,
    numbered_acceptance_criteria,
    requirement_block,
    wrap_tool_result,
)
from tp_core.gateway.masking import (
    MaskingSession,
    PiiMasker,
    mask_tool_args,
    scrub_secrets,
    secret_tool_values,
)
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
    "DEFECT_GOLDEN_KEY",
    "EVIDENCE_PREFIX",
    "FINAL_TOOL",
    "FORBIDDEN_TOOLS",
    "FORBIDDEN_TOOL_ARGS",
    "FREE_TEXT_KEY",
    "HAND_PREPARED_MODEL",
    "MATCHED",
    "MISS_NEUTRAL",
    "PENDING_LABEL",
    "RESTRICTED_TOOL_ARGS",
    "UNGRANTED_MCP_TOOLS",
    "VERIFY_AGENT_DEALER",
    "VERIFY_AGENT_DEALER_NAME",
    "VERIFY_BASE_URL",
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
    "approved_case_text",
    "bug_draft_messages",
    "build_gateway",
    "candidates_text",
    "canonical_test_file",
    "canonical_test_title",
    "case_block",
    "default_is_snapshot",
    "defect_replay_key",
    "deterministic_call_id",
    "digest_matches",
    "dup_rank_messages",
    "dup_rank_problems",
    "evaluation_summary",
    "failure_block",
    "failure_text",
    "find_rules_dir",
    "finding_block",
    "finding_text",
    "golden_name",
    "input_hash",
    "input_mismatches",
    "invented_dup_keys",
    "literal_evidence_refs",
    "load_bundle",
    "load_model_table",
    "load_schema",
    "mask_tool_args",
    "mode_label",
    "narrow_tool",
    "normalize_text",
    "numbered_acceptance_criteria",
    "output_origin",
    "requirement_block",
    "resolve_evidence",
    "resolve_mode",
    "restricted_args",
    "result_digest",
    "scrub_secrets",
    "secret_tool_values",
    "triage_messages",
    "wrap_tool_result",
    "wrap_untrusted",
]
