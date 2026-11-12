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


def _message(content, stop="end_turn", model="claude-sonnet-5-5", **usage) -> Message:
    return Message.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": content,
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5, **usage},
        }
    )


class FakeStream:
    def __init__(self, messages: "FakeMessages") -> None:
        self.messages = messages

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def get_final_message(self):
        if isinstance(self.messages.outcome, Exception):
            raise self.messages.outcome
        return self.messages.outcome


class FakeMessages:
    def __init__(self, outcome, calls: list[str], path: str) -> None:
        self.outcome = outcome
        self.calls = calls
        self.path = path
        self.kwargs: dict = {}

    def create(self, **kwargs):
        self.kwargs = kwargs
        self.calls.append(f"{self.path}.create")
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    def stream(self, **kwargs):
        self.kwargs = kwargs
        self.calls.append(f"{self.path}.stream")
        return FakeStream(self)


class FakeBeta:
    def __init__(self, messages: FakeMessages) -> None:
        self.messages = messages


class FakeClient:
    """`messages` ve `beta.messages`; `calls` hangi yolun kullanıldığını tutar."""

    def __init__(self, outcome) -> None:
        self.calls: list[str] = []
        self.messages = FakeMessages(outcome, self.calls, "messages")
        beta = FakeMessages(outcome, self.calls, "beta.messages")
        beta.kwargs = self.messages.kwargs
        self.beta = FakeBeta(beta)

    @property
    def last_kwargs(self) -> dict:
        path = self.calls[-1].rsplit(".", 1)[0]
        return (self.beta.messages if path == "beta.messages" else self.messages).kwargs


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
    kw = client.last_kwargs
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
    kw = client.last_kwargs
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


# ------------------------------------------------------------ zaman aşımı, akış, ret yedeği


def _req(model="claude-sonnet-5-5", max_tokens=4096, **kw) -> ProviderRequest:
    return ProviderRequest(
        model=model,
        system="s",
        messages=[{"role": "user", "content": "x"}],
        max_tokens=max_tokens,
        **kw,
    )


def test_per_purpose_timeout_reaches_request() -> None:
    from tp_core.gateway.config import load_model_table

    table = load_model_table(REAL_RULES)
    assert table.purpose("case_generation").timeout_s == 600
    assert table.purpose("consistency_check").timeout_s == 300
    assert table.purpose("triage").timeout_s == 120  # varsayılan
    client = FakeClient(_message([{"type": "text", "text": "{}"}]))
    provider = AnthropicProvider(client=client)
    cfg = table.purpose("case_generation")
    provider.complete(_req(max_tokens=cfg.max_tokens, timeout_s=cfg.timeout_s))
    assert client.last_kwargs["timeout"] == 600
    # 16K çıktı akışla gelir (HTTP zaman aşımı tüm yanıta değil parçalar arasına uygulanır)
    assert client.calls == ["beta.messages.stream"]


def test_small_requests_are_not_streamed_and_haiku_has_no_fallback() -> None:
    client = FakeClient(_message([{"type": "text", "text": "{}"}], model="claude-haiku-5-5"))
    provider = AnthropicProvider(client=client)
    provider.complete(_req(model="claude-haiku-5-5", max_tokens=2048))
    assert client.calls == ["messages.create"]
    kw = client.last_kwargs
    assert "fallbacks" not in kw and "betas" not in kw and "timeout" not in kw


def test_timeout_maps_to_transient_timeout() -> None:
    import anthropic

    err = anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com"))
    provider = AnthropicProvider(client=FakeClient(err))
    with pytest.raises(ProviderTransientError) as exc:
        provider.complete(_req(max_tokens=16000, timeout_s=600))
    assert exc.value.timeout is True


