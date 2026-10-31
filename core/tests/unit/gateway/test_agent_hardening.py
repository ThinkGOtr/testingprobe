"""Ajan döngüsü sertleştirmeleri (Faz 3 inceleme bulguları).

1. `tool_call` (append-only) parola alanına yazılan metni ve bilinen sırları ham saklamaz.
2. Ajan girdi token tavanı önbellekten okunan öneki saymaz; gerçekçi 15 turluk yörünge sığar.
3. Anthropic: ilk kullanıcı mesajı (case + sembol tablosu) önbellek kırılma noktasıdır.
4. Verilen araçların dosya yazan argümanları (`browser_snapshot.filename`) modele sunulmaz ve
   çağrıda gelirse çalıştırılmaz.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tp_core.gateway import (
    ALLOWED_AGENT_TOOLS,
    FINAL_TOOL,
    BudgetExceeded,
    Gateway,
    ReplayStore,
    load_schema,
    mask_tool_args,
    narrow_tool,
    restricted_args,
    scrub_secrets,
    secret_tool_values,
)
from tp_core.gateway.config import load_model_table
from tp_core.gateway.providers.anthropic_provider import AnthropicProvider, with_prefix_cache
from tp_core.gateway.providers.base import ProviderRequest, ProviderResponse, ToolCall, Usage
from tp_core.gateway.testing import InMemoryCallRecorder, tool_response
from tp_core.ports import ModelMessage, ToolSpec

from .test_agent import KEY, MSGS, OUTPUT, TOOLS, run

PASSWORD = "Demo123!"
MCP_FIXTURE = Path(__file__).parent / "fixtures" / "playwright_mcp_tools.json"
MCP_TOOLS: list[dict[str, Any]] = json.loads(MCP_FIXTURE.read_text(encoding="utf-8"))["tools"]
TYPE_TOOL = ToolSpec(name="browser_type", description="yaz", input_schema={"type": "object"})


def _leaks(rows: list[dict[str, Any]], secret: str = PASSWORD) -> list[dict[str, Any]]:
    return [r for r in rows if secret in json.dumps(r, ensure_ascii=False, default=str)]


# ------------------------------------------------------------------ 1. sır maskeleme


def test_mask_tool_args_hides_password_fields_only() -> None:
    by_element = {"element": "Parola", "target": "#x", "text": PASSWORD}
    by_target = {"element": "alan", "target": '[data-testid="login-password"]', "text": PASSWORD}
    by_ref = {"element": "Şifre", "ref": "e7", "text": PASSWORD}
    user = {"element": "Kullanıcı adı", "target": '[data-testid="login-username"]', "text": "b3"}
    assert mask_tool_args(by_element)["text"] == "***"
    assert mask_tool_args(by_target)["text"] == "***"
    assert mask_tool_args(by_ref)["text"] == "***"
    assert mask_tool_args(user) == user
    form = {"fields": [{"name": "Parola", "type": "textbox", "ref": "e3", "value": PASSWORD}]}
    assert mask_tool_args(form)["fields"][0]["value"] == "***"
    assert secret_tool_values(form) == [PASSWORD]
    assert by_element["text"] == PASSWORD  # kopya döner
    assert scrub_secrets(f"fill('{PASSWORD}')", [PASSWORD]) == "fill('***')"
    assert scrub_secrets("abc", ["ab"]) == "abc"  # çok kısa değerler silinmez


def test_live_tool_rows_never_store_the_typed_password(make_gateway, rules_dir, recorder) -> None:
    def browser(name: str, args: dict[str, Any]) -> str:
        if name == "browser_type":
            return f"await page.locator('{args['target']}').fill('{args['text']}');"
        return "- Page Snapshot\n  - button 'Giriş yap' [ref=e3]"

    gw, _ = make_gateway(
        [
            tool_response(
                (
                    "browser_type",
                    {
                        "element": "Parola",
                        "target": '[data-testid="login-password"]',
                        "text": PASSWORD,
                    },
                )
            ),
            tool_response(("browser_snapshot", {})),
            tool_response((FINAL_TOOL, OUTPUT)),
        ]
    )
    calls: list[tuple[str, dict[str, Any]]] = []

    def execute(name: str, args: dict[str, Any]) -> str:
        calls.append((name, args))
        return browser(name, args)

    result = run_with(gw, rules_dir, [*TOOLS, TYPE_TOOL], execute)
    # Tarayıcıya gerçek parola gider; kayda gitmez.
    assert calls[0][1]["text"] == PASSWORD
    assert _leaks(recorder.tool_calls) == []
    typed = recorder.tool_calls[0]
    assert typed["arguman_ozeti"]["text"] == "***"
    assert "fill('***')" in typed["sonuc_ozeti"]
    # Son çıktı (login argümanı case verisidir) tool_call özetinde de gizlenir; çıktı değişmez.
    assert result.output == OUTPUT
    assert result.steps[0].result_summary.endswith("fill('***');")


def test_known_secret_values_are_scrubbed_from_results(make_gateway, rules_dir, recorder) -> None:
    gw, _ = make_gateway(
        [tool_response(("browser_snapshot", {})), tool_response((FINAL_TOOL, OUTPUT))],
        secret_values=["S3cr3t-xyz"],
    )
    run(gw, rules_dir, lambda name, args: "token=S3cr3t-xyz görünür")
    assert _leaks(recorder.tool_calls, "S3cr3t-xyz") == []


def test_replayed_golden_steps_do_not_store_the_password(rules_dir) -> None:
    """Golden yörüngesinde (`browser_type` → Parola) parola var; replay'in tool_call satırları
    ve akan adım özetleri onu taşımaz."""
    recorder = InMemoryCallRecorder()
    gw = Gateway(
        provider=None,
        recorder=recorder,
        mode="replay",
        models=load_model_table(rules_dir),
        rules_dir=rules_dir,
        replay_store=ReplayStore(rules_dir / "replay"),
        replay_executes_tools=False,
    )
    golden = json.loads(
        (rules_dir / "replay/verify_and_map/golden/TPD-1-C2.json").read_text(encoding="utf-8")
    )
    assert _leaks(golden["steps"])  # önkoşul: golden'da parola var
    tools = [
        ToolSpec(name=n, description=n, input_schema={"type": "object"})
        for n in sorted(ALLOWED_AGENT_TOOLS["verify_and_map"])
    ]
    from .demo_sources import load_golden
    from .test_codegen_goldens import _verify_messages

    case = load_golden("case_generation", "TPD-1")["output"]["cases"][1]
    result = gw.run_agent(
        "verify_and_map",
        "verify-and-map",
        _verify_messages(case, 2),
        tools,
        lambda name, args: "",
        load_schema(rules_dir, "verify_and_map"),
        replay_key={"name": "TPD-1-C2", "jira_key": "TPD-1"},
    )
    assert recorder.tool_calls and _leaks(recorder.tool_calls) == []
    assert all(PASSWORD not in s.result_summary for s in result.steps)


def run_with(gw, rules_dir, tools, execute):
    return gw.run_agent(
        "verify_and_map",
        "verify-and-map",
        MSGS,
        tools,
        execute,
        load_schema(rules_dir, "verify_and_map"),
        replay_key=KEY,
    )


# ------------------------------------------------------------------ 2. token tavanı


def _turn(name: str, args: dict[str, Any], usage: Usage) -> ProviderResponse:
    response = tool_response((name, args))
    response.usage = usage
    return response


def _realistic_usage(turn: int) -> Usage:
    """Ölçülen boyutlarla bir tur: önek (sistem+araçlar+case+sembol tablosu) ~10.5k token;
    1. turda önbelleğe yazılır, sonra okunur. Önbelleksiz kısım: geçmiş (~400/tur) + son snapshot
    (~1.2k)."""
    prefix = 10_500
    fresh = 1_200 + 400 * (turn - 1)
    if turn == 1:
        return Usage(input_tokens=fresh, output_tokens=300, cache_write_tokens=prefix)
    return Usage(input_tokens=fresh, output_tokens=300, cache_read_tokens=prefix)


def test_realistic_fifteen_turn_trajectory_fits_the_input_budget(make_gateway, rules_dir) -> None:
    turns = 15
    script = [_turn("browser_snapshot", {}, _realistic_usage(t)) for t in range(1, turns)]
    script.append(_turn(FINAL_TOOL, OUTPUT, _realistic_usage(turns)))
    gw, provider = make_gateway(script)
    cap = gw.models.purpose("verify_and_map").max_input_tokens
    result = run(gw, rules_dir, lambda name, args: "- Page Snapshot\n  - button 'x' [ref=e1]")
    assert result.output == OUTPUT and len(provider.requests) == turns
    usages = [_realistic_usage(t) for t in range(1, turns + 1)]
    cumulative_all = sum(
        u.input_tokens + u.cache_read_tokens + u.cache_write_tokens for u in usages
    )
    budgeted = sum(u.input_tokens + u.cache_write_tokens for u in usages)
    # Eski sayım (önbellek okuması dahil) bu yörüngeyi durdururdu; yeni sayım sığar.
    assert cap is not None and cumulative_all > cap > budgeted


def test_runaway_uncached_context_still_trips_the_cap(make_gateway, rules_dir) -> None:
    usage = Usage(input_tokens=40_000, output_tokens=100, cache_read_tokens=10_000)
    gw, _ = make_gateway([_turn("browser_snapshot", {}, usage)] * 6)
    with pytest.raises(BudgetExceeded) as exc:
        run(gw, rules_dir, lambda name, args: "ok")
    assert exc.value.scope == "ajan girdi token'ı"


def test_cache_misses_count_against_the_cap(make_gateway, rules_dir) -> None:
    """Önbellek her tur ıskalarsa (yazma) önek her tur sayılır: tavan yine korur."""
    usage = Usage(input_tokens=1_000, output_tokens=100, cache_write_tokens=30_000)
    gw, _ = make_gateway([_turn("browser_snapshot", {}, usage)] * 8)
    with pytest.raises(BudgetExceeded):
        run(gw, rules_dir, lambda name, args: "ok")


# ------------------------------------------------------------------ 3. önbellek kırılma noktası


def _request(messages: list[dict[str, Any]], *, tools: bool = True) -> ProviderRequest:
    return ProviderRequest(
        model="claude-sonnet-5-5",
        system="sistem",
        messages=messages,
        max_tokens=1024,
        tools=[TYPE_TOOL] if tools else [],
    )


def _breakpoints(kwargs: dict[str, Any]) -> list[tuple[int, int]]:
    out = []
    for mi, message in enumerate(kwargs["messages"]):
        content = message["content"]
        for bi, block in enumerate(content if isinstance(content, list) else []):
            if isinstance(block, dict) and "cache_control" in block:
                out.append((mi, bi))
    return out


def test_agent_cache_breakpoints_are_initial_message_and_rolling_last_block() -> None:
    """Önek (ilk mesaj) + kayan kırılma noktası (son mesajın son bloğu); aradaki tool_result'lar
    kırılma noktası değildir. Toplam: sistem + 2 = 3 (API sınırı 4)."""
    provider = AnthropicProvider(client=object(), server_fallback=False)
    first = {"role": "user", "content": "case + sembol tablosu " * 50}
    call = ToolCall(id="toolu_1", name="browser_snapshot", args={})
    messages = [
        first,
        {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_1", "name": "x"}]},
        provider.tool_result_message([(call, "[eski snapshot bağlamdan çıkarıldı]", False)]),
        {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_2", "name": "x"}]},
        provider.tool_result_message([(call, "- Page Snapshot", False)]),
    ]
    kwargs = provider.build_kwargs(_request(messages))
    assert _breakpoints(kwargs) == [(0, 0), (4, 0)]
    assert "cache_control" not in messages[4]["content"][0]  # özgün tool_result değişmedi
    assert kwargs["messages"][0]["content"][0]["text"] == first["content"]
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert isinstance(first["content"], str)  # özgün mesaj değişmedi
    # Önek turlar boyunca aynı: ikinci turun ilk mesajı birinciyle birebir aynı.
    again = provider.build_kwargs(_request(messages[:1]))
    assert again["messages"][0] == kwargs["messages"][0]


def test_list_content_gets_the_breakpoint_on_its_last_block() -> None:
    first = {
        "role": "user",
        "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}],
    }
    out = with_prefix_cache([first])
    assert "cache_control" not in out[0]["content"][0]
    assert out[0]["content"][1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in first["content"][1]


def test_rolling_breakpoint_moves_with_the_conversation() -> None:
    """Bir tur sonra kayan kırılma noktası yeni son mesaja geçer; önceki turun son bloğu artık
    işaretsizdir (önbellek yazımı ve okuması aynı öneki görür; ≤ 4 kırılma noktası)."""
    provider = AnthropicProvider(client=object(), server_fallback=False)
    call = ToolCall(id="toolu_1", name="browser_click", args={})
    turn1 = [
        {"role": "user", "content": "case"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_1", "name": "x"}]},
        provider.tool_result_message([(call, "tıklandı", False)]),
    ]
    turn2 = [
        *turn1,
        {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_2", "name": "x"}]},
        provider.tool_result_message([(call, "yazıldı", False)]),
    ]
    one = provider.build_kwargs(_request(turn1))
    two = provider.build_kwargs(_request(turn2))
    assert _breakpoints(one) == [(0, 0), (2, 0)]
    assert _breakpoints(two) == [(0, 0), (4, 0)]
    assert "cache_control" not in two["messages"][2]["content"][0]
    # Metin (nudge) son mesajı da blok olur ve işaretlenir; thinking bloğu işaretlenmez.
    nudge = provider.build_kwargs(_request([*turn1[:2], {"role": "user", "content": "sonuç?"}]))
    assert nudge["messages"][-1]["content"] == [
        {"type": "text", "text": "sonuç?", "cache_control": {"type": "ephemeral"}}
    ]
    assert len(_breakpoints(two)) + 1 <= 4  # + sistem


def test_single_calls_do_not_cache_the_message() -> None:
    provider = AnthropicProvider(client=object(), server_fallback=False)
    kwargs = provider.build_kwargs(_request([{"role": "user", "content": "x"}], tools=False))
    assert kwargs["messages"] == [{"role": "user", "content": "x"}]


# ------------------------------------------------------------------ 4. dosya yazan argümanlar


def _file_args(schema: dict[str, Any]) -> list[str]:
    props = schema.get("properties") or {}
    return [
        k
        for k, v in props.items()
        if k in ("filename", "path", "paths")
        or any(w in str(v.get("description", "")).lower() for w in ("save ", "file"))
    ]


def test_recorded_mcp_fixture_has_input_schemas() -> None:
    assert all("input_schema" in t for t in MCP_TOOLS)
    snapshot = next(t for t in MCP_TOOLS if t["name"] == "browser_snapshot")
    assert "filename" in snapshot["input_schema"]["properties"]  # dosya yazar (kanıt)


def test_granted_tools_expose_no_file_path_arguments_to_the_model() -> None:
    granted = set().union(*ALLOWED_AGENT_TOOLS.values())
    for tool in MCP_TOOLS:
        if tool["name"] not in granted:
            continue
        spec = narrow_tool(
            ToolSpec(name=tool["name"], description="", input_schema=tool["input_schema"])
        )
        assert _file_args(spec.input_schema) == [], tool["name"]
    snapshot = next(t for t in MCP_TOOLS if t["name"] == "browser_snapshot")
    narrowed = narrow_tool(
        ToolSpec(name="browser_snapshot", description="", input_schema=snapshot["input_schema"])
    )
    assert set(narrowed.input_schema["properties"]) == {"target", "depth"}
    assert "filename" in snapshot["input_schema"]["properties"]  # fikstür değişmedi
    assert restricted_args("browser_snapshot") >= {"filename", "boxes"}


def test_model_never_sees_and_cannot_use_snapshot_filename(
    make_gateway, rules_dir, recorder
) -> None:
    snapshot = next(t for t in MCP_TOOLS if t["name"] == "browser_snapshot")
    tools = [
        ToolSpec(name="browser_snapshot", description="s", input_schema=snapshot["input_schema"])
    ]
    executed: list[tuple[str, dict[str, Any]]] = []
    gw, provider = make_gateway(
        [
            tool_response(("browser_snapshot", {"filename": "../../etc/x.md"})),
            tool_response(("browser_snapshot", {})),
            tool_response((FINAL_TOOL, OUTPUT)),
        ]
    )
    result = run_with(gw, rules_dir, tools, lambda n, a: executed.append((n, a)) or "ok")
    offered = next(t for t in provider.requests[0].tools if t.name == "browser_snapshot")
    assert "filename" not in offered.input_schema["properties"]
    assert executed == [("browser_snapshot", {})]
    assert [(s.tool, s.allowed) for s in result.steps] == [
        ("browser_snapshot", False),
        ("browser_snapshot", True),
    ]
    assert recorder.tool_calls[0]["izin_verildi"] is False
    assert "Argüman izinli değil" in recorder.tool_calls[0]["sonuc_ozeti"]


def test_replay_does_not_execute_a_recorded_filename_argument(tmp_path: Path, rules_dir) -> None:
    store_root = tmp_path / "replay"
    golden_dir = store_root / "verify_and_map" / "golden"
    golden_dir.mkdir(parents=True)
    (golden_dir / "X-C1.json").write_text(
        json.dumps(
            {
                "kind": "agent",
                "golden": "X-C1",
                "output": OUTPUT,
                "steps": [
                    {
                        "tool": "browser_snapshot",
                        "args": {"filename": "x.md"},
                        "result_summary": "",
                        "allowed": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    recorder = InMemoryCallRecorder()
    gw = Gateway(
        provider=None,
        recorder=recorder,
        mode="replay",
        models=load_model_table(rules_dir),
        rules_dir=rules_dir,
        replay_store=ReplayStore(store_root),
    )
    executed: list[str] = []
    result = gw.run_agent(
        "verify_and_map",
        "verify-and-map",
        [ModelMessage(role="user", content="x")],
        [ToolSpec(name="browser_snapshot", description="s", input_schema={"type": "object"})],
        lambda n, a: executed.append(n) or "",
        load_schema(rules_dir, "verify_and_map"),
        replay_key={"name": "X-C1"},
    )
    assert executed == []
    assert result.steps[0].allowed is False
    assert "Argüman izinli değil" in result.steps[0].result_summary
