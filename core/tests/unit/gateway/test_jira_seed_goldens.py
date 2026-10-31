"""Jira'ya giden golden çıktıların jira-sim seed'iyle tutarlılığı (golden sürüklenmesi).

Replay modunda bu çıktılar PO'ya Jira yorumu olarak gider ve portalda gösterilir; seed'deki story
ve bug'larla çelişirlerse demo yanlış hikâye anlatır:

- requirement_review: `ac_ref` story'de gerçekten olan bir AC'yi gösterir; AC'lerin zaten
  tanımladığı bir mesajı soru olarak sormaz.
- TPD-5 (açık Bug, mükerrer adayı): ana demo yolunun (`f2-kod-hatasi`) defect adayını anlatır:
  C3 "6 adet kampanyalı üründe bedava ürün verilmez" bugünkü kodda (`adet // 6`) kırmızıdır. TPD-5
  aynı belirtiyi (6 adet → 1 bedava, 25,00 TL) ve C3'ün beklenenini (bedava 0, 0,00 TL, toplam
  150,00 TL) yazar; bugün geçen 7 adet davranışını hata diye anlatmaz.
- dup_rank (break-campaign): mükerrer aday listesi jira-sim aramasının döndürdüğü kayıtlardan çıkar.

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


def test_break_campaign_dup_candidates_come_from_sim_search(sim: TestClient) -> None:
    hits = _search(sim, DUP_JQL)
    assert "TPD-5" in hits, hits  # seed: kampanya hatasının açık Bug'ı
    out = load_golden("dup_rank", "break-campaign")["output"]
    keys = [c["key"] for c in out["candidates"]]
    assert set(keys) <= set(hits), f"aramada olmayan aday uyduruldu: {set(keys) - set(hits)}"
    assert sorted(c["rank"] for c in out["candidates"]) == list(range(1, len(keys) + 1))


@pytest.mark.parametrize(("path", "golden"), [(p, g) for _, p, g in goldens("dup_rank")])
def test_dup_rank_recommendation_follows_prompt_rule(path: Path, golden: dict) -> None:
    """rules/prompts/dup-rank.md: `link` yalnızca `high` bir aday varsa, link_key o aday."""
    out = golden["output"]
    high = {c["key"] for c in out["candidates"] if c["likelihood"] == "high"}
    if out["recommendation"] == "link":
        assert out["link_key"] in high
    else:
        assert not high and out["link_key"] is None


# ------------------------------------------------------------------ TPD-5 = ana yolun defect'i

# C3'ün (f2-kod-hatasi) beklenen ve bugünkü kodda gerçekleşen değerleri.
C3_TITLE = "6 adet kampanyalı üründe bedava ürün verilmez"
TPD5_EXPECTED = ("bedava 0 adet", "indirim 0,00 TL", "toplam 150,00 TL")
TPD5_ACTUAL = ("bedava 1 adet", "indirim 25,00 TL", "toplam 125,00 TL")
CAMPAIGN_PY = REPO / "demo-app" / "api" / "src" / "demoapp_api" / "campaign.py"


def _c3_case() -> dict:
    cases = load_golden("case_generation", "f2-kod-hatasi/TPD-1")["output"]["cases"]
    return next(c for c in cases if c["title"] == C3_TITLE)


def test_tpd5_describes_the_main_path_6_adet_defect(sim: TestClient) -> None:
    tpd5 = _issue_text(sim, "TPD-5")
    assert "Portakal Gazozu 1L ürününden 6 adet sepete ekle" in tpd5
    for value in TPD5_EXPECTED + TPD5_ACTUAL:
        assert value in tpd5, f"seed TPD-5'te yok: {value}"
    # Bugün geçen davranış (7 adette 1 bedava, C2) hata diye anlatılmaz.
    assert "7 adet sepete ekle" not in tpd5
    assert "Gerçekleşen: indirim tutarı farklı" not in tpd5


def test_tpd5_expected_matches_c3_case_and_actual_matches_todays_code(sim: TestClient) -> None:
    tpd5 = _issue_text(sim, "TPD-5")
    c3 = _c3_case()
    assert "bedava adet 0" in c3["steps"][-1]["expected"]
    for amount in ("indirim 0,00 TL", "toplam 150,00 TL"):
        assert amount in c3["steps"][-1]["expected"] and amount in tpd5, amount
    # Bugünkü kod `adet // 6`: 6 adette 1 bedava (P-001 25,00 TL) → TPD-5'in "gerçekleşen"i.
    assert "return adet // 6" in CAMPAIGN_PY.read_text(encoding="utf-8")
    assert all(value in tpd5 for value in TPD5_ACTUAL)


def test_main_path_dup_search_finds_tpd5(sim: TestClient) -> None:
    # 6 adet bug taslağının özeti de kampanya indirimini anar; arama TPD-5'i döndürür.
    assert "TPD-5" in _search(sim, DUP_JQL)


def test_break_campaign_dup_rank_does_not_claim_tpd5_as_7_adet_duplicate() -> None:
    out = load_golden("dup_rank", "break-campaign")["output"]
    for c in out["candidates"]:
        if c["key"] == "TPD-5":
            assert c["likelihood"] != "high", c
            assert "7 adet" not in c["rationale"], c
