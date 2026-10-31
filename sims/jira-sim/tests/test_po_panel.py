"""PO onay paneli yalnızca story'lerde; uzun metin dar ekranda kaydırma yapmaz; durum geçişleri."""

from __future__ import annotations

from fastapi.testclient import TestClient

from jira_sim.adf import text_to_adf
from tests.conftest import WRITER, login_po

APPROVE_BUTTON = 'data-testid="po-onayla"'


def _create(client: TestClient, issue_type: str) -> str:
    r = client.post(
        "/rest/api/3/issue",
        json={
            "fields": {
                "project": {"key": "TPD"},
                "issuetype": {"name": issue_type},
                "summary": f"Örnek {issue_type}",
            }
        },
        auth=WRITER,
    )
    assert r.status_code == 201, r.text
    return r.json()["key"]


def test_story_shows_approve_controls(client: TestClient) -> None:
    login_po(client)
    page = client.get("/browse/TPD-1").text
    assert APPROVE_BUTTON in page
    assert "Sorulara cevabınızı yazın" in page
    assert 'data-testid="po-onay-yok"' not in page


def test_test_and_bug_issues_hide_approve_controls(client: TestClient) -> None:
    test_key = _create(client, "Test")
    login_po(client, test_key)
    for key in (test_key, "TPD-5"):
        page = client.get(f"/browse/{key}").text
        assert APPROVE_BUTTON not in page, key
        assert "Onayla (tp-po-approved ekle)" not in page
        assert "Sorulara cevabınızı yazın" not in page
        assert 'data-testid="po-onay-yok"' in page
        assert "Yorumu gönder" in page  # yorum yazmak hâlâ mümkün


def test_ui_refuses_po_approval_label_on_non_story(client: TestClient) -> None:
    test_key = _create(client, "Test")
    csrf = login_po(client, test_key)
    r = client.post(
        f"/browse/{test_key}/labels",
        data={"csrf": csrf, "action": "add", "label": "tp-po-approved"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "hata=" in r.headers["location"]
    labels = client.get(f"/rest/api/3/issue/{test_key}", auth=WRITER).json()["fields"]["labels"]
    assert "tp-po-approved" not in labels
    r = client.post(f"/browse/{test_key}/reapprove", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 303 and "hata=" in r.headers["location"]
    hist = client.get(f"/rest/api/3/issue/{test_key}/changelog", auth=WRITER).json()
    assert hist["total"] == 0
    # Diğer etiketler non-story'de de eklenebilir.
    r = client.post(
        f"/browse/{test_key}/labels",
        data={"csrf": csrf, "action": "add", "label": "inceleme"},
        follow_redirects=False,
    )
    assert "hata=" not in r.headers["location"]


def test_long_unbroken_comment_text_can_wrap(client: TestClient) -> None:
    chain = "Denetim zinciri: " + "a3f9" * 32
    client.post("/rest/api/3/issue/TPD-1/comment", json={"body": text_to_adf(chain)}, auth=WRITER)
    page = client.get("/browse/TPD-1").text
    assert "a3f9" * 32 in page
    assert ".desc, .comment, h1, dd, .chip { overflow-wrap: anywhere; }" in page


def test_transitions_api(client: TestClient) -> None:
    r = client.get("/rest/api/3/issue/TPD-5/transitions", auth=WRITER)
    assert r.status_code == 200
    ts = r.json()["transitions"]
    assert {t["to"]["name"] for t in ts} == {"In Progress", "Done"}
    done = next(t for t in ts if t["to"]["statusCategory"]["key"] == "done")
    assert (
        client.post(
            "/rest/api/3/issue/TPD-5/transitions",
            json={"transition": {"id": done["id"]}},
            auth=("reader@sim.local", "t"),
        ).status_code
        == 403
    )
    r = client.post(
        "/rest/api/3/issue/TPD-5/transitions", json={"transition": {"id": done["id"]}}, auth=WRITER
    )
    assert r.status_code == 204, r.text
    f = client.get("/rest/api/3/issue/TPD-5", auth=WRITER).json()["fields"]
    assert f["status"]["name"] == "Done"
    hist = client.get("/rest/api/3/issue/TPD-5/changelog", auth=WRITER).json()["values"]
    assert hist[-1]["items"][0]["field"] == "status"
    assert hist[-1]["author"]["emailAddress"] == "writer@sim.local"
    # Aynı duruma geçiş ve bilinmeyen id: Jira gibi 400.
    for body in ({"transition": {"id": done["id"]}}, {"transition": {"id": "999"}}, {}):
        r = client.post("/rest/api/3/issue/TPD-5/transitions", json=body, auth=WRITER)
        assert r.status_code == 400, body
    assert "Durum güncellendi" in client.get("/browse/TPD-5").text
    hits = client.get(
        "/rest/api/3/search/jql",
        params={"jql": "project = TPD AND statusCategory != Done"},
        auth=WRITER,
    ).json()["issues"]
    assert "TPD-5" not in {i["key"] for i in hits}
