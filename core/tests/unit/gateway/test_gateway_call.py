import json
from uuid import uuid4

import pytest

from tp_core.gateway import (
    Budget,
    BudgetExceeded,
    PiiMasker,
    ProviderPermanentError,
    ProviderTransientError,
    ReplayNotFound,
    SchemaValidationFailed,
    load_schema,
)
from tp_core.gateway.testing import text_response
from tp_core.ports import ModelGateway, ModelMessage

VALID = {"questions": [], "verdict": "ready", "summary": "Hazır."}
MSGS = [
    ModelMessage(
        role="user", content='<untrusted kind="jira" source="jira:TPD-4">Bayi girişi</untrusted>'
    )
]
KEY = {"name": "TPD-4", "jira_key": "TPD-4"}


def call(gw, rules_dir, *, messages=MSGS, key=KEY, workflow_id=None, purpose="requirement_review"):
    return gw.call(
        purpose,
        "requirement-review",
        messages,
        load_schema(rules_dir, purpose),
        replay_key=key,
        workflow_id=workflow_id,
    )


def test_implements_port(make_gateway) -> None:
    gw, _ = make_gateway([])
    assert isinstance(gw, ModelGateway)


def test_live_success_records_and_costs(make_gateway, rules_dir, recorder) -> None:
    gw, provider = make_gateway([text_response(VALID, input_tokens=1000, output_tokens=200)])
    result = call(gw, rules_dir)
    assert result.mode == "live"
    assert result.output == VALID
    # sonnet 5.5: 2 USD/M girdi, 10 USD/M çıktı
    assert result.cost_usd == pytest.approx(1000 * 2 / 1e6 + 200 * 10 / 1e6)
    assert len(recorder.ai_calls) == 1
    row = recorder.ai_calls[0]
    assert row["id"] == result.call_id
    assert row["mod"] == "live"
    assert row["model"] == "claude-sonnet-5-5"
    assert row["surum"] == "requirement-review@v1"
    assert row["sema_gecerli"] is True
    assert row["deneme"] == 1
    assert len(row["bundle_hash"]) == 64
    assert row["maskeleme_farki"] == {"enabled": False, "counts": {}, "placeholders": []}
    req = provider.requests[0]
    assert req.model == "claude-sonnet-5-5"
    assert req.output_schema == load_schema(rules_dir, "requirement_review")
    assert "Security rules" in req.system  # ortak güvenlik kuralları her bundle'da
    assert req.params["effort"] == "medium"


def test_schema_reask_then_success(make_gateway, rules_dir, recorder) -> None:
    bad = {"questions": [{"id": "X", "type": "nope", "text": "", "ac_ref": None}], "verdict": "ok"}
    gw, provider = make_gateway(
        [text_response("bu JSON değil"), text_response(bad), text_response(VALID)]
    )
    result = call(gw, rules_dir)
    assert result.output == VALID
    assert [r["sema_gecerli"] for r in recorder.ai_calls] == [False, False, True]
    assert [r["deneme"] for r in recorder.ai_calls] == [1, 2, 3]
    first = recorder.ai_calls[0]["id"]
    assert all(r["parent_call_id"] == first for r in recorder.ai_calls[1:])
    assert "JSON ayrıştırılamadı" in recorder.ai_calls[0]["ek"]["sema_hatalari"][0]
    assert recorder.ai_calls[0]["hata"].startswith("şema: JSON ayrıştırılamadı")
    # İkinci denemede model önceki yanıtı ve hata listesini görür
    second = provider.requests[1].messages
    assert second[-2] == {"role": "assistant", "content": "bu JSON değil"}
    assert "did not match the required JSON schema" in second[-1]["content"]
    third = provider.requests[2].messages[-1]["content"]
    assert "verdict" in third and "summary" in third  # eksik/yanlış alanlar listelenir
    assert result.input_tokens == 300  # üç denemenin toplamı


def test_schema_fails_after_two_reasks(make_gateway, rules_dir, recorder) -> None:
    gw, _ = make_gateway([text_response({"x": 1})] * 3)
    with pytest.raises(SchemaValidationFailed) as exc:
        call(gw, rules_dir)
    assert len(recorder.ai_calls) == 3
    assert exc.value.errors
    assert exc.value.last_output == {"x": 1}


