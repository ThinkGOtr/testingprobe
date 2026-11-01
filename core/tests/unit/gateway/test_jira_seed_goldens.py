"""Jira'ya giden golden çıktıların jira-sim seed'iyle tutarlılığı (golden sürüklenmesi).

Replay modunda bu çıktılar PO'ya Jira yorumu olarak gider ve portalda gösterilir; seed'deki story
ve bug'larla çelişirlerse demo yanlış hikâye anlatır:

- requirement_review: `ac_ref` story'de gerçekten olan bir AC'yi gösterir; AC'lerin zaten
  tanımladığı bir mesajı soru olarak sormaz.
- TPD-5 (açık Bug, mükerrer adayı): ana demo yolunun (`f2-kod-hatasi`) defect adayını anlatır:
  C3 "6 adet kampanyalı üründe bedava ürün verilmez" bugünkü kodda (`adet // 6`) kırmızıdır. TPD-5
  aynı belirtiyi (6 adet → 1 bedava, 25,00 TL) ve C3'ün beklenenini (bedava 0, 0,00 TL, toplam
  150,00 TL) yazar; bugün geçen 7 adet davranışını hata diye anlatmaz.
- dup_rank (Faz 4): golden'ların aday kümeleri jira-sim aramasının döndürdüğü kümelerdir (açık
  Bug'lar; kapalı TPD-7 yok); C3 ve F2 TPD-5'e bağlanır, kırma koşusu (ters belirti) bağlanmaz.

jira-sim süreç içinde (ağsız) koşar; arama gerçek JQL değerlendiricisinden geçer.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.unit.gateway import defect_inputs as di
from tests.unit.gateway.demo_sources import REPO, goldens, load_golden, scenario_goldens

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


# ------------------------------------------------------------------ dup_rank (Faz 4)

# Mükerrer araması (§8.12): proje içindeki AÇIK Bug'lar. Golden'ların iki aday kümesi iki arama
# biçimine karşılık gelir: hata imzasından bir terimle metin araması (yalnızca TPD-5) ya da tüm
# açık Bug'lar (TPD-5, TPD-6). Kapalı TPD-7 hiçbirinde aday olmaz.
OPEN_BUGS = "project = TPD AND issuetype = Bug AND statusCategory != Done"
DUP_JQL = f'{OPEN_BUGS} AND text ~ "kampanya"'
DUP_GOLDENS = [*goldens("dup_rank"), *scenario_goldens("dup_rank")]


def test_defect_inputs_use_the_same_text_search() -> None:
    assert DUP_JQL == di.DUP_JQL


def test_candidate_sets_of_the_goldens_are_what_sim_search_returns(sim: TestClient) -> None:
    sets = {
        tuple(sorted(_search(sim, DUP_JQL))),
        tuple(sorted(_search(sim, OPEN_BUGS))),
    }
    assert sets == {("TPD-5",), ("TPD-5", "TPD-6")}, sets
    for _, path, golden in DUP_GOLDENS:
        spec = golden["input_match"]["candidates"]
        declared = {*spec["required"], *spec["optional"]}
        for keys in sets:
            # Seed'in her arama sonucu beyana uyar: zorunlular kümede, küme beyanın içinde.
            assert set(spec["required"]) <= set(keys) <= declared, (path, keys)
        assert {c["key"] for c in golden["output"]["candidates"]} == declared


def test_seed_candidate_text_matches_the_dup_input_builder(sim: TestClient) -> None:
    """Golden girdisindeki aday metni (`di.seed_bug`) jira-sim REST'inin döndürdüğüyle aynı."""
    r = sim.get(
        "/rest/api/3/issue/TPD-5",
        params={"fields": "summary,description,status,issuetype"},
        auth=READER,
    )
    assert r.status_code == 200, r.text
    from tp_core.integrations.jira import issue_from_json

    assert issue_from_json(r.json()).model_dump(exclude={"updated"}) == di.seed_bug(
        "TPD-5"
    ).model_dump(exclude={"updated"})


@pytest.mark.parametrize(("path", "golden"), [(p, g) for _, p, g in DUP_GOLDENS])
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
    assert "TPD-5" in _search(sim, DUP_JQL)


def test_break_dup_rank_does_not_claim_tpd5_as_7_adet_duplicate() -> None:
    for name in ("kirma-kampanya/HATA",):
        out = load_golden("dup_rank", name)["output"]
        tpd5 = next(c for c in out["candidates"] if c["key"] == "TPD-5")
        assert tpd5["rank"] == 1 and tpd5["likelihood"] == "medium", tpd5
        assert out["recommendation"] == "new"


def test_main_path_and_f2_dup_rank_link_tpd5(sim: TestClient) -> None:
    """C3 ve F2 aynı hatayı anlatır (6 adette 1 bedava); TPD-5 de: bağla önerilir."""
    tpd5 = _issue_text(sim, "TPD-5")
    assert "6 adet" in tpd5
    for name in ("HATA", "f2-kampanya/HATA"):
        out = load_golden("dup_rank", name)["output"]
        assert out["candidates"][0]["key"] == "TPD-5"
        assert out["candidates"][0]["likelihood"] == "high"
        assert (out["recommendation"], out["link_key"]) == ("link", "TPD-5")


def test_c3_bug_draft_values_are_tpd5_values(sim: TestClient) -> None:
    """C3 taslağının beklenen değerleri TPD-5'in beklenenidir (aynı hata, bağlanabilir)."""
    tpd5 = _issue_text(sim, "TPD-5")
    out = load_golden("bug_draft", "HATA")["output"]
    for value in ("bedava adet 0", "indirim 0,00 TL", "toplam 150,00 TL"):
        assert value in out["expected"]
    for value in ("indirim 0,00 TL", "toplam 150,00 TL"):
        assert value in tpd5


