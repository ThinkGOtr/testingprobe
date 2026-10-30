"""§8.2b adım 2 replay'de yakınsar: bulgular → fix_doc → yeniden kontrol → "son hal".

Anahtarsız demo (TP_MODEL_MODE=auto → replay) bu döngüyü 3 tura düşmeden bitirebilmeli; düzeltilmiş
doküman kod ve veriyle (demo-app saf fonksiyonları + seed) tutarlı olmalı ve case üretimi o dokümana
dayanmalı.
"""

from __future__ import annotations

from itertools import permutations
from typing import Any

import pytest

from tests.unit.gateway.demo_sources import (
    DEMO_APP,
    apply_fix_doc,
    cart,
    demo_module,
    load_golden,
    seed_setting,
    story_acs,
)
from tp_core.gateway import golden_name, load_schema, wrap_untrusted
from tp_core.ports import ModelMessage, ToolSpec

TOOLS = [
    ToolSpec(name=n, description=n, input_schema={"type": "object"})
    for n in ("search_code", "get_file_contents", "db_query")
]
MAX_ROUNDS = 3  # §8.2b adım 7


def _doc(acs: dict[str, str]) -> str:
    return "Kabul Kriterleri\n" + "\n".join(acs[k] for k in sorted(acs, key=lambda a: int(a[2:])))


def _check(gw, rules_dir, acs: dict[str, str], round_no: int) -> tuple[Any, str]:
    msg = ModelMessage(
        role="user", content=wrap_untrusted(_doc(acs), source="jira:TPD-1", kind="jira")
    )
    result = gw.run_agent(
        "consistency_check",
        "consistency-check",
        [msg],
        TOOLS,
        lambda name, args: f"{name} sonucu",
        load_schema(rules_dir, "consistency_check"),
        replay_key={"name": golden_name("TPD-1", check_round=round_no), "jira_key": "TPD-1"},
    )
    return result.output, result.mode


def _verify_evidence(finding: dict[str, Any]) -> bool:
    """§8.2b adım 4: kanıt deterministik olarak yeniden doğrulanır (LLM'siz)."""
    for ev in finding["evidence"]:
        if ev["kind"] == "code":
            lines = (DEMO_APP / ev["path"]).read_text(encoding="utf-8").splitlines()
            if ev["snippet"] not in lines[ev["line"] - 1]:
                return False
        else:
            key, value = ev["result_digest"].split("=", 1)
            if seed_setting(key) != value:
                return False
    return True


def _run_loop(gw, rules_dir, decide) -> tuple[dict[str, str], list[dict[str, Any]]]:
    acs = story_acs("TPD-1")
    rounds = []
    for round_no in range(1, MAX_ROUNDS + 1):
        output, mode = _check(gw, rules_dir, acs, round_no)
        assert mode == "replay_miss"  # golden kayıt: dürüst etiket
        findings = [f for f in output["findings"] if _verify_evidence(f)]
        assert len(findings) == len(output["findings"]), "doğrulanamayan kanıt"
        blocking = [f for f in findings if f["severity"] == "blocking"]
        rounds.append({"round": round_no, "blocking": [f["id"] for f in blocking]})
        if not blocking:
            return acs, rounds
        fixes = [f for f in blocking if decide(f) == "fix_doc"]
        for finding in fixes:
            acs = apply_fix_doc(acs, finding["suggested_doc_text"])
    pytest.fail(f"{MAX_ROUNDS} turda son hale gelmedi: {rounds}")


def _decide(finding: dict[str, Any]) -> str:
    return "code_defect" if finding["suggested_doc_text"] is None else "fix_doc"


def test_round1_finds_the_four_planted_inconsistencies(make_gateway, rules_dir) -> None:
    gw, _ = make_gateway(mode="replay")
    output, _ = _check(gw, rules_dir, story_acs("TPD-1"), 1)
    types = sorted(f["type"] for f in output["findings"])
    assert types == ["doc_vs_code", "doc_vs_data", "internal_contradiction", "missing_in_code"]
    assert all(f["severity"] == "blocking" for f in output["findings"])


