"""REPLAY-MISS politikaları (rules/replay/README.md "Arama sırası").

- Golden'ı olmayan Jira anahtarı (demo sırasında açılan story) nötr REPLAY-MISS alır, iş ölmez.
- Case üretiminde başka dokümanın case'leri asla taslak olarak dönmez (`ReplayNoOutput`).
- 1. tur golden adı uymazsa aynı story'nin sonraki tur golden'ı içerikle eşleşebilir.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from tests.unit.gateway.demo_sources import load_golden
from tp_core.gateway import (
    ALLOWED_AGENT_TOOLS,
    FREE_TEXT_KEY,
    MATCHED,
    MISS_NEUTRAL,
    Gateway,
    ReplayMiss,
    ReplayNoOutput,
    ReplayNotFound,
    ReplayStore,
    golden_name,
    load_schema,
    requirement_block,
)
from tp_core.gateway.config import load_model_table
from tp_core.gateway.replay import MISS_FILE, NO_GOLDEN_REASON
from tp_core.gateway.testing import InMemoryCallRecorder
from tp_core.ports import ModelMessage, ToolSpec

CONSISTENCY_TOOLS = [
    ToolSpec(name=n, description=n, input_schema={"type": "object"})
    for n in sorted(ALLOWED_AGENT_TOOLS["consistency_check"])
]
# TPD-4'ün metni, demo sırasında jira-sim'de açılmış yeni bir anahtarla (TPD-24).
NEW_KEY = "TPD-24"


def _gateway(rules_dir, recorder, *, strict: bool = False) -> Gateway:
    return Gateway(
        provider=None,
        recorder=recorder,
        mode="replay",
        models=load_model_table(rules_dir),
        rules_dir=rules_dir,
        replay_store=ReplayStore(rules_dir / "replay", strict=strict),
        record_extras=True,
    )


def _jira_block(key: str, acs: list[str]) -> list[ModelMessage]:
    block = requirement_block(
        summary="Bayi girişi",
        description="Bayi portala giriş yapabilmelidir.",
        acceptance_criteria=acs,
        jira_key=key,
    )
    return [ModelMessage(role="user", content=block)]


def _free_block(acs: list[str]) -> list[ModelMessage]:
    block = requirement_block(
        summary="Fatura indirme (RV)",
        description="Bayi siparişin faturasını PDF olarak indirebilmelidir.",
        acceptance_criteria=acs,
        requirement_id=str(uuid4()),
    )
    return [ModelMessage(role="user", content=block)]


def _review(gw, rules_dir, key, messages):
    return gw.call(
        "requirement_review",
        "requirement-review",
        messages,
        load_schema(rules_dir, "requirement_review"),
        replay_key={"name": golden_name(key), "jira_key": key},
    )


def _check(gw, rules_dir, key, messages, round_no=1):
    return gw.run_agent(
        "consistency_check",
        "consistency-check",
        messages,
        CONSISTENCY_TOOLS,
        lambda name, args: f"{name} sonucu",
        load_schema(rules_dir, "consistency_check"),
        replay_key={"name": golden_name(key, check_round=round_no), "jira_key": key},
    )


def _cases(gw, rules_dir, key, messages):
    return gw.call(
        "case_generation",
        "case-generation",
        messages,
        load_schema(rules_dir, "case_generation"),
        replay_key={"name": golden_name(key), "jira_key": key},
    )


# ------------------------------------------------------------ golden'ı olmayan Jira anahtarı


def test_unknown_jira_key_review_gets_neutral_replay_miss(rules_dir) -> None:
    recorder = InMemoryCallRecorder()
    gw = _gateway(rules_dir, recorder)
    result = _review(gw, rules_dir, NEW_KEY, _jira_block(NEW_KEY, ["Giriş yapılır."]))
    assert result.mode == "replay_miss"
    neutral = json.loads((rules_dir / "replay/requirement_review" / MISS_FILE).read_text())
    assert result.output == neutral["output"]
    row = recorder.ai_calls[-1]
    assert row["mod"] == "replay_miss" and row["hata"] is None
    assert row["ek"]["replay_kokeni"] == MISS_NEUTRAL
    assert row["ek"]["cikti_kokeni"] == "notr_yedek"
    assert row["ek"]["replay_eslesme"] == [NO_GOLDEN_REASON]
    assert row["ek"]["replay_kaynagi"] == f"requirement_review/{MISS_FILE}"


def test_unknown_jira_key_consistency_check_gets_neutral_replay_miss(rules_dir) -> None:
    recorder = InMemoryCallRecorder()
    gw = _gateway(rules_dir, recorder)
    result = _check(gw, rules_dir, NEW_KEY, _jira_block(NEW_KEY, ["Giriş yapılır."]))
    assert result.mode == "replay_miss"
    assert result.output["findings"] == []
    assert "REPLAY-MISS" in result.output["notes"]
    assert recorder.ai_calls[-1]["ek"]["replay_eslesme"] == [NO_GOLDEN_REASON]


def test_unknown_jira_key_is_still_replay_miss_in_strict_mode(rules_dir) -> None:
    recorder = InMemoryCallRecorder()
    gw = _gateway(rules_dir, recorder, strict=True)
    with pytest.raises(ReplayMiss):
        _review(gw, rules_dir, NEW_KEY, _jira_block(NEW_KEY, ["Giriş yapılır."]))
    assert recorder.ai_calls[-1]["mod"] == "replay_miss"  # denetimde


def test_unknown_key_without_fallback_still_raises_not_found(rules_dir) -> None:
    (rules_dir / "replay" / "triage" / "on_miss.json").unlink()  # iskalama yedeği yok
    gw = _gateway(rules_dir, InMemoryCallRecorder())
    with pytest.raises(ReplayNotFound):
        gw.call(
            "triage",
            "triage",
            [ModelMessage(role="user", content="x")],
            load_schema(rules_dir, "triage"),
            replay_key={"name": "olmayan-senaryo"},
        )


@pytest.mark.parametrize(
    ("purpose", "bundle"), [("bug_draft", "bug-draft"), ("dup_rank", "dup-rank")]
)
def test_defect_purposes_never_return_another_errors_output(rules_dir, purpose, bundle) -> None:
    """Faz 4: bug taslağı ve mükerrer sıralamasının nötr hali yok; golden'sız ad da çıktı vermez."""
    recorder = InMemoryCallRecorder()
    gw = _gateway(rules_dir, recorder)
    with pytest.raises(ReplayNoOutput):
        gw.call(
            purpose,
            bundle,
            [ModelMessage(role="user", content="x")],
            load_schema(rules_dir, purpose),
            replay_key={"name": "olmayan-senaryo"},
        )
    assert recorder.ai_calls[-1]["mod"] == "replay_miss"


