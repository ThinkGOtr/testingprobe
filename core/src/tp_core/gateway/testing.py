"""Test yardımcıları: senaryolu sahte sağlayıcı ve bellek içi kayıtçı.

Diğer şeritler de kendi birim testlerinde geçidi DB'siz ve anahtarsız kullanabilsin diye paket
içindedir. Üretim kodu bunları kullanmaz.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID, uuid4

from tp_core.gateway.providers.base import (
    ProviderRequest,
    ProviderResponse,
    ToolCall,
    Usage,
)

Scripted = ProviderResponse | Exception | Callable[[ProviderRequest], ProviderResponse]


def text_response(
    obj: Any, *, input_tokens: int = 100, output_tokens: int = 50
) -> ProviderResponse:
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return ProviderResponse(
        text=text,
        stop_reason="end_turn",
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
        raw_assistant_content=[{"type": "text", "text": text}],
    )


def tool_response(
    *calls: tuple[str, dict[str, Any]], input_tokens: int = 100, output_tokens: int = 50
) -> ProviderResponse:
    tool_calls = [
        ToolCall(id=f"toolu_{uuid4().hex[:12]}", name=name, args=args) for name, args in calls
    ]
    return ProviderResponse(
        tool_calls=tool_calls,
        stop_reason="tool_use",
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
        raw_assistant_content=[
            {"type": "tool_use", "id": c.id, "name": c.name, "input": c.args} for c in tool_calls
        ],
    )


class FakeProvider:
    """Senaryodaki yanıtları sırayla döndürür; istekleri `requests`'te saklar."""

    name = "fake"

    def __init__(self, script: list[Scripted]) -> None:
        self.script = list(script)
        self.requests: list[ProviderRequest] = []

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request.model_copy(deep=True))
        if not self.script:
            raise AssertionError("FakeProvider senaryosu bitti")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item(request)
        return item

    def assistant_message(self, response: ProviderResponse) -> dict[str, Any]:
        return {"role": "assistant", "content": response.raw_assistant_content}

    def tool_result_message(self, results: list[tuple[ToolCall, str, bool]]) -> dict[str, Any]:
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": c.id, "content": t, "is_error": e}
                for c, t, e in results
            ],
        }


class InMemoryCallRecorder:
    def __init__(self) -> None:
        self.ai_calls: list[dict[str, Any]] = []
        self.tool_calls: list[dict[str, Any]] = []

    def record_ai_call(self, row: Mapping[str, Any]) -> UUID:
        self.ai_calls.append(dict(row))
        return row["id"]

    def record_tool_call(self, row: Mapping[str, Any]) -> UUID:
        self.tool_calls.append(dict(row))
        return row["id"]

    def find_ai_calls(self, root_id: UUID) -> list[Mapping[str, Any]]:
        """`core.CallLookup`: Postgres kaydı gibi aynı `id`'yi ikinci kez yazmaz sayılır."""
        seen: set[UUID] = set()
        out = []
        for row in self.ai_calls:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            if row["id"] == root_id or row.get("parent_call_id") == root_id:
                out.append(row)
        return out