def test_transient_errors_retry_with_backoff(make_gateway, rules_dir, recorder, sleeps) -> None:
    gw, _ = make_gateway(
        [
            ProviderTransientError("429", status=429),
            ProviderTransientError("529", status=529),
            ProviderTransientError("500", status=500),
            text_response(VALID),
        ]
    )
    result = call(gw, rules_dir)
    assert result.output == VALID
    assert sleeps == [1.0, 2.0, 4.0]
    assert recorder.ai_calls[0]["ek"]["yeniden_deneme"] == 3


def test_transient_errors_exhausted(make_gateway, rules_dir, recorder, sleeps) -> None:
    gw, _ = make_gateway([ProviderTransientError("529", status=529)] * 4)
    with pytest.raises(ProviderTransientError):
        call(gw, rules_dir)
    assert len(sleeps) == 3
    assert recorder.ai_calls[0]["hata"].startswith("ProviderTransientError")


def test_permanent_error_not_retried(make_gateway, rules_dir, sleeps) -> None:
    gw, _ = make_gateway([ProviderPermanentError("400", status=400), text_response(VALID)])
    with pytest.raises(ProviderPermanentError):
        call(gw, rules_dir)
    assert sleeps == []


def test_workflow_budget(make_gateway, rules_dir) -> None:
    wf = uuid4()
    budget = Budget(workflow_cap_usd=0.01, daily_cap_usd=30)
    # 1 çağrı: 1000*2/1e6 + 1000*10/1e6 = 0.012 USD → ikinci çağrı engellenir
    gw, provider = make_gateway(
        [text_response(VALID, input_tokens=1000, output_tokens=1000)] * 2, budget=budget
    )
    call(gw, rules_dir, workflow_id=wf)
    with pytest.raises(BudgetExceeded) as exc:
        call(gw, rules_dir, workflow_id=wf)
    assert exc.value.scope == "iş akışı"
    assert len(provider.requests) == 1
    # Başka iş akışı etkilenmez
    call(gw, rules_dir, workflow_id=uuid4())


def test_daily_budget(make_gateway, rules_dir) -> None:
    budget = Budget(workflow_cap_usd=100, daily_cap_usd=0.005)
    gw, _ = make_gateway(
        [text_response(VALID, input_tokens=1000, output_tokens=1000)] * 2, budget=budget
    )
    call(gw, rules_dir, workflow_id=uuid4())
    with pytest.raises(BudgetExceeded) as exc:
        call(gw, rules_dir, workflow_id=uuid4())
    assert exc.value.scope == "günlük"


def test_record_then_replay_hit(make_gateway, rules_dir, recorder) -> None:
    gw, _ = make_gateway([text_response(VALID)], mode="record")
    live = call(gw, rules_dir)
    assert live.mode == "live"
    files = list((rules_dir / "replay" / "requirement_review").glob("*.json"))
    assert len(files) == 1
    stored = json.loads(files[0].read_text())
    assert stored["output"] == VALID and stored["kind"] == "call"

    replay_gw, _ = make_gateway(mode="replay")
    # zaman damgası ve UUID'ler normalize edilir → aynı anahtar
    result = call(replay_gw, rules_dir)
    assert result.mode == "replay"
    assert result.output == VALID
    assert result.cost_usd == 0
    row = recorder.ai_calls[-1]
    assert row["mod"] == "replay"
    assert row["saglayici"] == "replay"
    assert row["ek"]["replay_kaynagi"] == f"requirement_review/{files[0].name}"


def test_replay_key_ignores_timestamps_and_uuids(make_gateway, rules_dir) -> None:
    def msg(ts: str, u: str) -> list[ModelMessage]:
        return [ModelMessage(role="user", content=f"çekim {ts} id {u} [ref=e12]")]

    gw, _ = make_gateway([text_response(VALID)], mode="record")
    call(gw, rules_dir, messages=msg("2026-10-30T10:00:00Z", str(uuid4())))
    replay_gw, _ = make_gateway(mode="replay")
    result = call(replay_gw, rules_dir, messages=msg("2026-11-02 08:15:42+03:00", str(uuid4())))
    assert result.mode == "replay"


