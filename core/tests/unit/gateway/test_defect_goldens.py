"""Faz 4 golden'ları (triage / bug_draft / dup_rank): demo hikâyesinin her girdisi tam olarak kendi
golden'ına düşer (REPLAY, sıkı kip), başka hata REPLAY-MISS olur, çıktılar yönergeye ve girdiye
bağlıdır. Girdiler şeritlerin kullanacağı kanonik kuruculardan (`tp_core.gateway.defects`) gelir.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tests.unit.gateway import defect_inputs as di
from tests.unit.gateway.demo_sources import RULES, golden_ref, goldens, scenario_goldens
from tp_core.gateway import (
    DEFECT_GOLDEN_KEY,
    EVIDENCE_PREFIX,
    PENDING_LABEL,
    Gateway,
    ReplayMiss,
    ReplayNoOutput,
    ReplayStore,
    defect_replay_key,
    dup_rank_messages,
    dup_rank_problems,
    failure_block,
    invented_dup_keys,
    load_schema,
    resolve_evidence,
)
from tp_core.gateway.config import load_model_table
from tp_core.gateway.matching import matched_output, untrusted_blocks
from tp_core.gateway.testing import InMemoryCallRecorder
from tp_core.ports import ModelMessage

PURPOSES = {"triage": "triage", "bug_draft": "bug-draft", "dup_rank": "dup-rank"}
DEFECT_GOLDENS = [g for p in PURPOSES for g in [*goldens(p), *scenario_goldens(p)]]


def _gateway(rules_dir: Path, recorder: InMemoryCallRecorder, *, strict: bool) -> Gateway:
    return Gateway(
        provider=None,
        recorder=recorder,
        mode="replay",
        models=load_model_table(rules_dir),
        rules_dir=rules_dir,
        replay_store=ReplayStore(rules_dir / "replay", strict=strict),
        record_extras=True,
    )


def _call(gw: Gateway, purpose: str, messages: list[ModelMessage]) -> Any:
    return gw.call(
        purpose,
        PURPOSES[purpose],
        messages,
        load_schema(gw.rules_dir, purpose),
        replay_key=defect_replay_key("TPD-1"),
    )


# (kimlik, amaç, mesaj kurucusu, beklenen golden)
DEMO_INPUTS: list[tuple[str, str, Callable[[], list[ModelMessage]], str]] = [
    ("triage-zaman-asimi", "triage", di.timeout_messages, "HATA"),
    ("bug-c3", "bug_draft", lambda: di.bug_messages(di.c3_sources()), "HATA"),
    *[
        (
            f"bug-kirma-{i}",
            "bug_draft",
            (lambda i=i: di.bug_messages(di.break_sources(i))),
            "kirma-kampanya/HATA",
        )
        for i in range(len(di.BREAK_TESTS))
    ],
    *[
        (
            f"bug-f2-{g}",
            "bug_draft",
            (lambda g=g, f=f: di.bug_messages(di.finding_sources(g, f))),
            "f2-kampanya/HATA",
        )
        for g, f in di.F2_FINDINGS
    ],
    *[
        (
            f"bug-f4-{g}",
            "bug_draft",
            (lambda g=g, f=f: di.bug_messages(di.finding_sources(g, f))),
            "f4-kredi-limiti/HATA",
        )
        for g, f in di.F4_FINDINGS
    ],
    *[
        (
            f"dup-c3-{'-'.join(keys)}",
            "dup_rank",
            (lambda keys=keys: di.dup_messages(di.c3_sources(), keys)),
            "HATA",
        )
        for keys in di.DUP_KEY_SETS
    ],
    *[
        (
            f"dup-f2-{g}-{'-'.join(keys)}",
            "dup_rank",
            (lambda g=g, f=f, keys=keys: di.dup_messages(di.finding_sources(g, f), keys)),
            "f2-kampanya/HATA",
        )
        for g, f in di.F2_FINDINGS
        for keys in di.DUP_KEY_SETS
    ],
    *[
        (
            f"dup-f4-{g}-{'-'.join(keys)}",
            "dup_rank",
            (lambda g=g, f=f, keys=keys: di.dup_messages(di.finding_sources(g, f), keys)),
            "f4-kredi-limiti/HATA",
        )
        for g, f in di.F4_FINDINGS
        for keys in (["TPD-5", "TPD-6"], ["TPD-5"], ["TPD-6"], ["TPD-5", "@kredi-limiti"])
    ],
    *[
        (
            f"dup-kirma-{i}-{'-'.join(keys)}",
            "dup_rank",
            (lambda i=i, keys=keys: di.dup_messages(di.break_sources(i), keys)),
            "kirma-kampanya/HATA",
        )
        for i in range(len(di.BREAK_TESTS))
        for keys in di.DUP_KEY_SETS
    ],
]


@pytest.mark.parametrize(
    ("purpose", "build", "expected"),
    [(p, b, e) for _, p, b, e in DEMO_INPUTS],
    ids=[i for i, *_ in DEMO_INPUTS],
)
def test_demo_input_replays_its_own_golden_in_strict_mode(
    rules_dir: Path, purpose: str, build: Callable[[], list[ModelMessage]], expected: str
) -> None:
    recorder = InMemoryCallRecorder()
    result = _call(_gateway(rules_dir, recorder, strict=True), purpose, build())
    assert result.mode == "replay"
    row = recorder.ai_calls[-1]
    assert row["ek"]["replay_kaynagi"] == f"{purpose}/golden/{expected}.json"
    assert row["ek"]["replay_kokeni"] == "golden_matched"
    assert row["ek"]["cikti_kokeni"] == "elle_hazirlanmis" and row["model"] == "golden-elle"


def test_every_defect_golden_is_reached_by_a_demo_input() -> None:
    reached = {(p, e) for _, p, _, e in DEMO_INPUTS}
    have = {(p, golden_ref(path)) for p, path, _ in DEFECT_GOLDENS}
    assert have == reached, f"ulaşılmayan golden: {have - reached}; olmayan: {reached - have}"


# ------------------------------------------------------------------ dürüst iskalama


def test_c3_failure_without_its_case_is_not_the_c3_bug(rules_dir: Path) -> None:
    """Adet (6) yalnızca case'te: case'siz girdi C3 taslağını almaz (adımlar uydurulmaz)."""
    msgs = di.bug_messages(di.c3_sources()[:1])
    with pytest.raises(ReplayMiss):
        _call(_gateway(rules_dir, InMemoryCallRecorder(), strict=True), "bug_draft", msgs)
    recorder = InMemoryCallRecorder()
    with pytest.raises(ReplayNoOutput):
        _call(_gateway(rules_dir, recorder, strict=False), "bug_draft", msgs)
    row = recorder.ai_calls[-1]
    assert row["mod"] == "replay_miss" and row["cikti"] is None


def test_other_assertion_failure_gets_no_bug_and_no_ranking(rules_dir: Path) -> None:
    other = di.free_quantity_failure(
        expected=2, received=1, qty=12, test_file="tests/cart.spec.ts", line=50
    )
    src = [failure_block(other, test_title="12 adet", test_file="tests/cart.spec.ts")]
    gw = _gateway(rules_dir, InMemoryCallRecorder(), strict=False)
    with pytest.raises(ReplayNoOutput):
        _call(gw, "bug_draft", di.bug_messages(src))
    with pytest.raises(ReplayNoOutput):
        _call(gw, "dup_rank", di.dup_messages(src, ["TPD-5"]))


def test_triage_miss_is_neutral_unknown(rules_dir: Path) -> None:
    """Kuralın sınıflaması gereken hata yanlışlıkla modele giderse başka hatanın sınıfı dönmez."""
    recorder = InMemoryCallRecorder()
    from tp_core.gateway import triage_messages

    msgs = triage_messages(di.c3_sources()[0])
    result = _call(_gateway(rules_dir, recorder, strict=False), "triage", msgs)
    assert result.mode == "replay_miss"
    assert result.output["class"] == "unknown" and result.output["sub_type"] is None
    assert "REPLAY-MISS" in result.output["rationale"]
    assert recorder.ai_calls[-1]["ek"]["replay_kokeni"] == "miss_neutral"


def test_candidate_set_outside_the_goldens_is_replay_miss(rules_dir: Path) -> None:
    """Done olan TPD-7 aramaya karışırsa hiçbir golden'ın aday kümesi tutmaz (uydurma yok)."""
    gw = _gateway(rules_dir, InMemoryCallRecorder(), strict=False)
    with pytest.raises(ReplayNoOutput):
        _call(gw, "dup_rank", di.dup_messages(di.c3_sources(), ["TPD-5", "TPD-6", "TPD-7"]))


