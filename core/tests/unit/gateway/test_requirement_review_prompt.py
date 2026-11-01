"""requirement-review v3 sözleşmesi: `missing_ac` story'deki somut bir cümleye dayanır; story'nin
anmadığı genel güvenlik/oturum/kilitleme konuları soru olmaz (temiz TPD-4 → `ready`).

v2 canlıda (3/3 koşu) TPD-4'te hesap kilitleme, boş kullanıcı adı, pasif hesap, oturum zaman aşımı,
çıkış soruları üretip `needs_po` döndürdü; değerlendirme seti 4/5'te kaldı. v3 canlıda art arda
4 koşuda 5/5 geçti (TPD-4 `ready`). Bu test prompt metnindeki kuralların, sürüm kaydının, setin ve
golden'ın birbirinden kopmamasını zorlar (canlı davranışı `make eval-live` doğrular).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from tp_core.gateway.bundle import parse_prompt_file
from tp_core.gateway.eval_set import load_set

RULES = Path(__file__).resolve().parents[4] / "rules"
PROMPT = RULES / "prompts" / "requirement-review.md"


def _prompt() -> tuple[dict, str]:
    meta, body = parse_prompt_file(PROMPT.read_text(encoding="utf-8"), PROMPT)
    return meta, " ".join(body.split())  # satır kırılımından bağımsız


def test_prompt_is_v3_or_later() -> None:
    meta, _ = _prompt()
    assert meta["id"] == "requirement-review"
    assert int(meta["version"]) >= 3


def test_missing_ac_must_be_anchored_in_story_text() -> None:
    _, body = _prompt()
    assert "concrete sentence" in body
    assert "If you cannot point to one, drop the question." in body
    # AC'siz story (TPD-2) yine missing_ac: açıklamaya dayanır.
    assert "no acceptance criteria at all is always `missing_ac`" in body


def test_generic_topics_the_story_never_mentions_are_excluded() -> None:
    _, body = _prompt()
    scope = body[body.index("Scope (what is NOT a question)") : body.index(" Rules:")]
    # v2'nin canlıda TPD-4'e eklediği konular açıkça kapsam dışı.
    for topic in ("account lockout", "session", "timeout", "logout", "empty", "passive accounts"):
        assert topic in scope, topic
    # Yalnızca özette, kapsam dışı fikir olarak; karara etki etmez.
    assert "`summary`" in scope


def test_only_conflict_and_missing_ac_change_ready_verdict() -> None:
    _, body = _prompt()
    assert "`ready` only when there are no `conflict` or `missing_ac` questions" in body
    assert "`ambiguity` and `untestable` questions alone do not change a `ready` verdict" in body


def test_versions_in_sync_across_record_set_and_readme() -> None:
    meta, _ = _prompt()
    version = int(meta["version"])
    records = yaml.safe_load((RULES / "evaluations.yaml").read_text(encoding="utf-8"))
    assert records["bundles"]["requirement-review"]["version"] == version
    assert load_set(RULES, "requirement-review")["version"] == version
    readme = (RULES / "README.md").read_text(encoding="utf-8")
    assert f"| `requirement-review` | v{version} |" in readme


def test_clean_story_tpd4_expected_ready_in_set_and_golden() -> None:
    data = load_set(RULES, "requirement-review")
    case = next(c for c in data["cases"] if c["id"] == "tpd-4")
    assert case["expect"]["verdict"] == "ready"
    golden = json.loads(
        (RULES / "replay" / "requirement_review" / "golden" / "TPD-4.json").read_text("utf-8")
    )
    assert golden["output"]["verdict"] == "ready"
    assert not any(q["type"] in ("missing_ac", "conflict") for q in golden["output"]["questions"])