def test_fix_doc_recheck_reaches_final_state(make_gateway, rules_dir) -> None:
    gw, _ = make_gateway(mode="replay")
    acs, rounds = _run_loop(gw, rules_dir, _decide)
    assert rounds == [
        {"round": 1, "blocking": ["F1", "F2", "F3", "F4"]},
        {"round": 2, "blocking": []},
    ]
    # Son hal kod ve veriyle tutarlı (demo-app saf fonksiyonları + seed).
    money = demo_module("money")
    min_msg = demo_module("pricing").min_siparis_mesaji(seed_setting("min_siparis_tutari"))
    assert "her 6 adette 1 adet bedava" in acs["AC2"]
    assert cart([("P-001", 6)]).satirlar[0].bedava_adet == 1
    assert f'"{min_msg}"' in acs["AC3"] and "Kampanyasız" in acs["AC3"]
    assert cart([("P-002", 10)]).uyarilar[0].mesaj == min_msg  # kampanyasız: uyarı
    assert acs["AC6"] == story_acs("TPD-1")["AC6"]  # AC6 korunur …
    assert cart([("P-001", 7)]).uyarilar == []  # … ve kod onu uygular
    assert money.format_tl(cart([("P-001", 7)]).toplam) == "150,00 TL"
    # AC4 kod hatası: doküman değişmez (bug taslağına gider).
    assert acs["AC4"] == story_acs("TPD-1")["AC4"]


@pytest.mark.parametrize("order", list(permutations(["F1", "F3"])))
def test_overlapping_fixes_are_order_independent(order: tuple[str, str]) -> None:
    """F1 (AC3↔AC6) ve F3 (500↔750) aynı AC'yi yazar; sıra sonucu değiştirmemeli."""
    findings = {f["id"]: f for f in load_golden("consistency_check", "TPD-1")["output"]["findings"]}
    acs = story_acs("TPD-1")
    for fid in order:
        acs = apply_fix_doc(acs, findings[fid]["suggested_doc_text"])
    assert findings["F1"]["suggested_doc_text"] == findings["F3"]["suggested_doc_text"]
    assert "750,00 TL" in acs["AC3"] and "500,00 TL" not in acs["AC3"]
    assert "Kampanyasız" in acs["AC3"]


def test_round2_golden_selected_for_later_rounds(make_gateway, rules_dir, recorder) -> None:
    gw, _ = make_gateway(mode="replay")
    for round_no in (2, 3):
        output, _ = _check(gw, rules_dir, story_acs("TPD-1"), round_no)
        assert not [f for f in output["findings"] if f["severity"] == "blocking"]
    assert recorder.ai_calls[-1]["ek"]["replay_kaynagi"] == "consistency_check/golden/TPD-1-r2.json"


def test_case_generation_golden_uses_final_document() -> None:
    """Case üretimi son hal + PO onayından sonra: case metinleri düzeltilmiş AC'lerle uyumlu."""
    acs, _ = _final_acs()
    cases = load_golden("case_generation", "TPD-1")["output"]["cases"]
    refs = {r for c in cases for r in c["acceptance_criteria_refs"]}
    assert refs == set(acs)  # her AC en az bir case ile kapsanır
    min_msg = demo_module("pricing").min_siparis_mesaji(seed_setting("min_siparis_tutari"))
    assert min_msg in acs["AC3"]
    assert any(min_msg in c["expected_result"] for c in cases)


def _final_acs() -> tuple[dict[str, str], None]:
    findings = load_golden("consistency_check", "TPD-1")["output"]["findings"]
    acs = story_acs("TPD-1")
    for f in findings:
        if f["suggested_doc_text"]:
            acs = apply_fix_doc(acs, f["suggested_doc_text"])
    return acs, None
