import json
import re
from pathlib import Path
from uuid import uuid4

import pytest

from tp_core.gateway import (
    ALLOWED_AGENT_TOOLS,
    FINAL_TOOL,
    FORBIDDEN_TOOLS,
    UNGRANTED_MCP_TOOLS,
    AgentTurnLimit,
    GatewayConfigError,
    SchemaValidationFailed,
    load_schema,
)
from tp_core.gateway.core import ELIDED_SNAPSHOT
from tp_core.gateway.testing import text_response, tool_response
from tp_core.ports import AgentStep, ModelMessage, ToolSpec

TOOLS = [
    ToolSpec(name="browser_navigate", description="git", input_schema={"type": "object"}),
    ToolSpec(name="browser_snapshot", description="snapshot", input_schema={"type": "object"}),
    ToolSpec(name="browser_click", description="tıkla", input_schema={"type": "object"}),
]
MSGS = [ModelMessage(role="user", content="Case: S1 giriş yap")]
KEY = {"name": "TPD-4-case-1", "jira_key": "TPD-4", "case_no": 1}
OUTPUT = {
    "step_mapping": [
        {
            "step_id": "S1",
            "po": "LoginPage",
            "method": "login",
            "args": ["bayi1", "Demo123!"],
            "verified": True,
            "evidence_ref": "button 'Giriş'",
        }
    ],
    "expects": [{"po": "CatalogPage", "method": "expectVisible", "args": []}],
    "missing_methods": [],
}


class Browser:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, name: str, args: dict) -> str:
        self.calls.append((name, args))
        if name == "browser_click" and args.get("ref") == "boom":
            raise RuntimeError("eleman yok")
        return f"- Page Snapshot\n  - button 'Giriş' [ref=e{len(self.calls)}]"


def run(gw, rules_dir, execute, **kw):
    return gw.run_agent(
        "verify_and_map",
        "verify-and-map",
        MSGS,
        TOOLS,
        execute,
        load_schema(rules_dir, "verify_and_map"),
        replay_key=KEY,
        **kw,
    )


def test_agent_loop_with_allowlist_denial(make_gateway, rules_dir, recorder) -> None:
    browser = Browser()
    steps_seen: list[AgentStep] = []
    gw, provider = make_gateway(
        [
            tool_response(("browser_navigate", {"url": "http://demo-app-web:8080/login"})),
            tool_response(
                ("browser_evaluate", {"function": "() => document.cookie"}),
                ("browser_take_screenshot", {}),
            ),
            tool_response(("browser_click", {"ref": "e1"})),
            tool_response((FINAL_TOOL, OUTPUT)),
        ]
    )
    result = run(gw, rules_dir, browser, on_step=steps_seen.append, workflow_id=uuid4())

    assert result.mode == "live"
    assert result.output == OUTPUT
    assert [(s.tool, s.allowed) for s in result.steps] == [
        ("browser_navigate", True),
        ("browser_evaluate", False),
        ("browser_take_screenshot", False),
        ("browser_click", True),
    ]
    assert steps_seen == result.steps
    # İzinsiz araçlar hiç çalıştırılmadı
    assert [c[0] for c in browser.calls] == ["browser_navigate", "browser_click"]
    # Her tur bir ai_call, parent_call_id ile ilk tura bağlı
    assert len(recorder.ai_calls) == 4
    assert result.call_ids == [r["id"] for r in recorder.ai_calls]
    assert all(r["parent_call_id"] == result.call_ids[0] for r in recorder.ai_calls[1:])
    # Her araç çağrısı tool_call; ret izin_verildi=False ile kayıtlı
    denied = [t for t in recorder.tool_calls if not t["izin_verildi"]]
    assert {t["arac"] for t in denied} == {"browser_evaluate", "browser_take_screenshot"}
    assert all(t["kanal"] == "agent" for t in recorder.tool_calls)
    assert recorder.tool_calls[-1]["arac"] == FINAL_TOOL
    # Model ret mesajını hata olarak görür
    third_turn = provider.requests[2].messages
    denial = third_turn[-1]["content"]
    assert all(block["is_error"] for block in denial)
    assert "Araç izinli değil" in denial[0]["content"]
    # Son çıktı aracı ve izinli araçlar modele sunulur; izinsizler sunulmaz
    offered = [t.name for t in provider.requests[0].tools]
    assert offered == ["browser_navigate", "browser_snapshot", "browser_click", FINAL_TOOL]
    assert "submit_result" in provider.requests[0].system


