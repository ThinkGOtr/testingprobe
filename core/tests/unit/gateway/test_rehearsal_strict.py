"""Prova kipi (`TP_REPLAY_STRICT=1`): sunumun ANA yolu (`f2-kod-hatasi`, docs/DEMO-VERISI.md) baştan
sona tek geçit örneğinde REPLAY-MISS'siz koşar (TEKNIK-TASARIM §13 prova listesi).

Geçit ORTAMDAN kurulur (`build_gateway`: `TP_MODEL_MODE=replay`, `TP_REPLAY_STRICT=1`) — core-worker
ile aynı yol. Girdiler üretimin kurucularıdır: gereksinim akışının `Snapshot.message()` +
`replay_key_for` (ön inceleme, tutarlılık turları), case üretiminin `generation_messages` (PO
cevapları + test verisi blokları dahil), kod üretiminin `mapping_messages` (sembol tablosu dahil),
Faz 4'ün `gateway.defects` kurucuları (bug taslağı, mükerrer sıralaması). Story metni süreç içi
jira-sim'den `RestJira` ile okunur; doküman düzeltmeleri Jira'ya yazılıp yeniden çekilir.

Sıkı kipte golden'a düşmek yerine `ReplayMiss` fırlar; yani bu test geçiyorsa provadaki her AI
adımının girdisi kendi golden beyanına uyar. Ayrıca her satır dürüst etiketlidir: mod `replay`,
sağlayıcı `replay`, model `golden-elle` (elle hazırlanmış örnek), değerlendirme etiketi "canlı
değerlendirme bekliyor".
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.unit.gateway import defect_inputs as di
from tests.unit.gateway.test_codegen_goldens import _run_verify
from tests.unit.gateway.test_replay_matching import jira  # noqa: F401 (fikstür)
from tp_core.features.cases.service import generation_messages
from tp_core.features.cases.service import replay_key_for as case_replay_key_for
from tp_core.features.requirements.flow import Snapshot, replay_key_for
from tp_core.gateway import (
    ALLOWED_AGENT_TOOLS,
    HAND_PREPARED_MODEL,
    MATCHED,
    PENDING_LABEL,
    Gateway,
    defect_replay_key,
    load_schema,
)
from tp_core.gateway.config import GatewaySettings
from tp_core.gateway.factory import build_gateway
from tp_core.gateway.testing import InMemoryCallRecorder
from tp_core.integrations.jira import RestJira
from tp_core.models.requirements import Requirement
from tp_core.ports import JiraIssue, ToolSpec

SCENARIO = "f2-kod-hatasi"
CONSISTENCY_TOOLS = [
    ToolSpec(name=n, description=n, input_schema={"type": "object"})
    for n in sorted(ALLOWED_AGENT_TOOLS["consistency_check"])
]
# Ana yolun kullandığı golden'lar (docs/DEMO-VERISI.md "Ana demo yolu" tablosu).
MAIN_PATH_GOLDENS = {
    "requirement_review/golden/TPD-1.json",
    "consistency_check/golden/TPD-1.json",
    f"consistency_check/golden/{SCENARIO}/TPD-1-r2.json",
    f"case_generation/golden/{SCENARIO}/TPD-1.json",
    *(f"verify_and_map/golden/TPD-1-C{n}.json" for n in (1, 5, 6, 7, 8, 9, 10)),
    # Senaryoda C2 (7 adet = eşik, boundary), C3 (6 adette bedava yok) ve C4 (5 adet, positive)
    # ana golden'dan ayrışır (case metni/türü); tarayıcı kayıtları senaryo dizinindedir.
    *(f"verify_and_map/golden/{SCENARIO}/TPD-1-C{n}.json" for n in (2, 3, 4)),
    "bug_draft/golden/f2-kampanya/HATA.json",
    "dup_rank/golden/f2-kampanya/HATA.json",
    "bug_draft/golden/f4-kredi-limiti/HATA.json",
    "bug_draft/golden/HATA.json",
    "dup_rank/golden/HATA.json",
    "bug_draft/golden/kirma-kampanya/HATA.json",
    "dup_rank/golden/kirma-kampanya/HATA.json",
}
# PO'nun ön inceleme sorularına Jira'daki cevabı (case üretimi girdisinde ayrı blok).
PO_ANSWER = {"id": "10001", "metin": "AC3: kampanyasız siparişlerde 750,00 TL geçerlidir."}


@pytest.fixture
def strict_gateway(monkeypatch: pytest.MonkeyPatch, rules_dir) -> Gateway:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("TP_MODEL_MODE", "replay")
    monkeypatch.setenv("TP_REPLAY_STRICT", "1")
    monkeypatch.setenv("TP_RULES_DIR", str(rules_dir))
    gw = build_gateway(InMemoryCallRecorder(), settings=GatewaySettings())
    assert gw.mode == "replay" and gw.replay_store.strict and gw.provider is None
    return gw


def _snapshot(issue: JiraIssue, rid: uuid.UUID, tur: int = 1) -> Snapshot:
    return Snapshot(
        rid,
        "jira",
        issue.key,
        issue.summary,
        issue.description,
        list(issue.acceptance_criteria),
        "h",
        tur,
    )


def _review(gw: Gateway, snap: Snapshot):
    return gw.call(
        "requirement_review",
        "requirement-review",
        [snap.message()],
        load_schema(gw.rules_dir, "requirement_review"),
        replay_key=replay_key_for(gw, "requirement_review", snap),
    )


def _check(gw: Gateway, snap: Snapshot, tur: int):
    return gw.run_agent(
        "consistency_check",
        "consistency-check",
        [snap.message()],
        CONSISTENCY_TOOLS,
        lambda name, args: f"{name} sonucu",
        load_schema(gw.rules_dir, "consistency_check"),
        replay_key=replay_key_for(gw, "consistency_check", snap, tur),
    )


def _generate(gw: Gateway, issue: JiraIssue, questions: list[dict[str, Any]]):
    req = Requirement(
        id=uuid.uuid4(),
        kaynak="jira",
        jira_key=issue.key,
        baslik=issue.summary,
        aciklama=issue.description,
        kabul_kriterleri=list(issue.acceptance_criteria),
        po_cevaplari=[PO_ANSWER] if questions else [],
    )
    messages = generation_messages(req, questions, test_verisi=di.testdata_block())
    return gw.call(
        "case_generation",
        "case-generation",
        messages,
        load_schema(gw.rules_dir, "case_generation"),
        replay_key=case_replay_key_for(req),
    )


def _defect(gw: Gateway, purpose: str, messages) -> Any:
    return gw.call(
        purpose,
        purpose.replace("_", "-"),
        messages,
        load_schema(gw.rules_dir, purpose),
        replay_key=defect_replay_key("TPD-1"),
    )


def _demo_a(gw: Gateway, jira: RestJira) -> list[dict[str, Any]]:  # noqa: F811
    """Ana yolun Demo-A'sı: F1/F3 dokümanda düzeltilir, F2/F4 `code_defect`."""
    rid = uuid.uuid4()
    issue = jira.get_issue("TPD-1")
    review = _review(gw, _snapshot(issue, rid))
    first = _check(gw, _snapshot(issue, rid), 1)
    by_id = {f["id"]: f for f in first.output["findings"]}
    assert {by_id[f]["severity"] for f in ("F1", "F2", "F3", "F4")} == {"blocking"}
    acs = {a.split(":", 1)[0]: a for a in issue.acceptance_criteria}
    for fid in ("F1", "F3"):  # fix_doc
        text = by_id[fid]["suggested_doc_text"]
        acs[text.split(":", 1)[0]] = text
    jira.update_description(
        "TPD-1", issue.description, [acs[k] for k in sorted(acs, key=lambda r: int(r[2:]))]
    )
    issue = jira.get_issue("TPD-1")
    second = _check(gw, _snapshot(issue, rid, 2), 2)
    blocking = [f for f in second.output["findings"] if f["severity"] == "blocking"]
    assert all(f.get("type") != "internal_contradiction" for f in blocking)
    cases = _generate(gw, issue, list(review.output.get("questions") or []))
    return list(cases.output["cases"])


