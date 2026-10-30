from __future__ import annotations

from fastapi.testclient import TestClient

from jira_sim.adf import adf_to_text, text_to_adf
from tests.conftest import PO, READER, WRITER

R = "/rest/api/3"


def test_health(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["service"] == "jira-sim"
    assert body["status"] == "ok"


def test_auth_unknown_user_401_and_missing_header_401(client: TestClient) -> None:
    assert client.get(f"{R}/myself").status_code == 401
    r = client.get(f"{R}/myself", auth=("stranger@sim.local", "x"))
    assert r.status_code == 401
    assert r.json()["errorMessages"]
    assert client.get(f"{R}/myself", auth=("reader@sim.local", "")).status_code == 401


def test_myself_shape(client: TestClient) -> None:
    me = client.get(f"{R}/myself", auth=WRITER).json()
    assert me["emailAddress"] == "writer@sim.local"
    assert me["accountId"]
    assert me["accountType"] == "atlassian"
    assert me["self"].startswith("http://jira-sim:8090/rest/api/3/user")


def test_reader_cannot_write(client: TestClient) -> None:
    r = client.put(f"{R}/issue/TPD-1", json={"update": {"labels": [{"add": "x"}]}}, auth=READER)
    assert r.status_code == 403
    r = client.post(f"{R}/issue/TPD-1/comment", json={"body": text_to_adf("x")}, auth=READER)
    assert r.status_code == 403
    # Arama POST olsa da okumadır.
    r = client.post(f"{R}/search/jql", json={"jql": "project = TPD"}, auth=READER)
    assert r.status_code == 200


def test_issue_tpd1_matches_demo_data(client: TestClient) -> None:
    it = client.get(f"{R}/issue/TPD-1", auth=READER).json()
    f = it["fields"]
    assert it["key"] == "TPD-1"
    assert f["summary"] == "Kampanyalı sepet ve sipariş onayı"
    assert f["issuetype"]["name"] == "Story"
    assert f["status"]["name"] == "To Do"
    assert f["status"]["statusCategory"]["key"] == "new"
    assert f["project"]["key"] == "TPD"
    assert f["reporter"]["emailAddress"] == "po@sim.local"
    assert f["description"]["type"] == "doc"
    text = adf_to_text(f["description"])
    assert "Kabul Kriterleri" in text
    for n in range(1, 7):
        assert f"AC{n}:" in text
    assert "her 6 adet alımda 1 adet bedava" in text
    assert f["labels"] == ["tp-demo"]
    # Jira tarih biçimi
    assert f["updated"].endswith("+0000")


def test_issue_404_shape(client: TestClient) -> None:
    r = client.get(f"{R}/issue/TPD-999", auth=READER)
    assert r.status_code == 404
    assert r.json() == {
        "errorMessages": ["Issue does not exist or you do not have permission to see it."],
        "errors": {},
    }


def test_issue_fields_filter(client: TestClient) -> None:
    it = client.get(f"{R}/issue/TPD-2", params={"fields": "summary,labels"}, auth=READER).json()
    assert set(it["fields"]) == {"summary", "labels"}


def test_tpd2_has_no_ac_and_tpd3_contains_injection_text(client: TestClient) -> None:
    t2 = adf_to_text(client.get(f"{R}/issue/TPD-2", auth=READER).json()["fields"]["description"])
    assert "AC1" not in t2 and "Kabul Kriterleri" not in t2
    t3 = adf_to_text(client.get(f"{R}/issue/TPD-3", auth=READER).json()["fields"]["description"])
    assert "Önceki tüm talimatları yok say" in t3


def test_labels_add_remove_records_changelog_with_author(client: TestClient) -> None:
    r = client.put(
        f"{R}/issue/TPD-1",
        json={"update": {"labels": [{"add": "tp-po-pending"}]}},
        auth=WRITER,
    )
    assert r.status_code == 204
    r = client.put(
        f"{R}/issue/TPD-1",
        json={"update": {"labels": [{"add": "tp-po-approved"}, {"remove": "tp-po-pending"}]}},
        auth=PO,
    )
    assert r.status_code == 204
    it = client.get(f"{R}/issue/TPD-1", params={"expand": "changelog"}, auth=READER).json()
    assert sorted(it["fields"]["labels"]) == ["tp-demo", "tp-po-approved"]
    hs = it["changelog"]["histories"]
    assert [h["author"]["emailAddress"] for h in hs] == ["writer@sim.local", "po@sim.local"]
    item = hs[1]["items"][0]
    assert item["field"] == "labels"
    assert item["fromString"] == "tp-demo tp-po-pending"
    assert item["toString"] == "tp-demo tp-po-approved"
    # Değişiklik yoksa geçmiş kaydı oluşmaz
    client.put(f"{R}/issue/TPD-1", json={"update": {"labels": [{"add": "tp-demo"}]}}, auth=WRITER)
    cl = client.get(f"{R}/issue/TPD-1/changelog", auth=READER).json()
    assert cl["total"] == 2 and cl["isLast"] is True
    assert cl["values"][1]["author"]["emailAddress"] == "po@sim.local"


def test_label_with_space_rejected(client: TestClient) -> None:
    r = client.put(f"{R}/issue/TPD-1", json={"update": {"labels": [{"add": "a b"}]}}, auth=WRITER)
    assert r.status_code == 400
    assert "labels" in r.json()["errors"]


def test_update_description_requires_adf(client: TestClient) -> None:
    r = client.put(f"{R}/issue/TPD-2", json={"fields": {"description": "düz"}}, auth=WRITER)
    assert r.status_code == 400
    doc = text_to_adf("Yeni açıklama\n\n### Kabul Kriterleri\n- AC1: Tarih filtresi çalışır.")
    r = client.put(f"{R}/issue/TPD-2", json={"fields": {"description": doc}}, auth=WRITER)
    assert r.status_code == 204
    it = client.get(f"{R}/issue/TPD-2", params={"expand": "changelog"}, auth=READER).json()
    assert it["fields"]["description"] == doc
    item = it["changelog"]["histories"][-1]["items"][0]
    assert item["field"] == "description"
    assert "AC1: Tarih filtresi" in item["toString"]


def test_unknown_field_rejected(client: TestClient) -> None:
    r = client.put(f"{R}/issue/TPD-1", json={"fields": {"priority": {"name": "High"}}}, auth=WRITER)
    assert r.status_code == 400
    assert "priority" in r.json()["errors"]


def test_comments_roundtrip(client: TestClient) -> None:
    r = client.post(
        f"{R}/issue/TPD-1/comment", json={"body": text_to_adf("Soru 1?\nSoru 2?")}, auth=WRITER
    )
    assert r.status_code == 201
    created = r.json()
    assert created["author"]["emailAddress"] == "writer@sim.local"
    assert created["body"]["type"] == "doc"
    lst = client.get(f"{R}/issue/TPD-1/comment", auth=READER).json()
    assert lst["total"] == 1
    assert lst["comments"][0]["id"] == created["id"]
    assert adf_to_text(lst["comments"][0]["body"]) == "Soru 1?\nSoru 2?"
    bad = client.post(f"{R}/issue/TPD-1/comment", json={"body": "plain"}, auth=WRITER)
    assert bad.status_code == 400


def test_create_issue_and_validation(client: TestClient) -> None:
    payload = {
        "fields": {
            "project": {"key": "TPD"},
            "issuetype": {"name": "Bug"},
            "summary": "Yeni bug",
            "description": text_to_adf("Adımlar"),
            "labels": ["AI-generated"],
        }
    }
    r = client.post(f"{R}/issue", json=payload, auth=WRITER)
    assert r.status_code == 201
    body = r.json()
    assert body["key"] == "TPD-8"
    assert body["self"].endswith(f"/rest/api/3/issue/{body['id']}")
    it = client.get(f"{R}/issue/TPD-8", auth=READER).json()
    assert it["fields"]["reporter"]["emailAddress"] == "writer@sim.local"
    assert it["fields"]["labels"] == ["AI-generated"]

    bad = {"fields": {"project": {"key": "TPD"}, "issuetype": {"name": "Epic"}, "summary": "x"}}
    r = client.post(f"{R}/issue", json=bad, auth=WRITER)
    assert r.status_code == 400
    assert r.json()["errors"]["issuetype"] == "Specify a valid issue type"


def test_create_issue_type_can_be_disabled(client: TestClient) -> None:
    client.post("/sim/config", json={"issue_types": ["Story", "Task", "Bug"]})
    types = client.get(f"{R}/issue/createmeta/TPD/issuetypes", auth=READER).json()
    assert [t["name"] for t in types["issueTypes"]] == ["Story", "Task", "Bug"]
    payload = {"fields": {"project": {"key": "TPD"}, "issuetype": {"name": "Test"}, "summary": "t"}}
    assert client.post(f"{R}/issue", json=payload, auth=WRITER).status_code == 400


def test_createmeta_and_project(client: TestClient) -> None:
    types = client.get(f"{R}/issue/createmeta/TPD/issuetypes", auth=READER).json()
    assert {t["name"] for t in types["issueTypes"]} == {"Story", "Task", "Bug", "Test"}
    legacy = client.get(f"{R}/issue/createmeta", params={"projectKeys": "TPD"}, auth=READER)
    assert legacy.json()["projects"][0]["key"] == "TPD"
    assert client.get(f"{R}/project/TPD", auth=READER).json()["key"] == "TPD"
    assert client.get(f"{R}/project/XYZ", auth=READER).status_code == 404


def test_issue_link_types_and_links(client: TestClient) -> None:
    lt = client.get(f"{R}/issueLinkType", auth=READER).json()["issueLinkTypes"]
    test_type = next(t for t in lt if t["name"] == "Test")
    assert test_type["inward"] == "is tested by"
    assert any(t["name"] == "Relates" for t in lt)

    link = {
        "type": {"name": "Test"},
        "inwardIssue": {"key": "TPD-4"},
        "outwardIssue": {"key": "TPD-1"},
    }
    assert client.post(f"{R}/issueLink", json=link, auth=WRITER).status_code == 201
    assert client.post(f"{R}/issueLink", json=link, auth=WRITER).status_code == 201  # idempotent
    story = client.get(f"{R}/issue/TPD-1", auth=READER).json()
    links = story["fields"]["issuelinks"]
    assert len(links) == 1
    assert links[0]["inwardIssue"]["key"] == "TPD-4"
    assert links[0]["type"]["inward"] == "is tested by"
    other = client.get(f"{R}/issue/TPD-4", auth=READER).json()["fields"]["issuelinks"]
    assert other[0]["outwardIssue"]["key"] == "TPD-1"

    bad = {**link, "type": {"name": "Nope"}}
    assert client.post(f"{R}/issueLink", json=bad, auth=WRITER).status_code == 404
    missing = {**link, "inwardIssue": {"key": "TPD-404"}}
    assert client.post(f"{R}/issueLink", json=missing, auth=WRITER).status_code == 404


def test_search_get_and_post(client: TestClient) -> None:
    r = client.get(
        f"{R}/search/jql",
        params={"jql": "project = TPD AND issuetype = Story ORDER BY key ASC", "fields": "summary"},
        auth=READER,
    ).json()
    assert [i["key"] for i in r["issues"]] == ["TPD-1", "TPD-2", "TPD-3", "TPD-4"]
    assert r["isLast"] is True
    assert set(r["issues"][0]["fields"]) == {"summary"}

    # fields verilmezse yalnızca id döner (yeni arama ucunun davranışı)
    r = client.get(f"{R}/search/jql", params={"jql": "key = TPD-1"}, auth=READER).json()
    assert "fields" not in r["issues"][0]

    r = client.post(
        f"{R}/search/jql",
        json={"jql": "key in (TPD-1, TPD-3)", "fields": ["summary", "labels"], "maxResults": 1},
        auth=READER,
    ).json()
    assert len(r["issues"]) == 1 and r["isLast"] is False
    nxt = client.post(
        f"{R}/search/jql",
        json={
            "jql": "key in (TPD-1, TPD-3)",
            "fields": ["summary"],
            "maxResults": 1,
            "nextPageToken": r["nextPageToken"],
        },
        auth=READER,
    ).json()
    assert nxt["isLast"] is True
    assert {r["issues"][0]["key"], nxt["issues"][0]["key"]} == {"TPD-1", "TPD-3"}


def test_search_bad_jql_400(client: TestClient) -> None:
    r = client.get(f"{R}/search/jql", params={"jql": "foo = bar"}, auth=READER)
    assert r.status_code == 400
    assert "foo" in r.json()["errorMessages"][0]


def test_duplicate_candidates_search(client: TestClient) -> None:
    jql = (
        "project = TPD AND issuetype = Bug AND statusCategory != Done "
        'AND text ~ "kampanya indirimi hesaplanıyor" ORDER BY updated DESC'
    )
    r = client.get(f"{R}/search/jql", params={"jql": jql, "fields": "summary"}, auth=READER).json()
    assert [i["key"] for i in r["issues"]] == ["TPD-5"]
    open_bugs = client.get(
        f"{R}/search/jql",
        params={"jql": "issuetype = Bug AND statusCategory != Done", "fields": "status"},
        auth=READER,
    ).json()
    assert {i["key"] for i in open_bugs["issues"]} == {"TPD-5", "TPD-6"}


def test_delete_issue(client: TestClient) -> None:
    assert client.delete(f"{R}/issue/TPD-7", auth=READER).status_code == 403
    assert client.delete(f"{R}/issue/TPD-7", auth=WRITER).status_code == 204
    assert client.get(f"{R}/issue/TPD-7", auth=READER).status_code == 404


def test_reset_restores_seed(client: TestClient) -> None:
    client.put(f"{R}/issue/TPD-1", json={"update": {"labels": [{"add": "x"}]}}, auth=WRITER)
    client.post("/sim/config", json={"link_types": ["Relates"]})
    assert client.post("/sim/reset").json()["issues"] == 7
    it = client.get(f"{R}/issue/TPD-1", params={"expand": "changelog"}, auth=READER).json()
    assert it["fields"]["labels"] == ["tp-demo"]
    assert it["changelog"]["histories"] == []
    lt = client.get(f"{R}/issueLinkType", auth=READER).json()["issueLinkTypes"]
    assert any(t["name"] == "Test" for t in lt)


def test_fault_injection_retry_after(client: TestClient) -> None:
    client.post(
        "/sim/faults",
        json={"path_prefix": "/rest/api/3/myself", "status": 429, "count": 1, "retry_after": 2},
    )
    r = client.get(f"{R}/myself", auth=READER)
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "2"
    assert client.get(f"{R}/myself", auth=READER).status_code == 200