def test_credit_limit_bug_needs_the_test_data_block(rules_dir: Path) -> None:
    """bayi2'nin 500,00 TL limiti girdide yoksa golden'ın adımları uydurma olurdu."""
    from tp_core.gateway import bug_draft_messages

    msgs = bug_draft_messages(
        di.finding_sources("TPD-1", "F4"), testdata=None, story_key="TPD-1", test_case_key=None
    )
    with pytest.raises(ReplayMiss):
        _call(_gateway(rules_dir, InMemoryCallRecorder(), strict=True), "bug_draft", msgs)


# ------------------------------------------------------------------ golden içeriği


@pytest.mark.parametrize(
    ("purpose", "path", "golden"),
    DEFECT_GOLDENS,
    ids=[f"{p}/{golden_ref(path)}" for p, path, _ in DEFECT_GOLDENS],
)
def test_defect_golden_is_declared_valid_and_hand_written(
    purpose: str, path: Path, golden: dict
) -> None:
    assert golden["purpose"] == purpose and golden["kind"] == "call"
    assert golden["golden"] == golden_ref(path)
    assert path.stem == DEFECT_GOLDEN_KEY
    spec = golden["input_match"]
    assert spec["sources"] and spec["contains"]
    if purpose == "dup_rank":
        # Aday kümesi `candidates` ile beyan edilir; sabit `Aday anahtarları` satırı değil
        # (demo sırasında açılan Bug kümeyi genişletince golden düşmesin).
        assert set(spec) == {"sources", "contains", "candidates"}
        assert "jira-arama:*" in spec["sources"]
        assert not any(c.startswith("Aday anahtarları") for c in spec["contains"])
        assert set(golden["extra_candidates"]) == set(spec["candidates"]["by_summary"])
    else:
        assert set(spec) == {"sources", "contains"} and "extra_candidates" not in golden
    assert "Elle hazırlandı" in golden["note"] and "recording" not in golden
    errors = list(Draft202012Validator(load_schema(RULES, purpose)).iter_errors(golden["output"]))
    assert not errors, [e.message for e in errors]