def test_only_last_snapshot_kept(make_gateway, rules_dir) -> None:
    gw, provider = make_gateway(
        [
            tool_response(("browser_navigate", {"url": "/"})),
            tool_response(("browser_snapshot", {})),
            tool_response(("browser_click", {"ref": "e2"})),
            tool_response((FINAL_TOOL, OUTPUT)),
        ]
    )
    run(gw, rules_dir, Browser())
    last = provider.requests[3].messages
    results = [
        block["content"]
        for m in last
        if m["role"] == "user" and isinstance(m["content"], list)
        for block in m["content"]
    ]
    assert results[:2] == [ELIDED_SNAPSHOT, ELIDED_SNAPSHOT]
    assert "Page Snapshot" in results[2]
    assert sum("Page Snapshot" in r for r in results) == 1


def test_tool_exception_returned_as_error(make_gateway, rules_dir, recorder) -> None:
    gw, provider = make_gateway(
        [tool_response(("browser_click", {"ref": "boom"})), tool_response((FINAL_TOOL, OUTPUT))]
    )
    result = run(gw, rules_dir, Browser())
    assert "Araç hatası (RuntimeError): eleman yok" in result.steps[0].result_summary
    block = provider.requests[1].messages[-1]["content"][0]
    assert block["is_error"] is True


def test_final_output_schema_retry(make_gateway, rules_dir) -> None:
    gw, provider = make_gateway(
        [
            tool_response((FINAL_TOOL, {"step_mapping": "yanlış"})),
            tool_response((FINAL_TOOL, OUTPUT)),
        ]
    )
    result = run(gw, rules_dir, Browser())
    assert result.output == OUTPUT
    feedback = provider.requests[1].messages[-1]["content"][0]
    assert feedback["is_error"] and "did not match" in feedback["content"]


def test_final_output_schema_gives_up(make_gateway, rules_dir) -> None:
    gw, _ = make_gateway([tool_response((FINAL_TOOL, {"x": 1}))] * 3)
    with pytest.raises(SchemaValidationFailed):
        run(gw, rules_dir, Browser())


def test_plain_text_answer_is_nudged(make_gateway, rules_dir) -> None:
    gw, provider = make_gateway([text_response(OUTPUT), tool_response((FINAL_TOOL, OUTPUT))])
    result = run(gw, rules_dir, Browser())
    assert result.output == OUTPUT
    nudge = provider.requests[1].messages[-1]
    assert nudge["role"] == "user" and FINAL_TOOL in nudge["content"]


def test_max_turns(make_gateway, rules_dir) -> None:
    gw, _ = make_gateway([tool_response(("browser_snapshot", {}))] * 3)
    with pytest.raises(AgentTurnLimit):
        run(gw, rules_dir, Browser(), max_turns=3)


def test_reserved_tool_name(make_gateway, rules_dir) -> None:
    gw, _ = make_gateway([])
    with pytest.raises(GatewayConfigError):
        gw.run_agent(
            "verify_and_map",
            "verify-and-map",
            MSGS,
            [ToolSpec(name=FINAL_TOOL, description="x", input_schema={"type": "object"})],
            Browser(),
            {"type": "object"},
            replay_key=KEY,
        )


@pytest.mark.parametrize(
    "tool", ["browser_run_code_unsafe", "browser_evaluate", "browser_take_screenshot"]
)
def test_forbidden_browser_tool_is_refused_before_provider(make_gateway, rules_dir, tool) -> None:
    assert tool in FORBIDDEN_TOOLS
    gw, provider = make_gateway([tool_response((tool, {}))])
    with pytest.raises(GatewayConfigError, match=tool):
        gw.run_agent(
            "verify_and_map",
            "verify-and-map",
            MSGS,
            [*TOOLS, ToolSpec(name=tool, description="x", input_schema={"type": "object"})],
            Browser(),
            {"type": "object"},
            replay_key=KEY,
        )
    assert provider.requests == []


