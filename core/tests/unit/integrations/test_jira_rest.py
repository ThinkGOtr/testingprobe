"""RestJira, jira-sim simülatörüne karşı süreç içinde (ağsız) koşar."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from tp_core.integrations.jira import (
    PO_APPROVED_LABEL,
    RESERVED_LABELS,
    JiraAuthError,
    JiraConfigError,
    JiraError,
    JiraNotFound,
    JiraPermissionError,
    JiraSettings,
    JiraUnavailable,
    ReservedLabelError,
    RestJira,
    authorized_po_approvals,
    get_jira,
    parse_jira_datetime,
    person_id,
    retry_after_seconds,
    send_with_retry,
)
from tp_core.ports import JiraPort, LabelChange

SIM_SRC = Path(__file__).resolve().parents[4] / "sims" / "jira-sim" / "src"
if str(SIM_SRC) not in sys.path:
    sys.path.insert(0, str(SIM_SRC))

from jira_sim.app import create_app  # noqa: E402

BASE = "http://jira-sim:8090"
PO_PASSWORD = "po-test-parola"
PO_AUTH = ("po@sim.local", PO_PASSWORD)


class SimTransport(httpx.BaseTransport):
    """Gerçek ``httpx.Client`` isteklerini süreç içindeki simülatöre iletir (ağ yok)."""

    def __init__(self, sim: TestClient) -> None:
        self.sim = sim
        self.paths: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        r = self.sim.request(
            request.method,
            str(request.url),
            headers=dict(request.headers),
            content=request.read(),
        )
        return httpx.Response(r.status_code, headers=dict(r.headers), content=r.content)


@pytest.fixture
def sim() -> Iterator[TestClient]:
    with TestClient(
        create_app(data_path="", base_url=BASE, po_password=PO_PASSWORD), base_url=BASE
    ) as client:
        yield client


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def jira(sim: TestClient, sleeps: list[float]) -> RestJira:
    return RestJira(
        BASE,
        ("reader@sim.local", "t"),
        ("writer@sim.local", "t"),
        http=httpx.Client(transport=SimTransport(sim)),
        sleep=sleeps.append,
    )


def test_implements_port(jira: RestJira) -> None:
    assert isinstance(jira, JiraPort)


def test_get_issue_parses_description_and_acs(jira: RestJira) -> None:
    it = jira.get_issue("TPD-1")
    assert it.key == "TPD-1"
    assert it.issue_type == "Story"
    assert it.summary == "Kampanyalı sepet ve sipariş onayı"
    assert it.description == (
        "Bayi, katalogdan ürünleri sepete ekleyip kampanya indirimiyle siparişini "
        "onaylayabilmelidir."
    )
    assert len(it.acceptance_criteria) == 6
    assert it.acceptance_criteria[0].startswith('AC1: Bayi katalogda bir ürün için "Sepete ekle"')
    assert it.acceptance_criteria[5] == (
        "AC6: Kampanyalı siparişlerde minimum sipariş tutarı şartı aranmaz."
    )
    assert it.labels == ["tp-demo"]
    assert it.status == "To Do"
    assert it.reporter == "po@sim.local"
    assert it.updated is not None and it.updated.utcoffset() is not None


def test_tpd2_has_no_ac(jira: RestJira) -> None:
    assert jira.get_issue("TPD-2").acceptance_criteria == []


def test_get_issue_not_found(jira: RestJira) -> None:
    with pytest.raises(JiraNotFound) as err:
        jira.get_issue("TPD-999")
    assert err.value.status == 404


def test_search_with_pagination(jira: RestJira) -> None:
    stories = jira.search("project = TPD AND issuetype = Story ORDER BY key ASC")
    assert [i.key for i in stories] == ["TPD-1", "TPD-2", "TPD-3", "TPD-4"]
    assert stories[0].acceptance_criteria  # alanlar istenmiş olmalı
    two = jira.search("project = TPD ORDER BY key ASC", max_results=2)
    assert [i.key for i in two] == ["TPD-1", "TPD-2"]


def test_search_pages_follow_next_token(sim: TestClient, jira: RestJira) -> None:
    calls: list[int] = []
    original = sim.request

    def spy(method: str, url: str, **kw: object) -> httpx.Response:
        if url.endswith("/search/jql"):
            calls.append(1)
        return original(method, url, **kw)  # type: ignore[arg-type]

    sim.request = spy  # type: ignore[method-assign]
    for n in range(120):
        jira.create_issue("TPD", "Task", f"Görev {n}", "", ["toplu"])
    found = jira.search("labels = toplu", max_results=500)
    assert len(found) == 120
    assert len(calls) == 2  # 100 + 20


def test_duplicate_candidate_search(jira: RestJira) -> None:
    hits = jira.search(
        "project = TPD AND issuetype = Bug AND statusCategory != Done "
        'AND text ~ "kampanya indirimi"'
    )
    assert [h.key for h in hits] == ["TPD-5"]


def test_comments_roundtrip(jira: RestJira) -> None:
    cid = jira.add_comment("TPD-1", "1. Soru bir?\n2. Soru iki?\n\nAI-generated")
    comments = jira.get_comments("TPD-1")
    assert [c.id for c in comments] == [cid]
    assert comments[0].author == "writer@sim.local"
    assert comments[0].body == "1. Soru bir?\n2. Soru iki?\n\nAI-generated"
    assert comments[0].created is not None


def test_labels_and_label_history(sim: TestClient, jira: RestJira) -> None:
    jira.add_labels("TPD-1", ["tp-po-pending"])
    jira.add_labels("TPD-1", [])  # no-op
    # PO (insan) onay etiketini kendi kimliğiyle koyar
    r = sim.put(
        "/rest/api/3/issue/TPD-1",
        json={"update": {"labels": [{"add": "tp-po-approved"}]}},
        auth=PO_AUTH,
    )
    assert r.status_code == 204
    jira.remove_labels("TPD-1", ["tp-po-pending"])
    assert sorted(jira.get_issue("TPD-1").labels) == ["tp-demo", "tp-po-approved"]

    hist = jira.label_history("TPD-1", "tp-po-approved")
    assert len(hist) == 1
    assert hist[0].author == "po@sim.local"
    assert hist[0].label == "tp-po-approved"
    assert hist[0].at is not None
    pending = jira.label_history("TPD-1", "tp-po-pending")
    assert [h.author for h in pending] == ["writer@sim.local"]
    assert jira.label_history("TPD-1", "yok") == []


def test_update_description_roundtrip(jira: RestJira) -> None:
    before = jira.get_issue("TPD-1")
    acs = [*before.acceptance_criteria[:2], "AC3: Minimum sipariş tutarı 750,00 TL'dir."]
    jira.update_description("TPD-1", before.description, acs)
    after = jira.get_issue("TPD-1")
    assert after.description == before.description
    assert after.acceptance_criteria == acs


def test_create_issue_and_link(sim: TestClient, jira: RestJira) -> None:
    key = jira.create_issue(
        "TPD", "Bug", "Kampanya hesabı hatalı", "Adımlar\n- bir\n- iki", ["AI-generated"]
    )
    it = jira.get_issue(key)
    assert it.issue_type == "Bug" and it.labels == ["AI-generated"]
    assert it.description == "Adımlar\n\n- bir\n- iki"
    jira.link_issues(key, "TPD-1", "Relates")
    raw = sim.get("/rest/api/3/issue/TPD-1", auth=("reader@sim.local", "x")).json()
    assert raw["fields"]["issuelinks"][0]["inwardIssue"]["key"] == key
    assert jira.issue_url(key) == f"{BASE}/browse/{key}"


def test_metadata_helpers(sim: TestClient, jira: RestJira) -> None:
    assert set(jira.issue_types("TPD")) == {"Story", "Task", "Bug", "Test"}
    assert {"Test", "Relates"} <= set(jira.link_type_names())
    jira.delete_issue("TPD-7")
    with pytest.raises(JiraNotFound):
        jira.get_issue("TPD-7")


def test_read_and_write_use_separate_credentials(sim: TestClient, sleeps: list[float]) -> None:
    # Okuma kimliğiyle yazmaya çalışmak 403 vermeli: adaptör yazmada okuma kimliğini kullanmamalı.
    swapped = RestJira(
        BASE,
        ("reader@sim.local", "t"),
        ("reader@sim.local", "t"),
        http=httpx.Client(transport=SimTransport(sim)),
    )
    with pytest.raises(JiraPermissionError):
        swapped.add_labels("TPD-1", ["x"])
    read_only = RestJira(
        BASE, ("reader@sim.local", "t"), None, http=httpx.Client(transport=SimTransport(sim))
    )
    assert read_only.get_issue("TPD-1").key == "TPD-1"
    with pytest.raises(JiraConfigError):
        read_only.add_comment("TPD-1", "x")
    assert read_only.myself()["emailAddress"] == "reader@sim.local"
    ok = RestJira(
        BASE,
        ("reader@sim.local", "t"),
        ("writer@sim.local", "t"),
        http=httpx.Client(transport=SimTransport(sim)),
    )
    assert ok.myself(write=True)["emailAddress"] == "writer@sim.local"


def test_unknown_user_is_auth_error(sim: TestClient) -> None:
    bad = RestJira(
        BASE, ("nobody@sim.local", "t"), None, http=httpx.Client(transport=SimTransport(sim))
    )
    with pytest.raises(JiraAuthError):
        bad.get_issue("TPD-1")


# ------------------------------------------------------------------ yeniden deneme


def test_retries_429_honouring_retry_after(
    sim: TestClient, jira: RestJira, sleeps: list[float]
) -> None:
    sim.post(
        "/sim/faults",
        json={
            "path_prefix": "/rest/api/3/issue/TPD-1",
            "status": 429,
            "count": 2,
            "retry_after": 3,
        },
    )
    assert jira.get_issue("TPD-1").key == "TPD-1"
    assert sleeps == [3.0, 3.0]


def test_retries_5xx_with_exponential_backoff_then_gives_up(
    sim: TestClient, jira: RestJira, sleeps: list[float]
) -> None:
    sim.post("/sim/faults", json={"path_prefix": "/rest/api/3/myself", "status": 503, "count": 10})
    with pytest.raises(JiraUnavailable) as err:
        jira.myself()
    assert err.value.status == 503
    assert sleeps == [0.5, 1.0, 2.0]  # en fazla 3 yeniden deneme


def test_post_is_not_retried_on_502(sim: TestClient, jira: RestJira, sleeps: list[float]) -> None:
    # 502 ağ geçidinden gelebilir; Jira yorumu yazmış olabilir → tekrar gönderilmez.
    sim.post(
        "/sim/faults",
        json={
            "path_prefix": "/rest/api/3/issue/TPD-1/comment",
            "status": 502,
            "count": 1,
            "method": "POST",
        },
    )
    with pytest.raises(JiraUnavailable) as err:
        jira.add_comment("TPD-1", "tekrar")
    assert err.value.status == 502
    assert sleeps == []


def test_put_is_retried_on_502(sim: TestClient, jira: RestJira, sleeps: list[float]) -> None:
    sim.post(
        "/sim/faults",
        json={"path_prefix": "/rest/api/3/issue/TPD-1", "status": 502, "count": 1, "method": "PUT"},
    )
    jira.add_labels("TPD-1", ["x"])
    assert "x" in jira.get_issue("TPD-1").labels
    assert sleeps == [0.5]


def test_post_is_retried_on_429_and_503_with_retry_after(
    sim: TestClient, jira: RestJira, sleeps: list[float]
) -> None:
    sim.post(
        "/sim/faults",
        json=[
            {
                "path_prefix": "/rest/api/3/issue/TPD-1/comment",
                "status": 429,
                "count": 1,
                "method": "POST",
                "retry_after": 2,
            },
        ],
    )
    jira.add_comment("TPD-1", "hız sınırı")
    sim.post(
        "/sim/faults",
        json={
            "path_prefix": "/rest/api/3/issue/TPD-1/comment",
            "status": 503,
            "count": 1,
            "method": "POST",
            "retry_after": 1,
        },
    )
    jira.add_comment("TPD-1", "bakım")
    assert [c.body for c in jira.get_comments("TPD-1")] == ["hız sınırı", "bakım"]
    assert sleeps == [2.0, 1.0]


class _Sequence(httpx.BaseTransport):
    """Sırayla verilen yanıtları döner ve gelen istekleri kaydeder."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, str]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        return self.responses.pop(0)


