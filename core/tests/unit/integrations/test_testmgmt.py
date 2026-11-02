"""JiraTestManagement, jira-sim'e karşı süreç içinde."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from tp_core import ports
from tp_core.integrations.jira import JiraSettings, RestJira
from tp_core.integrations.jira_adf import (
    NOT_APPLICABLE,
    TEMPLATE_SECTIONS,
    adf_to_text,
    inline_text,
)
from tp_core.integrations.testmgmt import (
    CaseContent,
    JiraTestManagement,
    TestManagementError,
    case_description_adf,
    case_description_text,
    get_test_management,
)

SIM_SRC = Path(__file__).resolve().parents[4] / "sims" / "jira-sim" / "src"
if str(SIM_SRC) not in sys.path:
    sys.path.insert(0, str(SIM_SRC))

from jira_sim.app import create_app  # noqa: E402

BASE = "http://jira-sim:8090"


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


READ = ("reader@sim.local", "x")


@pytest.fixture
def sim() -> Iterator[TestClient]:
    with TestClient(
        create_app(data_path="", base_url=BASE, po_password="po-test-parola"), base_url=BASE
    ) as client:
        yield client


@pytest.fixture
def jira(sim: TestClient) -> RestJira:
    return RestJira(
        BASE,
        ("reader@sim.local", "t"),
        ("writer@sim.local", "t"),
        http=httpx.Client(transport=SimTransport(sim)),
        sleep=lambda _: None,
    )


def make_case(case_id: UUID | None = None, **over: Any) -> dict[str, Any]:
    case = {
        "id": str(case_id or uuid4()),
        "title": "Kampanya: 7 adette 1 bedava uygulanır",
        "type": "positive",
        "risk": "high",
        "acceptance_criteria_refs": ["AC2"],
        "preconditions": ["bayi1 ile giriş yapılmış"],
        "steps": [
            {"id": "S1", "action": "Kataloğu aç", "data": None, "expected": "Ürünler listelenir"},
            {
                "id": "S2",
                "action": "Portakal Gazozu 1L ekle",
                "data": "7 adet",
                "expected": "1 adet bedava",
            },
        ],
        "expected_result": "Sepette 1 adet bedava ve 25,00 TL indirim görünür",
        "tags": ["AI-generated"],
        "approved_by": "analist",
        "content_hash": "abc123",
    }
    case.update(over)
    return case


def _sections(desc: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Seviye-3 başlık → altındaki bloklar (son bölüm kimlik satırını da içerir)."""
    out: dict[str, list[dict[str, Any]]] = {}
    current: list[dict[str, Any]] = []
    for node in desc["content"]:
        if node["type"] == "heading":
            current = out.setdefault(inline_text(node), [])
        else:
            current.append(node)
    return out


def _text(blocks: list[dict[str, Any]]) -> str:
    return adf_to_text({"type": "doc", "content": blocks})


def test_description_follows_task_template() -> None:
    cid = uuid4()
    case = CaseContent.from_mapping(make_case(cid, uretim_modu="REPLAY (kayıtlı)"))
    desc = case_description_adf(case, "TPD-1")
    headings = [inline_text(n) for n in desc["content"] if n["type"] == "heading"]
    assert headings == [title for _, title, _ in TEMPLATE_SECTIONS]
    assert all(n["attrs"]["level"] == 3 for n in desc["content"] if n["type"] == "heading")
    assert desc["content"][0]["type"] == "heading"  # önsöz yok, ilk blok Objective

    sec = _sections(desc)
    objective = _text(sec["🎯 Objective (Amaç)"])
    assert "Kampanya: 7 adette 1 bedava uygulanır" in objective
    assert "onaylayan: analist" in objective
    scope = _text(sec["🚀 Scope (Kapsam)"])
    assert "Test türü: pozitif" in scope and "Risk: yüksek" in scope and "AC2" in scope
    flow = sec["🔄 User Flow (Kullanıcı Akışı)"]
    assert "bayi1 ile giriş yapılmış" in _text(flow)
    assert [n["type"] for n in flow].count("table") == 1
    deps = _text(sec["🔗 Dependencies & Integration (Bağımlılıklar ve Entegrasyon)"])
    assert deps == "Kaynak story: TPD-1"
    other = _text(sec["ℹ️ Other Information & Assets (Diğer Bilgiler & Kaynaklar)"])
    assert other == "Üretim modu: REPLAY (kayıtlı)"
    ac = _text(sec["🔑 Acceptance Criteria (Kabul Kriterleri)"])
    assert "Sepette 1 adet bedava ve 25,00 TL indirim görünür" in ac and "AC2" in ac
    qa = sec["🧪 QA Checklist"]
    assert qa[0]["type"] == "bulletList" and len(qa[0]["content"]) == 2
    assert "Adım 2: 1 adet bedava" in _text(qa)
    # Kimlik/hash izi son paragraf, biçimi değişmedi (yayın bu satırı arar).
    assert _text([desc["content"][-1]]) == f"Kimlik: tp-{cid} · onaylanan içerik hash: abc123"


