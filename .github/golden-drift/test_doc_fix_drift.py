"""§8.2b tutarlılık döngüsünün golden kayıtları demo-app ile hâlâ yakınsıyor mu (saf veri).

core/tests/unit/gateway/test_consistency_flow.py aynı döngüyü Gateway üzerinden (replay) koşar;
o test yerel birim paketinde kalır. CI'da ajan yolu ÇALIŞTIRILMAZ (anayasa II): burada golden
kayıtlar doğrudan okunur, kanıtlar deterministik olarak yeniden doğrulanır ve düzeltilmiş
dokümanın demo-app saf fonksiyonları + seed ile tutarlılığı kontrol edilir.
"""

from __future__ import annotations

from itertools import permutations
from typing import Any

import pytest

from drift_sources import (
    DEMO_APP,
    apply_fix_doc,
    cart,
    demo_module,
    golden_name,
    load_golden,
    seed_setting,
    story_acs,
)

MAX_ROUNDS = 3  # §8.2b adım 7


def _findings(round_no: int) -> list[dict[str, Any]]:
    name = golden_name("TPD-1", check_round=round_no)
    return load_golden("consistency_check", name)["output"]["findings"]


def _verify_evidence(finding: dict[str, Any]) -> bool:
    """§8.2b adım 4: kanıt deterministik olarak yeniden doğrulanır (LLM'siz)."""
    for ev in finding["evidence"]:
        if ev["kind"] == "code":
            lines = (DEMO_APP / ev["path"]).read_text(encoding="utf-8").splitlines()
            if ev["line"] > len(lines) or ev["snippet"] not in lines[ev["line"] - 1]:
                return False
        else:
            key, value = ev["result_digest"].split("=", 1)
            if seed_setting(key) != value:
                return False
    return True


def _decide(finding: dict[str, Any]) -> str:
    return "code_defect" if finding["suggested_doc_text"] is None else "fix_doc"


def _run_loop() -> tuple[dict[str, str], list[dict[str, Any]]]:
    acs = story_acs("TPD-1")
    rounds = []
    for round_no in range(1, MAX_ROUNDS + 1):
        findings = _findings(round_no)
        unverified = [f["id"] for f in findings if not _verify_evidence(f)]
        assert not unverified, f"tur {round_no}: doğrulanamayan kanıt {unverified}"
        blocking = [f for f in findings if f["severity"] == "blocking"]
        rounds.append({"round": round_no, "blocking": [f["id"] for f in blocking]})
        if not blocking:
            return acs, rounds
        for finding in blocking:
            if _decide(finding) == "fix_doc":
                acs = apply_fix_doc(acs, finding["suggested_doc_text"])
    pytest.fail(f"{MAX_ROUNDS} turda son hale gelmedi: {rounds}")


def test_round1_golden_has_the_four_planted_inconsistencies() -> None:
    findings = _findings(1)
    assert sorted(f["type"] for f in findings) == [
        "doc_vs_code",
        "doc_vs_data",
        "internal_contradiction",
        "missing_in_code",
    ]
    assert all(f["severity"] == "blocking" for f in findings)


def test_later_rounds_use_the_r2_golden_without_blockers() -> None:
    assert golden_name("TPD-1", check_round=2) == golden_name("TPD-1", check_round=3) == "TPD-1-r2"
    assert not [f for f in _findings(2) if f["severity"] == "blocking"]


def test_fix_doc_loop_reaches_final_state_consistent_with_demo_app() -> None:
    acs, rounds = _run_loop()
    assert rounds == [
        {"round": 1, "blocking": ["F1", "F2", "F3", "F4"]},
        {"round": 2, "blocking": []},
    ]
    money = demo_module("money")
    min_msg = demo_module("pricing").min_siparis_mesaji(seed_setting("min_siparis_tutari"))
    assert "her 6 adette 1 adet bedava" in acs["AC2"]
    assert cart([("P-001", 6)]).satirlar[0].bedava_adet == 1
    assert f'"{min_msg}"' in acs["AC3"] and "Kampanyasız" in acs["AC3"]
    assert cart([("P-002", 10)]).uyarilar[0].mesaj == min_msg
    assert acs["AC6"] == story_acs("TPD-1")["AC6"]
    assert cart([("P-001", 7)]).uyarilar == []
    assert money.format_tl(cart([("P-001", 7)]).toplam) == "150,00 TL"
    # AC4 kod hatası: doküman değişmez (bug taslağına gider).
    assert acs["AC4"] == story_acs("TPD-1")["AC4"]


def test_evidence_check_rejects_a_drifted_line() -> None:
    """Kontrolün kendisi: kayıtlı satır kayarsa kanıt reddedilir (yanlış pozitif yok)."""
    finding = next(f for f in _findings(1) if any(e["kind"] == "code" for e in f["evidence"]))
    assert _verify_evidence(finding)
    drifted = {
        **finding,
        "evidence": [
            {**e, "line": e["line"] + 1} if e["kind"] == "code" else e for e in finding["evidence"]
        ],
    }
    assert not _verify_evidence(drifted)


@pytest.mark.parametrize("order", list(permutations(["F1", "F3"])))
def test_overlapping_fixes_are_order_independent(order: tuple[str, str]) -> None:
    findings = {f["id"]: f for f in _findings(1)}
    acs = story_acs("TPD-1")
    for fid in order:
        acs = apply_fix_doc(acs, findings[fid]["suggested_doc_text"])
    assert findings["F1"]["suggested_doc_text"] == findings["F3"]["suggested_doc_text"]
    assert "750,00 TL" in acs["AC3"] and "500,00 TL" not in acs["AC3"]
    assert "Kampanyasız" in acs["AC3"]


def test_case_generation_golden_uses_final_document() -> None:
    acs, _ = _run_loop()
    cases = load_golden("case_generation", "TPD-1")["output"]["cases"]
    refs = {r for c in cases for r in c["acceptance_criteria_refs"]}
    assert refs == set(acs)
    min_msg = demo_module("pricing").min_siparis_mesaji(seed_setting("min_siparis_tutari"))
    assert min_msg in acs["AC3"]
    assert any(min_msg in c["expected_result"] for c in cases)