@pytest.mark.parametrize("status", [500, 502, 504])
def test_create_issue_post_sent_exactly_once_on_5xx(status: int) -> None:
    transport = _Sequence(
        httpx.Response(status, json={"errorMessages": ["gateway"]}),
        httpx.Response(201, json={"id": "1", "key": "TPD-99"}),
    )
    sleeps: list[float] = []
    j = RestJira(
        BASE,
        ("r", "t"),
        ("w", "t"),
        http=httpx.Client(transport=transport),
        sleep=sleeps.append,
    )
    with pytest.raises(JiraUnavailable):
        j.create_issue("TPD", "Bug", "s", "d")
    assert transport.requests == [("POST", "/rest/api/3/issue")]
    assert sleeps == []


def test_post_503_without_retry_after_is_not_retried() -> None:
    transport = _Sequence(httpx.Response(503), httpx.Response(201, json={"ok": True}))
    with httpx.Client(transport=transport) as http:
        r = send_with_retry(http, "POST", "http://x/y", what="t", sleep=lambda _: None)
    assert r.status_code == 503 and len(transport.requests) == 1
    # Açıkça idempotent işaretlenen POST (ör. Xray token) tekrarlanır.
    transport = _Sequence(httpx.Response(502), httpx.Response(200, json={"ok": True}))
    with httpx.Client(transport=transport) as http:
        r = send_with_retry(
            http, "POST", "http://x/y", what="t", sleep=lambda _: None, idempotent=True
        )
    assert r.status_code == 200 and len(transport.requests) == 2