def test_design_allowlist_has_no_forbidden_tool() -> None:
    allowlist = {
        "browser_navigate",
        "browser_snapshot",
        "browser_click",
        "browser_type",
        "browser_select_option",
        "browser_wait_for",
        "browser_generate_locator",
    }
    assert not allowlist & FORBIDDEN_TOOLS


def test_record_then_replay_reexecutes_allowed_steps(make_gateway, rules_dir, recorder) -> None:
    gw, _ = make_gateway(
        [
            tool_response(("browser_navigate", {"url": "/login"})),
            tool_response(("browser_evaluate", {"function": "x"})),
            tool_response((FINAL_TOOL, OUTPUT)),
        ],
        mode="record",
    )
    run(gw, rules_dir, Browser())
    files = list((rules_dir / "replay" / "verify_and_map").glob("*.json"))
    assert len(files) == 1 and json.loads(files[0].read_text())["kind"] == "agent"

    browser = Browser()
    replay_gw, _ = make_gateway(mode="replay")
    result = run(replay_gw, rules_dir, browser)
    assert result.mode == "replay"
    assert result.output == OUTPUT
    assert browser.calls == [("browser_navigate", {"url": "/login"})]  # yalnızca izinli adım
    assert [(s.tool, s.allowed) for s in result.steps] == [
        ("browser_navigate", True),
        ("browser_evaluate", False),
    ]
    assert recorder.ai_calls[-1]["mod"] == "replay"
    assert recorder.tool_calls[-1]["izin_verildi"] is False


def test_replay_enforces_current_allowlist(make_gateway, rules_dir) -> None:
    golden_dir = rules_dir / "replay" / "verify_and_map" / "golden"
    golden_dir.mkdir(parents=True, exist_ok=True)
    (golden_dir / "TPD-4-case-1.json").write_text(
        json.dumps(
            {
                "kind": "agent",
                "output": OUTPUT,
                "steps": [
                    {"tool": "browser_install", "args": {}, "result_summary": "", "allowed": True},
                    {
                        "tool": "browser_click",
                        "args": {"ref": "e1"},
                        "result_summary": "ok",
                        "allowed": True,
                    },
                ],
            }
        )
    )
    browser = Browser()
    gw, _ = make_gateway(mode="replay")
    result = run(gw, rules_dir, browser)
    assert result.mode == "replay_miss"
    assert browser.calls == [("browser_click", {"ref": "e1"})]
    assert result.steps[0].allowed is False


def test_agent_input_token_cap(make_gateway, rules_dir) -> None:
    from tp_core.gateway import BudgetExceeded

    gw, _ = make_gateway([tool_response(("browser_snapshot", {}), input_tokens=100_000)] * 3)
    with pytest.raises(BudgetExceeded) as exc:
        run(gw, rules_dir, Browser())
    assert exc.value.scope == "ajan girdi token'ı"


def test_tool_rows_match_platform_columns(make_gateway, rules_dir, recorder) -> None:
    from tp_core.audit.recorder import TOOL_CALL_COLUMNS

    gw, _ = make_gateway(
        [tool_response(("browser_evaluate", {"f": "x"})), tool_response((FINAL_TOOL, OUTPUT))]
    )
    run(gw, rules_dir, Browser())
    for row in recorder.tool_calls:
        assert set(row) <= set(TOOL_CALL_COLUMNS)
    assert recorder.tool_calls[0]["arguman_ozeti"] == {"f": "x"}


# ------------------------------------------------------------------ aşama başına izin listesi

MCP_FIXTURE = Path(__file__).parent / "fixtures" / "playwright_mcp_tools.json"
MCP_TOOLS = [t["name"] for t in json.loads(MCP_FIXTURE.read_text(encoding="utf-8"))["tools"]]


def _spec(name: str) -> ToolSpec:
    return ToolSpec(name=name, description=name, input_schema={"type": "object"})