DUP = [(path, g) for p, path, g in DEFECT_GOLDENS if p == "dup_rank"]


def _one_sentence(rationale: str) -> None:
    # Tek kısa cümle (sıra sayısı "6. adette" cümle sonu değildir); dup-rank.md: ≤ 200 karakter.
    assert len(rationale) <= 200, rationale
    assert not re.search(r"\.\s+[A-ZÇĞİÖŞÜ]", rationale), rationale


@pytest.mark.parametrize(("path", "golden"), DUP, ids=[golden_ref(p) for p, _ in DUP])
def test_dup_rank_golden_base_output_ranks_exactly_its_declared_keys(
    path: Path, golden: dict
) -> None:
    out = golden["output"]
    cands = golden["input_match"]["candidates"]
    declared = [*cands["required"], *cands["optional"]]
    assert [c["key"] for c in out["candidates"]] and {c["key"] for c in out["candidates"]} == set(
        declared
    )
    assert [c["rank"] for c in out["candidates"]] == list(range(1, len(declared) + 1))
    assert out["candidates"][0]["key"] == "TPD-5"  # seed'deki kampanya hatası en üstte
    for c in [*out["candidates"], *golden["extra_candidates"].values()]:
        _one_sentence(c["rationale"])
        assert c["likelihood"] in ("high", "medium", "low")
    # Geçidin kurduğu çıktı, seed kümesi için golden'ın yazılı çıktısıyla aynıdır.
    msgs = _dup_input_for(golden_ref(path), ["TPD-5", "TPD-6"])
    assert matched_output(golden, msgs) == out
    assert dup_rank_problems(out, [di.candidate(k) for k in declared]) == []
    others = [c for c in out["candidates"] if c["key"] != "TPD-5"]
    assert all(c["likelihood"] == "low" for c in others)  # TPD-6: sipariş geçmişi, ilgisiz


DUP_SOURCES: dict[str, Callable[[], list[str]]] = {
    "HATA": di.c3_sources,
    "f2-kampanya/HATA": lambda: di.finding_sources("TPD-1", "F2"),
    "f4-kredi-limiti/HATA": lambda: di.finding_sources("TPD-1", "F4"),
    "kirma-kampanya/HATA": di.break_sources,
}


def _dup_input_for(ref: str, keys: list[str]) -> list[ModelMessage]:
    return di.dup_messages(DUP_SOURCES[ref](), keys)


