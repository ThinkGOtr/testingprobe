"""Ortamdan geçit kurulumu (core-worker başlangıcında bir kez).

TP_MODEL_MODE=auto   → ANTHROPIC_API_KEY varsa live, yoksa replay (varsayılan)
TP_MODEL_MODE=live   → anahtar zorunlu; yoksa ProviderNotConfigured
TP_MODEL_MODE=replay → rules/replay kayıtları (REPLAY / REPLAY-MISS)
TP_MODEL_MODE=record → live + başarılı çıktıyı rules/replay/<purpose>/<key>.json'a yazar
                       (replay dizini yazılamıyorsa başlangıçta GatewayConfigError)

Kriter 7 (canlı akış düşerse REPLAY'den devam): `auto` kipinde (anahtar varken live) bir çağrı
sağlayıcı hatası ya da zaman aşımıyla düşerse geçit aynı çağrıyı REPLAY golden'ından sürdürür;
satır `replay`/`replay_miss` etiketlidir, `ek.canli_hata_yedegi` düşen canlı çağrıyı gösterir.
`TP_REPLAY_FALLBACK=1/0` bunu açıkça açar/kapatır (açık `live` kipinde varsayılan kapalı);
`record` kipinde hiçbir zaman açılmaz. Model reddi (refusal) yedeğe düşmez, insana gider.

`engine` verilirse (core-worker): harcama defteri `PgSpendLedger` (tavanlar yeniden başlatmada
korunur) ve `call_id` idempotency'si için `PgCallLookup` kullanılır. Verilmezse süreç içi defter
(yalnızca testler/araçlar için).
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from sqlalchemy import Engine

from tp_core.gateway.budget import Budget, SpendLedger
from tp_core.gateway.config import (
    GatewaySettings,
    find_rules_dir,
    load_model_table,
    resolve_mode,
    resolve_replay_fallback,
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


# Ajan araç kaydından (tool_call) her zaman silinen sırların ortam değişkenleri (değer boşsa yok).
SECRET_ENV_VARS = ("TP_AGENT_DEALER_PASSWORD",)


def known_secret_values() -> list[str]:
    return [v for v in (os.environ.get(name, "") for name in SECRET_ENV_VARS) if v]


def build_provider(settings: GatewaySettings) -> Provider:
    if settings.model_provider == "azure_openai":
        from tp_core.gateway.providers.azure_openai_provider import AzureOpenAIProvider

        return AzureOpenAIProvider()
    from tp_core.gateway.providers.anthropic_provider import AnthropicProvider

    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
    workspace = (
        settings.anthropic_workspace_id.get_secret_value()
        if settings.anthropic_workspace_id
        else None
    )
    return AnthropicProvider(api_key=key, workspace_id=workspace)


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
        secret_values=known_secret_values(),
        # Kriter 7: `auto` kipinde canlı çağrı düşerse REPLAY golden'ıyla (etiketli) devam.
        replay_fallback=resolve_replay_fallback(settings),
    )
