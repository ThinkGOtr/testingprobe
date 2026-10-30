from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote

from fastapi.testclient import TestClient

from jira_sim.adf import adf_to_html, text_to_adf
from jira_sim.app import create_app
from tests.conftest import READER, WRITER

X = "/xray/api/v2"
R = "/rest/api/3"


# ------------------------------------------------------------------------ Xray


def _token(client: TestClient) -> str:
    r = client.post(f"{X}/authenticate", json={"client_id": "id", "client_secret": "s"})
    assert r.status_code == 200
    token = r.json()
    assert isinstance(token, str) and token
    return token


def test_xray_authenticate_rejects_empty() -> None:
    client = TestClient(create_app(data_path=""))
    r = client.post(f"{X}/authenticate", json={"client_id": "", "client_secret": "s"})
    assert r.status_code == 401
    assert "error" in r.json()


def test_xray_bulk_import_creates_test_issue_with_steps(client: TestClient) -> None:
    token = _token(client)
    h = {"Authorization": f"Bearer {token}"}
    tests = [
        {
            "testtype": "Manual",
            "fields": {
                "summary": "Kampanya: 7 adette 1 bedava",
                "project": {"key": "TPD"},
                "description": "Kaynak story TPD-1",
                "labels": ["AI-generated", "tp-1111"],
            },
            "steps": [
                {"action": "Giriş yap", "data": "bayi1", "result": "Katalog açılır"},
                {"action": "7 adet ekle", "data": "P-001", "result": "1 bedava"},
            ],
        },
        {"fields": {"project": {"key": "TPD"}}},  # özet yok → hata
    ]
    job = client.post(f"{X}/import/test/bulk", json=tests, headers=h).json()["jobId"]
    first = client.get(f"{X}/import/test/bulk/{job}/status", headers=h).json()
    assert first["status"] == "working"
    final = client.get(f"{X}/import/test/bulk/{job}/status", headers=h).json()
    assert final["status"] == "partially_successful"
    issues = final["result"]["issues"]
    assert len(issues) == 1 and issues[0]["elementNumber"] == 0
    assert final["result"]["errors"][0]["elementNumber"] == 1

    key = issues[0]["key"]
    it = client.get(f"{R}/issue/{key}", auth=READER).json()
    assert it["fields"]["issuetype"]["name"] == "Test"
    assert it["fields"]["labels"] == ["AI-generated", "tp-1111"]
    page = client.get(f"/browse/{key}").text
    assert "Test adımları" in page and "7 adet ekle" in page