def test_triage_without_golden_is_neutral_unknown(rules_dir) -> None:
    result = _gateway(rules_dir, InMemoryCallRecorder()).call(
        "triage",
        "triage",
        [ModelMessage(role="user", content="x")],
        load_schema(rules_dir, "triage"),
        replay_key={"name": "olmayan-senaryo"},
    )
    assert result.mode == "replay_miss" and result.output["class"] == "unknown"


# ------------------------------------------------------------ case üretimi: çıktı yok


def test_case_generation_miss_returns_no_drafts_for_other_free_text(rules_dir) -> None:
    """Fatura indirme metni SERBEST golden'ına (Sepetten ürün çıkarma) düşer ama case'leri
    dönmez: başka özelliğin case'leri taslak olmaz."""
    recorder = InMemoryCallRecorder()
    gw = _gateway(rules_dir, recorder)
    messages = _free_block(['"Fatura indir" butonu görünür.', "PDF iner.", "Dosya adı doğru."])
    with pytest.raises(ReplayNoOutput) as exc:
        _cases(gw, rules_dir, FREE_TEXT_KEY, messages)
    assert "REPLAY-MISS" in str(exc.value) and "canlı model gerekir" in str(exc.value)
    assert isinstance(exc.value, ReplayNotFound)  # özellik şeritleri aynı yoldan ele alır
    assert exc.value.reasons  # neden listesi
    row = recorder.ai_calls[-1]
    assert row["amac"] == "case_generation" and row["mod"] == "replay_miss"
    assert row["cikti"] is None and row["hata"].startswith("ReplayNoOutput")
    assert row["ek"]["replay_eslesme"] == exc.value.reasons


def test_case_generation_miss_for_unknown_jira_key(rules_dir) -> None:
    gw = _gateway(rules_dir, InMemoryCallRecorder())
    with pytest.raises(ReplayNoOutput) as exc:
        _cases(gw, rules_dir, NEW_KEY, _jira_block(NEW_KEY, ["Giriş yapılır."]))
    assert exc.value.reasons == [NO_GOLDEN_REASON]


