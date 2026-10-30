"""PO onayı bayatladığında sim arayüzü bunu gösterir ve tek adımda yeniden onaylatır."""

from __future__ import annotations

from fastapi.testclient import TestClient

from jira_sim.ui import approval_is_stale
from tests.conftest import WRITER

LABEL = "tp-po-approved"


def _changelog(client: TestClient, key: str) -> list[dict]:
    r = client.get(f"/rest/api/3/issue/{key}/changelog", auth=WRITER)
    assert r.status_code == 200
    return r.json()["values"]


def _label_adds(changelog: list[dict]) -> list[dict]:
    out = []
    for h in changelog:
        for it in h["items"]:
            if it["field"] == "labels":
                before = set((it.get("fromString") or "").split())
                after = set((it.get("toString") or "").split())
                if LABEL in after and LABEL not in before:
                    out.append(h)
    return out


def _item(field: str, before: str = "", after: str = "x") -> dict:
    return {"field": field, "fromString": before, "toString": after}


def test_approval_is_stale_rules() -> None:
    add = {"items": [_item("labels", "", LABEL)]}
    desc = {"items": [_item("description")]}
    other_label = {"items": [_item("labels", LABEL, f"{LABEL} y")]}
    assert approval_is_stale([]) is False
    assert approval_is_stale([desc]) is False  # hiç onay yok
    assert approval_is_stale([add]) is False
    assert approval_is_stale([add, other_label]) is False  # etiket-dışı değişiklik bayatlatmaz
    assert approval_is_stale([add, desc]) is True
    assert approval_is_stale([desc, add]) is False
    assert approval_is_stale([add, desc, add]) is False
    # Aynı düzenlemede içerik + onay: onay o içeriği kapsar.
    assert (
        approval_is_stale([{"items": [_item("description"), _item("labels", "", LABEL)]}]) is False
    )
    assert approval_is_stale([add, {"items": [_item("summary")]}]) is True


def test_edit_after_approval_offers_reapprove(po_client: tuple[TestClient, str]) -> None:
    client, csrf = po_client
    r = client.post(
        "/browse/TPD-1/labels",
        data={"csrf": csrf, "action": "add", "label": LABEL},
        follow_redirects=False,
    )
    assert r.status_code == 303
    page = client.get("/browse/TPD-1").text
    assert 'data-testid="approval-stale"' not in page
    assert "Onayla (tp-po-approved ekle)" in page

    r = client.post(
        "/browse/TPD-1/description",
        data={"csrf": csrf, "text": "Yeni açıklama\n\nAC2 değişti"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    page = client.get("/browse/TPD-1").text
    assert "Onay eski: içerik onaydan sonra değişti" in page
    assert 'data-testid="reapprove"' in page
    assert "Onayla (tp-po-approved ekle)" not in page

    before = _label_adds(_changelog(client, "TPD-1"))
    r = client.post("/browse/TPD-1/reapprove", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 303
    log = _changelog(client, "TPD-1")
    adds = _label_adds(log)
    assert len(adds) == len(before) + 1
    assert adds[-1]["author"]["emailAddress"] == "po@sim.local"
    # Yeni ekleme son içerik değişikliğinden sonra gelir.
    last_content = max(
        i for i, h in enumerate(log) if any(it["field"] == "description" for it in h["items"])
    )
    assert log.index(adds[-1]) > last_content
    issue = client.get("/rest/api/3/issue/TPD-1", auth=WRITER).json()
    assert LABEL in issue["fields"]["labels"]
    page = client.get("/browse/TPD-1").text
    assert "Onay eski" not in page


def test_reapprove_requires_po_session_and_csrf(client: TestClient) -> None:
    r = client.post("/browse/TPD-1/reapprove", data={"csrf": "x"}, follow_redirects=False)
    assert r.status_code in (303, 401, 403)
    issue = client.get("/rest/api/3/issue/TPD-1", auth=WRITER).json()
    assert LABEL not in issue["fields"]["labels"]
