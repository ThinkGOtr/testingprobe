"""Kriter 7 (TEKNIK-TASARIM §1, §13): canlı akış düşerse REPLAY'den devam — çağrı başına, etiketli.

`auto` kipinde (anahtar varken live) bir çağrı sağlayıcı hatası/zaman aşımıyla düşerse geçit aynı
çağrıyı golden'dan sürdürür: düşen canlı satır denetimde kalır, sonuç `replay` etiketlidir (asla
`live` değil), `ek.canli_hata_yedegi` düşen çağrıya bağlanır. Model reddi, bütçe ve `record` kipi
yedeğe düşmez. Ayrıca fiyatsız ret yedeği modelinin maliyeti eksik sayılmaz.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.unit.gateway.demo_sources import RULES
from tp_core.gateway import (
    ALLOWED_AGENT_TOOLS,
    ProviderPermanentError,
    ProviderRefusal,
    ProviderTransientError,
)
from tp_core.gateway.bundle import load_schema
from tp_core.gateway.config import (
    GatewaySettings,
    ModelTable,
    load_model_table,
    resolve_replay_fallback,
)
from tp_core.gateway.core import _response_cost
from tp_core.gateway.eval_set import case_messages, case_replay_key, load_set
from tp_core.gateway.factory import build_gateway
from tp_core.gateway.providers.base import ProviderResponse, Usage
from tp_core.gateway.testing import InMemoryCallRecorder, text_response, tool_response
from tp_core.ports import ToolSpec


def _review_case() -> tuple[dict[str, Any], dict[str, Any]]:
    data = load_set(RULES, "requirement-review")
    return data, next(c for c in data["cases"] if c["id"] == "tpd-1")


def _call(gw, rules_dir: Path):
    data, case = _review_case()
    return gw.call(
        "requirement_review",
        "requirement-review",
        case_messages(case),
        load_schema(rules_dir, "requirement_review"),
        replay_key=case_replay_key(data, case),
    )


def test_timeout_falls_back_to_labelled_replay(make_gateway, rules_dir, recorder) -> None:
    timeouts = [ProviderTransientError("zaman aşımı", timeout=True)] * 2
    gw, fake = make_gateway(timeouts, replay_fallback=True)
    result = _call(gw, rules_dir)
    assert result.mode == "replay"  # asla "live" değil
    assert result.output["verdict"] == "needs_po" and len(fake.requests) == 2
    failed, replayed = recorder.ai_calls
    assert failed["mod"] == "live" and failed["hata"].startswith("ProviderTransientError")
    assert replayed["mod"] == "replay" and replayed["maliyet"] == 0.0
    assert replayed["parent_call_id"] == failed["id"]
    note = replayed["ek"]["canli_hata_yedegi"]
    assert note["zaman_asimi"] is True and note["canli_cagri"] == str(failed["id"])
    assert "REPLAY ile sürdürüldü" in note["etiket"]


def test_provider_error_400_falls_back(make_gateway, rules_dir, recorder) -> None:
    gw, _ = make_gateway(
        [ProviderPermanentError("workspace header", status=400)], replay_fallback=True
    )
    assert _call(gw, rules_dir).mode == "replay"
    assert recorder.ai_calls[-1]["ek"]["canli_hata_yedegi"]["durum"] == 400


def test_refusal_is_not_masked_by_a_golden(make_gateway, rules_dir) -> None:
    gw, _ = make_gateway([ProviderRefusal("ret", status=200)], replay_fallback=True)
    with pytest.raises(ProviderRefusal):
        _call(gw, rules_dir)


def test_fallback_is_off_unless_enabled(make_gateway, rules_dir, recorder) -> None:
    gw, _ = make_gateway([ProviderPermanentError("x", status=400)])
    with pytest.raises(ProviderPermanentError):
        _call(gw, rules_dir)
    assert [r["mod"] for r in recorder.ai_calls] == ["live"]


def test_record_mode_never_falls_back(make_gateway, rules_dir) -> None:
    gw, _ = make_gateway(
        [ProviderPermanentError("x", status=400)], mode="record", replay_fallback=True
    )
    assert gw.replay_fallback is False
    with pytest.raises(ProviderPermanentError):
        _call(gw, rules_dir)


def test_successful_live_call_is_untouched(make_gateway, rules_dir) -> None:
    gw, _ = make_gateway(
        [text_response({"questions": [], "verdict": "ready", "summary": "tamam"})],
        replay_fallback=True,
    )
    assert _call(gw, rules_dir).mode == "live"


def test_agent_falls_back_to_recorded_trajectory(make_gateway, rules_dir, recorder) -> None:
    data = load_set(RULES, "consistency-check")
    case = data["cases"][0]
    tools = [
        ToolSpec(name=n, description=n, input_schema={"type": "object"})
        for n in sorted(ALLOWED_AGENT_TOOLS["consistency_check"])
    ]
    gw, _ = make_gateway(
        [
            tool_response(("search_code", {"query": "kampanya"})),
            ProviderTransientError("bağlantı", status=529),
            ProviderTransientError("bağlantı", status=529),
            ProviderTransientError("bağlantı", status=529),
            ProviderTransientError("bağlantı", status=529),
        ],
        replay_fallback=True,
    )
    result = gw.run_agent(
        "consistency_check",
        "consistency-check",
        case_messages(case),
        tools,
        lambda name, args: f"{name} sonucu",
        load_schema(rules_dir, "consistency_check"),
        replay_key=case_replay_key(data, case),
    )
    assert result.mode == "replay"
    assert {f["doc_ref"] for f in result.output["findings"]} >= {"AC2", "AC4"}
    last = recorder.ai_calls[-1]
    assert last["mod"] == "replay" and last["ek"]["canli_hata_yedegi"]["tur"] == 2


@pytest.mark.parametrize(
    ("mode", "flag", "expected"),
    [
        ("auto", None, True),
        ("live", None, False),
        ("live", True, True),
        ("auto", False, False),
        ("record", True, False),
        ("replay", True, False),
    ],
)
def test_resolve_replay_fallback(mode: str, flag: bool | None, expected: bool) -> None:
    settings = GatewaySettings(TP_MODEL_MODE=mode, TP_REPLAY_FALLBACK=flag)
    assert resolve_replay_fallback(settings) is expected


def test_factory_enables_fallback_in_auto_live(
    monkeypatch: pytest.MonkeyPatch, rules_dir: Path
) -> None:
    monkeypatch.setenv("TP_RULES_DIR", str(rules_dir))
    monkeypatch.setenv("TP_MODEL_MODE", "auto")
    monkeypatch.delenv("TP_REPLAY_FALLBACK", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-TESTKEYabcdefghijkl")
    gw = build_gateway(InMemoryCallRecorder())
    assert gw.mode == "live" and gw.replay_fallback is True
    monkeypatch.setenv("TP_MODEL_MODE", "live")
    assert build_gateway(InMemoryCallRecorder()).replay_fallback is False


# ------------------------------------------------------------------ ret yedeği maliyeti


def _fallback_response(model: str) -> ProviderResponse:
    return ProviderResponse(
        text="{}",
        usage=Usage(input_tokens=1_000_000, output_tokens=1_000_000),
        model=model,
        fallback_from="claude-sonnet-5-5",
    )


def test_opus_fallback_is_charged_at_opus_price(rules_dir: Path) -> None:
    models = load_model_table(rules_dir)
    cfg = models.purpose("case_generation")
    assert _response_cost(models, cfg, _fallback_response("claude-opus-5-5")) == 24.0


def test_unpriced_fallback_is_charged_at_the_highest_price(rules_dir: Path) -> None:
    models: ModelTable = load_model_table(rules_dir)
    cfg = models.purpose("case_generation")
    cost = _response_cost(models, cfg, _fallback_response("claude-yeni-model"))
    top = models.max_price()
    assert cost == top.input + top.output  # 1M + 1M token
    assert cost > models.cost(cfg.model, _fallback_response("x").usage)  # eksik sayılmadı


def test_unpriced_fallback_is_flagged_in_the_audit_row(make_gateway, rules_dir, recorder) -> None:
    resp = text_response({"questions": [], "verdict": "ready", "summary": "tamam"})
    resp.model, resp.fallback_from = "claude-yeni-model", "claude-sonnet-5-5"
    gw, _ = make_gateway([resp])
    _call(gw, rules_dir)
    row = recorder.ai_calls[-1]
    assert row["model"] == "claude-yeni-model"
    assert "fiyat tablosunda yok" in row["ek"]["maliyet_tahmini"]["neden"]
    top = load_model_table(rules_dir).max_price()
    assert row["maliyet"] == round((100 * top.input + 50 * top.output) / 1_000_000, 6)