def test_main_rehearsal_path_runs_without_replay_miss_in_strict_mode(
    strict_gateway: Gateway,
    jira: RestJira,  # noqa: F811
) -> None:
    gw = strict_gateway
    recorder = gw.recorder
    assert isinstance(recorder, InMemoryCallRecorder)

    # Demo-A
    cases = _demo_a(gw, jira)
    assert len(cases) == 15  # 011 K17: C11–C15 sınır case'leri sona eklendi (sıra korunur)
    assert cases[2]["title"] == di.C3_TITLE

    # Demo-B: doğrulama ajanı kaydı olan C1–C10 (sahnede C1, C2, C3, C5; hepsi hazır). C11–C15'in
    # tarayıcı kaydı yok; prova kod üretimini onlarla çalıştırmaz.
    for n, case in enumerate(cases[:10], start=1):
        result, _calls, _streamed = _run_verify(gw, gw.rules_dir, case, n)
        assert result.mode == "replay", case["title"]

    # Faz 4: F2 code_defect → bug taslağı → TPD-5 bağla; F4 → taslak (JQL aday yok, sıralama yok).
    _defect(gw, "bug_draft", di.bug_messages(di.finding_sources("TPD-1", "F2")))
    dup_f2 = _defect(gw, "dup_rank", di.dup_messages(di.finding_sources("TPD-1", "F2"), ["TPD-5"]))
    assert (dup_f2.output["recommendation"], dup_f2.output["link_key"]) == ("link", "TPD-5")
    _defect(gw, "bug_draft", di.bug_messages(di.finding_sources("TPD-1", "F4")))
    # C3 defect adayı → triage kuralla product_defect (AI yok) → taslak → TPD-5 high + bağla.
    # Üretim C3'ün Test issue'sunu (TPD-10) ve kırmada C2'ninkini (TPD-9) da girdiye koyar.
    _defect(gw, "bug_draft", di.bug_messages(di.c3_sources(), test_case_key="TPD-10"))
    dup_c3 = _defect(gw, "dup_rank", di.dup_messages(di.c3_sources(), ["TPD-5"]))
    assert dup_c3.output["link_key"] == "TPD-5"
    # Kırarak doğrula (C2) kırmızı aşaması → taslak → TPD-5 medium + yeni kayıt.
    _defect(gw, "bug_draft", di.bug_messages(di.break_sources(0), test_case_key="TPD-9"))
    dup_break = _defect(gw, "dup_rank", di.dup_messages(di.break_sources(0), ["TPD-5"]))
    assert dup_break.output["recommendation"] == "new"

    rows = recorder.ai_calls
    assert rows
    for row in rows:
        where = (row["amac"], row["ek"].get("replay_kaynagi"))
        assert row["mod"] == "replay" and row["saglayici"] == "replay", where  # asla "live"
        assert row["ek"]["replay_kokeni"] == MATCHED, where
        assert "replay_eslesme" not in row["ek"], where
        assert row["model"] == HAND_PREPARED_MODEL, where  # elle hazırlanmış örnek, model değil
        assert row["ek"]["degerlendirme"]["etiket"] == PENDING_LABEL, where  # dürüst durum
    used = {row["ek"]["replay_kaynagi"] for row in rows}
    assert used == MAIN_PATH_GOLDENS, (
        f"eksik: {sorted(MAIN_PATH_GOLDENS - used)}; fazla: {sorted(used - MAIN_PATH_GOLDENS)}"
    )