def test_gateway_retries_timeout_only_once(make_gateway, rules_dir, sleeps) -> None:
    from tp_core.gateway import load_schema
    from tp_core.ports import ModelMessage

    timeout = ProviderTransientError("zaman aşımı", timeout=True)
    gw, provider = make_gateway([timeout, timeout, timeout])
    with pytest.raises(ProviderTransientError):
        gw.call(
            "case_generation",
            "case-generation",
            [ModelMessage(role="user", content="x")],
            load_schema(rules_dir, "case_generation"),
            replay_key={"name": "TPD-1"},
        )
    # case_generation zaman aşımında geçitte yeniden denenmez (models.yaml
    # `max_timeout_retries: 0`; iş kuyruğu yeniden dener — iş süresi bütçesi, 011 D1 #2).
    assert len(sleeps) == 0 and len(provider.requests) == 1
    assert provider.requests[0].timeout_s == 600

    # Ayarı olmayan amaçta geçit varsayılanı: ilk deneme + bir yeniden deneme (429/5xx için 3).
    gw, provider = make_gateway([timeout, timeout, timeout])
    sleeps.clear()
    with pytest.raises(ProviderTransientError):
        gw.call(
            "requirement_review",
            "requirement-review",
            [ModelMessage(role="user", content="x")],
            load_schema(rules_dir, "requirement_review"),
            replay_key={"name": "TPD-1"},
        )
    assert len(sleeps) == 1 and len(provider.requests) == 2


def test_server_side_fallback_default_is_sent_for_sonnet() -> None:
    client = FakeClient(_message([{"type": "text", "text": "{}"}]))
    provider = AnthropicProvider(client=client)
    resp = provider.complete(_req(params={"thinking": {"type": "between_tools"}}))
    kw = client.last_kwargs
    assert kw["fallbacks"] == "default"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert client.calls == ["beta.messages.create"]
    assert resp.fallback_from is None  # yedek devreye girmedi


def test_server_fallback_can_be_disabled_for_other_platforms() -> None:
    client = FakeClient(_message([{"type": "text", "text": "{}"}]))
    AnthropicProvider(client=client, server_fallback=False).complete(_req())
    assert "fallbacks" not in client.last_kwargs and client.calls == ["messages.create"]


def test_fallback_response_records_serving_model_and_drops_pre_fallback_steps() -> None:
    from anthropic.types.beta import BetaMessage

    message = BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5",
            "content": [
                {"type": "text", "text": "Bakı"},
                {"type": "tool_use", "id": "toolu_0", "name": "search_code", "input": {}},
                {
                    "type": "fallback",
                    "from": {"model": "claude-sonnet-5-5"},
                    "to": {"model": "claude-sonnet-5"},
                    "trigger": {"type": "refusal", "category": "cyber"},
                },
                {"type": "tool_use", "id": "toolu_1", "name": "db_schema", "input": {}},
            ],
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
    )
    provider = AnthropicProvider(client=FakeClient(message))
    resp = provider.complete(_req())
    assert resp.model == "claude-sonnet-5" and resp.fallback_from == "claude-sonnet-5-5"
    assert [c.id for c in resp.tool_calls] == ["toolu_1"]  # reddedenin adımı çalıştırılmaz
    assert [b["type"] for b in resp.raw_assistant_content] == ["text", "tool_use"]


def test_gateway_records_fallback_model(make_gateway, rules_dir, recorder) -> None:
    from tp_core.gateway import load_schema
    from tp_core.gateway.providers.base import ProviderResponse, Usage
    from tp_core.ports import ModelMessage

    resp = ProviderResponse(
        text='{"questions": [], "verdict": "ready", "summary": "Hazır."}',
        model="claude-opus-5-5",
        fallback_from="claude-sonnet-5-5",
        usage=Usage(input_tokens=1000, output_tokens=100),
    )
    gw, _ = make_gateway([resp])
    gw.call(
        "requirement_review",
        "requirement-review",
        [ModelMessage(role="user", content="x")],
        load_schema(rules_dir, "requirement_review"),
        replay_key={"name": "TPD-4"},
    )
    row = recorder.ai_calls[-1]
    assert row["model"] == "claude-opus-5-5"
    assert row["ek"]["yedek_model"] == {
        "istenen": "claude-sonnet-5-5",
        "yanitlayan": "claude-opus-5-5",
    }


def test_mid_stream_error_event_classified() -> None:
    import anthropic

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    overloaded = anthropic.APIError(
        "overloaded", req, body={"type": "error", "error": {"type": "overloaded_error"}}
    )
    invalid = anthropic.APIError(
        "invalid", req, body={"type": "error", "error": {"type": "invalid_request_error"}}
    )
    with pytest.raises(ProviderTransientError):
        AnthropicProvider(client=FakeClient(overloaded)).complete(_req(max_tokens=16000))
    with pytest.raises(ProviderPermanentError) as exc:
        AnthropicProvider(client=FakeClient(invalid)).complete(_req(max_tokens=16000))
    assert not isinstance(exc.value, ProviderTransientError)
