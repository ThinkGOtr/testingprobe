"""``jira-seed``: bir prova sonrası Jira'yı demo başlangıcına döndürme (jira-sim'e karşı, ağsız).

Gerçek sitede ``/sim/reset`` yoktur; komut aynı ``RestJira`` kod yoluyla çalışır. Burada provanın
bıraktığı izler (yeniden yazılmış AC'ler, ``tp-po-*`` etiketleri, PO onayı, ``tp-<uuid>`` etiketli
Test/Bug kayıtları, tohum kayıtlarındaki yorumlar) simülatörde üretilir ve komutun hepsini geri
aldığı doğrulanır.
"""

from __future__ import annotations

import copy
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from tp_core.integrations import jira_seed
from tp_core.integrations.jira import (
    PO_APPROVED_LABEL,
    ReservedLabelError,
    RestJira,
)
from tp_core.integrations.jira_adf import build_description, text_to_adf
from tp_core.integrations.jira_seed import DEMO_STORIES, apply, is_run_label, main, plan

SIM_SRC = Path(__file__).resolve().parents[4] / "sims" / "jira-sim" / "src"
if str(SIM_SRC) not in sys.path:
    sys.path.insert(0, str(SIM_SRC))

from jira_sim.app import create_app  # noqa: E402
from jira_sim.seed import initial_state  # noqa: E402

BASE = "http://jira-sim:8090"
PO_PASSWORD = "po-test-parola"
WRITER = ("writer@sim.local", "t")
PO_AUTH = ("po@sim.local", PO_PASSWORD)


class SimTransport(httpx.BaseTransport):
    def __init__(self, sim: TestClient) -> None:
        self.sim = sim
        self.writes: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != "GET" and not request.url.path.endswith("/search/jql"):
            self.writes.append(f"{request.method} {request.url.path}")
        r = self.sim.request(
            request.method, str(request.url), headers=dict(request.headers), content=request.read()
        )
        return httpx.Response(r.status_code, headers=dict(r.headers), content=r.content)


@pytest.fixture
def sim() -> Iterator[TestClient]:
    with TestClient(
        create_app(data_path="", base_url=BASE, po_password=PO_PASSWORD), base_url=BASE
    ) as client:
        yield client


@pytest.fixture
def transport(sim: TestClient) -> SimTransport:
    return SimTransport(sim)


@pytest.fixture
def jira(transport: SimTransport) -> RestJira:
    return RestJira(BASE, ("reader@sim.local", "t"), WRITER, http=httpx.Client(transport=transport))


@pytest.fixture(autouse=True)
def _sim_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", BASE)
    monkeypatch.setenv("JIRA_PROJECT", "TPD")


def _fields(sim: TestClient, key: str) -> dict:
    r = sim.get(f"/rest/api/3/issue/{key}", auth=WRITER)
    assert r.status_code == 200, r.text
    return r.json()["fields"]


def _rehearse(sim: TestClient) -> dict[str, str]:
    """Bir provanın Jira'da bıraktıkları (apply-doc-fixes, PO onayı, case/bug aktarımı)."""
    tpd1 = next(s for s in DEMO_STORIES if s.number == 1)
    acs = list(tpd1.acceptance_criteria)
    acs[1] = "AC2: Kampanyalı üründen her 6 adette 1 adet bedava verilir (12 adette 2 bedava)."
    acs[2] = "AC3: Kampanyasız siparişlerde minimum sipariş tutarı 500,00 TL'dir."
    r = sim.put(
        "/rest/api/3/issue/TPD-1",
        json={
            "fields": {"description": build_description(tpd1.paragraph, acs)},
            "update": {"labels": [{"add": "tp-po-pending"}, {"add": "AI-generated"}]},
        },
        auth=WRITER,
    )
    assert r.status_code == 204, r.text
    r = sim.put(
        "/rest/api/3/issue/TPD-1",
        json={"update": {"labels": [{"add": PO_APPROVED_LABEL}]}},
        auth=PO_AUTH,
    )
    assert r.status_code == 204, r.text
    r = sim.put(
        "/rest/api/3/issue/TPD-4",
        json={"update": {"labels": [{"remove": "tp-demo"}, {"add": "tp-po-pending"}]}},
        auth=WRITER,
    )
    assert r.status_code == 204, r.text

    def create(issue_type: str, labels: list[str]) -> str:
        r = sim.post(
            "/rest/api/3/issue",
            json={
                "fields": {
                    "project": {"key": "TPD"},
                    "issuetype": {"name": issue_type},
                    "summary": f"[AI-generated] {issue_type}",
                    "labels": labels,
                }
            },
            auth=WRITER,
        )
        assert r.status_code == 201, r.text
        return r.json()["key"]

    run = f"tp-{uuid.uuid4()}"
    keys = {
        "test": create("Test", ["AI-generated", run]),
        "task_case": create("Task", ["AI-generated", "test-case", f"tp-{uuid.uuid4()}"]),
        "bug": create("Bug", ["AI-generated", f"tp-{uuid.uuid4()}"]),
        "foreign": create("Task", ["musteri-isi"]),  # ürünün olmayan kayıt: dokunulmaz
    }
    # Ürünün yorumları (PO sorusu, kanıt yorumu) ve PO cevabı; koşu kaydının yorumu tohum dışı.
    for key, auth, text in (
        ("TPD-1", WRITER, "🤖 AI Testing Probe: PO teyidi"),
        ("TPD-1", PO_AUTH, "Onaylıyorum."),
        ("TPD-5", WRITER, "🤖 AI Testing Probe: kanıt"),
        (keys["bug"], WRITER, "🤖 AI Testing Probe: koşu"),
    ):
        r = sim.post(
            f"/rest/api/3/issue/{key}/comment", json={"body": text_to_adf(text)}, auth=auth
        )
        assert r.status_code == 201, r.text
    # Tohum Bug'ına koşu etiketi düşmüş olsa bile tohum kaydı kapatılmaz.
    r = sim.put("/rest/api/3/issue/TPD-5", json={"update": {"labels": [{"add": run}]}}, auth=WRITER)
    assert r.status_code == 204, r.text
    return keys


