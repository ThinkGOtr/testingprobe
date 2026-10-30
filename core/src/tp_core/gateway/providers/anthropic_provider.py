"""Anthropic (Claude) adaptörü.

Sağlayıcıya özgü kararlar yalnızca burada:
- Yapılandırılmış çıktı: yerel structured output (`output_config.format` = `json_schema`). Şema
  SDK'nın `transform_schema` yardımcısıyla API'nin desteklediği alt kümeye indirgenir; tam şema
  (maxLength, pattern …) geçitte jsonschema ile ayrıca doğrulanır.
- Prompt caching: sistem prompt'u tek metin bloğu, `cache_control: ephemeral` (araç tanımları
  sistemden önce işlendiği için önbelleğe onlar da girer).
- Örnekleme parametreleri: kurulu SDK/API sürümünde `temperature` yoktur (API 2026-10-21 örnekleme
  parametrelerini kaldırdı); `params.temperature` gönderilmez, determinizm replay ile sağlanır.
  Çaba (`effort`) ve `thinking` models.yaml'dan gelir.
- Zorunlu araç seçimi (`tool_choice: tool/any`) Sonnet 5.5'te 400 döndüğü için kullanılmaz; ajan
  son çıktı aracını `auto` + talimatla çağırır.
- SDK'nın kendi yeniden denemesi kapalıdır (`max_retries=0`); politika geçit çekirdeğindedir.
"""

from __future__ import annotations

import json
from typing import Any

from tp_core.gateway.errors import (
    ProviderNotConfigured,
    ProviderPermanentError,
    ProviderRefusal,
    ProviderTransientError,
)
from tp_core.gateway.providers.base import (
    ProviderRequest,
    ProviderResponse,
    StopReason,
    ToolCall,
    Usage,
)

_META_KEYS = {"$schema", "$id"}


def strip_meta(schema: Any) -> Any:
    """`$schema`, `$id` ve `x-*` uzantı anahtarlarını API'ye göndermeden önce temizler."""
    if isinstance(schema, dict):
        return {
            k: strip_meta(v)
            for k, v in schema.items()
            if k not in _META_KEYS and not k.startswith("x-")
        }
    if isinstance(schema, list):
        return [strip_meta(v) for v in schema]
    return schema


_STOP: dict[str, StopReason] = {
    "end_turn": "end_turn",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
}


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: Any | None = None,
        timeout_s: float = 120.0,
    ) -> None:
        if client is not None:
            self._client = client
            return
        if not api_key:
            raise ProviderNotConfigured(
                "ANTHROPIC_API_KEY tanımlı değil; canlı mod kullanılamaz (TP_MODEL_MODE=replay)"
            )
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=timeout_s)

    # ------------------------------------------------------------------ istek

    def build_kwargs(self, request: ProviderRequest) -> dict[str, Any]:
        from anthropic import transform_schema

        kwargs: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "system": [
                {"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}
            ],
            "messages": request.messages,
        }
        output_config: dict[str, Any] = {}
        effort = request.params.get("effort")
        if effort:
            output_config["effort"] = effort
        if request.output_schema is not None:
            output_config["format"] = {
                "type": "json_schema",
                "schema": transform_schema(strip_meta(request.output_schema)),
            }
        if output_config:
            kwargs["output_config"] = output_config
        thinking = request.params.get("thinking")
        if thinking:
            kwargs["thinking"] = thinking
        if request.tools:
            kwargs["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": strip_meta(t.input_schema),
                }
                for t in request.tools
            ]
            kwargs["tool_choice"] = {"type": "auto"}
        return kwargs

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        import anthropic

        try:
            message = self._client.messages.create(**self.build_kwargs(request))
        except anthropic.RateLimitError as exc:
            raise ProviderTransientError(f"429: {exc}", status=429) from exc
        except anthropic.InternalServerError as exc:  # ≥500, 529 (overloaded) dahil
            raise ProviderTransientError(
                f"{exc.status_code}: {exc}", status=exc.status_code
            ) from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise ProviderTransientError(
                    f"{exc.status_code}: {exc}", status=exc.status_code
                ) from exc
            raise ProviderPermanentError(
                f"{exc.status_code}: {exc}", status=exc.status_code
            ) from exc
        except anthropic.APIConnectionError as exc:  # zaman aşımı dahil
            raise ProviderTransientError(f"bağlantı: {exc}") from exc
        return self.parse_message(message)

    # ------------------------------------------------------------------ yanıt

    @staticmethod
    def parse_message(message: Any) -> ProviderResponse:
        texts: list[str] = []
        calls: list[ToolCall] = []
        raw: list[dict[str, Any]] = []
        for block in message.content:
            raw.append(block.model_dump(exclude_none=True))
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "tool_use":
                args = block.input if isinstance(block.input, dict) else json.loads(block.input)
                calls.append(ToolCall(id=block.id, name=block.name, args=args))
        stop = _STOP.get(message.stop_reason or "", "other")
        if stop == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise ProviderRefusal(f"model isteği reddetti (kategori: {category})")
        usage = message.usage
        return ProviderResponse(
            text="".join(texts),
            tool_calls=calls,
            stop_reason=stop,
            model=message.model,
            raw_assistant_content=raw,
            usage=Usage(
                input_tokens=usage.input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", None) or 0,
                cache_write_tokens=getattr(usage, "cache_creation_input_tokens", None) or 0,
            ),
        )

    def assistant_message(self, response: ProviderResponse) -> dict[str, Any]:
        # Thinking blokları dahil içerik değiştirilmeden geri gönderilir.
        return {"role": "assistant", "content": response.raw_assistant_content}

    def tool_result_message(self, results: list[tuple[ToolCall, str, bool]]) -> dict[str, Any]:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": text,
                    **({"is_error": True} if is_error else {}),
                }
                for call, text, is_error in results
            ],
        }
