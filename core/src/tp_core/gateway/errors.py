"""Model geçidi hataları.

Hepsi `GatewayError`'dan türer; iş akışı katmanı bu tipe bakarak "insana düş" kararı verir.
"""

from __future__ import annotations

from typing import Any


class GatewayError(Exception):
    """Model geçidinin tüm hatalarının tabanı."""


class GatewayConfigError(GatewayError):
    """rules/ dosyası, model tablosu veya ortam değişkeni eksik/hatalı."""


class ProviderNotConfigured(GatewayError):
    """Seçilen sağlayıcının kimlik bilgisi/uç noktası yok (ör. Azure OpenAI ayarlanmamış)."""


class ProviderTransientError(GatewayError):
    """Yeniden denenebilir sağlayıcı hatası (429, 529, 5xx, bağlantı).

    `timeout=True`: istemci zaman aşımı. Uzun üretimde her deneme yeniden faturalanabilir ve
    dakikalar sürer; geçit bunu en çok `RetryPolicy.max_timeout_retries` kez yeniden dener."""

    def __init__(self, message: str, *, status: int | None = None, timeout: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.timeout = timeout


class ProviderPermanentError(GatewayError):
    """Yeniden denenmeyen sağlayıcı hatası (400, 401, 403, 404, ret)."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ProviderRefusal(ProviderPermanentError):
    """Model isteği reddetti (`stop_reason == "refusal"`); insana düşer."""


class SchemaValidationFailed(GatewayError):
    """Çıktı şemaya uymadı ve yeniden isteme hakları (≤2) tükendi (constitution III)."""

    def __init__(self, message: str, *, errors: list[str], last_output: Any) -> None:
        super().__init__(message)
        self.errors = errors
        self.last_output = last_output


class BudgetExceeded(GatewayError):
    """İş akışı veya günlük maliyet tavanı aşıldı; iş akışı duraklar, insana sorulur."""

    def __init__(self, scope: str, spent_usd: float, cap_usd: float) -> None:
        super().__init__(
            f"Maliyet tavanı aşıldı ({scope}): harcanan {spent_usd:.4f}, tavan {cap_usd:.2f}"
        )
        self.scope = scope
        self.spent_usd = spent_usd
        self.cap_usd = cap_usd


class ReplayNotFound(GatewayError):
    """Replay modunda ne birebir kayıt ne de adlandırılmış golden kayıt bulundu."""

    def __init__(self, purpose: str, key: str, golden_name: str | None) -> None:
        where = f"golden '{golden_name}'" if golden_name else "golden adı verilmedi"
        super().__init__(f"REPLAY kaydı yok: purpose={purpose} key={key[:12]}… ({where})")
        self.purpose = purpose
        self.key = key
        self.golden_name = golden_name


class ReplayMiss(ReplayNotFound):
    """Prova kipi (`TP_REPLAY_STRICT=1`): birebir kayıt yok, golden'a düşülmedi (REPLAY-MISS)."""

    def __init__(self, purpose: str, key: str, golden_name: str | None) -> None:
        super().__init__(purpose, key, golden_name)
        self.args = (
            f"REPLAY-MISS (prova kipi): purpose={purpose} key={key[:12]}… birebir kayıt yok; "
            f"golden '{golden_name}' kullanılmadı. Kayıt için TP_MODEL_MODE=record.",
        )


class ReplayNoOutput(ReplayNotFound):
    """REPLAY-MISS, amacın iskalama politikası `raise` (ör. case üretimi): başka bir dokümanın
    golden çıktısı döndürülmez, nötr çıktı da yoktur; sıfır taslak, canlı model gerekir."""

    def __init__(
        self,
        purpose: str,
        key: str,
        golden_name: str | None,
        reasons: list[str] | None = None,
    ) -> None:
        super().__init__(purpose, key, golden_name)
        self.reasons = list(reasons or [])
        neden = f" ({'; '.join(self.reasons)})" if self.reasons else ""
        self.args = (
            "REPLAY-MISS: bu girdi için kayıtlı model çıktısı yok; canlı model gerekir "
            f"(amaç {purpose}, golden '{golden_name}'{neden}). Başka bir dokümanın kayıtlı "
            "çıktısı kullanılmadı.",
        )


class AgentTurnLimit(GatewayError):
    """Ajan `max_turns` içinde son çıktı aracını çağırmadı."""