def test_every_recorded_mcp_tool_is_classified() -> None:
    """MCP yükseltmesi yeni araç eklerse burada kırmızı olur: araç bilinçli olarak sınıflanmalı."""
    granted = set().union(*ALLOWED_AGENT_TOOLS.values())
    classified = granted | FORBIDDEN_TOOLS | UNGRANTED_MCP_TOOLS
    unclassified = sorted(set(MCP_TOOLS) - classified)
    assert not unclassified, f"sınıflanmamış MCP aracı: {unclassified}"
    assert not granted & FORBIDDEN_TOOLS
    assert not granted & UNGRANTED_MCP_TOOLS
    assert not FORBIDDEN_TOOLS & UNGRANTED_MCP_TOOLS


def test_file_and_code_tools_of_recorded_mcp_are_forbidden() -> None:
    for name in ("browser_drop", "browser_file_upload", "browser_run_code_unsafe"):
        assert name in MCP_TOOLS and name in FORBIDDEN_TOOLS
    # Açıklamasında dosya yolu/kod çalıştırma geçen her araç yasak listesinde.
    tools = json.loads(MCP_FIXTURE.read_text(encoding="utf-8"))["tools"]
    risky = {
        t["name"]
        for t in tools
        if re.search(r"\bfiles?\b|javascript|network request", t["description"], re.I)
    }
    assert risky <= FORBIDDEN_TOOLS, sorted(risky - FORBIDDEN_TOOLS)


def test_verify_and_map_allowlist_is_the_design_list() -> None:
    assert ALLOWED_AGENT_TOOLS["verify_and_map"] == {
        "browser_navigate",
        "browser_snapshot",
        "browser_click",
        "browser_type",
        "browser_select_option",
        "browser_wait_for",
        "browser_generate_locator",
    }


@pytest.mark.parametrize("tool", sorted(set(MCP_TOOLS) - ALLOWED_AGENT_TOOLS["verify_and_map"]))
def test_every_non_allowed_mcp_tool_is_refused(make_gateway, tool) -> None:
    gw, provider = make_gateway([tool_response((tool, {}))])
    with pytest.raises(GatewayConfigError, match=tool):
        gw.run_agent(
            "verify_and_map",
            "verify-and-map",
            MSGS,
            [*TOOLS, _spec(tool)],
            Browser(),
            {"type": "object"},
            replay_key=KEY,
        )
    assert provider.requests == []


def test_browser_drop_is_refused_before_provider(make_gateway) -> None:
    gw, provider = make_gateway([tool_response(("browser_drop", {"paths": ["/etc/passwd"]}))])
    with pytest.raises(GatewayConfigError, match="browser_drop"):
        gw.run_agent(
            "verify_and_map",
            "verify-and-map",
            MSGS,
            [*TOOLS, _spec("browser_drop")],
            Browser(),
            {"type": "object"},
            replay_key=KEY,
        )
    assert provider.requests == []


def test_unknown_future_tool_is_refused_by_allowlist(make_gateway) -> None:
    """Yasak listesinde olmayan yeni bir araç da izin listesi dışında olduğu için reddedilir."""
    gw, provider = make_gateway([])
    assert "browser_new_shiny_tool" not in FORBIDDEN_TOOLS
    with pytest.raises(GatewayConfigError, match="izin listesinde olmayan araç"):
        gw.run_agent(
            "verify_and_map",
            "verify-and-map",
            MSGS,
            [*TOOLS, _spec("browser_new_shiny_tool")],
            Browser(),
            {"type": "object"},
            replay_key=KEY,
        )
    assert provider.requests == []


def test_browser_tool_is_not_allowed_in_consistency_check(make_gateway) -> None:
    gw, provider = make_gateway([])
    with pytest.raises(GatewayConfigError, match="browser_navigate"):
        gw.run_agent(
            "consistency_check",
            "consistency-check",
            MSGS,
            [_spec("search_code"), _spec("browser_navigate")],
            Browser(),
            {"type": "object"},
            replay_key=KEY,
        )
    assert provider.requests == []


def test_purpose_without_allowlist_cannot_run_as_agent(make_gateway) -> None:
    gw, provider = make_gateway([])
    with pytest.raises(GatewayConfigError, match="izin listesi yok"):
        gw.run_agent(
            "triage",
            "triage",
            MSGS,
            [_spec("search")],
            Browser(),
            {"type": "object"},
            replay_key=KEY,
        )
    assert provider.requests == []