@pytest.mark.parametrize("key", ["TPD-2", "TPD-3", "TPD-4"])
def test_other_seed_stories_rehearse_strict(
    strict_gateway: Gateway,
    jira: RestJira,  # noqa: F811
    key: str,
) -> None:
    """Sunumda açılabilecek diğer tohum story'leri de prova kipinde REPLAY'dir (TPD-2 PO'da kalır:
    kabul kriteri yok, case üretimine gelmez)."""
    gw = strict_gateway
    rid = uuid.uuid4()
    issue = jira.get_issue(key)
    review = _review(gw, _snapshot(issue, rid))
    check = _check(gw, _snapshot(issue, rid), 1)
    assert not [f for f in check.output["findings"] if f["severity"] == "blocking"]
    if issue.acceptance_criteria:
        _generate(gw, issue, list(review.output.get("questions") or []))
    rows = gw.recorder.ai_calls  # type: ignore[attr-defined]
    assert len(rows) == (3 if issue.acceptance_criteria else 2)
    assert {r["mod"] for r in rows} == {"replay"}
    assert {r["ek"]["degerlendirme"]["etiket"] for r in rows} == {PENDING_LABEL}


def test_second_demo_a_without_reset_is_an_honest_review_miss(
    strict_gateway: Gateway,
    jira: RestJira,  # noqa: F811
) -> None:
    """Prova yolu dışı (rules/replay/README.md "Bilinen sınır"): `make reset` olmadan ikinci
    Demo-A'da TPD-1 düzeltilmiş metindir; ön incelemenin bu metin için golden'ı yoktur. Sıkı kip
    `ReplayMiss` verir, gevşek kip dürüst nötr REPLAY-MISS döner (başka metnin soruları değil)."""
    from tp_core.gateway import ReplayMiss, ReplayStore

    _demo_a(strict_gateway, jira)
    fixed = jira.get_issue("TPD-1")
    with pytest.raises(ReplayMiss):
        _review(strict_gateway, _snapshot(fixed, uuid.uuid4()))
    loose = Gateway(
        provider=None,
        recorder=InMemoryCallRecorder(),
        mode="replay",
        models=strict_gateway.models,
        rules_dir=strict_gateway.rules_dir,
        replay_store=ReplayStore(strict_gateway.rules_dir / "replay"),
        record_extras=True,
    )
    result = _review(loose, _snapshot(fixed, uuid.uuid4()))
    assert result.mode == "replay_miss" and result.output["questions"] == []
    # Tutarlılık 1. turu ise senaryo golden'ıyla REPLAY olur (README "Arama sırası" 3b).
    assert _check(strict_gateway, _snapshot(fixed, uuid.uuid4()), 1).mode == "replay"