def test_demo_stories_match_simulator_seed() -> None:
    """Gerçek Jira'ya yazılan içerik jira-sim tohumuyla birebir aynı ADF (aynı golden girdisi)."""
    issues = initial_state()["issues"]
    for story in DEMO_STORIES:
        seeded = issues[f"TPD-{story.number}"]
        assert seeded["issuetype"] == "Story"
        assert story.summary == seeded["summary"]
        assert story.adf() == seeded["description"]
        assert seeded["labels"] == ["tp-demo"]


def test_run_label_classification() -> None:
    assert is_run_label("tp-po-pending")
    assert is_run_label(PO_APPROVED_LABEL)
    assert is_run_label("AI-generated")
    assert is_run_label(f"tp-{uuid.uuid4()}")
    assert not is_run_label("tp-demo")
    assert not is_run_label("tp-bir-sey")
    assert not is_run_label("musteri-isi")


def test_fresh_project_needs_nothing(jira: RestJira, transport: SimTransport) -> None:
    p = plan(jira, "TPD")
    assert p.empty
    assert [s.key for s in p.stories] == ["TPD-1", "TPD-2", "TPD-3", "TPD-4"]
    assert main([], jira=jira) == 0
    assert main(["--onay"], jira=jira) == 0
    assert transport.writes == []


def test_dry_run_reports_plan_and_writes_nothing(
    sim: TestClient, jira: RestJira, transport: SimTransport, capsys: pytest.CaptureFixture[str]
) -> None:
    keys = _rehearse(sim)
    before = _fields(sim, "TPD-1")
    transport.writes.clear()

    assert main([], jira=jira) == 0
    out = capsys.readouterr().out
    assert "Kuru çalışma" in out
    assert "TPD-1: özet/açıklama/kabul kriterleri DEMO-VERISI'ye döndürülecek" in out
    assert PO_APPROVED_LABEL in out
    assert transport.writes == []
    assert _fields(sim, "TPD-1") == before

    p = plan(jira, "TPD")
    assert sorted(p.run_issues) == sorted([keys["test"], keys["task_case"], keys["bug"]])
    by_key = {s.key: s for s in p.stories}
    assert by_key["TPD-1"].restore_content
    assert by_key["TPD-1"].remove_labels == sorted(
        ["AI-generated", PO_APPROVED_LABEL, "tp-po-pending"]
    )
    assert not by_key["TPD-2"].needed
    assert by_key["TPD-4"].add_demo_label and not by_key["TPD-4"].restore_content
    assert {k: len(v) for k, v in p.comments.items()} == {"TPD-1": 2, "TPD-5": 1}
    assert "Silinecek yorumlar: TPD-1 (2), TPD-5 (1)" in out
    assert len(jira.get_comments("TPD-1")) == 2