DUP_INPUTS = [(i, b, e) for i, p, b, e in DEMO_INPUTS if p == "dup_rank"]


@pytest.mark.parametrize(
    ("build", "expected"), [(b, e) for _, b, e in DUP_INPUTS], ids=[i for i, _, _ in DUP_INPUTS]
)
def test_dup_rank_replay_ranks_exactly_the_search_result(
    rules_dir: Path, build: Callable[[], list[ModelMessage]], expected: str
) -> None:
    """Golden çıktısı girdideki GERÇEK aday kümesine göre kurulur: yalnızca aramadaki anahtarlar,
    her biri bir kez, sıra 1..n; demo sırasında açılan Bug (ör. F4 → TPD-8) TPD-5'in AI
    gerekçeli ilk sırasını ve 'bağla' önerisini bozmaz (constitution I: karar yine testçinin)."""
    msgs = build()
    search = next(b.body for b in untrusted_blocks(msgs) if b.source == "jira-arama:Bug")
    keys = re.search(r"Aday anahtarları: \[(.+)\]", search).group(1).split(", ")
    result = _call(_gateway(rules_dir, InMemoryCallRecorder(), strict=True), "dup_rank", msgs)
    out = result.output
    assert [c["key"] for c in out["candidates"]] and sorted(
        c["key"] for c in out["candidates"]
    ) == sorted(keys)
    aliases = {di.candidate_key(a): a for a in di.PUBLISHED_BUGS}
    cands = [di.candidate(aliases.get(k, k)) for k in keys]
    assert dup_rank_problems(out, cands) == []
    for c in out["candidates"]:
        _one_sentence(c["rationale"])
    by_key = {c["key"]: c for c in out["candidates"]}
    kirma_bug = di.candidate_key("@kirma")
    f4_bug = di.candidate_key("@kredi-limiti")
    if expected in ("HATA", "f2-kampanya/HATA"):
        # Ana yol: TPD-5 AI gerekçesiyle ilk sırada, öneri bağla.
        assert out["candidates"][0]["key"] == "TPD-5"
        assert out["candidates"][0]["likelihood"] == "high"
        assert (out["recommendation"], out["link_key"]) == ("link", "TPD-5")
        if f4_bug in by_key:
            assert by_key[f4_bug]["likelihood"] == "low"
        if kirma_bug in by_key:
            assert by_key[kirma_bug]["likelihood"] == "medium"
    elif expected == "kirma-kampanya/HATA":
        if kirma_bug in by_key:
            # Testçinin önceki kırma koşusunda açtığı Bug aynı belirtidir: o önerilir.
            assert out["candidates"][0]["key"] == kirma_bug
            assert (out["recommendation"], out["link_key"]) == ("link", kirma_bug)
            assert by_key["TPD-5"]["rank"] == 2
        else:
            assert out["candidates"][0]["key"] == "TPD-5"
            assert out["candidates"][0]["likelihood"] == "medium"
            assert (out["recommendation"], out["link_key"]) == ("new", None)
    else:
        assert expected == "f4-kredi-limiti/HATA"
        if f4_bug in by_key:
            assert (out["recommendation"], out["link_key"]) == ("link", f4_bug)
        else:
            assert (out["recommendation"], out["link_key"]) == ("new", None)
            assert {c["likelihood"] for c in out["candidates"]} == {"low"}


def test_published_bug_summaries_are_recognized_by_exactly_one_declaration() -> None:
    """Her golden, demo sırasında açılabilen her Bug'ı tek bir `by_summary` beyanıyla tanır."""
    for _, golden in DUP:
        by_summary = golden["input_match"]["candidates"]["by_summary"]
        for alias in di.PUBLISHED_BUGS:
            summary = di.published_bug(alias).summary.casefold()
            hits = [n for n, sub in by_summary.items() if sub.casefold() in summary]
            assert len(hits) == 1, (golden["golden"], alias, hits)
        for key in ("TPD-5", "TPD-6", "TPD-7"):
            summary = di.seed_bug(key).summary.casefold()
            assert not [n for n, sub in by_summary.items() if sub.casefold() in summary], key


