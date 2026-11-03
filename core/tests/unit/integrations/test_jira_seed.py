"""``jira-seed``: bir prova sonrası Jira'yı demo başlangıcına döndürme (jira-sim'e karşı, ağsız).

Gerçek sitede ``/sim/reset`` yoktur; komut aynı ``RestJira`` kod yoluyla çalışır. Burada provanın
bıraktığı izler (yeniden yazılmış AC'ler, ``tp-po-*`` etiketleri, PO onayı, ``tp-<uuid>`` etiketli
Test/Bug kayıtları, tohum kayıtlarındaki yorumlar) simülatörde üretilir ve komutun hepsini geri
aldığı doğrulanır.
"""

from __future__ import annotations

import copy
import json
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from tp_core.features.requirements.content import requirement_hash
from tp_core.gateway import requirement_block
from tp_core.gateway.matching import input_mismatches
from tp_core.integrations import jira_seed
from tp_core.integrations.jira import (
    PO_APPROVED_LABEL,
    ReservedLabelError,
    RestJira,
)
from tp_core.integrations.jira_adf import (
    TEMPLATE_AC_HEADING,
    TEMPLATE_SECTIONS,
    adf_to_text,
    build_description,
    bullet_list,
    parse_description,
    template_doc,
    text_to_adf,
)
from tp_core.integrations.jira_seed import (
    DEMO_STORIES,
    SEED_BUGS,
    apply,
    is_run_label,
    main,
    plan,
)

REPO = Path(__file__).resolve().parents[4]
SIM_SRC = REPO / "sims" / "jira-sim" / "src"
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
            # apply-doc-fixes gibi: şablonun diğer bölümleri yerinde, yalnızca AC'ler değişir.
            "fields": {"description": build_description(parse_description(tpd1.adf())[0], acs)},
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


def test_delete_mode_removes_open_and_closed_run_issues_and_is_idempotent(
    sim: TestClient, jira: RestJira, capsys: pytest.CaptureFixture[str]
) -> None:
    """``make reset`` (``--onay --sil``): açık ve kapalı tüm koşu kayıtları silinir; tohum kayıtları
    (TPD-5 koşu etiketi taşısa da) ve ürünün olmayan kayıtlar kalır; ikinci plan boştur."""
    keys = _rehearse(sim)
    done = next(
        t for t in jira.transitions(keys["test"]) if t["to"]["statusCategory"]["key"] == "done"
    )
    jira.transition(keys["test"], done["id"])  # önceki provadan kapalı kalan koşu kaydı
    # Etiketsiz/AI-generated'sız kayıt: ürünün değil, kapalı olsa da dokunulmaz.
    foreign_closed = sim.post(
        "/rest/api/3/issue",
        json={"fields": {"project": {"key": "TPD"}, "issuetype": {"name": "Bug"}, "summary": "x"}},
        auth=WRITER,
    ).json()["key"]
    jira.transition(foreign_closed, done["id"])
    run_keys = sorted([keys["test"], keys["task_case"], keys["bug"]])

    p = plan(jira, "TPD")
    assert keys["test"] not in p.run_issues
    assert sorted(p.delete_targets) == run_keys
    assert main(["--sil"], jira=jira) == 0
    out = capsys.readouterr().out
    assert "Koşu kayıtları (silinecek, açık ve kapalı): " + ", ".join(p.delete_targets) in out
    assert "tp-<uuid> etiketi kaldırılacak" not in out

    assert main(["--onay", "--sil"], jira=jira) == 0
    capsys.readouterr()
    for k in run_keys:
        assert sim.get(f"/rest/api/3/issue/{k}", auth=WRITER).status_code == 404
    for k in (keys["foreign"], foreign_closed, *(f"TPD-{n}" for n in range(1, 8))):
        assert sim.get(f"/rest/api/3/issue/{k}", auth=WRITER).status_code == 200, k

    p = plan(jira, "TPD")
    assert p.empty and p.delete_targets == []
    assert main(["--onay", "--sil"], jira=jira) == 0
    assert "zaten demo başlangıcında" in capsys.readouterr().out


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
    # Kapatılamayan açık kayıt etiketini korur: sonraki reset/--sil onu yine tanır.
    assert any(jira_seed.TP_UUID_LABEL.match(lb) for lb in _fields(sim, keys["test"])["labels"])
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


# ------------------------------------------------------------- görev şablonu (TPD-1..TPD-4)