def test_allowlist_override_cannot_grant_forbidden_tool(make_gateway) -> None:
    with pytest.raises(GatewayConfigError, match="browser_evaluate"):
        make_gateway([], agent_tools={"verify_and_map": {"browser_navigate", "browser_evaluate"}})


def test_model_calling_tool_outside_request_is_denied(make_gateway, rules_dir, recorder) -> None:
    """Model listede olmayan aracı (ör. browser_drop) çağırırsa yürütülmez; red kaydedilir."""
    browser = Browser()
    gw, _ = make_gateway(
        [
            tool_response(("browser_drop", {"paths": ["/etc/passwd"]})),
            tool_response((FINAL_TOOL, OUTPUT)),
        ]
    )
    result = run(gw, rules_dir, browser)
    assert result.output == OUTPUT
    assert all(name != "browser_drop" for name, _ in browser.calls)
    denied = [t for t in recorder.tool_calls if t["arac"] == "browser_drop"]
    assert denied and denied[0]["izin_verildi"] is False


def _with_thinking(response):
    """Sonnet 5.5 `between_tools`: araçlar arası ilerleme notu `thinking` bloğu olarak döner."""
    blocks = [
        {"type": "thinking", "thinking": "ilerleme notu", "signature": "sig"},
        {"type": "redacted_thinking", "data": "gizli"},
    ]
    response.raw_assistant_content = blocks + response.raw_assistant_content
    return response


def _assert_no_thinking_after_edit(messages) -> None:
    """Düzenlenen (ELIDED_SNAPSHOT) mesajdan sonra hiçbir asistan turu thinking taşımamalı."""
    edited_seen = False
    for m in messages:
        content = m["content"] if isinstance(m["content"], list) else []
        if m["role"] == "assistant" and edited_seen:
            assert not [b for b in content if b.get("type") in {"thinking", "redacted_thinking"}]
            assert content  # boş asistan içeriği gönderilmez
        if m["role"] == "user" and any(b.get("content") == ELIDED_SNAPSHOT for b in content):
            edited_seen = True


def test_thinking_blocks_dropped_after_elided_snapshot(make_gateway, rules_dir) -> None:
    gw, provider = make_gateway(
        [
            _with_thinking(tool_response(("browser_snapshot", {}))),
            _with_thinking(tool_response(("browser_click", {"ref": "e1"}))),
            _with_thinking(tool_response(("browser_snapshot", {}))),
            _with_thinking(tool_response(("browser_click", {"ref": "e3"}))),
            _with_thinking(tool_response(("browser_snapshot", {}))),
            _with_thinking(tool_response((FINAL_TOOL, OUTPUT))),
        ]
    )
    run(gw, rules_dir, Browser())
    for request in provider.requests:
        _assert_no_thinking_after_edit(request.messages)

    def thinking_turns(messages):
        return [
            any(b.get("type") == "thinking" for b in m["content"])
            for m in messages
            if m["role"] == "assistant"
        ]

    # Browser her araç sonucunda snapshot döndürür (Playwright MCP gibi): yalnızca son tur
    # snapshot'ı kalır. 2. istek: henüz düzenleme yok → geçmiş aynen (append-only).
    assert thinking_turns(provider.requests[1].messages) == [True]
    # 3. istek: 1. turun sonucu çıkarıldı → 1. tur korunur, sonrakilerden thinking düşer.
    assert thinking_turns(provider.requests[2].messages) == [True, False]
    assert thinking_turns(provider.requests[5].messages) == [True, False, False, False, False]


def test_thinking_only_turn_after_edit_keeps_non_empty_content(make_gateway, rules_dir) -> None:
    thinking_only = text_response("")
    thinking_only.raw_assistant_content = [
        {"type": "thinking", "thinking": "not", "signature": "sig"}
    ]
    gw, provider = make_gateway(
        [
            tool_response(("browser_snapshot", {})),
            tool_response(("browser_snapshot", {})),
            thinking_only,
            tool_response((FINAL_TOOL, OUTPUT)),
        ]
    )
    run(gw, rules_dir, Browser())
    _assert_no_thinking_after_edit(provider.requests[3].messages)
