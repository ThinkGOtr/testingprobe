"""Sağlayıcıdan bağımsız istek/yanıt tipleri (constitution XII).

Geçit çekirdeği yalnızca bu tiplerle konuşur; Anthropic'e ya da Azure OpenAI'ya özgü her şey
(prompt caching, structured output biçimi, hata sınıfları) adaptörün içindedir.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from tp_core.ports import ToolSpec


class ToolCall(BaseModel):
    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ProviderRequest(BaseModel):
    model: str
    system: str
    messages: list[dict[str, Any]]  # {"role": "user"|"assistant", "content": str | [blok]}
    max_tokens: int = 4096
    # Yapılandırılmış çıktı (tek çağrı). Ajan turlarında None; ajan son çıktıyı araçla verir.
    output_schema: dict[str, Any] | None = None
    tools: list[ToolSpec] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)  # models.yaml'daki amaç parametreleri
    # İstek başına istemci zaman aşımı (sn; models.yaml `timeout_s`). None: adaptör varsayılanı.
    timeout_s: float | None = None
    # Sağlayıcı tarafı ret yedeği (models.yaml `fallbacks`). None: adaptör varsayılanı;
    # "none": yedek istenmez (adaptör parametreyi göndermez).
    fallbacks: str | None = None


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


StopReason = Literal["end_turn", "tool_use", "max_tokens", "refusal", "other"]


class ProviderResponse(BaseModel):
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    stop_reason: StopReason = "end_turn"
    usage: Usage = Field(default_factory=Usage)
    model: str = ""
    # Sağlayıcının asistan mesajı (ör. Anthropic içerik blokları, thinking blokları dahil);
    # ajan döngüsünde değiştirilmeden geri gönderilir.
    raw_assistant_content: list[dict[str, Any]] = Field(default_factory=list)
    # Sağlayıcı tarafı ret yedeği devreye girdiyse isteğin asıl modeli (yanıtı `model` üretti).
    fallback_from: str | None = None


@runtime_checkable
class Provider(Protocol):
    name: str

    def complete(self, request: ProviderRequest) -> ProviderResponse: ...

    def tool_result_message(self, results: list[tuple[ToolCall, str, bool]]) -> dict[str, Any]:
        """Araç sonuçlarını sağlayıcının beklediği tek kullanıcı mesajına çevirir.

        `results`: (çağrı, sonuç metni, hata mı) üçlüleri — paralel çağrıların tümü tek mesajda.
        """
        ...

    def assistant_message(self, response: ProviderResponse) -> dict[str, Any]:
        """Asistan yanıtını sohbet geçmişine eklenecek mesaja çevirir."""
        ...