def test_demo_stories_follow_the_task_template() -> None:
    """Her story şablonun 7 bölümünü sırasıyla taşır; AC'li story ``template_doc`` ile aynı ADF."""
    titles = [title for _, title, _ in TEMPLATE_SECTIONS]
    for story in DEMO_STORIES:
        adf = story.adf()
        headings = [adf_to_text({"content": [n]}) for n in adf["content"] if n["type"] == "heading"]
        assert headings == titles, story.number
        desc, acs = parse_description(adf)
        assert acs == list(story.acceptance_criteria)
        assert story.paragraph in desc  # golden ``contains`` beyanı (Objective)
        if story.acceptance_criteria:
            sections = {**story.sections(), "acceptance_criteria": [bullet_list(acs)]}
            assert adf == template_doc(sections), story.number
    # TPD-2 (ac_missing): AC bölümü boş; "Not applicable" AC1 diye okunmaz.
    assert parse_description(DEMO_STORIES[1].adf())[1] == []


def test_demo_verisi_lists_every_story_template_verbatim() -> None:
    """docs/DEMO-VERISI.md, jira-sim tohumu ve jira_seed aynı içerik (üç yer)."""
    doc = (REPO / "docs" / "DEMO-VERISI.md").read_text(encoding="utf-8")
    for story in DEMO_STORIES:
        block = doc.split(f"**TPD-{story.number} açıklaması (görev şablonu):**", 1)[1]
        body = block.split("```text\n", 1)[1].split("\n```", 1)[0]
        assert body == story.text(), story.number


def _golden_specs() -> list[tuple[str, dict]]:
    out = []
    for path in sorted((REPO / "rules" / "replay").glob("*/golden/**/TPD-*.json")):
        spec = json.loads(path.read_text(encoding="utf-8")).get("input_match") or {}
        if any(src.startswith("jira:") for src in spec.get("sources") or []):
            out.append((str(path.relative_to(REPO / "rules" / "replay")), spec))
    return out


GOLDEN_SPECS = _golden_specs()


def test_golden_specs_cover_every_round_and_scenario() -> None:
    names = {n for n, _ in GOLDEN_SPECS}
    assert "consistency_check/golden/TPD-1-r2.json" in names
    assert "consistency_check/golden/f2-kod-hatasi/TPD-1-r2.json" in names
    assert "case_generation/golden/f2-kod-hatasi/TPD-1.json" in names
    assert len(names) == 14


@pytest.mark.parametrize(("name", "spec"), GOLDEN_SPECS, ids=[n for n, _ in GOLDEN_SPECS])
def test_template_story_still_matches_golden_input(
    name: str, spec: dict, sim: TestClient, jira: RestJira
) -> None:
    """Şablonlu story, golden'ın beyan ettiği AC'lerle (1. tur: tohum; 2. tur/senaryo: düzeltilmiş)
    Jira'ya ``update_description`` ile yazılıp geri okununca girdi beyanına birebir uyar.

    Yol üretimdekiyle aynıdır: jira-sim → ``RestJira.get_issue`` (``parse_description``) →
    ``requirement_block``; düzeltme ``build_description`` ile şablonun AC bölümüne yazılır.
    """
    key = spec["sources"][0].removeprefix("jira:")
    story = next(s for s in DEMO_STORIES if f"TPD-{s.number}" == key)
    before = jira.get_issue(key)
    declared = list(spec["acceptance_criteria"])
    if declared != list(before.acceptance_criteria):
        jira.update_description(key, before.description, declared)
    it = jira.get_issue(key)
    assert it.description == before.description  # diğer bölümler (QA Checklist dahil) yerinde
    assert list(it.acceptance_criteria) == declared
    block = requirement_block(
        summary=it.summary,
        description=it.description,
        acceptance_criteria=it.acceptance_criteria,
        jira_key=key,
    )
    assert input_mismatches(spec, [{"role": "user", "content": block}]) == [], name
    assert story.paragraph in it.description