def test_no_retry_on_4xx(sim: TestClient, jira: RestJira, sleeps: list[float]) -> None:
    with pytest.raises(JiraNotFound):
        jira.get_issue("TPD-404")
    assert sleeps == []


class _Flaky(httpx.BaseTransport):
    def __init__(self, exc: Exception, failures: int) -> None:
        self.exc = exc
        self.failures = failures
        self.calls = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.exc
        return httpx.Response(200, json={"ok": True})


def test_transport_errors_retry_only_when_safe() -> None:
    sleeps: list[float] = []
    connect = _Flaky(httpx.ConnectError("refused"), failures=2)
    with httpx.Client(transport=connect) as http:
        r = send_with_retry(http, "POST", "http://x/y", what="t", sleep=sleeps.append)
    assert r.status_code == 200 and connect.calls == 3

    # Okuma zaman aşımı: POST tekrarlanmaz (çift kayıt riski), GET tekrarlanır.
    timeout = _Flaky(httpx.ReadTimeout("slow"), failures=1)
    with httpx.Client(transport=timeout) as http, pytest.raises(JiraUnavailable):
        send_with_retry(http, "POST", "http://x/y", what="t", sleep=sleeps.append)
    timeout = _Flaky(httpx.ReadTimeout("slow"), failures=1)
    with httpx.Client(transport=timeout) as http:
        assert send_with_retry(http, "GET", "http://x/y", what="t", sleep=sleeps.append)