def test_replay_miss_falls_back_to_named_golden(make_gateway, rules_dir, recorder) -> None:
    gw, _ = make_gateway(mode="replay")
    result = call(gw, rules_dir, messages=[ModelMessage(role="user", content="farklı girdi")])
    assert result.mode == "replay_miss"
    golden = json.loads((rules_dir / "replay/requirement_review/golden/TPD-4.json").read_text())
    assert result.output == golden["output"]
    assert recorder.ai_calls[-1]["mod"] == "replay_miss"
    assert recorder.ai_calls[-1]["ek"]["replay_kaynagi"] == "requirement_review/golden/TPD-4.json"


def test_bundle_change_causes_replay_miss(make_gateway, rules_dir) -> None:
    gw, _ = make_gateway([text_response(VALID)], mode="record")
    call(gw, rules_dir)
    prompt = rules_dir / "prompts" / "requirement-review.md"
    prompt.write_text(prompt.read_text() + "\nExtra rule.\n")
    replay_gw, _ = make_gateway(mode="replay")
    assert call(replay_gw, rules_dir).mode == "replay_miss"


def test_replay_not_found_is_loud(make_gateway, rules_dir) -> None:
    gw, _ = make_gateway(mode="replay")
    with pytest.raises(ReplayNotFound):
        call(gw, rules_dir, key={"name": "TPD-999"})
    with pytest.raises(ReplayNotFound):
        call(gw, rules_dir, key={"jira_key": "TPD-4"})  # golden adı yok


def test_masking_hook_always_called(make_gateway, rules_dir) -> None:
    calls: list[object] = []

    class SpyMasker(PiiMasker):
        def new_session(self):
            s = super().new_session()
            original = s.mask

            def spy(obj):
                calls.append(obj)
                return original(obj)

            s.mask = spy  # type: ignore[method-assign]
            return s

    gw, _ = make_gateway([text_response(VALID)], masker=SpyMasker(enabled=False))
    call(gw, rules_dir)
    assert len(calls) == 1


def test_masking_round_trip_through_model(make_gateway, rules_dir, recorder) -> None:
    def echo(request):
        text = request.messages[0]["content"]
        assert "ali@ornek.com" not in text
        assert "<<PII_EMAIL_1>>" in text
        return text_response(
            {"questions": [], "verdict": "ready", "summary": "İletişim: <<PII_EMAIL_1>>"}
        )

    gw, _ = make_gateway([echo], masker=PiiMasker(enabled=True))
    wf = uuid4()
    result = call(
        gw,
        rules_dir,
        messages=[ModelMessage(role="user", content="PO: ali@ornek.com")],
        workflow_id=wf,
    )
    assert result.output["summary"] == "İletişim: ali@ornek.com"
    row = recorder.ai_calls[0]
    assert "ali@ornek.com" not in json.dumps(row["maskeli_girdi"], ensure_ascii=False)
    assert row["maskeleme_farki"]["counts"] == {"EMAIL": 1}
    assert row["cikti"]["summary"] == "İletişim: <<PII_EMAIL_1>>"  # kayıt maskeli kalır


def test_max_tokens_default_uses_purpose_config(make_gateway, rules_dir) -> None:
    gw, provider = make_gateway([text_response({"cases": []})] * 3)
    with pytest.raises(SchemaValidationFailed):  # boş cases minItems=1
        gw.call(
            "case_generation",
            "case-generation",
            MSGS,
            load_schema(rules_dir, "case_generation"),
            replay_key=KEY,
        )
    assert provider.requests[0].max_tokens == 16000


def test_rows_match_platform_ai_call_columns(make_gateway, rules_dir, recorder) -> None:
    """Varsayılan (record_extras=False) satırlar platformun PgCallRecorder'ına yazılabilir."""
    from tp_core.audit.recorder import AI_CALL_COLUMNS, AI_CALL_REQUIRED

    gw, _ = make_gateway([text_response("bozuk"), text_response(VALID)], record_extras=False)
    call(gw, rules_dir)
    for row in recorder.ai_calls:
        assert set(row) <= set(AI_CALL_COLUMNS)
        assert all(row[k] for k in AI_CALL_REQUIRED)
    assert recorder.ai_calls[0]["hata"].startswith("şema:")
