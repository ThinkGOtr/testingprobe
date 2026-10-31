"""Anthropic (Claude) adaptörü.

Sağlayıcıya özgü kararlar yalnızca burada:
- Yapılandırılmış çıktı: yerel structured output (`output_config.format` = `json_schema`). Şema
  SDK'nın `transform_schema` yardımcısıyla API'nin desteklediği alt kümeye indirgenir; tam şema
  (maxLength, pattern …) geçitte jsonschema ile ayrıca doğrulanır.
- Prompt caching: sistem prompt'u tek metin bloğu, `cache_control: ephemeral` (araç tanımları
  sistemden önce işlendiği için önbelleğe onlar da girer). Ajan isteklerinde (araç verilmişse)
  ilk kullanıcı mesajının son içerik bloğu da kırılma noktasıdır (§8.4: case + sembol tablosu
  önbellekte): her tur yeniden gönderilen en büyük kararlı önek odur; snapshot ayıklama yalnızca
  sonraki tool_result mesajlarını değiştirdiği için bu önek turlar boyunca geçerli kalır. Üçüncü,
  kayan kırılma noktası son mesajın son bloğudur (genelde tool_result): snapshot değişmeyen
  turlarda geçmiş yalnızca sona eklenir ve bir önceki turun tamamı önbellekten okunur. Tek
  çağrılık (`call`) isteklerde mesaj önbelleklenmez (okuma olmadan yazma 1.25× fiyatlanır).
- Örnekleme parametreleri: kurulu SDK/API sürümünde `temperature` yoktur (API 2026-10-21 örnekleme
  parametrelerini kaldırdı); `params.temperature` gönderilmez, determinizm replay ile sağlanır.
  Çaba (`effort`) ve `thinking` models.yaml'dan gelir.
- Zorunlu araç seçimi (`tool_choice: tool/any`) Sonnet 5.5'te 400 döndüğü için kullanılmaz; ajan
  son çıktı aracını `auto` + talimatla çağırır.
- SDK'nın kendi yeniden denemesi kapalıdır (`max_retries=0`); politika geçit çekirdeğindedir.
  İstemci zaman aşımı `ProviderTransientError(timeout=True)` olur; geçit onu en çok bir kez
  yeniden dener (uzun üretim her denemede yeniden faturalanır).
- Zaman aşımı ve akış: `max_tokens >= STREAM_MIN_MAX_TOKENS` (case üretimi 16K, ajanlar 8K)
  istekleri akışla gönderilir (`messages.stream(...).get_final_message()`); bekleme süresi tüm
  yanıt yerine parçalar arasıdır, uzun üretim HTTP zaman aşımına takılmaz. İstek başına zaman
  aşımı models.yaml `timeout_s`'den gelir (`ProviderRequest.timeout_s`).
- Ret yedeği (constitution: insana düşmeden önce dürüst yedek): Claude API'de sunucu tarafı
  `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`) yalnızca bunu kabul eden
  modellerde gönderilir (Sonnet 5.5 yalnızca `"default"` biçimini kabul eder; Haiku 5.5'te
  sunucu tarafı yedek yoktur). Ret kategorisine göre Anthropic'in önerdiği modele yönlendirir;
  `between_tools` isteği yedek modelde düşünmesiz koşar. Yanıtı üreten model `response.model`'dir
  ve `ai_call.model`'e yazılır (`ProviderResponse.fallback_from` asıl model). Zincirin tamamı
  reddederse `stop_reason == "refusal"` → `ProviderRefusal` (insana düşer).
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
# Bu eşik ve üstünde akışlı istek (HTTP zaman aşımı tüm yanıt yerine parçalar arası beklemeye
# uygulanır). models.yaml: case_generation 16000, consistency_check / verify_and_map 8192.
STREAM_MIN_MAX_TOKENS = 8192
DEFAULT_TIMEOUT_S = 120.0
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# `fallbacks: "default"` kabul eden modeller (Claude API). Haiku 5.5: sunucu tarafı yedek yok.
SERVER_FALLBACK_MODELS = frozenset(
    {"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"}
)
# Yedek geçişinden önceki bu bloklar geri gönderilmez (yalnızca metin süreklilik bağlamıdır).
_PRE_FALLBACK_DROP = {"thinking", "redacted_thinking", "tool_use", "server_tool_use"}


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


_TRANSIENT_STREAM_ERRORS = {"overloaded_error", "api_error", "rate_limit_error", "timeout_error"}


def _stream_error_type(exc: Any) -> str | None:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error") if isinstance(body.get("error"), dict) else body
        kind = err.get("type")
        return kind if isinstance(kind, str) else None
    return None


def with_prefix_cache(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """İlk kullanıcı mesajının son içerik bloğuna `cache_control: ephemeral` ekler (kopya).

    Diğer mesajlara dokunulmaz; özgün liste/sözlükler değiştirilmez.
    """
    if not messages or messages[0].get("role") != "user":
        return messages
    first = dict(messages[0])
    content = first.get("content")
    if isinstance(content, str):
        blocks: list[Any] = [{"type": "text", "text": content}]
    elif isinstance(content, list) and content:
        blocks = list(content)
    else:
        return messages
    last = blocks[-1]
    if not isinstance(last, dict):
        return messages
    blocks[-1] = {**last, "cache_control": {"type": "ephemeral"}}
    first["content"] = blocks
    return [first, *messages[1:]]


def with_rolling_cache(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ajan isteği: ilk kullanıcı mesajı (kararlı önek) + SON mesajın son içerik bloğu kırılma
    noktasıdır (kopya; özgün liste/sözlükler değiştirilmez).

    Son snapshot değişmediği sürece sohbet yalnızca sona eklenir; kayan kırılma noktası bir
    sonraki turda önceki tool_use/tool_result geçmişinin önbellekten (~0.1×) okunmasını sağlar.
    Kırılma noktası sayısı: sistem + ilk mesaj + son mesaj = 3 (API sınırı 4). Tek mesajlı ilk
    turda yalnızca önek kırılma noktası konur.
    """
    out = with_prefix_cache(messages)
    if len(out) < 2:
        return out
    last = _with_block_cache(out[-1])
    return out if last is None else [*out[:-1], last]


