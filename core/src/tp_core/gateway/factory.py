"""Ortamdan geçit kurulumu (core-worker başlangıcında bir kez).

TP_MODEL_MODE=auto   → ANTHROPIC_API_KEY varsa live, yoksa replay (varsayılan)
TP_MODEL_MODE=live   → anahtar zorunlu; yoksa ProviderNotConfigured
TP_MODEL_MODE=replay → rules/replay kayıtları (REPLAY / REPLAY-MISS)
TP_MODEL_MODE=record → live + başarılı çıktıyı rules/replay/<purpose>/<key>.json'a yazar
                       (replay dizini yazılamıyorsa başlangıçta GatewayConfigError)

`engine` verilirse (core-worker): harcama defteri `PgSpendLedger` (tavanlar yeniden başlatmada
korunur) ve `call_id` idempotency'si için `PgCallLookup` kullanılır. Verilmezse süreç içi defter
(yalnızca testler/araçlar için).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy import Engine

from tp_core.gateway.budget import Budget, SpendLedger
from tp_core.gateway.config import (
    GatewaySettings,
    find_rules_dir,
    load_model_table,
    resolve_mode,
)
from tp_core.gateway.core import CallLookup, Gateway
from tp_core.gateway.masking import PiiMasker
from tp_core.gateway.providers.base import Provider
from tp_core.gateway.replay import ReplayStore
from tp_core.ports import CallRecorder


def load_pii_allowlist(rules_dir: Path) -> list[str]:
    path = rules_dir / "pii-allowlist.yaml"
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [str(v) for v in data.get("values", [])]


def build_provider(settings: GatewaySettings) -> Provider:
    if settings.model_provider == "azure_openai":
        from tp_core.gateway.providers.azure_openai_provider import AzureOpenAIProvider

        return AzureOpenAIProvider()
    from tp_core.gateway.providers.anthropic_provider import AnthropicProvider

    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    return AnthropicProvider(api_key=key)


def build_gateway(
    recorder: CallRecorder,
    *,
    settings: GatewaySettings | None = None,
    ledger: SpendLedger | None = None,
    provider: Provider | None = None,
    engine: Engine | None = None,
    call_lookup: CallLookup | None = None,
    record_extras: bool = True,
) -> Gateway:
    settings = settings or GatewaySettings()
    rules_dir = find_rules_dir(settings.rules_dir)
    mode = resolve_mode(settings)
    replay_store = ReplayStore(rules_dir / "replay", strict=settings.replay_strict)
    if mode == "record":
        replay_store.ensure_writable()
    if engine is not None:
        from tp_core.gateway.store import PgCallLookup, PgSpendLedger

        ledger = ledger or PgSpendLedger(engine)
        call_lookup = call_lookup or PgCallLookup(engine)
    if mode != "replay" and provider is None:
        provider = build_provider(settings)
    return Gateway(
        provider=provider if mode != "replay" else None,
        recorder=recorder,
        mode=mode,
        models=load_model_table(rules_dir),
        rules_dir=rules_dir,
        budget=Budget(
            workflow_cap_usd=settings.workflow_budget_usd,
            daily_cap_usd=settings.daily_budget_usd,
            ledger=ledger,
        ),
        masker=PiiMasker(enabled=settings.pii_masking, allowlist=load_pii_allowlist(rules_dir)),
        replay_store=replay_store,
        call_lookup=call_lookup,
        # ai_call.ek (0005): replay_kokeni ile yükseltilmiş golden ↔ kayıt ayrımı denetimde görünür
        record_extras=record_extras,
    )
