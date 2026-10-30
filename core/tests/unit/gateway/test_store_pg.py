"""Kalıcı harcama defteri ve çağrı ailesi okuyucusu gerçek Postgres'e karşı (platform fikstürleri:
tek kullanımlık postgres:16 konteyneri, alembic head; Docker yoksa atlanır)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text

from tests.unit.platform.conftest import db, engine, pg  # noqa: F401  (pytest fikstürleri)
from tp_core.audit.recorder import PgCallRecorder
from tp_core.gateway import (
    Budget,
    BudgetExceeded,
    Gateway,
    GatewaySettings,
    RetryPolicy,
    build_gateway,
    deterministic_call_id,
    load_model_table,
    load_schema,
)
from tp_core.gateway.store import PgCallLookup, PgSpendLedger
from tp_core.gateway.testing import FakeProvider, text_response
from tp_core.ports import ModelMessage

VALID = {"questions": [], "verdict": "ready", "summary": "Hazır."}
MSGS = [ModelMessage(role="user", content="TPD-4 Bayi girişi")]


def _gateway(eng: Engine, rules_dir, script, *, workflow_cap=2.0, daily_cap=30.0):
    provider = FakeProvider(script)
    gw = Gateway(
        provider=provider,
        recorder=PgCallRecorder(eng),
        mode="live",
        models=load_model_table(rules_dir),
        rules_dir=rules_dir,
        budget=Budget(
            workflow_cap_usd=workflow_cap, daily_cap_usd=daily_cap, ledger=PgSpendLedger(eng)
        ),
        retry=RetryPolicy(max_retries=0),
        sleep=lambda _s: None,
        call_lookup=PgCallLookup(eng),
    )
    return gw, provider


def _call(gw, rules_dir, *, workflow_id=None, call_id=None):
    return gw.call(
        "requirement_review",
        "requirement-review",
        MSGS,
        load_schema(rules_dir, "requirement_review"),
        replay_key={"name": "TPD-4"},
        workflow_id=workflow_id,
        call_id=call_id,
    )


def test_spend_survives_a_new_gateway_instance(engine: Engine, rules_dir) -> None:  # noqa: F811
    wf = uuid4()
    gw1, _ = _gateway(
        engine, rules_dir, [text_response(VALID, input_tokens=100_000, output_tokens=20_000)]
    )
    first = _call(gw1, rules_dir, workflow_id=wf)
    assert first.cost_usd == pytest.approx(0.4)  # 0,1M × 2 + 0,02M × 10

    # core-worker yeniden başladı: yeni geçit, yeni defter nesnesi — harcama DB'den okunur.
    ledger = PgSpendLedger(engine)
    assert ledger.spent_workflow(wf) == pytest.approx(0.4)
    assert ledger.spent_today() >= 0.4
    gw2, provider2 = _gateway(engine, rules_dir, [text_response(VALID)], workflow_cap=0.4)
    with pytest.raises(BudgetExceeded, match="iş akışı"):
        _call(gw2, rules_dir, workflow_id=wf)
    assert provider2.requests == []  # tavan çağrıdan önce uygulandı

    gw3, _ = _gateway(engine, rules_dir, [text_response(VALID)], daily_cap=0.4)
    with pytest.raises(BudgetExceeded, match="günlük"):
        _call(gw3, rules_dir, workflow_id=uuid4())


def test_daily_spend_uses_utc_day(engine: Engine, rules_dir) -> None:  # noqa: F811
    gw, _ = _gateway(
        engine, rules_dir, [text_response(VALID, input_tokens=1_000_000, output_tokens=0)]
    )
    _call(gw, rules_dir)
    today = datetime.now(UTC).date()
    assert PgSpendLedger(engine, today=lambda: today).spent_today() == pytest.approx(2.0)
    yarin = today + timedelta(days=1)
    assert PgSpendLedger(engine, today=lambda: yarin).spent_today() == 0


def test_call_id_dedups_across_instances(engine: Engine, rules_dir) -> None:  # noqa: F811
    cid = deterministic_call_id(uuid4(), "requirement_review")
    wf = uuid4()
    gw1, p1 = _gateway(engine, rules_dir, [text_response(VALID, input_tokens=1000)])
    first = _call(gw1, rules_dir, workflow_id=wf, call_id=cid)
    spent = PgSpendLedger(engine).spent_workflow(wf)

    gw2, p2 = _gateway(engine, rules_dir, [])  # yeniden deneme yeni süreçte
    second = _call(gw2, rules_dir, workflow_id=wf, call_id=cid)
    assert p2.requests == [] and len(p1.requests) == 1
    assert second.output == first.output and second.call_id == cid
    assert second.cost_usd == pytest.approx(first.cost_usd)
    with engine.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM ai_call WHERE id = :c OR parent_call_id = :c"), {"c": cid}
        ).scalar_one()
    assert n == 1
    assert PgSpendLedger(engine).spent_workflow(wf) == spent


def test_build_gateway_with_engine_uses_pg(engine: Engine, rules_dir) -> None:  # noqa: F811
    gw = build_gateway(
        PgCallRecorder(engine),
        settings=GatewaySettings(TP_RULES_DIR=str(rules_dir), TP_MODEL_MODE="replay"),
        engine=engine,
    )
    assert isinstance(gw.budget.ledger, PgSpendLedger)
    assert isinstance(gw.call_lookup, PgCallLookup)
    result = _call(gw, rules_dir, call_id=uuid4())
    assert result.mode == "replay_miss"
    # build_gateway varsayılanı record_extras=True: ayrıntılar ai_call.ek'e (0005) yazılır.
    with engine.connect() as conn:
        mod, ek = conn.execute(
            text("SELECT mod, ek FROM ai_call WHERE id = :c"), {"c": result.call_id}
        ).one()
    assert mod == "replay_miss" and isinstance(ek, dict)


def test_promote_from_pg_audit_rows(engine: Engine, rules_dir) -> None:  # noqa: F811
    """Prova akışı gerçek ai_call ile: gevşek koşu → replay_miss satırları → yükselt → sıkı koşu."""
    from tp_core.gateway import ReplayStore
    from tp_core.gateway.promote import fetch_replay_misses, main, promote_from_rows

    wf = uuid4()
    loose = build_gateway(
        PgCallRecorder(engine),
        settings=GatewaySettings(TP_RULES_DIR=str(rules_dir), TP_MODEL_MODE="replay"),
        engine=engine,
    )
    assert _call(loose, rules_dir, workflow_id=wf).mode == "replay_miss"
    rows = fetch_replay_misses(engine, wf)
    assert len(rows) == 1 and rows[0]["amac"] == "requirement_review"
    assert fetch_replay_misses(engine, uuid4()) == []

    outcomes = promote_from_rows(ReplayStore(rules_dir / "replay"), rows)
    assert [(o.golden, o.reason) for o in outcomes] == [("TPD-4", "yazıldı")]
    strict = build_gateway(
        PgCallRecorder(engine),
        settings=GatewaySettings(
            TP_RULES_DIR=str(rules_dir), TP_MODEL_MODE="replay", TP_REPLAY_STRICT="1"
        ),
        engine=engine,
    )
    assert _call(strict, rules_dir, workflow_id=wf).mode == "replay"
    # CLI aynı satırları "zaten var" görür; eşleşmeyen yoksa 0 döner.
    url = engine.url.render_as_string(hide_password=False)
    assert main(["--rules", str(rules_dir), "--database-url", url, "--workflow", str(wf)]) == 0