# ------------------------------------------------------------------ demo sırasında açılan Bug'lar

WRITER = ("writer@sim.local", "t")


def _create_bug(client: TestClient, golden: str) -> str:
    """publish_bug'ın "Yeni kayıt"ı: golden taslağın özeti ve bugs şeridinin ADF açıklaması
    (adımlar, beklenen, gerçekleşen, ortam: arama terimleri bu metne de çarpar)."""
    from tp_core.features.bugs.content import description_adf

    icerik = load_golden("bug_draft", golden)["output"]
    r = client.post(
        "/rest/api/3/issue",
        json={
            "fields": {
                "project": {"key": "TPD"},
                "issuetype": {"name": "Bug"},
                "summary": icerik["summary"],
                "description": description_adf(
                    icerik,
                    draft_label="bug-taslagi",
                    onaylayan="testci",
                    mod_etiketi="REPLAY",
                    icerik_hash="0" * 64,
                    zincir_hash=None,
                ),
                "labels": ["AI-generated"],
            }
        },
        auth=WRITER,
    )
    assert r.status_code == 201, r.text
    return str(r.json()["key"])


def _production_search(client: TestClient, texts: list[str]) -> list:
    """bugs şeridinin araması: `jql.key_terms` + `duplicate_search_jql`, açık Bug'lar."""
    from tp_core.features.bugs import jql
    from tp_core.integrations.jira import issue_from_json

    query = jql.duplicate_search_jql("TPD", jql.key_terms(texts))
    assert query is not None
    r = client.get(
        "/rest/api/3/search/jql",
        params={
            "jql": query,
            "fields": ["summary", "description", "status", "issuetype"],
            "maxResults": 100,
        },
        auth=READER,
    )
    assert r.status_code == 200, r.text
    issues = [issue_from_json(i) for i in r.json()["issues"]]
    return [i for i in issues if i.issue_type == "Bug" and i.status != "Done"]


def test_f4_and_break_published_as_new_keep_tpd5_ranked_first_for_c3_and_f2(
    rules_dir: Path,
) -> None:
    """Sahne sırası serbest: F4 "Yeni kayıt" (canlıda TPD-8) ve kırma "Yeni kayıt" önce
    yayımlansa da C3 ve F2 sıralaması REPLAY'dir; TPD-5 AI gerekçesiyle ilk, öneri bağla. Kırma
    koşusunun tekrarında önceki kırma Bug'ı aynı belirti olarak önerilir."""
    from tp_core.gateway import (
        Gateway,
        ReplayStore,
        defect_replay_key,
        dup_rank_messages,
        dup_rank_problems,
        load_schema,
    )
    from tp_core.gateway.config import load_model_table
    from tp_core.gateway.testing import InMemoryCallRecorder

    gw = Gateway(
        provider=None,
        recorder=InMemoryCallRecorder(),
        mode="replay",
        models=load_model_table(rules_dir),
        rules_dir=rules_dir,
        replay_store=ReplayStore(rules_dir / "replay", strict=True),
    )

    def rank(sources: list[str], cands: list) -> dict:
        msgs = dup_rank_messages(
            sources, draft={"summary": "taslak", "story_key": "TPD-1"}, candidates=cands
        )
        out = gw.call(
            "dup_rank",
            "dup-rank",
            msgs,
            load_schema(rules_dir, "dup_rank"),
            replay_key=defect_replay_key("TPD-1"),
        ).output
        assert dup_rank_problems(out, cands) == []
        return out

    c3 = _c3_case()
    ac2 = di.story_ac("AC2")
    c3_texts = [ac2, C3_TITLE, c3["steps"][-1]["expected"], C3_TITLE]
    f2 = di.finding_kwargs("TPD-1", "F2")
    f2_texts = [ac2, f2["claim"], f2["doc_text"], f2["observed"]]
    with TestClient(create_app(data_path="", base_url=BASE), base_url=BASE) as fresh:
        f4_key = _create_bug(fresh, "f4-kredi-limiti/HATA")
        for sources, texts in (
            (di.c3_sources(), c3_texts),
            (di.finding_sources("TPD-1", "F2"), f2_texts),
        ):
            cands = _production_search(fresh, texts)
            keys = {c.key for c in cands}
            # Canlı yığındaki durum: genel terimler ('adette' …) yeni F4 Bug'ına da çarpar.
            assert {"TPD-5", f4_key} <= keys
            out = rank(sources, cands)
            assert out["candidates"][0]["key"] == "TPD-5"
            assert out["candidates"][0]["likelihood"] == "high"
            assert (out["recommendation"], out["link_key"]) == ("link", "TPD-5")
            assert {c["key"] for c in out["candidates"]} == keys
            f4 = next(c for c in out["candidates"] if c["key"] == f4_key)
            assert f4["likelihood"] == "low"

        # Kırma koşusu "Yeni kayıt" → yayımlandı; sonraki kırma koşusu onu önerir, C3 yine TPD-5.
        kirma_key = _create_bug(fresh, "kirma-kampanya/HATA")
        cands = _production_search(fresh, c3_texts)
        assert rank(di.c3_sources(), cands)["link_key"] == "TPD-5"
        break_texts = [ac2, di.C2_TITLE, "7 adet Portakal Gazozu bedava adet"]
        cands = _production_search(fresh, break_texts)
        out = rank(di.break_sources(0), cands)
        assert kirma_key in {c.key for c in cands}
        assert (out["recommendation"], out["link_key"]) == ("link", kirma_key)
        tpd5 = next(c for c in out["candidates"] if c["key"] == "TPD-5")
        assert tpd5["likelihood"] == "medium"