def test_undeclared_or_missing_candidates_are_replay_miss(rules_dir: Path) -> None:
    """Golden bilmediği bir kaydı sıralamaz; TPD-5 aramada yoksa C3 golden'ı da düşmez."""
    gw = _gateway(rules_dir, InMemoryCallRecorder(), strict=False)
    other = di.seed_bug("TPD-5").model_copy(
        update={"key": "TPD-20", "summary": "Katalog: arama kutusu boş sonuç veriyor"}
    )
    msgs = dup_rank_messages(
        di.c3_sources(),
        draft={"summary": "taslak", "story_key": "TPD-1"},
        candidates=[di.seed_bug("TPD-5"), other],
    )
    recorder = InMemoryCallRecorder()
    gw = _gateway(rules_dir, recorder, strict=False)
    with pytest.raises(ReplayNoOutput):
        _call(gw, "dup_rank", msgs)
    assert any(
        "beyan dışı aday: TPD-20" in r for r in recorder.ai_calls[-1]["ek"]["replay_eslesme"]
    )
    with pytest.raises(ReplayNoOutput):
        _call(gw, "dup_rank", di.dup_messages(di.c3_sources(), ["TPD-6", "@kredi-limiti"]))


def test_dup_rank_problems_enforces_the_prompt_invariants() -> None:
    cands = [di.seed_bug("TPD-5"), di.seed_bug("TPD-6")]

    def row(key: str, rank: int, likelihood: str = "low", why: str = "Farklı alan") -> dict:
        return {"key": key, "rank": rank, "likelihood": likelihood, "rationale": why}

    ok = {
        "candidates": [row("TPD-5", 1, "high"), row("TPD-6", 2)],
        "recommendation": "link",
        "link_key": "TPD-5",
    }
    assert dup_rank_problems(ok, cands) == []
    assert any(
        "birden çok" in p
        for p in dup_rank_problems({**ok, "candidates": [row("TPD-5", 1, "high")] * 2}, cands)
    )
    assert "aday sıralanmadı: TPD-6" in dup_rank_problems(
        {**ok, "candidates": [row("TPD-5", 1, "high")]}, cands
    )
    assert any(
        "sıra numaraları" in p
        for p in dup_rank_problems(
            {**ok, "candidates": [row("TPD-5", 1, "high"), row("TPD-6", 1)]}, cands
        )
    )
    assert any(
        "200" in p
        for p in dup_rank_problems(
            {**ok, "candidates": [row("TPD-5", 1, "high"), row("TPD-6", 2, why="x" * 201)]},
            cands,
        )
    )
    assert any(
        "link" in p
        for p in dup_rank_problems(
            {**ok, "candidates": [row("TPD-5", 1, "medium"), row("TPD-6", 2)]}, cands
        )
    )
    assert any(
        "aramada olmayan" in p for p in dup_rank_problems({**ok, "link_key": "TPD-9"}, cands)
    )
    assert any("link_key" in p for p in dup_rank_problems({**ok, "recommendation": "new"}, cands))


def test_dup_rank_schema_caps_the_rationale_length() -> None:
    schema = load_schema(RULES, "dup_rank")
    rationale = schema["properties"]["candidates"]["items"]["properties"]["rationale"]
    assert rationale["maxLength"] == 200
    bad = {
        "candidates": [{"key": "TPD-5", "rank": 1, "likelihood": "low", "rationale": "x" * 201}],
        "recommendation": "new",
        "link_key": None,
    }
    assert list(Draft202012Validator(schema).iter_errors(bad))


BUGS = [(path, g) for p, path, g in DEFECT_GOLDENS if p == "bug_draft"]


@pytest.mark.parametrize(("path", "golden"), BUGS, ids=[golden_ref(p) for p, _ in BUGS])
def test_bug_draft_evidence_is_only_what_the_input_offers(path: Path, golden: dict) -> None:
    out = golden["output"]
    ref = golden_ref(path)
    build = next(b for _, p, b, e in DEMO_INPUTS if p == "bug_draft" and e == ref)
    text = "\n".join(b.body for b in untrusted_blocks(build()))
    for ev in out["evidence"]:
        if ev["ref"].startswith(EVIDENCE_PREFIX):
            assert ev["ref"] in text or ev["ref"] == "kanit:allure", ev
        else:
            assert ev["ref"] in text, ev  # kod referansı bulgu kanıtında aynen geçer
    assert "http" not in str(out["evidence"])
    assert out["labels"] == ["AI-generated"] and out["story_key"] == "TPD-1"
    assert out["test_case_key"] is None  # Jira Test anahtarını şerit yazar


