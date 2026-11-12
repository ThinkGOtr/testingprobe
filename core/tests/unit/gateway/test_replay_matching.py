"""Golden girdi beyanı (`input_match`): senaryodaki Demo-A yolu REPLAY-MISS'siz, sapma dürüstçe
REPLAY-MISS.

Demo-A'nın gerçek kod yolu kullanılır: jira-sim (süreç içi) → `RestJira.get_issue` →
`requirement_block` → geçit (replay, `TP_REPLAY_STRICT=1`). Doküman düzeltmeleri Jira'ya
`RestJira.update_description` ile yazılıp story yeniden çekilir (§8.2b adım 6–7).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.unit.gateway.demo_sources import REPO, load_golden
from tp_core.gateway import (
    ALLOWED_AGENT_TOOLS,
    FREE_TEXT_KEY,
    HAND_PREPARED_MODEL,
    MATCHED,
    MISS_NEUTRAL,
    Gateway,
    ReplayMiss,
    ReplayStore,
    golden_name,
    input_mismatches,
    load_schema,
    mode_label,
    numbered_acceptance_criteria,
    requirement_block,
    wrap_untrusted,
)
from tp_core.gateway.config import load_model_table
from tp_core.gateway.testing import InMemoryCallRecorder
from tp_core.integrations.jira import RestJira
from tp_core.ports import JiraIssue, ModelMessage, ToolSpec

SIM_SRC = REPO / "sims" / "jira-sim" / "src"
if str(SIM_SRC) not in sys.path:
    sys.path.insert(0, str(SIM_SRC))

from jira_sim.app import create_app  # noqa: E402

BASE = "http://jira-sim:8090"
STORIES = ("TPD-1", "TPD-2", "TPD-3", "TPD-4")
MAX_ROUNDS = 3
CONSISTENCY_TOOLS = [
    ToolSpec(name=n, description=n, input_schema={"type": "object"})
    for n in sorted(ALLOWED_AGENT_TOOLS["consistency_check"])
]
VERIFY_TOOLS = [
    ToolSpec(name=n, description=n, input_schema={"type": "object"})
    for n in sorted(ALLOWED_AGENT_TOOLS["verify_and_map"])
]
# Serbest metin demo gereksinimi (rules/replay/README.md "Serbest metin örneği").
FREE_TEXT = {
    "baslik": "Sepetten ürün çıkarma",
    "aciklama": (
        "Bayi sepetteki bir ürün satırını kaldırabilmeli; toplamlar ve kampanya indirimi "
        "yeniden hesaplanmalıdır."
    ),
    "ac": [
        'Satırdaki "Kaldır" butonuna basıldığında ürün sepetten çıkar ve sepet sayacı azalır.',
        "Kaldırma sonrası kampanya indirimi her 7 adette 1 bedava kuralıyla yeniden hesaplanır.",
        "Sepet tutarı 500,00 TL altına düşerse minimum tutar uyarısı gösterilir.",
    ],
}


class SimTransport(httpx.BaseTransport):
    def __init__(self, sim: TestClient) -> None:
        self.sim = sim

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        r = self.sim.request(
            request.method, str(request.url), headers=dict(request.headers), content=request.read()
        )
        return httpx.Response(r.status_code, headers=dict(r.headers), content=r.content)


@pytest.fixture
def jira() -> Iterator[RestJira]:
    with TestClient(create_app(data_path="", base_url=BASE), base_url=BASE) as sim:
        yield RestJira(
            BASE,
            ("reader@sim.local", "t"),
            ("writer@sim.local", "t"),
            http=httpx.Client(transport=SimTransport(sim)),
            sleep=lambda _s: None,
        )


def _gateway(rules_dir, recorder, *, strict: bool) -> Gateway:
    return Gateway(
        provider=None,
        recorder=recorder,
        mode="replay",
        models=load_model_table(rules_dir),
        rules_dir=rules_dir,
        replay_store=ReplayStore(rules_dir / "replay", strict=strict),
        record_extras=True,
    )


def _story_messages(issue: JiraIssue) -> list[ModelMessage]:
    """İş akışının kuracağı girdi: story bloğu + (ayrı kaynaklı) PO cevabı bloğu."""
    story = requirement_block(
        summary=issue.summary,
        description=issue.description,
        acceptance_criteria=issue.acceptance_criteria,
        jira_key=issue.key,
    )
    # Başka kaynaklı bloktaki AC alıntısı golden eşleşmesini etkilememeli.
    po = wrap_untrusted(
        "PO cevabı: AC3: Tüm siparişlerde 500,00 TL. (eski görüş)",
        source=f"jira:{issue.key}#yorum-10001",
        kind="jira",
    )
    return [ModelMessage(role="user", content=f"{story}\n\n{po}")]


def _review(gw: Gateway, rules_dir, key: str, messages: list[ModelMessage]):
    return gw.call(
        "requirement_review",
        "requirement-review",
        messages,
        load_schema(rules_dir, "requirement_review"),
        replay_key={"name": golden_name(key), "jira_key": key},
    )


def _check(gw: Gateway, rules_dir, key: str, messages: list[ModelMessage], round_no: int):
    return gw.run_agent(
        "consistency_check",
        "consistency-check",
        messages,
        CONSISTENCY_TOOLS,
        lambda name, args: f"{name} sonucu",
        load_schema(rules_dir, "consistency_check"),
        replay_key={"name": golden_name(key, check_round=round_no), "jira_key": key},
    )


def _cases(gw: Gateway, rules_dir, key: str, messages: list[ModelMessage]):
    return gw.call(
        "case_generation",
        "case-generation",
        messages,
        load_schema(rules_dir, "case_generation"),
        replay_key={"name": golden_name(key), "jira_key": key},
    )


def _apply_fixes(acs: list[str], findings: list[dict[str, Any]]) -> list[str]:
    """fix_doc kararlı (önerili) engelleyici bulguların AC satırları yerine geçer."""
    by_ref = {a.split(":", 1)[0]: a for a in acs}
    for f in findings:
        if f["severity"] == "blocking" and f["suggested_doc_text"]:
            by_ref[f["suggested_doc_text"].split(":", 1)[0]] = f["suggested_doc_text"]
    return [by_ref[r] for r in sorted(by_ref, key=lambda r: int(r[2:]))]


def _jira_story_flow(gw: Gateway, rules_dir, jira: RestJira, key: str) -> list[str]:
    issue = jira.get_issue(key)
    modes = [_review(gw, rules_dir, key, _story_messages(issue)).mode]
    for round_no in range(1, MAX_ROUNDS + 1):
        result = _check(gw, rules_dir, key, _story_messages(issue), round_no)
        modes.append(result.mode)
        blocking = [f for f in result.output["findings"] if f["severity"] == "blocking"]
        if not blocking:
            break
        jira.update_description(
            key, issue.description, _apply_fixes(issue.acceptance_criteria, blocking)
        )
        issue = jira.get_issue(key)
    else:
        pytest.fail(f"{key}: {MAX_ROUNDS} turda son hale gelmedi")
    if issue.acceptance_criteria:  # ac_missing story PO'da kalır (adım 4'e gelmez)
        modes.append(_cases(gw, rules_dir, key, _story_messages(issue)).mode)
    return modes


# ------------------------------------------------------------------ senaryodaki demo yolu


def test_scripted_demo_a_has_no_replay_miss_in_strict_mode(rules_dir, jira) -> None:
    """§13 prova maddesi "REPLAY-MISS olmadan replay": yükseltme (promote) gerekmeden."""
    recorder = InMemoryCallRecorder()
    gw = _gateway(rules_dir, recorder, strict=True)
    for key in STORIES:
        modes = _jira_story_flow(gw, rules_dir, jira, key)
        assert set(modes) == {"replay"}, (key, modes)
    assert recorder.ai_calls, "çağrı kaydı yok"
    for row in recorder.ai_calls:
        assert row["mod"] == "replay"  # asla "live"
        assert row["saglayici"] == "replay"
        assert row["ek"]["replay_kokeni"] == MATCHED
        assert "replay_eslesme" not in row["ek"]
        # Golden'lar elle hazırlandı: model kaydı gibi sunulmaz (constitution VIII/X).
        assert row["model"] == HAND_PREPARED_MODEL
        assert row["ek"]["cikti_kokeni"] == "elle_hazirlanmis"
        assert mode_label(row["mod"], row["model"]) == (
            "REPLAY (hazırlanmış örnek çıktı; canlı model değil)"
        )
    used = {row["ek"]["replay_kaynagi"] for row in recorder.ai_calls}
    assert "consistency_check/golden/TPD-1-r2.json" in used
    assert "case_generation/golden/TPD-1.json" in used


def test_tpd1_doc_fix_rounds_go_through_jira(rules_dir, jira) -> None:
    recorder = InMemoryCallRecorder()
    gw = _gateway(rules_dir, recorder, strict=True)
    modes = _jira_story_flow(gw, rules_dir, jira, "TPD-1")
    assert modes == ["replay"] * 4  # ön inceleme, 1. tur, 2. tur, case üretimi
    fixed = jira.get_issue("TPD-1").acceptance_criteria
    assert (
        fixed == load_golden("consistency_check", "TPD-1-r2")["input_match"]["acceptance_criteria"]
    )
    assert fixed == load_golden("case_generation", "TPD-1")["input_match"]["acceptance_criteria"]


def test_free_text_demo_requirement_runs_strict(rules_dir) -> None:
    recorder = InMemoryCallRecorder()
    gw = _gateway(rules_dir, recorder, strict=True)
    rid = str(uuid4())
    acs = list(FREE_TEXT["ac"])  # portal girdisi önekisiz; requirement_block numaralar

    def messages() -> list[ModelMessage]:
        block = requirement_block(
            summary=FREE_TEXT["baslik"],
            description=FREE_TEXT["aciklama"],
            acceptance_criteria=acs,
            requirement_id=rid,
        )
        return [ModelMessage(role="user", content=block)]

    assert _review(gw, rules_dir, FREE_TEXT_KEY, messages()).mode == "replay"
    for round_no in (1, 2):
        result = _check(gw, rules_dir, FREE_TEXT_KEY, messages(), round_no)
        assert result.mode == "replay"
        blocking = [f for f in result.output["findings"] if f["severity"] == "blocking"]
        if round_no == 1:
            assert {f["type"] for f in blocking} == {"doc_vs_code", "doc_vs_data", "missing_in_doc"}
            acs = _apply_fixes(numbered_acceptance_criteria(acs), blocking)
        else:
            assert not blocking
    assert _cases(gw, rules_dir, FREE_TEXT_KEY, messages()).mode == "replay"


def test_verify_and_map_matches_the_approved_case_even_as_ascii_json(rules_dir) -> None:
    recorder = InMemoryCallRecorder()
    gw = _gateway(rules_dir, recorder, strict=True)
    cases = load_golden("case_generation", "TPD-1")["output"]["cases"]
    # Doğrulama ajanı kaydı olan C1–C10 (C11–C15, 011 K17 sınır case'leri: kayıt yok).
    for n, case in enumerate(cases[:10], start=1):
        # json.dumps varsayılanı ensure_ascii=True: "ü" → "ü"; eşleşme yine bulmalı.
        block = wrap_untrusted(json.dumps(case), source=f"case:TPD-1-C{n}")
        msg = ModelMessage(role="user", content=f"Onaylı case:\n{block}")
        result = gw.run_agent(
            "verify_and_map",
            "verify-and-map",
            [msg],
            VERIFY_TOOLS,
            lambda name, args: "- Page Snapshot",
            load_schema(rules_dir, "verify_and_map"),
            replay_key={"name": golden_name("TPD-1", case_no=n), "jira_key": "TPD-1"},
        )
        assert result.mode == "replay", case["title"]


# ------------------------------------------------------------------ sapma: dürüst REPLAY-MISS


def test_changed_story_is_an_honest_replay_miss(rules_dir, jira) -> None:
    issue = jira.get_issue("TPD-1")
    acs = list(issue.acceptance_criteria)
    acs[1] = acs[1].replace("7 adette", "8 adette")  # PO AC2'yi değiştirdi
    jira.update_description("TPD-1", issue.description, acs)
    changed = jira.get_issue("TPD-1")

    recorder = InMemoryCallRecorder()
    loose = _gateway(rules_dir, recorder, strict=False)
    result = _review(loose, rules_dir, "TPD-1", _story_messages(changed))
    assert result.mode == "replay_miss"
    row = recorder.ai_calls[-1]
    assert row["mod"] == "replay_miss" and row["ek"]["replay_kokeni"] == MISS_NEUTRAL
    assert row["ek"]["replay_eslesme"] == ["AC2 metni farklı"]
    # Golden'ın soruları başka (özgün) doküman içindir: gösterilmez, nötr yedek döner.
    assert result.output["questions"] == [] and "REPLAY-MISS" in result.output["summary"]

    strict = _gateway(rules_dir, InMemoryCallRecorder(), strict=True)
    with pytest.raises(ReplayMiss):
        _review(strict, rules_dir, "TPD-1", _story_messages(changed))


def test_round_two_golden_does_not_match_round_one_document(rules_dir, jira) -> None:
    """Analist düzeltmeyi uygulamadan yeniden kontrol ederse r2 golden'ı (son hal) uymaz."""
    recorder = InMemoryCallRecorder()
    gw = _gateway(rules_dir, recorder, strict=False)
    result = _check(gw, rules_dir, "TPD-1", _story_messages(jira.get_issue("TPD-1")), 2)
    assert result.mode == "replay_miss"
    reasons = recorder.ai_calls[-1]["ek"]["replay_eslesme"]
    assert reasons == ["AC2 metni farklı", "AC3 metni farklı"]