def test_retry_after_parsing() -> None:
    assert retry_after_seconds("5") == 5.0
    assert retry_after_seconds(None) is None
    assert retry_after_seconds("garbage") is None
    assert retry_after_seconds("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


# ---------------------------------------------------------------------- ayarlar


def test_settings_defaults_point_to_simulator(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "JIRA_BASE_URL",
        "JIRA_READ_EMAIL",
        "JIRA_READ_TOKEN",
        "JIRA_WRITE_EMAIL",
        "JIRA_WRITE_TOKEN",
        "TP_TEST_MGMT",
        "JIRA_PROJECT",
    ):
        monkeypatch.setenv(var, "")
    s = JiraSettings()
    assert s.jira_base_url == BASE
    assert s.jira_project == "TPD"
    assert s.test_mgmt == "jira"
    assert s.is_simulator
    j = get_jira(s)
    assert j.base_url == BASE


def test_settings_real_jira_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_READ_EMAIL", "")
    monkeypatch.setenv("JIRA_READ_TOKEN", "")
    with pytest.raises(JiraConfigError):
        get_jira(JiraSettings())
    monkeypatch.setenv("JIRA_READ_EMAIL", "r@example.com")
    monkeypatch.setenv("JIRA_READ_TOKEN", "tok")
    monkeypatch.setenv("JIRA_WRITE_EMAIL", "")
    monkeypatch.setenv("JIRA_BROWSE_URL", "")
    j = get_jira(JiraSettings())
    with pytest.raises(JiraConfigError):  # yazma kimliği yok → yazma reddedilir (ağa çıkmadan)
        j.add_comment("TPD-1", "x")
    assert j.issue_url("TPD-1") == "https://example.atlassian.net/browse/TPD-1"


def test_settings_rejects_unknown_test_mgmt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_TEST_MGMT", "testrail")
    with pytest.raises(ValueError):
        JiraSettings()


# ------------------------------------------------------- PO onay kapısı (anayasa I)


def test_bot_cannot_write_reserved_po_label(sim: TestClient, jira: RestJira) -> None:
    assert PO_APPROVED_LABEL in RESERVED_LABELS
    with pytest.raises(ReservedLabelError) as err:
        jira.add_labels("TPD-1", ["tp-po-pending", PO_APPROVED_LABEL])
    assert isinstance(err.value, ValueError) and isinstance(err.value, JiraError)
    with pytest.raises(ReservedLabelError):
        jira.create_issue("TPD", "Bug", "s", "d", labels=[PO_APPROVED_LABEL])
    with pytest.raises(ReservedLabelError):
        jira.create_issue("TPD", "Bug", "s", "d", fields={"labels": [PO_APPROVED_LABEL]})
    # Hiçbir istek gönderilmedi: diğer etiket de eklenmedi.
    assert jira.get_issue("TPD-1").labels == ["tp-demo"]
    assert [i.key for i in jira.search("labels = tp-po-approved")] == []


def test_bot_may_withdraw_reserved_po_label(sim: TestClient, jira: RestJira) -> None:
    """Bot onay etiketini ekleyemez ama kaldırabilir (bayat onayı geri çekmek)."""
    sim.put(
        "/rest/api/3/issue/TPD-1",
        json={"update": {"labels": [{"add": PO_APPROVED_LABEL}]}},
        auth=PO_AUTH,
    )
    jira.remove_labels("TPD-1", [PO_APPROVED_LABEL])
    jira.add_labels("TPD-1", ["tp-po-pending"])
    assert sorted(jira.get_issue("TPD-1").labels) == ["tp-demo", "tp-po-pending"]


def _set_description(sim: TestClient, key: str, text: str, auth: tuple[str, str]) -> None:
    from tp_core.integrations.jira_adf import build_description

    r = sim.put(
        f"/rest/api/3/issue/{key}",
        json={"fields": {"description": build_description(text, ["AC yeni"])}},
        auth=auth,
    )
    assert r.status_code == 204, r.text


def _po_label(sim: TestClient, key: str, op: str) -> None:
    r = sim.put(
        f"/rest/api/3/issue/{key}",
        json={"update": {"labels": [{op: PO_APPROVED_LABEL}]}},
        auth=PO_AUTH,
    )
    assert r.status_code == 204, r.text


def test_po_approval_is_stale_after_description_change(sim: TestClient, jira: RestJira) -> None:
    """Onaydan sonra açıklama (AC) değişirse eski etiket onay sayılmaz (anayasa I)."""
    _po_label(sim, "TPD-1", "add")
    assert [a.author for a in jira.po_approvals("TPD-1", ["po@sim.local"])] == ["po@sim.local"]

    # apply-doc-fixes: bot açıklamayı yeniden yazar; etiket hâlâ üzerinde ve geçmişte.
    jira.update_description("TPD-1", "Yeni açıklama", ["AC 1 (düzeltilmiş)"])
    assert PO_APPROVED_LABEL in jira.get_issue("TPD-1").labels
    assert len(jira.label_history("TPD-1", PO_APPROVED_LABEL)) == 1
    assert jira.po_approvals("TPD-1", ["po@sim.local"]) == []
    [(_, changed)] = jira.label_events("TPD-1", PO_APPROVED_LABEL)
    assert changed is True

    # Bot bayat onayı geri çeker, PO yeni içeriği görüp yeniden onaylar → tek geçerli onay.
    jira.remove_labels("TPD-1", [PO_APPROVED_LABEL])
    jira.add_labels("TPD-1", ["tp-po-pending"])
    assert jira.po_approvals("TPD-1", ["po@sim.local"]) == []
    _po_label(sim, "TPD-1", "add")
    approvals = jira.po_approvals("TPD-1", ["po@sim.local"])
    assert len(approvals) == 1
    assert approvals[0].at == jira.label_history("TPD-1", PO_APPROVED_LABEL)[-1].at


def test_po_approval_is_stale_after_summary_change(sim: TestClient, jira: RestJira) -> None:
    _po_label(sim, "TPD-3", "add")
    r = sim.put(
        "/rest/api/3/issue/TPD-3",
        json={"fields": {"summary": "Özet değişti"}},
        auth=("writer@sim.local", "sim"),
    )
    assert r.status_code == 204
    assert jira.po_approvals("TPD-3", ["po@sim.local"]) == []


def test_label_only_changes_do_not_invalidate_approval(sim: TestClient, jira: RestJira) -> None:
    _po_label(sim, "TPD-1", "add")
    jira.add_labels("TPD-1", ["tp-review-probe"])
    jira.add_comment("TPD-1", "Rapor hazır")
    assert len(jira.po_approvals("TPD-1", ["po@sim.local"])) == 1


def test_po_edit_and_approve_in_same_change_counts(sim: TestClient, jira: RestJira) -> None:
    """PO açıklamayı kendisi değiştirip aynı düzenlemede onaylarsa onay geçerlidir."""
    from tp_core.integrations.jira_adf import build_description

    r = sim.put(
        "/rest/api/3/issue/TPD-1",
        json={
            "fields": {"description": build_description("PO yazdı", ["AC"])},
            "update": {"labels": [{"add": PO_APPROVED_LABEL}]},
        },
        auth=PO_AUTH,
    )
    assert r.status_code == 204
    assert len(jira.po_approvals("TPD-1", ["po@sim.local"])) == 1
    _set_description(sim, "TPD-1", "sonradan", ("writer@sim.local", "sim"))
    assert jira.po_approvals("TPD-1", ["po@sim.local"]) == []


def _changelog_jira(values: list[dict], **kw: object) -> RestJira:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/myself"):
            return httpx.Response(200, json={"accountId": "bot"})
        return httpx.Response(200, json={"values": values, "isLast": True})

    return RestJira(
        BASE,
        ("r", "t"),
        ("w", "t"),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        **kw,  # type: ignore[arg-type]
    )


def _hist(created: str, field: str, to: str = "x", field_id: str | None = None) -> dict:
    item = {"field": field, "fieldId": field_id or field, "fromString": "", "toString": to}
    return {"author": {"accountId": "po"}, "created": created, "items": [item]}


def test_ac_custom_field_change_invalidates_approval() -> None:
    label = _hist("2026-10-30T10:00:00.000+0000", "labels", PO_APPROVED_LABEL)
    ac = _hist("2026-10-30T11:00:00.000+0000", "Acceptance Criteria", "yeni", "customfield_10050")
    other = _hist("2026-10-30T11:00:00.000+0000", "Story Points", "5", "customfield_10016")
    assert _changelog_jira([label, other]).po_approvals("TPD-1", ["po"]) != []
    assert _changelog_jira([label, ac]).po_approvals("TPD-1", ["po"]) == []
    # Adı ipucu içermeyen AC alanı yapılandırmayla içerik sayılır.
    custom = _hist("2026-10-30T11:00:00.000+0000", "AK", "yeni", "customfield_10099")
    assert _changelog_jira([label, custom]).po_approvals("TPD-1", ["po"]) != []
    j = _changelog_jira([label, custom], content_fields=["customfield_10099"])
    assert j.po_approvals("TPD-1", ["po"]) == []


def test_staleness_uses_changelog_order_within_same_millisecond() -> None:
    ts = "2026-10-30T10:00:00.000+0000"
    label, desc = _hist(ts, "labels", PO_APPROVED_LABEL), _hist(ts, "description")
    assert _changelog_jira([label, desc]).po_approvals("TPD-1", ["po"]) == []
    assert len(_changelog_jira([desc, label]).po_approvals("TPD-1", ["po"])) == 1


def test_person_id_never_uses_display_name() -> None:
    assert person_id({"displayName": "Ürün Sahibi (PO)"}) == ""
    assert person_id({"displayName": "PO", "accountId": "5b10ac"}) == "5b10ac"
    assert person_id({"emailAddress": "po@x.com", "accountId": "5b10ac"}) == "po@x.com"
    assert person_id(None) == ""


def test_label_history_author_is_account_id_when_email_hidden() -> None:
    """Jira Cloud e-postayı gizler: yazar görünen ad değil accountId olmalı."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "values": [
                    {
                        "author": {"accountId": "acc-impostor", "displayName": "Ürün Sahibi"},
                        "created": "2026-10-30T10:00:00.000+0000",
                        "items": [
                            {"field": "labels", "fromString": "", "toString": "tp-po-approved"}
                        ],
                    }
                ],
                "isLast": True,
            },
        )

    j = RestJira(BASE, ("r", "t"), http=httpx.Client(transport=httpx.MockTransport(handler)))
    hist = j.label_history("TPD-1", PO_APPROVED_LABEL)
    assert [h.author for h in hist] == ["acc-impostor"]
    # PO izin listesi accountId ile: görünen adı PO'nunkiyle aynı yapan kişi onaylayamaz.
    assert authorized_po_approvals(hist, ["acc-real-po"]) == []
    assert authorized_po_approvals(hist, ["Ürün Sahibi"]) == []
    assert authorized_po_approvals(hist, ["acc-impostor"]) == hist


def test_authorized_po_approvals_filters_bot_and_unknown() -> None:
    po = LabelChange(label=PO_APPROVED_LABEL, author="PO@sim.local")
    bot = LabelChange(label=PO_APPROVED_LABEL, author="writer@sim.local")
    anon = LabelChange(label=PO_APPROVED_LABEL, author="")
    other = LabelChange(label=PO_APPROVED_LABEL, author="dev@sim.local")
    changes = [po, bot, anon, other]
    assert authorized_po_approvals(changes, ["po@sim.local"], ["writer@sim.local"]) == [po]
    # Bot hesabı yanlışlıkla izin listesine konsa da sayılmaz.
    assert authorized_po_approvals(
        changes, ["po@sim.local", "writer@sim.local"], ["writer@sim.local"]
    ) == [po]
    assert authorized_po_approvals(changes, []) == []  # izin listesi boş → onay yok


def test_po_approvals_ignores_bot_authored_label(sim: TestClient, jira: RestJira) -> None:
    # Adaptör engelini atlayan bir bot yazımı (ör. doğrudan REST) PO onayı sayılmamalı.
    sim.put(
        "/rest/api/3/issue/TPD-2",
        json={"update": {"labels": [{"add": PO_APPROVED_LABEL}]}},
        auth=("writer@sim.local", "sim"),
    )
    assert [h.author for h in jira.label_history("TPD-2", PO_APPROVED_LABEL)] == [
        "writer@sim.local"
    ]
    assert jira.bot_identities() == {"writer@sim.local", "sim-writer-0002"}
    assert jira.po_approvals("TPD-2", ["po@sim.local", "writer@sim.local"]) == []

    sim.put(
        "/rest/api/3/issue/TPD-2",
        json={"update": {"labels": [{"remove": PO_APPROVED_LABEL}]}},
        auth=PO_AUTH,
    )
    sim.put(
        "/rest/api/3/issue/TPD-2",
        json={"update": {"labels": [{"add": PO_APPROVED_LABEL}]}},
        auth=PO_AUTH,
    )
    approvals = jira.po_approvals("TPD-2", ["po@sim.local"])
    assert [a.author for a in approvals] == ["po@sim.local"]


def test_po_account_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "")
    monkeypatch.setenv("JIRA_PO_ACCOUNT_IDS", "")
    assert JiraSettings().po_accounts == {"po@sim.local"}
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    assert JiraSettings().po_accounts == frozenset()  # gerçek Jira'da varsayılan yok
    monkeypatch.setenv("JIRA_PO_ACCOUNT_IDS", " 5b10ac , 6c20bd ,")
    assert JiraSettings().po_accounts == {"5b10ac", "6c20bd"}


def _label_hist(created: str, before: str, after: str, author: str = "po") -> dict:
    item = {"field": "labels", "fieldId": "labels", "fromString": before, "toString": after}
    return {"author": {"accountId": author}, "created": created, "items": [item]}


def test_label_removal_withdraws_po_approval() -> None:
    """Etiket sonradan kaldırılırsa önceki ekleme onay sayılmaz (anayasa I, MIMARI §6)."""
    add = _label_hist("2026-10-30T10:00:00.000+0000", "", PO_APPROVED_LABEL)
    remove = _label_hist("2026-10-30T11:00:00.000+0000", PO_APPROVED_LABEL, "")
    assert len(_changelog_jira([add]).po_approvals("TPD-1", ["po"])) == 1
    assert _changelog_jira([add, remove]).po_approvals("TPD-1", ["po"]) == []
    # Başka etiketin kaldırılması onayı etkilemez.
    other = _label_hist("2026-10-30T11:00:00.000+0000", f"{PO_APPROVED_LABEL} x", PO_APPROVED_LABEL)
    assert len(_changelog_jira([add, other]).po_approvals("TPD-1", ["po"])) == 1
    # label_history yine her eklemeyi gösterir (denetim), ama onay değildir.
    assert len(_changelog_jira([add, remove]).label_history("TPD-1", PO_APPROVED_LABEL)) == 1


def test_label_add_remove_add_counts_only_last_addition() -> None:
    add1 = _label_hist("2026-10-30T10:00:00.000+0000", "", PO_APPROVED_LABEL)
    remove = _label_hist("2026-10-30T11:00:00.000+0000", PO_APPROVED_LABEL, "")
    add2 = _label_hist("2026-10-30T12:00:00.000+0000", "", PO_APPROVED_LABEL)
    approvals = _changelog_jira([add1, remove, add2]).po_approvals("TPD-1", ["po"])
    assert [a.at for a in approvals] == [parse_jira_datetime("2026-10-30T12:00:00.000+0000")]
    # Aynı milisaniyede: changelog sırası belirleyicidir.
    ts = "2026-10-30T10:00:00.000+0000"
    a, r = _label_hist(ts, "", PO_APPROVED_LABEL), _label_hist(ts, PO_APPROVED_LABEL, "")
    assert _changelog_jira([a, r]).po_approvals("TPD-1", ["po"]) == []


def test_po_withdraws_approval_in_sim(sim: TestClient, jira: RestJira) -> None:
    _po_label(sim, "TPD-1", "add")
    assert len(jira.po_approvals("TPD-1", ["po@sim.local"])) == 1
    _po_label(sim, "TPD-1", "remove")
    assert PO_APPROVED_LABEL not in jira.get_issue("TPD-1").labels
    assert jira.po_approvals("TPD-1", ["po@sim.local"]) == []
    _po_label(sim, "TPD-1", "add")
    approvals = jira.po_approvals("TPD-1", ["po@sim.local"])
    assert len(approvals) == 1
    assert approvals[0].at == jira.label_history("TPD-1", PO_APPROVED_LABEL)[-1].at


def test_sim_ui_reapprove_restores_po_approval(sim: TestClient, jira: RestJira) -> None:
    """Sim arayüzünde 'Yeniden onayla' çekirdeğin saydığı taze bir PO onayı üretir."""
    import re

    r = sim.post("/giris", data={"password": PO_PASSWORD, "sonra": "/browse/TPD-1"})
    assert r.status_code == 200
    m = re.search(r'name="csrf" value="([^"]+)"', sim.get("/browse/TPD-1").text)
    assert m
    csrf = m.group(1)
    _po_label(sim, "TPD-1", "add")
    sim.post("/browse/TPD-1/description", data={"csrf": csrf, "text": "AC2 değişti"})
    assert jira.po_approvals("TPD-1", ["po@sim.local"]) == []
    sim.post("/browse/TPD-1/reapprove", data={"csrf": csrf})
    approvals = jira.po_approvals("TPD-1", ["po@sim.local"])
    assert [a.author for a in approvals] == ["po@sim.local"]
