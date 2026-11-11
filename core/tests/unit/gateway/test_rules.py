"""rules/ içeriği: her amaç için prompt + şema + model yüklenir; golden kayıtlar şemaya uyar."""

import json

import pytest
from jsonschema import Draft202012Validator

from tp_core.gateway import load_bundle, load_model_table, load_schema
from tp_core.gateway.config import PurposeConfig

from .conftest import REAL_RULES

PURPOSES = {
    "requirement_review": "requirement-review",
    "consistency_check": "consistency-check",
    "case_generation": "case-generation",
    "verify_and_map": "verify-and-map",
    "triage": "triage",
    "bug_draft": "bug-draft",
    "dup_rank": "dup-rank",
    # Portal asistanı: iki amaç tek prompt paketini paylaşır (AI-ASISTAN-PLANI §6.1).
    "assistant": "assistant",
    "assistant_deep": "assistant",
    # 012 karar tablosu taslağı (ANALIZ §4.1).
    "decision_table_draft": "decision-table-draft",
}


@pytest.mark.parametrize(("purpose", "bundle"), PURPOSES.items())
def test_every_purpose_has_bundle_schema_model(purpose: str, bundle: str) -> None:
    table = load_model_table(REAL_RULES)
    cfg = table.purpose(purpose)
    schema = load_schema(REAL_RULES, purpose)
    Draft202012Validator.check_schema(schema)
    b = load_bundle(REAL_RULES, bundle, schema, cfg)
    assert b.id == bundle and b.version >= 1
    assert "<untrusted" in b.system_prompt  # ortak güvenlik kuralı eklendi
    assert table.price(cfg.model).input > 0


def test_model_classes_per_task() -> None:
    table = load_model_table(REAL_RULES)
    for p in ("requirement_review", "case_generation", "consistency_check", "verify_and_map"):
        assert table.purpose(p).model == "claude-sonnet-5-5"
    for p in ("triage", "bug_draft", "dup_rank", "assistant"):
        assert table.purpose(p).model == "claude-haiku-5-5"
    assert table.purpose("assistant_deep").model == "claude-sonnet-5-5"
    for cfg in table.purposes.values():
        assert 0 <= cfg.params["temperature"] <= 0.2


def test_bundle_hash_changes_with_model_params_and_schema() -> None:
    schema = load_schema(REAL_RULES, "triage")
    base = PurposeConfig("triage", "claude-haiku-5-5", 2048, {"effort": "low"})
    h1 = load_bundle(REAL_RULES, "triage", schema, base).hash
    assert h1 == load_bundle(REAL_RULES, "triage", schema, base).hash
    other_model = PurposeConfig("triage", "claude-sonnet-5-5", 2048, {"effort": "low"})
    other_params = PurposeConfig("triage", "claude-haiku-5-5", 2048, {"effort": "high"})
    other_schema = {**schema, "title": "değişti"}
    assert load_bundle(REAL_RULES, "triage", schema, other_model).hash != h1
    assert load_bundle(REAL_RULES, "triage", schema, other_params).hash != h1
    assert load_bundle(REAL_RULES, "triage", other_schema, base).hash != h1


def test_fewshot_included_in_hash_and_prompt(tmp_path) -> None:
    import shutil

    rules = tmp_path / "rules"
    shutil.copytree(REAL_RULES, rules)
    schema = load_schema(rules, "triage")
    cfg = load_model_table(rules).purpose("triage")
    before = load_bundle(rules, "triage", schema, cfg)
    (rules / "fewshot" / "triage").mkdir(parents=True)
    (rules / "fewshot" / "triage" / "01.json").write_text('{"input": "x", "output": "y"}')
    after = load_bundle(rules, "triage", schema, cfg)
    assert after.hash != before.hash
    assert '<example index="1">' in after.system_prompt


@pytest.mark.parametrize(
    "path", sorted(REAL_RULES.glob("replay/*/golden/*.json")), ids=lambda p: p.name
)
def test_golden_records_match_schema(path) -> None:
    purpose = path.parent.parent.name
    record = json.loads(path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(load_schema(REAL_RULES, purpose))
    assert list(validator.iter_errors(record["output"])) == []
    for step in record.get("steps", []):
        assert set(step) >= {"tool", "args", "result_summary", "allowed"}


def test_golden_coverage_for_demo_story() -> None:
    for purpose in ("requirement_review", "consistency_check", "case_generation"):
        assert (REAL_RULES / "replay" / purpose / "golden" / "TPD-1.json").is_file()


def test_consistency_golden_contains_planted_mismatches() -> None:
    record = json.loads(
        (REAL_RULES / "replay/consistency_check/golden/TPD-1.json").read_text(encoding="utf-8")
    )
    types = {f["type"] for f in record["output"]["findings"]}
    assert types == {"internal_contradiction", "doc_vs_code", "doc_vs_data", "missing_in_code"}


def test_invalid_names_rejected() -> None:
    from tp_core.gateway import GatewayConfigError

    with pytest.raises(GatewayConfigError):
        load_schema(REAL_RULES, "../models")
    cfg = load_model_table(REAL_RULES).purpose("triage")
    with pytest.raises(GatewayConfigError):
        load_bundle(REAL_RULES, "../README", {}, cfg)