def test_description_template_fills_missing_sections() -> None:
    case = CaseContent.from_mapping(
        make_case(
            type=None,
            risk=None,
            acceptance_criteria_refs=[],
            preconditions=[],
            steps=[{"action": "Aç", "expected": ""}],
            expected_result="",
            approved_by=None,
            content_hash=None,
        )
    )
    sec = _sections(case_description_adf(case, ""))
    for title in (
        "🚀 Scope (Kapsam)",
        "🔗 Dependencies & Integration (Bağımlılıklar ve Entegrasyon)",
        "ℹ️ Other Information & Assets (Diğer Bilgiler & Kaynaklar)",
        "🔑 Acceptance Criteria (Kabul Kriterleri)",
    ):
        assert _text(sec[title]) == NOT_APPLICABLE, title
    qa = _text(sec["🧪 QA Checklist"])
    assert qa.startswith(NOT_APPLICABLE) and qa.endswith(f"Kimlik: {case.tp_label}")
    assert "insan onayından geçti" in _text(sec["🎯 Objective (Amaç)"])


def test_description_text_without_steps_table_for_xray() -> None:
    case = CaseContent.from_mapping(make_case())
    text = case_description_text(case, "TPD-1", steps_table=False)
    assert "Adımlar Xray test adımlarında (2 adım)." in text
    assert "Adım | Veri" not in text
    assert "🔄 User Flow (Kullanıcı Akışı)" in text and "Kaynak story: TPD-1" in text


def test_implements_port(jira: RestJira) -> None:
    assert isinstance(JiraTestManagement(jira, "TPD"), ports.TestManagementPort)


def test_publish_creates_test_issue_with_table_labels_and_link(
    sim: TestClient, jira: RestJira
) -> None:
    tm = JiraTestManagement(jira, "TPD")
    cid = uuid4()
    assert tm.find_existing(cid) is None
    pub = tm.publish_case(make_case(cid), "TPD-1")
    assert pub.case_id == cid
    assert pub.url == f"{BASE}/browse/{pub.external_key}"
    assert tm.find_existing(cid) == pub.external_key

    raw = sim.get(f"/rest/api/3/issue/{pub.external_key}", auth=READ).json()
    f = raw["fields"]
    assert f["issuetype"]["name"] == "Test"
    assert f["summary"] == "Kampanya: 7 adette 1 bedava uygulanır"
    assert f["labels"] == ["AI-generated", f"tp-{cid}"]
    desc = f["description"]
    tables = [n for n in desc["content"] if n["type"] == "table"]
    assert len(tables) == 1
    header = [
        adf_to_text({"type": "doc", "content": c["content"]})
        for c in tables[0]["content"][0]["content"]
    ]
    assert header == ["#", "Adım", "Veri", "Beklenen"]
    assert len(tables[0]["content"]) == 3  # başlık + 2 adım
    text = adf_to_text(desc)
    assert "Kaynak story: TPD-1" in text
    assert "onaylayan: analist" in text
    assert "1 adet bedava" in text and "7 adet" in text
    assert f"tp-{cid}" in text and "abc123" in text

    story = sim.get("/rest/api/3/issue/TPD-1", auth=READ).json()
    links = story["fields"]["issuelinks"]
    assert links[0]["type"]["name"] == "Test"
    assert links[0]["type"]["inward"] == "is tested by"
    assert links[0]["inwardIssue"]["key"] == pub.external_key


