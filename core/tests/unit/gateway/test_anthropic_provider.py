import httpx
import pytest
from anthropic import BadRequestError, InternalServerError, RateLimitError
from anthropic.types import Message

from tp_core.gateway import (
    ProviderNotConfigured,
    ProviderPermanentError,
    ProviderRefusal,
    ProviderTransientError,
    load_schema,
)
from tp_core.gateway.providers.anthropic_provider import AnthropicProvider
from tp_core.gateway.providers.base import ProviderRequest, ToolCall
from tp_core.ports import ToolSpec

from .conftest import REAL_RULES


def _message(content, stop="end_turn", **usage) -> Message:
    return Message.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5-5",
            "content": content,
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5, **usage},
        }
    )


class FakeMessages:
    def __init__(self, outcome) -> None:
        self.outcome = outcome
        self.kwargs: dict = {}

    def create(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeClient:
    def __init__(self, outcome) -> None:
        self.messages = FakeMessages(outcome)


def _status_error(cls, status: int):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("hata", response=httpx.Response(status, request=req), body=None)


def test_requires_key() -> None:
    with pytest.raises(ProviderNotConfigured):
        AnthropicProvider(api_key=None)


def test_structured_output_request_shape() -> None:
    client = FakeClient(_message([{"type": "text", "text": '{"verdict": "ready"}'}]))
    provider = AnthropicProvider(client=client)
    schema = load_schema(REAL_RULES, "requirement_review")
    resp = provider.complete(
        ProviderRequest(
            model="claude-sonnet-5-5",
            system="SYS",
            messages=[{"role": "user", "content": "x"}],
            max_tokens=4096,
            output_schema=schema,
            params={"effort": "medium", "temperature": 0},
        )
    )
    kw = client.messages.kwargs
    assert kw["system"] == [{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}]
    fmt = kw["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert "$schema" not in fmt["schema"] and "x-version" not in str(fmt["schema"])
    assert fmt["schema"]["additionalProperties"] is False
    assert kw["output_config"]["effort"] == "medium"
    assert "temperature" not in kw  # API örnekleme parametresini kabul etmez
    assert "tools" not in kw and "thinking" not in kw
    assert resp.text == '{"verdict": "ready"}'
    assert resp.usage.input_tokens == 10


def test_agent_request_shape_and_tool_parsing() -> None:
    client = FakeClient(
        _message(
            [
                {"type": "text", "text": "Bakıyorum."},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "browser_click",
                    "input": {"ref": "e3"},
                },
            ],
            stop="tool_use",
            cache_read_input_tokens=7,
        )
    )
    provider = AnthropicProvider(client=client)
    resp = provider.complete(
        ProviderRequest(
            model="claude-sonnet-5-5",
            system="S",
            messages=[{"role": "user", "content": "x"}],
            tools=[
                ToolSpec(
                    name="browser_click",
                    description="d",
                    input_schema={"$schema": "x", "type": "object"},
                )
            ],
            params={"thinking": {"type": "between_tools"}},
        )
    )
    kw = client.messages.kwargs
    assert kw["tool_choice"] == {"type": "auto"}  # zorunlu tool_choice kullanılmaz
    assert kw["tools"][0]["input_schema"] == {"type": "object"}
    assert kw["thinking"] == {"type": "between_tools"}
    assert resp.stop_reason == "tool_use"
    assert resp.tool_calls == [ToolCall(id="toolu_1", name="browser_click", args={"ref": "e3"})]
    assert resp.usage.cache_read_tokens == 7
    # Asistan içeriği değiştirilmeden geri gönderilir
    assert provider.assistant_message(resp)["content"][1]["id"] == "toolu_1"
    msg = provider.tool_result_message([(resp.tool_calls[0], "ok", False)])
    assert msg == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"}],
    }


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_status_error(RateLimitError, 429), ProviderTransientError),
        (_status_error(InternalServerError, 529), ProviderTransientError),
        (_status_error(InternalServerError, 503), ProviderTransientError),
        (_status_error(BadRequestError, 400), ProviderPermanentError),
    ],
)
def test_error_mapping(error, expected) -> None:
    provider = AnthropicProvider(client=FakeClient(error))
    req = ProviderRequest(model="m", system="s", messages=[{"role": "user", "content": "x"}])
    with pytest.raises(expected) as exc:
        provider.complete(req)
    assert exc.value.status == error.status_code
    if expected is ProviderPermanentError:
        assert not isinstance(exc.value, ProviderTransientError)


def test_refusal_raises() -> None:
    provider = AnthropicProvider(client=FakeClient(_message([], stop="refusal")))
    req = ProviderRequest(model="m", system="s", messages=[{"role": "user", "content": "x"}])
    with pytest.raises(ProviderRefusal):
        provider.complete(req)