def test_free_text_golden_does_not_match_other_free_text(rules_dir) -> None:
    recorder = InMemoryCallRecorder()
    gw = _gateway(rules_dir, recorder, strict=False)
    block = requirement_block(
        summary="Deneme",
        description="Açıklama",
        acceptance_criteria=["Sepet tutarı 500,00 TL altındaysa uyarı gösterilir."],
        requirement_id=str(uuid4()),
    )
    result = _review(gw, rules_dir, FREE_TEXT_KEY, [ModelMessage(role="user", content=block)])
    assert result.mode == "replay_miss"
    # SERBEST golden'ının "AC2/AC3" soruları bu metinde olmayan AC'lere atıf yapar; gösterilmez.
    assert result.output["questions"] == []
    assert recorder.ai_calls[-1]["ek"]["replay_kokeni"] == MISS_NEUTRAL


def test_every_requirement_review_miss_shows_only_existing_acs(rules_dir) -> None:
    """Ön inceleme REPLAY-MISS'te girdide olmayan AC'ye atıf yapan soru asla dönmez."""
    gw = _gateway(rules_dir, InMemoryCallRecorder(), strict=False)
    block = requirement_block(
        summary="UXR iade talebi",
        description="Bayi teslim aldığı siparişte iade talebi açabilmelidir.",
        acceptance_criteria=['Sipariş detayında "İade talebi" butonu görünür.'],
        requirement_id=str(uuid4()),
    )
    for name in ("TPD-1", "TPD-2", "TPD-3", "TPD-4", FREE_TEXT_KEY):
        result = _review(gw, rules_dir, name, [ModelMessage(role="user", content=block)])
        assert result.mode == "replay_miss", name
        refs = {q["ac_ref"] for q in result.output["questions"]}
        assert refs <= {None, "AC1"}, (name, refs)
        assert not result.output["questions"], name