def test_doc_fix_round_trip_keeps_template_and_hash(sim: TestClient, jira: RestJira) -> None:
    """apply-doc-fixes (F1/F3 → AC3): yazılan içerik yeniden okununca aynı hash'i verir; AC bölümü
    şablondaki yerinde (QA Checklist'ten önce) kalır, diğer bölümler değişmez."""
    before = jira.get_issue("TPD-1")
    acs = list(before.acceptance_criteria)
    acs[2] = (
        "AC3: Kampanyasız siparişlerde minimum sipariş tutarı 750,00 TL'dir; altında "
        '"Minimum sipariş tutarı 750,00 TL" uyarısı gösterilir ve onay butonu pasif olur.'
    )
    beklenen = requirement_hash(before.summary, before.description, acs)
    jira.update_description("TPD-1", before.description, acs)
    after = jira.get_issue("TPD-1")
    assert requirement_hash(after.summary, after.description, list(after.acceptance_criteria)) == (
        beklenen
    )
    assert after.description == before.description
    headings = [
        adf_to_text({"content": [n]})
        for n in _fields(sim, "TPD-1")["description"]["content"]
        if n["type"] == "heading"
    ]
    assert headings == [title for _, title, _ in TEMPLATE_SECTIONS]
    assert headings.index(TEMPLATE_AC_HEADING) == len(headings) - 2
    # İkinci düzeltme turu da aynı yapıyı korur (idempotent yeniden yazım).
    jira.update_description("TPD-1", after.description, list(after.acceptance_criteria))
    again = jira.get_issue("TPD-1")
    assert (again.description, list(again.acceptance_criteria)) == (after.description, acs)


def test_old_format_story_is_planned_for_rewrite(sim: TestClient, jira: RestJira) -> None:
    """Şablon öncesi biçimdeki TPD-1 (ör. eski tohum) ilk ``make reset``'te şablona döndürülür."""
    tpd1 = next(s for s in DEMO_STORIES if s.number == 1)
    eski = build_description(tpd1.paragraph, list(tpd1.acceptance_criteria))
    r = sim.put("/rest/api/3/issue/TPD-1", json={"fields": {"description": eski}}, auth=WRITER)
    assert r.status_code == 204, r.text
    p = plan(jira, "TPD")
    assert {s.key: s.restore_content for s in p.stories}["TPD-1"]
    apply(jira, p)
    assert _fields(sim, "TPD-1")["description"] == tpd1.adf()
    assert plan(jira, "TPD").empty


def test_run_labels_are_stripped_from_closed_and_newly_closed_issues(
    sim: TestClient, jira: RestJira, capsys: pytest.CaptureFixture[str]
) -> None:
    """Önceki provadan kapalı kalan Test'in tp-<uuid> etiketi de kaldırılır (yayın onu bulmasın)."""
    keys = _rehearse(sim)
    # Önceki bir reset'in etiketini bırakarak kapattığı kayıt.
    done = next(
        t for t in jira.transitions(keys["test"]) if t["to"]["statusCategory"]["key"] == "done"
    )
    jira.transition(keys["test"], done["id"])
    p = plan(jira, "TPD")
    assert keys["test"] not in p.run_issues and keys["test"] in p.run_labels
    assert main(["--onay"], jira=jira) == 0
    out = capsys.readouterr().out
    assert f"Kapalı koşu kayıtlarından tp-<uuid> etiketi kaldırılacak: {keys['test']}" in out
    for k in ("test", "task_case", "bug"):
        labels = _fields(sim, keys[k])["labels"]
        assert "AI-generated" in labels
        assert not any(jira_seed.TP_UUID_LABEL.match(lb) for lb in labels)
    assert "musteri-isi" in _fields(sim, keys["foreign"])["labels"]  # ürünün olmayan kayıt
    assert plan(jira, "TPD").empty


# ------------------------------------------------------- tohum Bug'ları (TPD-5..TPD-7, şablon)

# Şablon öncesi serbest metin (eski tohum; gerçek Jira'da ilk ``make reset``'e kadar bu durur).
# Mükerrer araması terimleri bu cümlelere çarptığı için her cümle şablonda birebir korunur.
OLD_SEED_BUGS = {
    5: '"6 al 1 bedava" kampanyası bir adet erken başlıyor: 6 adet alımda bedava ürün '
    "veriliyor. Kampanya 7. adette başlamalı (6 öde + 1 bedava).\n\n"
    "Adımlar:\n"
    "1. bayi1 ile giriş yap\n"
    "2. Portakal Gazozu 1L ürününden 6 adet sepete ekle\n"
    "3. Sepetteki bedava adet ve indirim satırını kontrol et\n\n"
    "Beklenen: bedava 0 adet, indirim 0,00 TL, toplam 150,00 TL.\n"
    "Gerçekleşen: bedava 1 adet, indirim 25,00 TL, toplam 125,00 TL.",
    6: "Sipariş geçmişi tablosunda en eski sipariş en üstte listeleniyor; en yeni sipariş "
    "en üstte olmalı.",
    7: "Hatalı parolada mesaj Türkçe yerine İngilizce gösteriliyordu. Düzeltildi.",
}