def test_publish_is_idempotent(sim: TestClient, jira: RestJira) -> None:
    tm = JiraTestManagement(jira, "TPD")
    case = make_case()
    first = tm.publish_case(case, "TPD-1")
    second = JiraTestManagement(jira, "TPD").publish_case(case, "TPD-1")
    assert first.external_key == second.external_key
    tests = sim.get(
        "/rest/api/3/search/jql", params={"jql": "issuetype = Test", "fields": "summary"}, auth=READ
    ).json()["issues"]
    assert len(tests) == 1
    links = sim.get("/rest/api/3/issue/TPD-1", auth=READ).json()["fields"]["issuelinks"]
    assert len(links) == 1


def test_fallback_to_task_and_relates(sim: TestClient, jira: RestJira) -> None:
    sim.post(
        "/sim/config",
        json={"issue_types": ["Story", "Task", "Bug"], "link_types": ["Relates", "Blocks"]},
    )
    tm = JiraTestManagement(jira, "TPD")
    pub = tm.publish_case(make_case(), "TPD-1")
    raw = sim.get(f"/rest/api/3/issue/{pub.external_key}", auth=READ).json()["fields"]
    assert raw["issuetype"]["name"] == "Task"
    assert "test-case" in raw["labels"] and "AI-generated" in raw["labels"]
    link = sim.get("/rest/api/3/issue/TPD-1", auth=READ).json()["fields"]["issuelinks"][0]
    assert link["type"]["name"] == "Relates"


class _NoMeta:
    """Meta veri yardımcıları olmayan bir JiraPort (ör. başka bir uygulama)."""

    def __init__(self, inner: RestJira) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        if name in ("issue_types", "link_type_names", "issue_url"):
            raise AttributeError(name)
        return getattr(self._inner, name)


def test_fallback_via_errors_without_metadata(sim: TestClient, jira: RestJira) -> None:
    sim.post(
        "/sim/config", json={"issue_types": ["Story", "Task", "Bug"], "link_types": ["Relates"]}
    )
    tm = JiraTestManagement(_NoMeta(jira), "TPD")  # type: ignore[arg-type]
    pub = tm.publish_case(make_case(), "TPD-2")
    assert pub.url is None
    raw = sim.get(f"/rest/api/3/issue/{pub.external_key}", auth=READ).json()["fields"]
    assert raw["issuetype"]["name"] == "Task"
    link = sim.get("/rest/api/3/issue/TPD-2", auth=READ).json()["fields"]["issuelinks"][0]
    assert link["type"]["name"] == "Relates"


def test_no_usable_link_type_reports_partial_success(sim: TestClient, jira: RestJira) -> None:
    sim.post("/sim/config", json={"link_types": ["Blocks"]})
    tm = JiraTestManagement(jira, "TPD")
    with pytest.raises(TestManagementError) as err:
        tm.publish_case(make_case(), "TPD-1")
    assert err.value.external_key is not None  # issue oluştu, bağlantı kurulamadı


def test_missing_story_link_fails(jira: RestJira) -> None:
    tm = JiraTestManagement(jira, "TPD")
    with pytest.raises(TestManagementError):
        tm.publish_case(make_case(), "TPD-999")


def test_case_content_accepts_nested_and_rejects_invalid() -> None:
    cid = uuid4()
    nested = {"id": str(cid), "icerik": {k: v for k, v in make_case().items() if k != "id"}}
    c = CaseContent.from_mapping(nested)
    assert c.case_id == cid and len(c.steps) == 2
    with pytest.raises(TestManagementError):
        CaseContent.from_mapping({"title": "kimliksiz"})


def test_factory_selects_backend(monkeypatch: pytest.MonkeyPatch, jira: RestJira) -> None:
    monkeypatch.setenv("TP_TEST_MGMT", "jira")
    tm = get_test_management(JiraSettings(), jira=jira)
    assert tm.name == "jira"
    monkeypatch.setenv("TP_TEST_MGMT", "xray")
    monkeypatch.setenv("JIRA_BASE_URL", "")
    monkeypatch.setenv("XRAY_CLIENT_ID", "")
    tm = get_test_management(JiraSettings(), jira=jira)
    assert tm.name == "xray"