def _with_block_cache(message: dict[str, Any]) -> dict[str, Any] | None:
    content = message.get("content")
    if isinstance(content, str):
        if not content:
            return None
        blocks: list[Any] = [{"type": "text", "text": content}]
    elif isinstance(content, list) and content:
        blocks = list(content)
    else:
        return None
    tail = blocks[-1]
    if not isinstance(tail, dict) or tail.get("type") in {"thinking", "redacted_thinking"}:
        return None  # thinking bloğuna cache_control konamaz
    blocks[-1] = {**tail, "cache_control": {"type": "ephemeral"}}
    return {**message, "content": blocks}


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: Any | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        server_fallback: bool = True,
    ) -> None:
        # Sunucu tarafı ret yedeği yalnızca birinci taraf Claude API'de (Bedrock/Vertex/Foundry'de
        # parametre yoktur; orada istemci tarafı ara katman gerekir).
        self.server_fallback = server_fallback
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
            # Ajan döngüsü: ilk mesaj (case + sembol tablosu) her tur aynıdır → önbellek önekine;
            # son mesaj kayan kırılma noktasıdır (büyüyen geçmiş sonraki turda önbellekten okunur).
            "messages": with_rolling_cache(request.messages) if request.tools else request.messages,
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
        if request.timeout_s:
            kwargs["timeout"] = request.timeout_s
        if self.uses_server_fallback(request):
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
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

    def uses_server_fallback(self, request: ProviderRequest) -> bool:
        return self.server_fallback and request.model in SERVER_FALLBACK_MODELS

    @staticmethod
    def streams(request: ProviderRequest) -> bool:
        return request.max_tokens >= STREAM_MIN_MAX_TOKENS

    def _send(self, request: ProviderRequest) -> Any:
        kwargs = self.build_kwargs(request)
        api = self._client.beta.messages if "betas" in kwargs else self._client.messages
        if self.streams(request):
            with api.stream(**kwargs) as stream:
                return stream.get_final_message()
        return api.create(**kwargs)

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        import anthropic

        try:
            message = self._send(request)
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
        except anthropic.APITimeoutError as exc:
            raise ProviderTransientError(
                f"zaman aşımı ({request.timeout_s or 'varsayılan'} sn): {exc}", timeout=True
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderTransientError(f"bağlantı: {exc}") from exc
        except anthropic.APIError as exc:  # akış ortasında gelen hata olayı
            if _stream_error_type(exc) in _TRANSIENT_STREAM_ERRORS:
                raise ProviderTransientError(f"akış: {exc}") from exc
            raise ProviderPermanentError(f"akış: {exc}") from exc
        response = self.parse_message(message)
        if (
            response.model
            and response.model != request.model
            and self.uses_server_fallback(request)
        ):
            response.fallback_from = request.model
        return response

    # ------------------------------------------------------------------ yanıt

    @staticmethod
    def parse_message(message: Any) -> ProviderResponse:
        texts: list[str] = []
        calls: list[ToolCall] = []
        raw: list[dict[str, Any]] = []
        blocks = list(message.content)
        last_fallback = max(
            (i for i, b in enumerate(blocks) if getattr(b, "type", None) == "fallback"),
            default=-1,
        )
        for i, block in enumerate(blocks):
            if block.type == "fallback":
                continue  # denetim işareti; geri gönderilmesi gerekmez
            if i < last_fallback and block.type in _PRE_FALLBACK_DROP:
                continue  # reddeden modelin yarım kalan adımı: geri gönderilmez, çalıştırılmaz
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
