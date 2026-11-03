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
import re
from collections.abc import Mapping
from pathlib import Path

import yaml
from sqlalchemy import Engine

from tp_core.gateway.budget import Budget, SpendLedger
from tp_core.gateway.config import (
    EffectiveMode,
    GatewaySettings,
    find_rules_dir,
    load_model_table,
    resolve_mode,
    resolve_replay_fallback,
)
from tp_core.gateway.core import CallLookup, Gateway
from tp_core.gateway.errors import GatewayConfigError
from tp_core.gateway.masking import SECRET_VALUE_MIN_LEN, PiiMasker
from tp_core.gateway.providers.base import Provider
from tp_core.gateway.replay import ReplayStore
from tp_core.ports import CallRecorder


def load_pii_allowlist(rules_dir: Path) -> list[str]:
    path = rules_dir / "pii-allowlist.yaml"
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [str(v) for v in data.get("values", [])]


# Ajan araç kaydından (tool_call) ve asistan araç çıktılarından her zaman silinen sırların ortam
# değişkenleri (değer boşsa yok). İlki bilinen demo parolasıdır (uzunluk sınırı yok, geriye uyum);
# diğerleri yalnızca ≥ 8 karakterse alınır — `JIRA_WRITE_TOKEN=sim` gibi simülatör değerleri
# kayıtlarda rastgele eşleşmesin (AI-ASISTAN-PLANI §10.3 Şerit C1).
SECRET_ENV_VARS = (
    "TP_AGENT_DEALER_PASSWORD",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_WORKSPACE_ID",
    "AZURE_OPENAI_API_KEY",
    "GITHUB_TOKEN",
    "GITHUB_READ_TOKEN",
    "GITHUB_MERGE_TOKEN",
    "GH_APP_PRIVATE_KEY",
    "JIRA_READ_TOKEN",
    "JIRA_WRITE_TOKEN",
    "JIRA_SIM_ADMIN_TOKEN",
    "XRAY_CLIENT_SECRET",
    "TP_APP_PASSWORD",
    "TP_OWNER_PASSWORD",
    "TP_SESSION_SECRET",
    "TP_TOOLCHAIN_TOKEN",
    "TP_FORGE_REMOTE_TOKEN",
    "DEMOAPP_RO_PASSWORD",
    "SEED_USER_PASSWORD",
)
# Listede olmayan ama adı sır olan değişkenler (ör. yeni `GITHUB_*TOKEN`, `JIRA_*_TOKEN`).
# `_PATH`/`_ID` gibi sonekler eşleşmez (`GH_APP_PRIVATE_KEY_PATH` sır değil, yoldur).
SECRET_ENV_NAME_RE = re.compile(
    r"^(?:GITHUB_\w*TOKEN|GH_\w*TOKEN|JIRA_\w*TOKEN|\w+_PASSWORD|\w+_SECRET|\w+_API_KEY|\w+_PRIVATE_KEY)$"
)
_LEGACY_SECRET_ENV_VARS = frozenset({"TP_AGENT_DEALER_PASSWORD"})


def known_secret_values(environ: Mapping[str, str] | None = None) -> list[str]:
    """Ortamdaki sır değişkenlerinin değerleri (çok satırlı değerin ≥ 8 karakterli satırları da)."""
    env = os.environ if environ is None else environ
    adlar = list(SECRET_ENV_VARS) + sorted(
        ad for ad in env if ad not in SECRET_ENV_VARS and SECRET_ENV_NAME_RE.match(ad)
    )
    out: list[str] = []
    for ad in adlar:
        deger = env.get(ad, "") or ""
        if not deger:
            continue
        if ad in _LEGACY_SECRET_ENV_VARS:
            out.append(deger)
            continue
        if len(deger.strip()) < SECRET_VALUE_MIN_LEN:
            continue
        out.append(deger)
        if "\n" in deger:
            out += [s.strip() for s in deger.splitlines() if len(s.strip()) >= SECRET_VALUE_MIN_LEN]
    return list(dict.fromkeys(out))


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
    mode_override: EffectiveMode | None = None,
    replay_fallback: bool | None = None,
    budget: Budget | None = None,
) -> Gateway:
    """Ortamdan geçit kurar.

    Asistan (AI-ASISTAN-PLANI §10.2) pipeline kipinden bağımsız çalışır:
    - `mode_override`: `TP_MODEL_MODE` yerine bu kip (ör. `"live"`: pipeline REPLAY'deyken de canlı
      sağlayıcı; `record` dışı bir kip verilirse replay dizini yazılabilirlik denetimi yapılmaz ve
      kayıt dosyası yazılmaz).
    - `replay_fallback`: Kriter 7 yedeğini açıkça açar/kapatır (None: ortamdan; kip geçersiz
      kılındıysa geçersiz kılınan kibe göre).
    - `budget`: hazır bütçe (ör. `AsistanBudget`); verilirse `ledger`/ortam tavanları kullanılmaz.
    Hepsinin varsayılanı eski davranıştır.
    """
    settings = settings or GatewaySettings()
    rules_dir = find_rules_dir(settings.rules_dir)
    if mode_override is not None and mode_override not in ("live", "replay", "record"):
        raise GatewayConfigError(f"geçersiz kip: {mode_override!r}")
    mode: EffectiveMode = mode_override or resolve_mode(settings)
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
        budget=budget
        or Budget(
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
        replay_fallback=_replay_fallback(settings, mode_override, replay_fallback),
    )


def _replay_fallback(
    settings: GatewaySettings, mode_override: EffectiveMode | None, explicit: bool | None
) -> bool:
    if explicit is not None:
        return explicit
    if mode_override is None:
        return resolve_replay_fallback(settings)
    # Kip geçersiz kılındıysa `auto` varsayımı (anahtar varken yedek açık) uygulanmaz.
    return resolve_replay_fallback(settings.model_copy(update={"model_mode": mode_override}))