def test_case_generation_kept_doc_with_old_rule_gets_no_serbest_cases(rules_dir) -> None:
    """Analist AC2'yi '7 adette' bırakırsa (code_defect) SERBEST'in 6-adet case'leri dönmez."""
    golden = load_golden("case_generation", FREE_TEXT_KEY)
    acs = [a.split(": ", 1)[1] for a in golden["input_match"]["acceptance_criteria"]]
    acs[1] = (
        "Kaldırma sonrası kampanya indirimi her 7 adette 1 bedava kuralıyla yeniden hesaplanır."
    )
    block = requirement_block(
        summary="Sepetten ürün çıkarma",
        description=golden["input_match"]["contains"][0]
        if golden["input_match"]["contains"]
        else "",
        acceptance_criteria=acs,
        requirement_id=str(uuid4()),
    )
    gw = _gateway(rules_dir, InMemoryCallRecorder())
    with pytest.raises(ReplayNoOutput):
        _cases(gw, rules_dir, FREE_TEXT_KEY, [ModelMessage(role="user", content=block)])


def test_case_generation_matching_golden_still_replays(rules_dir) -> None:
    golden = load_golden("case_generation", "TPD-4")
    acs = golden["input_match"]["acceptance_criteria"]
    contains = golden["input_match"].get("contains") or []
    block = requirement_block(
        summary="x",
        description="\n\n".join(contains),
        acceptance_criteria=acs,
        jira_key="TPD-4",
    )
    gw = _gateway(rules_dir, InMemoryCallRecorder())
    result = _cases(gw, rules_dir, "TPD-4", [ModelMessage(role="user", content=block)])
    assert result.mode == "replay" and result.output == golden["output"]


def test_invalid_miss_policy_is_config_error(rules_dir) -> None:
    from tp_core.gateway import GatewayConfigError

    (rules_dir / "replay/case_generation" / MISS_FILE).write_text('{"policy": "belki"}')
    gw = _gateway(rules_dir, InMemoryCallRecorder())
    with pytest.raises(GatewayConfigError):
        _cases(gw, rules_dir, NEW_KEY, _jira_block(NEW_KEY, ["Giriş yapılır."]))


# ------------------------------------------------------------ tur golden'ları (TPD-1 → r2)


def _fixed_tpd1() -> list[ModelMessage]:
    golden = load_golden("consistency_check", "TPD-1-r2")
    spec = golden["input_match"]
    block = requirement_block(
        summary="Sepete ekleme ve sipariş onayı",
        description="\n\n".join(spec.get("contains") or []),
        acceptance_criteria=spec["acceptance_criteria"],
        jira_key="TPD-1",
    )
    return [ModelMessage(role="user", content=block)]


def test_round_one_on_already_fixed_tpd1_matches_r2_golden(rules_dir) -> None:
    """`make reset` olmadan ikinci koşu: jira-sim düzeltilmiş TPD-1'i tutar; 1. tur r2'ye uyar."""
    recorder = InMemoryCallRecorder()
    gw = _gateway(rules_dir, recorder, strict=True)
    result = _check(gw, rules_dir, "TPD-1", _fixed_tpd1(), round_no=1)
    assert result.mode == "replay"
    assert result.output == load_golden("consistency_check", "TPD-1-r2")["output"]
    row = recorder.ai_calls[0]
    assert row["ek"]["replay_kokeni"] == MATCHED
    assert row["ek"]["replay_kaynagi"] == "consistency_check/golden/TPD-1-r2.json"


def test_round_lookup_never_falls_back_to_earlier_round(rules_dir) -> None:
    store = ReplayStore(rules_dir / "replay")
    assert store._later_rounds("consistency_check", "TPD-1-r2") == []
    assert store._later_rounds("verify_and_map", "TPD-1-C1") == []
    names = [n for n, _ in store._later_rounds("consistency_check", "TPD-1")]
    assert names == ["TPD-1-r2"]
    # TPD-1 öneki TPD-10/TPD-1x golden'larını kapsamaz
    (rules_dir / "replay/consistency_check/golden/TPD-10-r2.json").write_text(
        json.dumps({"output": {"findings": [], "notes": ""}})
    )
    assert [n for n, _ in store._later_rounds("consistency_check", "TPD-1")] == ["TPD-1-r2"]