def test_apply_restores_demo_start_and_is_idempotent(
    sim: TestClient, jira: RestJira, capsys: pytest.CaptureFixture[str]
) -> None:
    keys = _rehearse(sim)
    seed = initial_state()["issues"]
    # Provada PO yeniden yazılmış içeriği onayladı; seed bu onayı da geri almalı.
    assert len(jira.po_approvals("TPD-1", ["po@sim.local"])) == 1

    assert main(["--onay"], jira=jira) == 0
    out = capsys.readouterr().out
    assert "Döndürülen story'ler: TPD-1, TPD-4" in out
    assert "Silinen yorumlar: 3" in out
    for n in range(1, 8):
        assert jira.get_comments(f"TPD-{n}") == []
    assert len(jira.get_comments(keys["bug"])) == 1  # koşu kaydı kapanır, yorumuna dokunulmaz

    for n in (1, 2, 3, 4):
        f = _fields(sim, f"TPD-{n}")
        assert f["summary"] == seed[f"TPD-{n}"]["summary"]
        assert f["description"] == seed[f"TPD-{n}"]["description"]
        assert f["labels"] == ["tp-demo"]
    issue = jira.get_issue("TPD-1")
    assert issue.acceptance_criteria[1].startswith('AC2: "6 al 1 bedava"')
    # Bayat PO onayı geri çekildi: yeni koşu PO'nun yeniden onaylamasını bekler.
    assert jira.po_approvals("TPD-1", ["po@sim.local"]) == []

    for k in ("test", "task_case", "bug"):
        assert _fields(sim, keys[k])["status"]["statusCategory"]["key"] == "done"
    assert _fields(sim, keys["foreign"])["status"]["name"] == "To Do"
    assert _fields(sim, "TPD-5")["status"]["name"] == "To Do"  # tohum kaydı

    # İkinci çalıştırma: değişecek bir şey kalmadı.
    assert plan(jira, "TPD").empty
    assert main(["--onay"], jira=jira) == 0
    assert "zaten demo başlangıcında" in capsys.readouterr().out


def test_delete_mode_removes_run_issues(sim: TestClient, jira: RestJira) -> None:
    keys = _rehearse(sim)
    r = apply(jira, plan(jira, "TPD"), delete=True)
    assert sorted(r.deleted) == sorted([keys["test"], keys["task_case"], keys["bug"]])
    assert r.failed == []
    for k in ("test", "task_case", "bug"):
        assert sim.get(f"/rest/api/3/issue/{keys[k]}", auth=WRITER).status_code == 404
    assert sim.get(f"/rest/api/3/issue/{keys['foreign']}", auth=WRITER).status_code == 200


def test_missing_story_and_failed_transition_are_reported(
    sim: TestClient, jira: RestJira, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys = _rehearse(sim)
    assert sim.delete("/rest/api/3/issue/TPD-2", auth=WRITER).status_code == 204
    p = plan(jira, "TPD")
    assert p.missing == ["TPD-2"]
    # "Done" kategorisine geçiş olmayan iş akışı: kayıt kapatılamaz, hata raporlanır.
    real = jira.transitions

    def no_done(key: str) -> list[dict]:
        return [t for t in real(key) if t["to"]["statusCategory"]["key"] != "done"]

    monkeypatch.setattr(jira, "transitions", no_done)
    r = apply(jira, p)
    assert r.closed == []
    assert any(f.startswith(keys["test"]) for f in r.failed)
    assert main(["--onay"], jira=jira) == 1


def test_edit_issue_refuses_reserved_label_but_removes_it(sim: TestClient, jira: RestJira) -> None:
    with pytest.raises(ReservedLabelError):
        jira.edit_issue("TPD-1", add_labels=[PO_APPROVED_LABEL])
    sim.put(
        "/rest/api/3/issue/TPD-1",
        json={"update": {"labels": [{"add": PO_APPROVED_LABEL}]}},
        auth=PO_AUTH,
    )
    jira.edit_issue("TPD-1", remove_labels=[PO_APPROVED_LABEL])
    assert PO_APPROVED_LABEL not in jira.get_issue("TPD-1").labels


def test_failed_comment_delete_is_reported(
    sim: TestClient, jira: RestJira, monkeypatch: pytest.MonkeyPatch
) -> None:
    _rehearse(sim)
    p = plan(jira, "TPD")

    def refuse(key: str, comment_id: str) -> None:
        raise jira_seed.JiraError("403 yetki yok", status=403)

    monkeypatch.setattr(jira, "delete_comment", refuse)
    r = apply(jira, p)
    assert r.comments_deleted == 0
    assert len([f for f in r.failed if " yorum " in f]) == 3


def test_sim_comment_delete_unknown_id_is_404(sim: TestClient) -> None:
    assert sim.delete("/rest/api/3/issue/TPD-1/comment/999999", auth=WRITER).status_code == 404


def test_transitions_round_trip(jira: RestJira) -> None:
    names = {t["to"]["name"] for t in jira.transitions("TPD-5")}
    assert names == {"In Progress", "Done"}
    done = next(t for t in jira.transitions("TPD-5") if t["name"] == "Done")
    jira.transition("TPD-5", done["id"])
    assert jira.get_issue("TPD-5").status == "Done"


def test_text_content_compare_ignores_adf_attrs(sim: TestClient, jira: RestJira) -> None:
    """Gerçek Jira ADF'ye ``localId`` ekler; aynı metin yeniden yazılmaz."""
    adf = copy.deepcopy(text_to_adf(DEMO_STORIES[3].text()))
    adf["content"][0]["attrs"] = {"localId": "abc"}
    assert jira_seed.adf_to_text(adf) == jira_seed.adf_to_text(DEMO_STORIES[3].adf())