# ------------------------------------------------------------------ eşleme kuralları


SPEC = {
    "sources": ["jira:TPD-1"],
    "acceptance_criteria": ["AC1: A olur.", 'AC2: "B" görünür.'],
    "contains": ["Açıklama metni."],
}


def _msgs(body: str, source: str = "jira:TPD-1") -> list[dict[str, Any]]:
    return [{"role": "user", "content": wrap_untrusted(body, source=source, kind="jira")}]


@pytest.mark.parametrize(
    "body",
    [
        'Açıklama metni.\nAC1: A olur.\nAC2: "B" görünür.',
        'Açıklama   metni.\n### Kabul Kriterleri\n- AC1: A  olur.\n- AC2: "B" görünür.',
        json.dumps({"description": "Açıklama metni.", "ac": ["AC1: A olur.", 'AC2: "B" görünür.']}),
        json.dumps(
            {"description": "Açıklama metni.", "ac": ["AC1: A olur.", 'AC2: "B" görünür.']},
            indent=2,
        ),
    ],
    ids=["satir", "madde-imi", "json", "json-girintili"],
)
def test_supported_renderings_match(body: str) -> None:
    assert input_mismatches(SPEC, _msgs(body)) == []


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("Açıklama metni.\nAC1: A olur.", "AC2 girdide yok"),
        ('Açıklama metni.\nAC1: A olur.\nAC2: "B" görünür.\nAC3: C.', "AC3 golden'da yok"),
        ('Açıklama metni.\nAC1: A olmaz.\nAC2: "B" görünür.', "AC1 metni farklı"),
        ('Başka açıklama.\nAC1: A olur.\nAC2: "B" görünür.', "girdide yok: Açıklama metni."),
        (
            'Açıklama metni.\nAC1: A olur.\nAC1: X.\nAC2: "B" görünür.',
            "çelişkili kabul kriteri: AC1",
        ),
    ],
)
def test_any_document_change_is_a_mismatch(body: str, reason: str) -> None:
    assert reason in input_mismatches(SPEC, _msgs(body))