def test_seed_bugs_match_simulator_seed() -> None:
    """jira_seed'in yazdığı tohum Bug'ları jira-sim tohumuyla birebir aynı ADF ve özet."""
    issues = initial_state()["issues"]
    assert [b.number for b in SEED_BUGS] == [5, 6, 7]
    for bug in SEED_BUGS:
        seeded = issues[f"TPD-{bug.number}"]
        assert seeded["issuetype"] == "Bug"
        assert bug.summary == seeded["summary"]
        assert bug.adf() == seeded["description"]
    assert issues["TPD-7"]["status"] == "Done"


def test_seed_bugs_follow_the_template_and_keep_old_sentences() -> None:
    """7 bölüm sırasıyla; eski açıklamanın her satırı (başlık "Adımlar:" hariç) şablonda birebir."""
    titles = [title for _, title, _ in TEMPLATE_SECTIONS]
    for bug in SEED_BUGS:
        adf = bug.adf()
        headings = [adf_to_text({"content": [n]}) for n in adf["content"] if n["type"] == "heading"]
        assert headings == titles, bug.number
        text = bug.text()
        for line in OLD_SEED_BUGS[bug.number].splitlines():
            if line and line != "Adımlar:":
                assert line in text, (bug.number, line)
    assert "- Story: TPD-1" in SEED_BUGS[0].text()


def test_demo_verisi_lists_every_seed_bug_template_verbatim() -> None:
    doc = (REPO / "docs" / "DEMO-VERISI.md").read_text(encoding="utf-8")
    for bug in SEED_BUGS:
        block = doc.split(f"**TPD-{bug.number} açıklaması (görev şablonu, Bug):**", 1)[1]
        body = block.split("```text\n", 1)[1].split("\n```", 1)[0]
        assert body == bug.text(), bug.number


def test_old_format_seed_bugs_are_restored_and_idempotent(
    sim: TestClient, jira: RestJira, capsys: pytest.CaptureFixture[str]
) -> None:
    """Gerçek Jira'da TPD-5..7 eski serbest metinde: ``jira-seed`` planlar, yalnızca içeriği
    yazar (durum ve etiketler yerinde, TPD-7 "Done" kalır); ikinci plan boştur."""
    for n, text in OLD_SEED_BUGS.items():
        r = sim.put(
            f"/rest/api/3/issue/TPD-{n}",
            json={"fields": {"description": text_to_adf(text)}},
            auth=WRITER,
        )
        assert r.status_code == 204, r.text
    r = sim.put(
        "/rest/api/3/issue/TPD-6",
        json={
            "fields": {"summary": "Sipariş geçmişi sıralaması"},
            "update": {"labels": [{"add": "x"}]},
        },
        auth=WRITER,
    )
    assert r.status_code == 204, r.text

    p = plan(jira, "TPD")
    assert p.bugs == ["TPD-5", "TPD-6", "TPD-7"]
    assert not any(s.needed for s in p.stories) and not p.empty
    assert main([], jira=jira) == 0
    out = capsys.readouterr().out
    assert "Tohum Bug'ları (özet/açıklama tohum içeriğine döndürülecek): TPD-5, TPD-6, TPD-7" in out

    assert main(["--onay"], jira=jira) == 0
    assert "Döndürülen tohum Bug'ları: TPD-5, TPD-6, TPD-7" in capsys.readouterr().out
    seed = initial_state()["issues"]
    for n in (5, 6, 7):
        f = _fields(sim, f"TPD-{n}")
        assert f["summary"] == seed[f"TPD-{n}"]["summary"]
        assert f["description"] == seed[f"TPD-{n}"]["description"]
        assert f["status"]["name"] == seed[f"TPD-{n}"]["status"]
    assert _fields(sim, "TPD-6")["labels"] == ["x"]  # etiketlere dokunulmaz

    # İkinci çalıştırma: değişecek bir şey kalmadı.
    p = plan(jira, "TPD")
    assert p.empty and p.bugs == []
    assert "  Tohum Bug'ları tohum içeriğinde, değişiklik yok" in p.lines()
    assert main(["--onay"], jira=jira) == 0
    assert "zaten demo başlangıcında" in capsys.readouterr().out


def test_missing_seed_bug_is_reported(sim: TestClient, jira: RestJira) -> None:
    r = sim.delete("/rest/api/3/issue/TPD-6", auth=WRITER)
    assert r.status_code == 204, r.text
    p = plan(jira, "TPD")
    assert "TPD-6" in p.missing and p.bugs == []
    assert main(["--onay"], jira=jira) == 1