def test_break_bug_says_the_break_was_deliberate() -> None:
    out = next(g for p, g in BUGS if golden_ref(p) == "kirma-kampanya/HATA")["output"]
    assert "BREAK_CAMPAIGN" in out["environment"] and "kasıtlı" in out["environment"]
    c3 = next(g for p, g in BUGS if golden_ref(p) == "HATA")["output"]
    assert "kapalı" in c3["environment"]


def test_c3_bug_summary_carries_the_literal_values() -> None:
    out = next(g for p, g in BUGS if golden_ref(p) == "HATA")["output"]
    assert out["summary"] == (
        "Sepet: 6 adet Portakal Gazozu sepete eklendiğinde bedava adet 0 beklenirken 1 görünüyor"
    )
    assert "bedava adet 0" in out["expected"] and "bedava adet 1" in out["actual"]
    # Koşu yalnızca bedava adedi ölçtü (ilk assertion'da durdu): gerçekleşene tutar yazılmaz.
    assert "TL" not in out["actual"]


def test_resolve_evidence_links_placeholders_and_drops_inventions() -> None:
    out = {
        "evidence": [
            {"kind": "trace", "ref": "kanit:trace"},
            {"kind": "screenshot", "ref": "kanit:screenshot"},
            {"kind": "allure", "ref": "kanit:allure"},
            {"kind": "log", "ref": "https://uydurma.example/log"},
            {"kind": "code", "ref": "api/src/demoapp_api/campaign.py:23"},
            {"kind": "trace", "ref": "kanit:trace"},
        ]
    }
    got = resolve_evidence(
        out,
        {"trace": "/api/artifacts/k/x/trace.zip", "screenshot": None},
        literal_refs=["api/src/demoapp_api/campaign.py:23"],
    )
    assert got["evidence"] == [
        {"kind": "trace", "ref": "/api/artifacts/k/x/trace.zip"},
        {"kind": "code", "ref": "api/src/demoapp_api/campaign.py:23"},
    ]


def test_invented_dup_keys_flags_keys_outside_the_search() -> None:
    cands = [di.seed_bug("TPD-5")]
    assert invented_dup_keys({"candidates": [{"key": "TPD-5"}], "link_key": "TPD-5"}, cands) == []
    assert invented_dup_keys(
        {"candidates": [{"key": "TPD-5"}, {"key": "TPD-9"}], "link_key": "TPD-12"}, cands
    ) == ["TPD-12", "TPD-9"]


# ------------------------------------------------------------------ constitution X


def test_replay_rows_carry_the_pending_live_evaluation_status(rules_dir: Path) -> None:
    recorder = InMemoryCallRecorder()
    gw = _gateway(rules_dir, recorder, strict=True)
    for purpose, build in (
        ("triage", di.timeout_messages),
        ("bug_draft", lambda: di.bug_messages(di.c3_sources())),
        ("dup_rank", lambda: di.dup_messages(di.c3_sources(), ["TPD-5"])),
    ):
        _call(gw, purpose, build())
        ev = recorder.ai_calls[-1]["ek"]["degerlendirme"]
        assert ev == {
            "paket": PURPOSES[purpose],
            "surum": 2,
            "durum": "pending",
            "etiket": PENDING_LABEL,
            "guardrails_durum": "pending",
        }
    assert gw.evaluation_of("bug-draft")["etiket"] == "canlı değerlendirme bekliyor"


FAILURE_BUGS = [(p, g) for p, g in BUGS if "failure:*" in g["input_match"]["sources"]]


@pytest.mark.parametrize(
    ("path", "golden"), FAILURE_BUGS, ids=[golden_ref(p) for p, _ in FAILURE_BUGS]
)
def test_failure_bug_actual_is_only_the_measured_value(path: Path, golden: dict) -> None:
    """bug-draft.md: test hatasında `actual` yalnızca gözleneni (assertion'ın gerçekleşen değeri)
    söyler; koşunun ölçmediği tutar veya çıkarım ("kampanya 6. adette başlıyor") Jira'ya gözlem
    diye yazılmaz."""
    spec = golden["input_match"]["contains"]
    expected = next(c for c in spec if c.startswith("Beklenen: ")).removeprefix("Beklenen: ")
    received = next(c for c in spec if c.startswith("Gerçekleşen: ")).removeprefix("Gerçekleşen: ")
    actual = golden["output"]["actual"]
    assert actual.endswith(f"(assertion: beklenen {expected}, gerçekleşen {received})"), actual
    assert actual.count(";") == 0 and "TL" not in actual, actual
    assert f"bedava adet {received.strip(chr(34))} görünüyor" in actual