def test_only_declared_sources_are_read() -> None:
    body = 'Açıklama metni.\nAC1: A olur.\nAC2: "B" görünür.'
    assert input_mismatches(SPEC, _msgs(body, source="jira:TPD-11")) == [
        "kaynak bloğu yok: jira:TPD-1"
    ]
    # Eşleşen bloğun yanındaki başka kaynaklı AC alıntısı karışmaz.
    other = wrap_untrusted("AC1: başka metin", source="tp:onceki-bulgular", kind="text")
    msgs = _msgs(body)
    msgs.append({"role": "user", "content": [{"type": "text", "text": other}]})
    assert input_mismatches(SPEC, msgs) == []


def test_golden_without_declaration_stays_replay_miss(rules_dir) -> None:
    """Beyansız golden (Faz 4'ten beri depoda yok) girdiyi bilmez: her zaman REPLAY-MISS."""
    folder = rules_dir / "replay" / "triage" / "golden"
    (folder / "beyansiz.json").write_text(
        json.dumps({"kind": "call", "purpose": "triage", "golden": "beyansiz", "output": {}}),
        encoding="utf-8",
    )
    store = ReplayStore(rules_dir / "replay")
    record, mode, _ = store.lookup("triage", "0" * 64, "beyansiz", [])
    assert mode == "replay_miss"
    assert record["_mismatch"] == ["golden girdi beyanı (input_match) içermiyor"]
    with pytest.raises(ReplayMiss):
        ReplayStore(rules_dir / "replay", strict=True).lookup("triage", "0" * 64, "beyansiz", [])
