"""Geçit yapılandırması: ortam değişkenleri ve `rules/models.yaml` (görev başına model + fiyat)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from tp_core.gateway.errors import GatewayConfigError
from tp_core.gateway.providers.base import Usage

ModelMode = Literal["auto", "live", "replay", "record"]
EffectiveMode = Literal["live", "replay", "record"]


class GatewaySettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    model_mode: ModelMode = Field(default="auto", validation_alias="TP_MODEL_MODE")
    model_provider: Literal["anthropic", "azure_openai"] = Field(
        default="anthropic", validation_alias="TP_MODEL_PROVIDER"
    )
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    # Çalışma alanına bağlı anahtarlar için `anthropic-workspace-id` başlığı (boş = gönderilmez).
    # Sır gibi ele alınır: loglanmaz, yazdırılmaz (SecretStr).
    anthropic_workspace_id: SecretStr | None = Field(
        default=None, validation_alias="ANTHROPIC_WORKSPACE_ID"
    )
    daily_budget_usd: float = Field(default=30.0, validation_alias="TP_DAILY_BUDGET_USD")
    workflow_budget_usd: float = Field(default=2.0, validation_alias="TP_WORKFLOW_BUDGET_USD")
    pii_masking: bool = Field(default=False, validation_alias="TP_PII_MASKING")
    rules_dir: Path | None = Field(default=None, validation_alias="TP_RULES_DIR")
    # Prova kipi: replay'de golden'a (REPLAY-MISS) düşmek yerine hata (§13 prova listesi).
    replay_strict: bool = Field(default=False, validation_alias="TP_REPLAY_STRICT")
    # Kriter 7 (TEKNIK-TASARIM §1, §13): canlı çağrı sağlayıcı hatası/zaman aşımıyla düşerse aynı
    # çağrı REPLAY golden'ından (etiketli `replay`/`replay_miss`) sürdürülür. Boş = `auto` kipinde
    # açık, açık `live`/`record` kipinde kapalı (değerlendirme/kayıt sahte başarı üretmesin).
    replay_fallback: bool | None = Field(default=None, validation_alias="TP_REPLAY_FALLBACK")


def resolve_replay_fallback(settings: GatewaySettings) -> bool:
    """Canlı hata → REPLAY yedeği açık mı? `record` kipinde hiçbir zaman (kayıt sahte olmasın)."""
    if settings.model_mode in ("record", "replay"):
        return False
    if settings.replay_fallback is not None:
        return settings.replay_fallback
    return settings.model_mode == "auto"


def resolve_mode(settings: GatewaySettings) -> EffectiveMode:
    """auto: anahtar varsa live, yoksa replay. record: live + replay dosyası yazar."""
    has_key = bool(settings.anthropic_api_key and settings.anthropic_api_key.get_secret_value())
    if settings.model_mode == "auto":
        return "live" if has_key else "replay"
    return settings.model_mode


def find_rules_dir(explicit: Path | None = None) -> Path:
    """`TP_RULES_DIR` > depo kökündeki `rules/` (kaynak ağacından çalışırken) > `/rules`."""
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("TP_RULES_DIR")
    if env:
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "rules"
        if (candidate / "models.yaml").is_file():
            return candidate
    return Path("/rules")


@dataclass(frozen=True)
class ModelPrice:
    """USD / 1M token."""

    input: float
    output: float
    cache_read: float = 0.0
    cache_write: float = 0.0

    def cost(self, usage: Usage) -> float:
        total = (
            usage.input_tokens * self.input
            + usage.output_tokens * self.output
            + usage.cache_read_tokens * self.cache_read
            + usage.cache_write_tokens * self.cache_write
        )
        return round(total / 1_000_000, 6)


@dataclass(frozen=True)
class PurposeConfig:
    name: str
    model: str
    max_tokens: int = 4096
    params: dict[str, Any] = field(default_factory=dict)
    max_input_tokens: int | None = None  # ajan: önbelleksiz+yazma girdi toplamı tavanı
    # İstemci zaman aşımı (sn). Taşıma ayarıdır, çıktıyı etkilemez: bundle hash'ine girmez.
    timeout_s: float | None = None


@dataclass(frozen=True)
class ModelTable:
    version: int
    prices: dict[str, ModelPrice]
    purposes: dict[str, PurposeConfig]

    def purpose(self, name: str) -> PurposeConfig:
        try:
            return self.purposes[name]
        except KeyError:
            raise GatewayConfigError(
                f"rules/models.yaml içinde '{name}' amacı tanımlı değil"
            ) from None

    def price(self, model: str) -> ModelPrice:
        try:
            return self.prices[model]
        except KeyError:
            raise GatewayConfigError(f"rules/models.yaml içinde '{model}' fiyatı yok") from None

    def cost(self, model: str, usage: Usage) -> float:
        return self.price(model).cost(usage)

    def max_price(self) -> ModelPrice:
        """Tablodaki her kalemin en yükseği: fiyatsız bir yedek model için üst sınır tahmini."""
        if not self.prices:
            raise GatewayConfigError("rules/models.yaml içinde fiyat yok")
        values = list(self.prices.values())
        return ModelPrice(
            input=max(p.input for p in values),
            output=max(p.output for p in values),
            cache_read=max(p.cache_read for p in values),
            cache_write=max(p.cache_write for p in values),
        )


def load_model_table(rules_dir: Path) -> ModelTable:
    path = rules_dir / "models.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise GatewayConfigError(f"{path} bulunamadı") from None
    if not isinstance(data, dict):
        raise GatewayConfigError(f"{path} geçersiz")
    prices = {
        model: ModelPrice(**{k: float(v) for k, v in spec.items()})
        for model, spec in (data.get("pricing_usd_per_mtok") or {}).items()
    }
    defaults = data.get("defaults") or {}
    purposes: dict[str, PurposeConfig] = {}
    for name, spec in (data.get("purposes") or {}).items():
        merged_params = {**(defaults.get("params") or {}), **(spec.get("params") or {})}
        cfg = PurposeConfig(
            name=name,
            model=spec["model"],
            max_tokens=int(spec.get("max_tokens", defaults.get("max_tokens", 4096))),
            params=merged_params,
            max_input_tokens=spec.get("max_input_tokens"),
            timeout_s=_timeout(name, spec.get("timeout_s", defaults.get("timeout_s"))),
        )
        if cfg.model not in prices:
            raise GatewayConfigError(f"'{name}' amacının modeli '{cfg.model}' için fiyat yok")
        purposes[name] = cfg
    return ModelTable(version=int(data.get("version", 1)), prices=prices, purposes=purposes)


def _timeout(purpose: str, value: Any) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        raise GatewayConfigError(f"'{purpose}' timeout_s sayı olmalı: {value!r}") from None
    if seconds <= 0:
        raise GatewayConfigError(f"'{purpose}' timeout_s pozitif olmalı: {value!r}")
    return seconds
