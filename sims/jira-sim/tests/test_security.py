"""PO onay kapısı ve yönetim uçlarının korunması (anayasa I: onay insandır)."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from jira_sim.app import create_app
from jira_sim.security import SESSION_COOKIE, SimSecurity, origin_of
from tests.conftest import ADMIN, ADMIN_TOKEN, PO_PASSWORD, READER, SIM_BASE, WRITER, login_po

R = "/rest/api/3"
APPROVE = {"action": "add", "label": "tp-po-approved"}


def _labels(client: TestClient, key: str = "TPD-1") -> list[str]:
    return client.get(f"{R}/issue/{key}", auth=READER).json()["fields"]["labels"]


def _comments(client: TestClient, key: str = "TPD-1") -> list[dict]:
    return client.get(f"{R}/issue/{key}/comment", auth=READER).json()["comments"]


# --------------------------------------------------------------- arayüz yazma uçları


@pytest.mark.parametrize(
    ("path", "data"),
    [
        ("/browse/TPD-1/labels", APPROVE),
        ("/browse/TPD-1/comment", {"body": "Onaylıyorum"}),
        ("/browse/TPD-1/description", {"text": "silindi"}),
    ],
)
def test_unauthenticated_ui_post_is_refused(client: TestClient, path: str, data: dict) -> None:
    before = client.get(f"{R}/issue/TPD-1", auth=READER).json()["fields"]
    r = client.post(path, data=data, follow_redirects=False)
    assert r.status_code == 401
    assert "PO olarak giriş yapmalısınız" in r.text
    after = client.get(f"{R}/issue/TPD-1", auth=READER).json()["fields"]
    assert after["labels"] == before["labels"] == ["tp-demo"]
    assert after["description"] == before["description"]
    assert _comments(client) == []


def test_post_without_csrf_token_is_refused_even_when_logged_in(client: TestClient) -> None:
    login_po(client)
    r = client.post("/browse/TPD-1/labels", data=APPROVE, follow_redirects=False)
    assert r.status_code == 403
    r = client.post(
        "/browse/TPD-1/labels", data={**APPROVE, "csrf": "sahte"}, follow_redirects=False
    )
    assert r.status_code == 403
    assert "tp-po-approved" not in _labels(client)


def test_cross_origin_post_is_refused_even_with_session_and_token(client: TestClient) -> None:
    csrf = login_po(client)
    for headers in (
        {"Origin": "http://evil.example"},
        {"Origin": "http://127.0.0.1:8081"},  # aynı site, başka port (demo uygulaması)
        {"Origin": "null"},
        {"Referer": "http://evil.example/sayfa"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
    ):
        r = client.post(
            "/browse/TPD-1/labels",
            data={**APPROVE, "csrf": csrf},
            headers=headers,
            follow_redirects=False,
        )
        assert r.status_code == 403, headers
        assert "başka bir siteden" in r.text
    assert "tp-po-approved" not in _labels(client)


def test_same_origin_browser_post_is_accepted(client: TestClient) -> None:
    csrf = login_po(client)
    for origin in (SIM_BASE, "http://testserver"):
        client.post(
            "/browse/TPD-1/labels",
            data={"action": "remove", "label": "tp-po-approved", "csrf": csrf},
        )
        r = client.post(
            "/browse/TPD-1/labels",
            data={**APPROVE, "csrf": csrf},
            headers={"Origin": origin, "Sec-Fetch-Site": "same-origin"},
            follow_redirects=False,
        )
        assert r.status_code == 303, origin
        assert "tp-po-approved" in _labels(client)


def test_dns_rebinding_host_is_refused(client: TestClient) -> None:
    csrf = login_po(client)
    r = client.post(
        "http://evil.example:8090/browse/TPD-1/labels",
        data={**APPROVE, "csrf": csrf},
        headers={"Origin": "http://evil.example:8090"},
        follow_redirects=False,
    )
    assert r.status_code == 403
    assert "tp-po-approved" not in _labels(client)


def test_login_wrong_password_and_forged_cookie(client: TestClient) -> None:
    r = client.post("/giris", data={"password": "yanlis"}, follow_redirects=False)
    assert r.status_code == 401
    assert "Parola hatalı." in r.text
    assert SESSION_COOKIE not in client.cookies
    client.cookies.set(SESSION_COOKIE, "nonce.imzasiz")
    r = client.post("/browse/TPD-1/labels", data={**APPROVE, "csrf": "x"})
    assert r.status_code == 401


def test_session_cookie_is_httponly_strict(client: TestClient) -> None:
    r = client.post(
        "/giris", data={"password": PO_PASSWORD, "sonra": "/browse/TPD-2"}, follow_redirects=False
    )
    assert r.headers["location"] == "/browse/TPD-2"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_login_redirect_is_local_only(client: TestClient) -> None:
    for target in ("https://evil.example/", "//evil.example/x", "/\\evil.example"):
        r = client.post(
            "/giris", data={"password": PO_PASSWORD, "sonra": target}, follow_redirects=False
        )
        assert r.headers["location"] == "/", target


def test_session_from_another_boot_is_not_accepted() -> None:
    a = TestClient(create_app(data_path="", base_url=SIM_BASE, po_password=PO_PASSWORD))
    login_po(a)
    b = TestClient(create_app(data_path="", base_url=SIM_BASE, po_password=PO_PASSWORD))
    b.cookies.set(SESSION_COOKIE, a.cookies[SESSION_COOKIE])
    assert "PO olarak giriş yapıldı" not in b.get("/browse/TPD-1").text


def test_logged_out_page_hides_po_forms(client: TestClient) -> None:
    page = client.get("/browse/TPD-1").text
    assert 'action="/browse/TPD-1/labels"' not in page
    assert 'action="/browse/TPD-1/comment"' not in page
    assert "PO olarak giriş yapın" in page
    login_po(client)
    page = client.get("/browse/TPD-1").text
    assert 'action="/browse/TPD-1/labels"' in page
    assert "PO olarak giriş yapıldı" in page


def test_logout_ends_session(client: TestClient) -> None:
    csrf = login_po(client)
    assert client.post("/cikis", data={"csrf": csrf}, follow_redirects=False).status_code == 303
    assert SESSION_COOKIE not in client.cookies
    r = client.post("/browse/TPD-1/labels", data={**APPROVE, "csrf": csrf})
    assert r.status_code == 401


def test_copied_cookie_is_useless_after_logout(client: TestClient) -> None:
    """Çıkıştan sonra çerezin kopyası PO adına etiket koyamaz (oturum sunucudan silinir)."""
    csrf = login_po(client, "TPD-4")
    stolen = client.cookies[SESSION_COOKIE]
    assert client.post("/cikis", data={"csrf": csrf}, follow_redirects=False).status_code == 303
    client.cookies.set(SESSION_COOKIE, stolen)
    for label in ("tp-review-probe", "tp-po-approved"):
        r = client.post(
            "/browse/TPD-4/labels",
            data={"action": "add", "label": label, "csrf": csrf},
            follow_redirects=False,
        )
        assert r.status_code == 401, label
    assert "PO olarak giriş yapıldı" not in client.get("/browse/TPD-4").text
    assert "tp-po-approved" not in _labels(client, "TPD-4")
    assert "tp-review-probe" not in _labels(client, "TPD-4")
    history = client.get(f"{R}/issue/TPD-4/changelog", auth=READER).json()["values"]
    assert all(h["author"]["emailAddress"] != "po@sim.local" for h in history)


def test_logout_ends_only_that_session(client: TestClient) -> None:
    other = TestClient(client.app)
    csrf_other = login_po(other)
    csrf = login_po(client)
    assert client.post("/cikis", data={"csrf": csrf}, follow_redirects=False).status_code == 303
    r = other.post("/browse/TPD-1/comment", data={"body": "hâlâ girişli", "csrf": csrf_other})
    assert r.status_code == 200  # yönlendirme izlendi
    assert [c["body"]["content"][0]["content"][0]["text"] for c in _comments(client)] == [
        "hâlâ girişli"
    ]


def test_session_expires_after_ttl() -> None:
    now = [1000.0]
    app = create_app(data_path="", base_url=SIM_BASE, po_password=PO_PASSWORD)
    sec: SimSecurity = app.state.security
    sec.clock = lambda: now[0]
    c = TestClient(app)
    csrf = login_po(c)
    r = c.post("/giris", data={"password": PO_PASSWORD}, follow_redirects=False)
    assert f"max-age={int(sec.session_ttl_s)}" in r.headers["set-cookie"].lower()
    now[0] += sec.session_ttl_s - 1
    assert "PO olarak giriş yapıldı" in c.get("/browse/TPD-1").text
    now[0] += 2
    r = c.post("/browse/TPD-1/labels", data={**APPROVE, "csrf": csrf}, follow_redirects=False)
    assert r.status_code == 401
    assert "tp-po-approved" not in _labels(c)


# ------------------------------------------------------------------------ REST PO


def test_rest_po_requires_po_password(client: TestClient) -> None:
    put = {"update": {"labels": [{"add": "tp-po-approved"}]}}
    for token in ("any-token", "sim", ""):
        r = client.put(f"{R}/issue/TPD-1", json=put, auth=("po@sim.local", token))
        assert r.status_code == 401, token
    assert "tp-po-approved" not in _labels(client)
    r = client.put(f"{R}/issue/TPD-1", json=put, auth=("po@sim.local", PO_PASSWORD))
    assert r.status_code == 204
    # Okuma ve bot kullanıcıları için her token geçerli kalır (çekirdeğin "sim" kimlikleri).
    assert client.get(f"{R}/myself", auth=("writer@sim.local", "sim")).status_code == 200
    assert client.get(f"{R}/myself", auth=WRITER).status_code == 200


def test_generated_po_password_when_env_missing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("JIRA_SIM_PO_PASSWORD", raising=False)
    with caplog.at_level(logging.WARNING, logger="jira_sim"):
        a = SimSecurity.from_env()
        b = SimSecurity.from_env()
    assert a.generated_password and len(a.po_password) >= 16
    assert a.po_password != b.po_password
    assert a.po_password in caplog.text
    monkeypatch.setenv("JIRA_SIM_PO_PASSWORD", "env-parola")
    assert SimSecurity.from_env().po_password == "env-parola"


# ---------------------------------------------------------------- /sim/* yönetim uçları


def test_sim_admin_cross_origin_refused(client: TestClient) -> None:
    client.put(f"{R}/issue/TPD-1", json={"update": {"labels": [{"add": "x"}]}}, auth=WRITER)
    for path, body in (
        ("/sim/reset", None),
        ("/sim/faults", {"path_prefix": "/", "status": 500, "count": 5}),
        ("/sim/config", {"link_types": []}),
    ):
        r = client.post(path, json=body, headers={"Origin": "http://evil.example"})
        assert r.status_code == 403, path
    assert "x" in _labels(client)  # sıfırlanmadı
    assert client.get(f"{R}/myself", auth=READER).status_code == 200  # hata enjekte edilmedi


def test_sim_admin_rejects_simple_form_post(client: TestClient) -> None:
    r = client.post("/sim/reset", data={"a": "1"})
    assert r.status_code == 415


def test_sim_admin_token_required_when_configured() -> None:
    c = TestClient(
        create_app(
            data_path="", base_url=SIM_BASE, po_password=PO_PASSWORD, admin_token=ADMIN_TOKEN
        )
    )
    assert c.post("/sim/reset").status_code == 403
    assert c.post("/sim/reset", headers={"X-Sim-Admin-Token": "yanlis"}).status_code == 403
    assert c.post("/sim/faults", json=[]).status_code == 403
    assert c.post("/sim/reset", headers=ADMIN).json()["issues"] == 7
    assert c.post("/sim/faults", json=[], headers=ADMIN).json() == {"faults": []}
    assert c.get("/sim/config").status_code == 200  # okuma serbest


def test_origin_of() -> None:
    assert origin_of("http://127.0.0.1:8090/browse/TPD-1?x=1") == "http://127.0.0.1:8090"
    assert origin_of("https://a.example:443/") == "https://a.example"
    assert origin_of("http://A.example:80") == "http://a.example"
    assert origin_of("null") is None
    assert origin_of("javascript:alert(1)") is None


def test_changelog_orders_approval_before_later_description_edit(client: TestClient) -> None:
    """Bayat onay tespiti için: onaydan sonraki açıklama düzenlemesi changelog'da sonra gelir;
    bot onayı ekleyemez ama geri çekebilir."""
    put = {"update": {"labels": [{"add": "tp-po-approved"}]}}
    assert client.put(f"{R}/issue/TPD-1", json=put, auth=("po@sim.local", PO_PASSWORD)).status_code
    doc = {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "bot yeniden yazdı"}]}
        ],
    }
    r = client.put(f"{R}/issue/TPD-1", json={"fields": {"description": doc}}, auth=WRITER)
    assert r.status_code == 204
    values = client.get(f"{R}/issue/TPD-1/changelog", auth=READER).json()["values"]
    fields = [(h["author"]["emailAddress"], [i["field"] for i in h["items"]]) for h in values]
    assert fields[-2:] == [("po@sim.local", ["labels"]), ("writer@sim.local", ["description"])]
    r = client.put(
        f"{R}/issue/TPD-1", json={"update": {"labels": [{"remove": "tp-po-approved"}]}}, auth=WRITER
    )
    assert r.status_code == 204
    assert "tp-po-approved" not in _labels(client)
