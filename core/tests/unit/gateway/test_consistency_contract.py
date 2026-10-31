"""consistency_check çıktı sözleşmesi: `doc_ref` ve `suggested_doc_text` biçimi.

Deterministik kod iki kurala dayanır (features/requirements/content.py):
- `doc_ref_valid` yalnızca `AC<n>` ya da açıklama referansını tanır; başka biçim bulguyu
  "doğrulanamaz" diye düşürür.
- `parse_fix_text` ilk `ACn:` satırından önceki metni AÇIKLAMA hedefi sayar; öneksiz bir AC
  önerisi story açıklamasının üzerine yazılır.
Model bu kuralları yalnızca yönergeden ve şemadan görür; burada ikisinin de sözleşmeyi taşıdığı
ve golden'ların ona uyduğu doğrulanır.
"""

from __future__ import annotations

import copy
import re

import pytest
from anthropic import transform_schema
from jsonschema import Draft202012Validator

from tests.unit.gateway.demo_sources import RULES, goldens
from tp_core.gateway import load_schema
from tp_core.gateway.bundle import parse_prompt_file
from tp_core.gateway.providers.anthropic_provider import strip_meta

PROMPT = RULES / "prompts" / "consistency-check.md"
AC_LINE = re.compile(r"^AC([1-9][0-9]*): \S")
AC_REF = re.compile(r"AC([1-9][0-9]*)")


def _schema() -> dict:
    return load_schema(RULES, "consistency_check")


def _finding(**over) -> dict:
    base = {
        "id": "F1",
        "type": "doc_vs_code",
        "doc_ref": "AC2",
        "claim": "c",
        "observed": "o",
        "evidence": [],
        "severity": "warning",
        "suggested_doc_text": None,
    }
    base.update(over)
    return {"findings": [base], "notes": ""}


def test_prompt_states_doc_ref_and_fix_text_format() -> None:
    meta, body = parse_prompt_file(PROMPT.read_text(encoding="utf-8"), PROMPT)
    assert meta["version"] >= 4
    for needle in ("`AC<n>`", "` ↔ `", "`Açıklama`", "starting with `AC<n>: `", "`null`"):
        assert needle in body, needle


@pytest.mark.parametrize(
    "ref", ["AC1", "AC3 ↔ AC6", "AC1, AC2", "Açıklama", "Açıklama ↔ AC2", "AC3 ↔ AC6 ↔ AC9"]
)
def test_schema_accepts_contract_doc_refs(ref: str) -> None:
    errors = list(Draft202012Validator(_schema()).iter_errors(_finding(doc_ref=ref)))
    assert not errors


@pytest.mark.parametrize(
    "ref", ["Kabul kriteri 3", "3. kabul kriteri", "AC0", "ac3", "AC3-AC6", "AC3 ve AC6", ""]
)
def test_schema_rejects_other_doc_refs(ref: str) -> None:
    errors = list(Draft202012Validator(_schema()).iter_errors(_finding(doc_ref=ref)))
    assert errors


def test_schema_rejects_empty_fix_text() -> None:
    assert list(Draft202012Validator(_schema()).iter_errors(_finding(suggested_doc_text="")))


def test_descriptions_reach_the_api_schema() -> None:
    sent = transform_schema(strip_meta(copy.deepcopy(_schema())))
    props = sent["properties"]["findings"]["items"]["properties"]
    assert "AC<n>" in props["doc_ref"]["description"]
    assert "AC<n>: " in props["suggested_doc_text"]["description"]


@pytest.mark.parametrize(
    "name,finding",
    [
        (f"{p.stem}:{f['id']}", f)
        for _, p, g in goldens("consistency_check")
        for f in g["output"]["findings"]
    ],
)
def test_golden_findings_follow_the_contract(name: str, finding: dict) -> None:
    text = finding["suggested_doc_text"]
    if text is None:
        return
    lines = [s.strip() for s in text.splitlines() if s.strip()]
    refs = set(AC_REF.findall(finding["doc_ref"]))
    ac_lines = [AC_LINE.match(s) for s in lines]
    # Açıklama metni (öneksiz) yalnızca doc_ref açıklamayı adlandırıyorsa ve AC satırlarından önce.
    first_ac = next((i for i, m in enumerate(ac_lines) if m), len(lines))
    assert all(ac_lines[first_ac:]), f"{name}: AC satırından sonra öneksiz satır"
    if first_ac:
        assert "Açıklama" in finding["doc_ref"], f"{name}: öneksiz metin açıklamanın üzerine yazar"
    assert {m.group(1) for m in ac_lines if m} <= refs, f"{name}: doc_ref dışı AC"
