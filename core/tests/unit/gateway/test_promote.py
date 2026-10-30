"""Golden yükseltme: TPD-1 adım 2, 4 ve 5 `TP_REPLAY_STRICT=1` ile REPLAY-MISS'siz koşar (§13).

Adım girdileri burada kurulur (iş akışı mesaj kurucusu henüz yok); anahtar her zaman geçidin kendi
hesabıyla (`Gateway.replay_key_for_*`) üretildiği için iş akışı hangi mesajları kurarsa kursun
denetim kaydından yükseltme (`promote_from_rows`) aynı sonucu verir.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.unit.gateway.demo_sources import apply_fix_doc, load_golden, story_acs
from tp_core.gateway import (
    ALLOWED_AGENT_TOOLS,
    ReplayMiss,
    ReplayStore,
    golden_name,
    load_schema,
    wrap_untrusted,
)
from tp_core.gateway.promote import (
    PROMOTED_NOTE,
    main,
    promote_agent,
    promote_call,
    promote_from_rows,
    stale_promotions,
)
from tp_core.gateway.replay import PROMOTED
from tp_core.ports import ModelMessage, ToolSpec

JIRA = "TPD-1"
CONSISTENCY_TOOLS = [
    ToolSpec(name=n, description=n, input_schema={"type": "object"})
    for n in ("search_code", "get_file_contents", "db_query")
]
VERIFY_TOOLS = [
    ToolSpec(name=n, description=n, input_schema={"type": "object"})
    for n in sorted(ALLOWED_AGENT_TOOLS["verify_and_map"])
]


def _doc(acs: dict[str, str]) -> str:
    return "Kabul Kriterleri\n" + "\n".join(acs[k] for k in sorted(acs, key=lambda a: int(a[2:])))


def _msg(text: str, source: str = f"jira:{JIRA}") -> list[ModelMessage]:
    return [ModelMessage(role="user", content=wrap_untrusted(text, source=source, kind="jira"))]


def _final_acs() -> dict[str, str]:
    acs = story_acs(JIRA)
    for f in load_golden("consistency_check", JIRA)["output"]["findings"]:
        if f["suggested_doc_text"]:
            acs = apply_fix_doc(acs, f["suggested_doc_text"])
    return acs


def _browser(name: str, args: dict) -> str:
    return "- Page Snapshot\n  - button 'Sepete ekle' [ref=e1]"


def demo_steps(rules_dir: Path) -> list[dict[str, Any]]:
    """TPD-1 adım 2 (ön inceleme + tutarlılık 2 tur), 4 (case üretimi), 5 (her case için eşleme)."""
    final_doc = _doc(_final_acs())
    steps: list[dict[str, Any]] = [
        {
            "kind": "call",
            "purpose": "requirement_review",
            "bundle": "requirement-review",
            "messages": _msg(_doc(story_acs(JIRA))),
            "schema": load_schema(rules_dir, "requirement_review"),
            "replay_key": {"name": golden_name(JIRA), "jira_key": JIRA},
        }
    ]
    for round_no, doc in ((1, _doc(story_acs(JIRA))), (2, final_doc)):
        steps.append(
            {
                "kind": "agent",
                "purpose": "consistency_check",
                "bundle": "consistency-check",
                "messages": _msg(doc),
                "tools": CONSISTENCY_TOOLS,
                "schema": load_schema(rules_dir, "consistency_check"),
                "replay_key": {
                    "name": golden_name(JIRA, check_round=round_no),
                    "jira_key": JIRA,
                },
            }
        )
    steps.append(
        {
            "kind": "call",
            "purpose": "case_generation",
            "bundle": "case-generation",
            "messages": _msg(final_doc),
            "schema": load_schema(rules_dir, "case_generation"),
            "replay_key": {"name": golden_name(JIRA), "jira_key": JIRA},
        }
    )
    cases = load_golden("case_generation", JIRA)["output"]["cases"]
    for n, case in enumerate(cases, start=1):
        steps.append(
            {
                "kind": "agent",
                "purpose": "verify_and_map",
                "bundle": "verify-and-map",
                "messages": _msg(json.dumps(case, ensure_ascii=False), source=f"case:{JIRA}-{n}"),
                "tools": VERIFY_TOOLS,
                "schema": load_schema(rules_dir, "verify_and_map"),
                "replay_key": {"name": golden_name(JIRA, case_no=n), "jira_key": JIRA},
            }
        )
    return steps


def run_step(gw, step: dict[str, Any]):
    if step["kind"] == "call":
        return gw.call(
            step["purpose"],
            step["bundle"],
            step["messages"],
            step["schema"],
            replay_key=step["replay_key"],
        )
    return gw.run_agent(
        step["purpose"],
        step["bundle"],
        step["messages"],
        step["tools"],
        _browser,
        step["schema"],
        replay_key=step["replay_key"],
    )


def promote_step(gw, step: dict[str, Any]) -> Path:
    if step["kind"] == "call":
        return promote_call(
            gw,
            step["purpose"],
            step["bundle"],
            step["messages"],
            step["schema"],
            replay_key=step["replay_key"],
        )
    return promote_agent(
        gw,
        step["purpose"],
        step["bundle"],
        step["messages"],
        step["tools"],
        step["schema"],
        replay_key=step["replay_key"],
    )


@pytest.fixture
def strict_gateway(make_gateway, rules_dir):
    def _make():
        gw, _ = make_gateway(
            mode="replay", replay_store=ReplayStore(rules_dir / "replay", strict=True)
        )
        return gw

    return _make


def test_demo_steps_cover_steps_2_4_5(rules_dir) -> None:
    purposes = [s["purpose"] for s in demo_steps(rules_dir)]
    assert purposes[:4] == [
        "requirement_review",
        "consistency_check",
        "consistency_check",
        "case_generation",
    ]
    assert purposes.count("verify_and_map") == 9


def test_strict_without_promotion_fails_on_named_golden(strict_gateway, rules_dir) -> None:
    """Sorunun kendisi: yalnızca adlandırılmış golden varken prova kipi ilk adımda durur."""
    gw = strict_gateway()
    with pytest.raises(ReplayMiss):
        run_step(gw, demo_steps(rules_dir)[0])


def test_tpd1_steps_2_4_5_replay_strict_without_miss(
    make_gateway, strict_gateway, rules_dir, recorder
) -> None:
    steps = demo_steps(rules_dir)
    promoter, _ = make_gateway(mode="replay")
    paths = [promote_step(promoter, s) for s in steps]
    assert len(set(paths)) == len(steps)  # her adımın kendi birebir anahtarı

    recorder.ai_calls.clear()
    gw = strict_gateway()
    for step in steps:
        result = run_step(gw, step)  # ReplayMiss olursa test kırmızı
        assert result.mode == "replay"
        golden = load_golden(step["purpose"], step["replay_key"]["name"])
        assert result.output == golden["output"]
    assert [r["mod"] for r in recorder.ai_calls] == ["replay"] * len(steps)
    assert {r["ek"]["replay_kokeni"] for r in recorder.ai_calls} == {PROMOTED}
    assert all(r["saglayici"] == "replay" for r in recorder.ai_calls)  # asla canlı gibi değil


def test_promoted_record_is_labelled_hand_authored(make_gateway, rules_dir) -> None:
    gw, _ = make_gateway(mode="replay")
    step = demo_steps(rules_dir)[1]  # tutarlılık, 1. tur (ajan)
    record = json.loads(promote_step(gw, step).read_text(encoding="utf-8"))
    golden = load_golden("consistency_check", JIRA)
    assert record["provenance"] == PROMOTED and record["note"] == PROMOTED_NOTE
    assert record["golden"] == JIRA
    assert record["output"] == golden["output"] and record["steps"] == golden["steps"]
    assert record["replay_key"] == step["replay_key"]
    assert "live" not in json.dumps(record)


def test_changed_input_after_promotion_misses(make_gateway, strict_gateway, rules_dir) -> None:
    """Birebir kayıt girdiye bağlıdır: story değişirse prova kipi yine ıskalamayı yakalar."""
    step = demo_steps(rules_dir)[0]
    promote_step(make_gateway(mode="replay")[0], step)
    changed = {**step, "messages": _msg(_doc(story_acs(JIRA)) + "\nAC7: yeni kriter")}
    with pytest.raises(ReplayMiss):
        run_step(strict_gateway(), changed)


def test_edited_golden_makes_promotion_stale(make_gateway, strict_gateway, rules_dir) -> None:
    step = demo_steps(rules_dir)[0]
    promote_step(make_gateway(mode="replay")[0], step)
    store = ReplayStore(rules_dir / "replay")
    assert stale_promotions(store) == []
    golden_path = store.golden_path("requirement_review", JIRA)
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    golden["output"]["summary"] = "Değişti."
    golden_path.write_text(json.dumps(golden, ensure_ascii=False), encoding="utf-8")

    assert len(stale_promotions(store)) == 1
    with pytest.raises(ReplayMiss):  # bayat kayıt kullanılmaz
        run_step(strict_gateway(), step)
    gw, _ = make_gateway(mode="replay")
    result = run_step(gw, step)
    assert result.mode == "replay_miss" and result.output["summary"] == "Değişti."
    assert main(["--rules", str(rules_dir), "--check-stale"]) == 1


def test_promote_from_audit_rows_then_strict_passes(
    make_gateway, strict_gateway, rules_dir, recorder
) -> None:
    """Prova akışı: gevşek koşu → ai_call replay_miss satırları → yükselt → sıkı koşu."""
    steps = demo_steps(rules_dir)
    gw, _ = make_gateway(mode="replay")
    for step in steps:
        assert run_step(gw, step).mode == "replay_miss"

    store = ReplayStore(rules_dir / "replay")
    dry = promote_from_rows(store, recorder.ai_calls, dry_run=True)
    assert {o.reason for o in dry} == {"deneme"}
    assert not list((rules_dir / "replay" / "requirement_review").glob("*.json"))

    outcomes = promote_from_rows(store, recorder.ai_calls)
    assert [o.reason for o in outcomes] == ["yazıldı"] * len(steps)
    assert [o.golden for o in outcomes] == [s["replay_key"]["name"] for s in steps]
    again = promote_from_rows(store, recorder.ai_calls)
    assert {o.reason for o in again} == {"zaten var"}

    recorder.ai_calls.clear()
    strict = strict_gateway()
    for step in steps:
        assert run_step(strict, step).mode == "replay"


def test_audit_row_without_matching_golden_is_not_promoted(rules_dir) -> None:
    store = ReplayStore(rules_dir / "replay")
    rows = [
        {"amac": "triage", "mod": "replay_miss", "replay_anahtari": "a" * 64, "cikti": {"x": 1}},
        {"amac": "triage", "mod": "live", "replay_anahtari": "b" * 64, "cikti": {}},
    ]
    outcomes = promote_from_rows(store, rows)
    assert len(outcomes) == 1 and outcomes[0].golden is None
    assert outcomes[0].reason == "golden eşleşmesi yok"
    assert not (rules_dir / "replay" / "triage" / f"{'a' * 64}.json").exists()


def test_promotion_requires_golden_name(make_gateway, rules_dir) -> None:
    from tp_core.gateway import GatewayConfigError

    gw, _ = make_gateway(mode="replay")
    step = {**demo_steps(rules_dir)[0], "replay_key": {"jira_key": JIRA}}
    with pytest.raises(GatewayConfigError, match="golden adı"):
        promote_step(gw, step)


def test_repository_has_no_stale_promotions() -> None:
    from tp_core.gateway import find_rules_dir

    assert stale_promotions(ReplayStore(find_rules_dir() / "replay")) == []
