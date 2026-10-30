"""Azure OpenAI adaptörü — iskelet (constitution XII: model bağımsızlığı).

Aynı `Provider` arayüzünü uygular; değerlendirme seti Azure erişimi geldiğinde iki sağlayıcıda
yan yana koşar (TEKNIK-TASARIM §8.8). Bu demoda Azure kimliği yoktur ve `openai` paketi çekirdek
bağımlılıklarında değildir; ayarlanmamışsa açık bir `ProviderNotConfigured` hatası verilir.

Eşleme planı (uygulanacak):
- Yapılandırılmış çıktı: `response_format={"type": "json_schema", "json_schema": {"strict": true}}`
- Araçlar: `tools=[{"type": "function", "function": {name, description, parameters}}]`
- Araç sonucu: `{"role": "tool", "tool_call_id": …, "content": …}` (her çağrı ayrı mesaj)
- `temperature` = models.yaml `params.temperature`
- 429/5xx → `ProviderTransientError`
"""

from __future__ import annotations

import os
from typing import Any

from tp_core.gateway.errors import ProviderNotConfigured
from tp_core.gateway.providers.base import ProviderRequest, ProviderResponse, ToolCall

_ENV = ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT")


class AzureOpenAIProvider:
    name = "azure_openai"

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        deployment: str | None = None,
    ) -> None:
        self.endpoint = endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT")
        self.api_key = api_key or os.environ.get("AZURE_OPENAI_API_KEY")
        self.deployment = deployment or os.environ.get("AZURE_OPENAI_DEPLOYMENT")
        values = (self.endpoint, self.api_key, self.deployment)
        missing = [name for name, value in zip(_ENV, values, strict=True) if not value]
        if missing:
            raise ProviderNotConfigured(
                "Azure OpenAI sağlayıcısı ayarlanmamış; eksik: " + ", ".join(missing)
            )

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        raise ProviderNotConfigured(
            "Azure OpenAI adaptörü henüz uygulanmadı (iskelet); `openai` bağımlılığı ve "
            "eşleme planı modül belgesinde"
        )

    def assistant_message(self, response: ProviderResponse) -> dict[str, Any]:
        return {"role": "assistant", "content": response.text}

    def tool_result_message(self, results: list[tuple[ToolCall, str, bool]]) -> dict[str, Any]:
        raise ProviderNotConfigured("Azure OpenAI adaptörü henüz uygulanmadı (iskelet)")