def test_xray_requires_token(client: TestClient) -> None:
    r = client.post(f"{X}/import/test/bulk", json=[{}], headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    token = _token(client)
    r = client.get(
        f"{X}/import/test/bulk/unknown/status", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 404


def test_xray_test_type_available_even_if_jira_type_disabled(client: TestClient) -> None:
    client.post("/sim/config", json={"issue_types": ["Story", "Task", "Bug"]})
    h = {"Authorization": f"Bearer {_token(client)}"}
    job = client.post(
        f"{X}/import/test/bulk",
        json=[{"fields": {"summary": "s", "project": {"key": "TPD"}}, "steps": []}],
        headers=h,
    ).json()["jobId"]
    client.get(f"{X}/import/test/bulk/{job}/status", headers=h)
    assert client.get(f"{X}/import/test/bulk/{job}/status", headers=h).json()["status"] == (
        "successful"
    )
    # Jira yapılandırması değişmedi
    assert client.get("/sim/config").json()["issue_types"] == ["Story", "Task", "Bug"]


# ---------------------------------------------------------------------- arayüz


def test_ui_list_and_detail(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert "TPD-1" in page.text and "Kampanyalı sepet ve sipariş onayı" in page.text
    detail = client.get("/browse/TPD-1").text
    assert "Kabul Kriterleri" in detail
    assert "PO olarak" in detail
    assert client.get("/browse/TPD-404").status_code == 404
    filtered = client.get("/", params={"jql": "issuetype = Bug"}).text
    assert "TPD-5" in filtered and "TPD-1<" not in filtered
    bad = client.get("/", params={"jql": "nope = 1"}).text
    assert "JQL hatası" in bad


def test_ui_po_comment_and_label_recorded_as_po(po_client: tuple[TestClient, str]) -> None:
    client, csrf = po_client
    r = client.post(
        "/browse/TPD-1/comment",
        data={"body": "AC6 kaldırılsın.", "csrf": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    r = client.post(
        "/browse/TPD-1/labels",
        data={"action": "add", "label": "tp-po-approved", "csrf": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    it = client.get(f"{R}/issue/TPD-1", params={"expand": "changelog"}, auth=READER).json()
    assert "tp-po-approved" in it["fields"]["labels"]
    assert it["changelog"]["histories"][-1]["author"]["emailAddress"] == "po@sim.local"
    comments = it["fields"]["comment"]["comments"]
    assert comments[-1]["author"]["emailAddress"] == "po@sim.local"
    page = client.get("/browse/TPD-1").text
    assert "Etiket eklendi: tp-po-approved" in page

    client.post(
        "/browse/TPD-1/labels", data={"action": "remove", "label": "tp-po-approved", "csrf": csrf}
    )
    labels = client.get(f"{R}/issue/TPD-1", auth=READER).json()["fields"]["labels"]
    assert "tp-po-approved" not in labels


def test_ui_label_error_is_shown_in_turkish(po_client: tuple[TestClient, str]) -> None:
    client, csrf = po_client
    r = client.post("/browse/TPD-1/labels", data={"action": "add", "label": "a b", "csrf": csrf})
    assert r.status_code == 200
    assert "Etiket boşluk içeremez: &#39;a b&#39;." in r.text
    assert "contains spaces" not in r.text


def test_ui_empty_comment_error_is_turkish(po_client: tuple[TestClient, str]) -> None:
    client, csrf = po_client
    r = client.post("/browse/TPD-1/comment", data={"body": "   ", "csrf": csrf})
    assert r.status_code == 200
    assert "Yorum boş olamaz." in r.text
    assert "can not be empty" not in r.text


def test_ui_unknown_issue_error_is_turkish(client: TestClient) -> None:
    from tests.conftest import login_po

    csrf = login_po(client)
    r = client.post(
        "/browse/TPD-404/comment", data={"body": "x", "csrf": csrf}, follow_redirects=False
    )
    assert r.status_code == 303
    assert unquote(r.headers["location"]).endswith(
        "?hata=Kayıt bulunamadı ya da görme yetkiniz yok.#yorumlar"
    )


def test_ui_jql_errors_are_turkish(client: TestClient) -> None:
    incomplete = client.get("/", params={"jql": "project ="}).text
    assert "JQL hatası: JQL sorgusu eksik." in incomplete
    assert "Error in the JQL Query" not in incomplete
    unknown = client.get("/", params={"jql": "nope = 1"}).text
    assert "&#39;nope&#39; alanı yok" in unknown
    # REST API Jira uyumu için İngilizce iletiyi korur.
    r = client.get(f"{R}/search/jql", params={"jql": "project ="}, auth=READER)
    assert r.status_code == 400
    assert "the query is incomplete" in r.json()["errorMessages"][0]


def test_ui_description_edit_roundtrip(po_client: tuple[TestClient, str]) -> None:
    client, csrf = po_client
    page = client.get("/browse/TPD-1").text
    assert "### Kabul Kriterleri" in page  # düzenleme kutusu
    text = "Yeni açıklama.\n\n### Kabul Kriterleri\n- AC1: Tek kriter."
    client.post("/browse/TPD-1/description", data={"text": text, "csrf": csrf})
    it = client.get(f"{R}/issue/TPD-1", auth=READER).json()
    content = it["fields"]["description"]["content"]
    assert [n["type"] for n in content] == ["paragraph", "heading", "bulletList"]


def test_ui_escapes_html(client: TestClient) -> None:
    client.post(
        f"{R}/issue/TPD-1/comment",
        json={"body": text_to_adf("<script>alert(1)</script>")},
        auth=WRITER,
    )
    page = client.get("/browse/TPD-1").text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_adf_html_link_sanitized() -> None:
    doc = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "x",
                        "marks": [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}],
                    },
                    {
                        "type": "text",
                        "text": "y",
                        "marks": [{"type": "link", "attrs": {"href": "https://a.b"}}],
                    },
                ],
            }
        ],
    }
    html = str(adf_to_html(doc))
    assert "javascript" not in html
    assert 'href="https://a.b"' in html


# ---------------------------------------------------------------------- kalıcılık


def test_state_persists_atomically_and_reloads(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "jira.json"
    c1 = TestClient(create_app(data_path=str(path)))
    assert path.exists()
    c1.put(f"{R}/issue/TPD-1", json={"update": {"labels": [{"add": "kalici"}]}}, auth=WRITER)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "kalici" in data["issues"]["TPD-1"]["labels"]
    assert not [p for p in path.parent.iterdir() if p.name.startswith(".jira-")]

    c2 = TestClient(create_app(data_path=str(path)))
    labels = c2.get(f"{R}/issue/TPD-1", auth=READER).json()["fields"]["labels"]
    assert "kalici" in labels
    assert c2.post("/sim/reset").status_code == 200
    assert "kalici" not in json.loads(path.read_text(encoding="utf-8"))["issues"]["TPD-1"]["labels"]


def test_failed_write_does_not_change_state(tmp_path: Path) -> None:
    path = tmp_path / "jira.json"
    c = TestClient(create_app(data_path=str(path)))
    before = path.read_text(encoding="utf-8")
    r = c.put(
        f"{R}/issue/TPD-1",
        json={"update": {"labels": [{"add": "ok"}, {"add": "a b"}]}},
        auth=WRITER,
    )
    assert r.status_code == 400
    assert path.read_text(encoding="utf-8") == before
    assert c.get(f"{R}/issue/TPD-1", auth=READER).json()["fields"]["labels"] == ["tp-demo"]
