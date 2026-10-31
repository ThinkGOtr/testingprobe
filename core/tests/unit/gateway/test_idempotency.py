"""`call_id` idempotency (§8.8): iş yeniden denemesi aynı çağrıyı iki kez faturalamaz ve
ikinci `ai_call` satırı yazmaz. Kayıt modu (record) yazma hatası ücretli sonucu kaybettirmez."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from tp_core.gateway import (
    Budget,
    GatewayConfigError,
    GatewaySettings,
    InMemorySpendLedger,
    ProviderTransientError,
    ReplayMiss,
    build_gateway,
    deterministic_call_id,
    golden_name,
    load_schema,
)
from tp_core.gateway.core import FINAL_TOOL, REPLAY_SAVE_FAILED
from tp_core.gateway.replay import ReplayStore
from tp_core.gateway.testing import InMemoryCallRecorder, text_response, tool_response
from tp_core.ports import ModelMessage, ToolSpec

VALID = {"questions": [], "verdict": "ready", "summary": "Hazır."}
MSGS = [ModelMessage(role="user", content="TPD-4 Bayi girişi")]
KEY = {"name": "TPD-4", "jira_key": "TPD-4"}


def _call(gw, rules_dir, call_id=None, workflow_id=None):
    return gw.call(
        "requirement_review",
        "requirement-review",
        MSGS,
        load_schema(rules_dir, "requirement_review"),
        replay_key=KEY,
        workflow_id=workflow_id,
        call_id=call_id,
    )


def test_deterministic_call_id_is_stable() -> None:
    job = uuid4()
    assert deterministic_call_id(job, "review") == deterministic_call_id(str(job), "review")
    assert deterministic_call_id(job, "review") != deterministic_call_id(job, "cases")


def test_same_call_id_one_provider_call_one_row_one_charge(make_gateway, rules_dir, recorder):
    ledger = InMemorySpendLedger()
    gw, provider = make_gateway(
        [text_response(VALID, input_tokens=1000, output_tokens=200)],
        budget=Budget(ledger=ledger),
    )
    wf, cid = uuid4(), deterministic_call_id(uuid4(), "requirement_review")
    first = _call(gw, rules_dir, cid, wf)
    spent = ledger.spent_workflow(wf)
    second = _call(gw, rules_dir, cid, wf)  # iş yeniden denemesi (senaryoda yanıt kalmadı)
    assert len(provider.requests) == 1
    assert len(recorder.ai_calls) == 1
    assert recorder.ai_calls[0]["id"] == cid == first.call_id == second.call_id
    assert second == first  # aynı çıktı, mod, token, maliyet
    assert ledger.spent_workflow(wf) == spent > 0


def test_without_call_id_each_call_is_new(make_gateway, rules_dir, recorder):
    gw, provider = make_gateway([text_response(VALID), text_response(VALID)])
    a, b = _call(gw, rules_dir), _call(gw, rules_dir)
    assert a.call_id != b.call_id and len(provider.requests) == 2


def test_retry_after_failed_attempt_calls_again_then_dedups(make_gateway, rules_dir, recorder):
    boom = ProviderTransientError("529", status=529)
    gw, provider = make_gateway([boom, boom, boom, boom, text_response(VALID)])
    cid = uuid4()
    with pytest.raises(ProviderTransientError):
        _call(gw, rules_dir, cid)
    assert recorder.ai_calls[0]["id"] == cid and recorder.ai_calls[0]["hata"]
    result = _call(gw, rules_dir, cid)  # yeniden deneme: kök başarısızdı → yeni çağrı
    assert result.output == VALID
    retry_row = recorder.ai_calls[1]
    assert retry_row["id"] != cid and retry_row["parent_call_id"] == cid
    assert result.call_id == retry_row["id"]
    again = _call(gw, rules_dir, cid)  # üçüncü deneme: başarılı sonuç ailede → sağlayıcı yok
    assert again == result
    assert len(provider.requests) == 5 and len(recorder.ai_calls) == 2


def test_schema_reask_rows_belong_to_the_call_id(make_gateway, rules_dir, recorder):
    gw, provider = make_gateway([text_response("JSON değil"), text_response(VALID)])
    cid = uuid4()
    result = _call(gw, rules_dir, cid)
    assert [r["id"] == cid for r in recorder.ai_calls] == [True, False]
    assert recorder.ai_calls[1]["parent_call_id"] == cid
    assert _call(gw, rules_dir, cid) == result
    assert len(provider.requests) == 2 and len(recorder.ai_calls) == 2


def test_replay_mode_call_id_writes_one_row(make_gateway, rules_dir, recorder):
    gw, _ = make_gateway(mode="replay")
    cid = uuid4()
    a, b = _call(gw, rules_dir, cid), _call(gw, rules_dir, cid)
    assert a == b and a.mode == "replay_miss"
    assert [r["id"] for r in recorder.ai_calls] == [cid]


def test_agent_call_id_is_idempotent(make_gateway, rules_dir, recorder):
    schema = load_schema(rules_dir, "triage")
    final = {
        "class": "product_defect",
        "sub_type": None,
        "rationale": "Kampanya indirimi beklenen 25,00 TL değil.",
        "signals": ["Assertion farkı: cart-discount"],
    }
    gw, provider = make_gateway(
        [tool_response(("search", {"q": "x"})), tool_response((FINAL_TOOL, final))],
        agent_tools={"triage": {"search"}},  # test amaçlı ajan izin listesi
    )
    tools = [ToolSpec(name="search", description="ara", input_schema={"type": "object"})]
    cid = uuid4()
    kwargs = {"replay_key": {"name": "break-campaign"}, "call_id": cid}
    first = gw.run_agent("triage", "triage", MSGS, tools, lambda n, a: "ok", schema, **kwargs)
    second = gw.run_agent("triage", "triage", MSGS, tools, lambda n, a: "ok", schema, **kwargs)
    assert first.output == second.output == final
    assert len(provider.requests) == 2  # yalnızca ilk koşunun iki turu
    assert len(recorder.ai_calls) == 2
    assert recorder.ai_calls[0]["id"] == cid
    assert recorder.ai_calls[1]["parent_call_id"] == cid
    assert second.mode == "live" and second.call_ids == [r["id"] for r in recorder.ai_calls]


def test_recorder_lookup_is_used_by_default(make_gateway):
    gw, _ = make_gateway([])
    assert gw.call_lookup is gw.recorder


# ------------------------------------------------------------------ record modu


class _ReadOnlyStore(ReplayStore):
    def save(self, purpose, key, record):  # type: ignore[override]
        raise PermissionError(30, "Read-only file system", str(self.root))


def test_record_save_failure_keeps_paid_result(make_gateway, rules_dir, recorder, caplog):
    gw, _ = make_gateway(
        [text_response(VALID)], mode="record", replay_store=_ReadOnlyStore(rules_dir / "replay")
    )
    result = _call(gw, rules_dir)
    assert result.output == VALID and result.mode == "live"
    row = recorder.ai_calls[0]
    assert row["sema_gecerli"] is True
    assert row["hata"].startswith(f"{REPLAY_SAVE_FAILED}: PermissionError")
    assert "replay kaydı yazılamadı" in caplog.text
    # İdempotency için bu satır hâlâ başarılı sayılır.
    assert gw.call_lookup is not None


def test_record_save_failure_in_agent_is_traced(make_gateway, rules_dir, recorder):
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
    gw, _ = make_gateway(
        [tool_response((FINAL_TOOL, {"ok": True}))],
        mode="record",
        replay_store=_ReadOnlyStore(rules_dir / "replay"),
    )
    result = gw.run_agent(
        "verify_and_map", "verify-and-map", MSGS, [], lambda n, a: "", schema, replay_key={}
    )
    assert result.output == {"ok": True}
    trace = [t for t in recorder.tool_calls if t["arac"] == "replay_kaydet"]
    assert len(trace) == 1 and trace[0]["sonuc_ozeti"].startswith(REPLAY_SAVE_FAILED)


@pytest.mark.skipif(os.geteuid() == 0, reason="root için chmod salt okuma sağlamaz")
def test_build_gateway_record_mode_fails_fast_on_read_only_rules(rules_dir: Path) -> None:
    replay = rules_dir / "replay"
    replay.chmod(0o555)
    try:
        settings = GatewaySettings(
            TP_RULES_DIR=str(rules_dir), TP_MODEL_MODE="record", ANTHROPIC_API_KEY="sk-test"
        )
        with pytest.raises(GatewayConfigError, match=r"yazılamıyor|salt okunur"):
            build_gateway(InMemoryCallRecorder(), settings=settings)
    finally:
        replay.chmod(0o755)


def test_build_gateway_record_mode_ok_when_writable(rules_dir: Path) -> None:
    settings = GatewaySettings(
        TP_RULES_DIR=str(rules_dir), TP_MODEL_MODE="record", ANTHROPIC_API_KEY="sk-test"
    )
    gw = build_gateway(InMemoryCallRecorder(), settings=settings)
    assert gw.mode == "record"
    assert not list((rules_dir / "replay").glob(".yazma-testi-*"))


# ------------------------------------------------------------------ prova kipi ve golden adları


def test_strict_replay_refuses_golden_fallback(rules_dir: Path) -> None:
    """§13 "REPLAY-MISS olmadan replay": prova kipinde golden'a düşen her çağrı hata verir."""
    settings = GatewaySettings(
        TP_RULES_DIR=str(rules_dir), TP_MODEL_MODE="replay", TP_REPLAY_STRICT="1"
    )
    recorder = InMemoryCallRecorder()
    gw = build_gateway(recorder, settings=settings)
    with pytest.raises(ReplayMiss, match="REPLAY-MISS"):
        _call(gw, rules_dir)
    # Sessizce golden çıktısı üretilmedi; yapılamayan çağrı yine de denetimde (VIII).
    assert [(r["mod"], r["cikti"]) for r in recorder.ai_calls] == [("replay_miss", None)]
    assert recorder.ai_calls[0]["hata"].startswith("ReplayMiss")


def test_strict_replay_serves_exact_recordings(make_gateway, rules_dir) -> None:
    rec_gw, _ = make_gateway([text_response(VALID)], mode="record")
    _call(rec_gw, rules_dir)  # canlı + kayıt
    settings = GatewaySettings(
        TP_RULES_DIR=str(rules_dir), TP_MODEL_MODE="replay", TP_REPLAY_STRICT="1"
    )
    result = _call(build_gateway(InMemoryCallRecorder(), settings=settings), rules_dir)
    assert result.mode == "replay" and result.output == VALID


def test_golden_name_convention() -> None:
    assert golden_name("TPD-1") == "TPD-1"
    assert golden_name("TPD-1", case_no=2) == "TPD-1-C2"
    assert golden_name("TPD-1", check_round=2) == golden_name("TPD-1", check_round=3) == "TPD-1-r2"
    with pytest.raises(ValueError):
        golden_name("TPD-1", case_no=0)
    with pytest.raises(ValueError):
        golden_name("TPD-1", case_no=1, check_round=2)
