"""Sprint otomasyonu (specs/013 §3.4): "QA To Do" durumu, gerçek Jira biçiminde geçiş uçları ve
tırnaklı/boşluklu durum adıyla JQL araması."""

from __future__ import annotations

from fastapi.testclient import TestClient

from jira_sim import jql

from .conftest import READER, WRITER


def _ara(client: TestClient, q: str) -> set[str]:
    r = client.post("/rest/api/3/search/jql", json={"jql": q, "fields": ["status"]}, auth=READER)
    assert r.status_code == 200, r.text
    return {i["key"] for i in r.json()["issues"]}


def test_story_qa_to_do_ya_tasinir_ve_jql_ile_bulunur(client: TestClient) -> None:
    sorgu = 'project = TPD AND issuetype = Story AND status = "QA To Do" ORDER BY key ASC'
    assert _ara(client, sorgu) == set()
    ts = client.get("/rest/api/3/issue/TPD-3/transitions", auth=READER).json()["transitions"]
    qa = next(t for t in ts if t["to"]["name"] == "QA To Do")
    assert qa["name"] == "QA To Do" and qa["to"]["statusCategory"]["key"] == "indeterminate"
    r = client.post(
        "/rest/api/3/issue/TPD-3/transitions", json={"transition": {"id": qa["id"]}}, auth=WRITER
    )
    assert r.status_code == 204, r.text
    f = client.get("/rest/api/3/issue/TPD-3", auth=READER).json()["fields"]
    assert f["status"]["name"] == "QA To Do"
    assert f["status"]["statusCategory"]["key"] == "indeterminate"
    assert _ara(client, sorgu) == {"TPD-3"}
    assert _ara(client, "project = TPD AND status = 'qa to do'") == {"TPD-3"}
    assert "TPD-3" not in _ara(client, "project = TPD AND status = QA")  # tırnaksız: tek kelime
    assert "TPD-3" in _ara(client, "project = TPD AND statusCategory = indeterminate")
    # Artık QA To Do'da: aynı geçiş listede yok, tekrar denemek 400.
    ts2 = client.get("/rest/api/3/issue/TPD-3/transitions", auth=READER).json()["transitions"]
    assert all(t["to"]["name"] != "QA To Do" for t in ts2)
    r = client.post(
        "/rest/api/3/issue/TPD-3/transitions", json={"transition": {"id": qa["id"]}}, auth=WRITER
    )
    assert r.status_code == 400


def test_jql_kacisli_durum_adi() -> None:
    d = {"key": ["TPD-1", "1"], "status": ['QA "Hazır" \\ To Do']}
    assert jql.parse(r'status = "QA \"Hazır\" \\ To Do"').predicate(d)
    assert not jql.parse('status = "QA To Do"').predicate(d)
