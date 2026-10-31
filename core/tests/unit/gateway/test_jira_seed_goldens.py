"""Jira'ya giden golden çıktıların jira-sim seed'iyle tutarlılığı (golden sürüklenmesi).

Replay modunda bu çıktılar PO'ya Jira yorumu olarak gider ve portalda gösterilir; seed'deki story
ve bug'larla çelişirlerse demo yanlış hikâye anlatır:

- requirement_review: `ac_ref` story'de gerçekten olan bir AC'yi gösterir; AC'lerin zaten
  tanımladığı bir mesajı soru olarak sormaz.
- dup_rank (break-campaign): §2 adım 12–13'te mükerrer kontrolü, jira-sim seed'inin bug taslağı
  için döndürdüğü açık Bug'ı (TPD-5) aday gösterir ve "mevcut kayda bağla" önerir.

jira-sim süreç içinde (ağsız) koşar; arama gerçek JQL değerlendiricisinden geçer.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.unit.gateway.demo_sources import REPO, goldens, load_golden

SIM_SRC = REPO / "sims" / "jira-sim" / "src"
if str(SIM_SRC) not in sys.path:
    sys.path.insert(0, str(SIM_SRC))

from jira_sim.app import create_app  # noqa: E402

BASE = "http://jira-sim:8090"
READER = ("reader@sim.local", "t")
QUOTED = re.compile(r'"([^"]+)"')


@pytest.fixture(scope="module")
def sim() -> Iterator[TestClient]:
    with TestClient(create_app(data_path="", base_url=BASE), base_url=BASE) as client:
        yield client


def _search(sim: TestClient, jql: str) -> dict[str, str]:
    r = sim.get(
        "/rest/api/3/search/jql",
        params={"jql": jql, "fields": ["summary", "description"], "maxResults": 100},
        auth=READER,
    )
    assert r.status_code == 200, r.text
    return {i["key"]: i["fields"]["summary"] for i in r.json()["issues"]}


def _adf_text(node: object) -> str:
    if isinstance(node, dict):
        own = node.get("text", "")
        return own + "".join(_adf_text(c) for c in node.get("content", []) or [])
    if isinstance(node, list):
        return "".join(_adf_text(c) for c in node)
    return ""


def _issue_text(sim: TestClient, key: str) -> str:
    r = sim.get(f"/rest/api/3/issue/{key}", params={"fields": "description"}, auth=READER)
    assert r.status_code == 200, r.text
    return _adf_text(r.json()["fields"]["description"])


def _story_acs(sim: TestClient, key: str) -> dict[str, str]:
    """{"AC1": "metin", ...}: seed açıklamasındaki kabul kriterleri."""
    text = _issue_text(sim, key)
    return dict(re.findall(r"(AC\d+): ?([^\n]*?)(?=AC\d+:|$)", text, re.DOTALL))


# ------------------------------------------------------------------ requirement_review

# Jira story golden'ları (serbest metin golden'ı `SERBEST` Jira'da yok; aynı kural aşağıda onun
# girdi beyanına karşı denetlenir).
REVIEWS = [r for r in goldens("requirement_review") if r[1].stem.startswith("TPD-")]


@pytest.mark.parametrize(
    ("path", "golden"), [(p, g) for _, p, g in REVIEWS], ids=[p.stem for _, p, _ in REVIEWS]
)
def test_review_questions_respect_seed_acs(sim: TestClient, path: Path, golden: dict) -> None:
    acs = _story_acs(sim, path.stem)
    defined_messages = {m for text in acs.values() for m in QUOTED.findall(text)}
    for q in golden["output"]["questions"]:
        if q["ac_ref"] is not None:
            assert q["ac_ref"] in acs, f"{path.stem}/{q['id']}: {q['ac_ref']} story'de yok"
        if q["type"] in ("ambiguity", "conflict", "untestable"):
            assert q["ac_ref"] is not None, f"{path.stem}/{q['id']}: hangi AC belirsiz?"
        # AC'nin zaten tanımladığı bir mesajı "eksik" diye sormaz.
        asked = set(QUOTED.findall(q["text"]))
        if q["type"] == "missing_ac":
            assert not asked & defined_messages, f"{path.stem}/{q['id']}: AC'de zaten var"


def test_free_text_review_questions_respect_declared_acs() -> None:
    golden = load_golden("requirement_review", "SERBEST")
    acs = {a.split(":", 1)[0] for a in golden["input_match"]["acceptance_criteria"]}
    for q in golden["output"]["questions"]:
        assert q["ac_ref"] is None or q["ac_ref"] in acs, q
        if q["type"] in ("ambiguity", "conflict", "untestable"):
            assert q["ac_ref"] is not None, q


def test_tpd3_review_does_not_ask_what_ac2_specifies(sim: TestClient) -> None:
    acs = _story_acs(sim, "TPD-3")
    assert "Ürün bulunamadı" in acs["AC2"]  # seed: sonuç yoksa mesaj tanımlı
    questions = load_golden("requirement_review", "TPD-3")["output"]["questions"]
    for q in questions:
        assert not re.search(r"bulunamad|hangi mesaj", q["text"], re.IGNORECASE), q["text"]
    q1 = questions[0]
    assert (q1["type"], q1["ac_ref"]) == ("ambiguity", "AC1")


# ------------------------------------------------------------------ dup_rank (break-campaign)

# Bug taslağı için mükerrer araması (§8.12): proje içindeki açık Bug'larda taslak özetinin
# anahtar terimleriyle JQL metin araması.
DUP_TERMS = "kampanya indirimi"
DUP_JQL = f'project = TPD AND issuetype = Bug AND statusCategory != Done AND text ~ "{DUP_TERMS}"'


def test_dup_search_terms_come_from_the_bug_draft() -> None:
    summary = load_golden("bug_draft", "break-campaign")["output"]["summary"]
    assert DUP_TERMS in summary.lower()


def test_break_campaign_dup_rank_matches_sim_seed(sim: TestClient) -> None:
    hits = _search(sim, DUP_JQL)
    assert "TPD-5" in hits, hits  # seed: kampanya hatasının açık Bug'ı
    out = load_golden("dup_rank", "break-campaign")["output"]
    keys = [c["key"] for c in out["candidates"]]
    assert keys, "seed bir aday döndürüyor; golden boş aday listesi veremez"
    assert set(keys) <= set(hits), f"aramada olmayan aday uyduruldu: {set(keys) - set(hits)}"
    assert "TPD-5" in keys
    assert sorted(c["rank"] for c in out["candidates"]) == list(range(1, len(keys) + 1))
    assert (out["recommendation"], out["link_key"]) == ("link", "TPD-5")


@pytest.mark.parametrize(("path", "golden"), [(p, g) for _, p, g in goldens("dup_rank")])
def test_dup_rank_recommendation_follows_prompt_rule(path: Path, golden: dict) -> None:
    """rules/prompts/dup-rank.md: `link` yalnızca `high` bir aday varsa, link_key o aday."""
    out = golden["output"]
    high = {c["key"] for c in out["candidates"] if c["likelihood"] == "high"}
    if out["recommendation"] == "link":
        assert out["link_key"] in high
    else:
        assert not high and out["link_key"] is None


def test_break_campaign_dup_rationale_names_signals_in_tpd5(sim: TestClient) -> None:
    tpd5 = _issue_text(sim, "TPD-5")
    cand = next(
        c
        for c in load_golden("dup_rank", "break-campaign")["output"]["candidates"]
        if c["key"] == "TPD-5"
    )
    for signal in ("Portakal Gazozu 1L", "7 adet", "25,00 TL"):
        assert signal in tpd5, f"seed TPD-5'te yok: {signal}"
        assert signal in cand["rationale"], f"gerekçede yok: {signal}"
