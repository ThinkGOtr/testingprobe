"""Asistan için geçit değişiklikleri (AI-ASISTAN-PLANI §10.3, §6.4, §10.1 "Süre", §13 "Geçit").

Yeni parametrelerin varsayılanı eski davranıştır (mevcut geçit testleri değişmeden yeşil); burada
yeni davranışlar ve varsayılanın korunduğu sınanır: `build_gateway(mode_override=,
replay_fallback=, budget=)`, `run_agent(tool_channel=, caller_user_id=, ek=, masking_session=,
bitis=, should_stop=, toparlama=)`, `PurposeConfig` yeni alanları, `ProviderRequest.fallbacks`,
`DataTools(session=)` ve asistan araç izin listesi.
"""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import yaml

from tp_core.features.requirements.datatools import DataTools, DemoDb, QueryResult
from tp_core.gateway import (
    ALLOWED_AGENT_TOOLS,
    FINAL_TOOL,
    FORBIDDEN_TOOLS,
    AgentTurnLimit,
    Budget,
    GatewayConfigError,
    GatewaySettings,
    PiiMasker,
    ProviderTransientError,
    build_gateway,
    load_model_table,
)
from tp_core.gateway.bundle import load_schema
from tp_core.gateway.core import TOPARLAMA_NUDGE
from tp_core.gateway.errors import AgentDeadlineExceeded, AgentStopped
from tp_core.gateway.providers.anthropic_provider import AnthropicProvider
from tp_core.gateway.providers.base import ProviderRequest
from tp_core.gateway.replay import ReplayStore
from tp_core.gateway.testing import (
    FakeProvider,
    InMemoryCallRecorder,
    text_response,
    tool_response,
)
from tp_core.ports import ModelMessage, ToolSpec

PURPOSE = "consistency_check"
BUNDLE = "consistency-check"
TOOLS = [
    ToolSpec(name=n, description=n, input_schema={"type": "object"})
    for n in sorted(ALLOWED_AGENT_TOOLS[PURPOSE])
]
SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"cevap": {"type": "string"}},
    "required": ["cevap"],
}
MSGS = [ModelMessage(role="user", content="Kampanya kuralı nedir?")]
KEY = {"name": "asistan-gecit-testi"}
DONE = {"cevap": "tamam"}


def _fake_key() -> str:
    # Gerçek biçimli sahte anahtar çalışma anında birleştirilir (repo public; push koruması).
    return "sk-" + "ant-" + "api03-" + "x" * 24


def _run(gw, execute=None, **kw):
    return gw.run_agent(
        PURPOSE,
        BUNDLE,
        kw.pop("messages", MSGS),
        TOOLS,
        execute or (lambda name, args: f"{name} sonucu"),
        kw.pop("schema", SCHEMA),
        replay_key=kw.pop("replay_key", KEY),
        **kw,
    )


def _texts(request: ProviderRequest) -> str:
    return json.dumps(request.messages, ensure_ascii=False)


def _edit_purpose(rules_dir: Path, purpose: str, **fields: Any) -> None:
    path = rules_dir / "models.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["purposes"][purpose].update(fields)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


class Saat:
    """Sahte geçit saati (`Gateway(clock=)`)."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


# ------------------------------------------------------------------ varsayılan = eski davranış


def test_varsayilanlar_eski_davranis(make_gateway, recorder) -> None:
    gw, provider = make_gateway(
        [tool_response(("search_code", {"q": "kampanya"})), tool_response((FINAL_TOOL, DONE))]
    )
    result = _run(gw)
    assert result.output == DONE and result.mode == "live"
    assert all(r["kanal"] == "agent" and r["cagiran_user_id"] is None for r in recorder.tool_calls)
    assert all(
        "kullanici_id" not in r["ek"] and "toparlama" not in r["ek"] for r in recorder.ai_calls
    )
    assert provider.requests[0].timeout_s == 300  # models.yaml consistency_check
    assert provider.requests[0].fallbacks is None


def test_toparlama_kapaliyken_nudge_yok(make_gateway) -> None:
    # İlk tur tavanın %75'ini geçer (120K > 112.5K) ama tavanı (150K) aşmaz.
    gw, provider = make_gateway(
        [
            tool_response(("search_code", {}), input_tokens=120_000),
            tool_response(("search_code", {}), input_tokens=1_000),
            tool_response(("search_code", {}), input_tokens=1_000),
        ]
    )
    with pytest.raises(AgentTurnLimit):
        _run(gw, max_turns=3)
    assert len(provider.requests) == 3
    assert not any(TOPARLAMA_NUDGE in _texts(r) for r in provider.requests)


# ------------------------------------------------------------------ kanal, kullanıcı, ek


def test_kanal_kullanici_ve_ek_kayda_yazilir(make_gateway, recorder) -> None:
    kullanici = uuid4()
    gw, _ = make_gateway(
        [tool_response(("db_query", {"sql": "SELECT 1"})), tool_response((FINAL_TOOL, DONE))]
    )
    _run(
        gw,
        tool_channel="asistan",
        caller_user_id=kullanici,
        ek={"kullanici_id": str(kullanici), "mesaj_id": "m1", "degerlendirme": "ezilmez"},
    )
    assert {r["kanal"] for r in recorder.tool_calls} == {"asistan"}
    assert {r["cagiran_user_id"] for r in recorder.tool_calls} == {kullanici}
    assert len(recorder.ai_calls) == 2
    for row in recorder.ai_calls:
        assert row["ek"]["kullanici_id"] == str(kullanici) and row["ek"]["mesaj_id"] == "m1"
        # Geçidin kendi alanı çağıranınkine baskın (denetim bütünlüğü).
        assert isinstance(row["ek"]["degerlendirme"], dict)
        assert "_cagiran_ek" not in row


def test_ek_record_extras_kapaliyken_de_yazilir(make_gateway, recorder) -> None:
    gw, _ = make_gateway([tool_response((FINAL_TOOL, DONE))], record_extras=False)
    _run(gw, ek={"kullanici_id": "u1"})
    assert recorder.ai_calls[0]["ek"] == {"kullanici_id": "u1"}
    gw2, _ = make_gateway([tool_response((FINAL_TOOL, DONE))], record_extras=False)
    _run(gw2)
    assert "ek" not in recorder.ai_calls[-1]


def test_replay_yolunda_kanal_ve_ek(make_gateway, rules_dir, recorder) -> None:
    golden = rules_dir / "replay" / PURPOSE / "golden" / "asistan-gecit-testi.json"
    golden.write_text(
        json.dumps(
            {
                "kind": "agent",
                "purpose": PURPOSE,
                "golden": "asistan-gecit-testi",
                "note": "elle hazırlandı (test)",
                "steps": [
                    {
                        "tool": "search_code",
                        "args": {"q": "x"},
                        "result_summary": "",
                        "allowed": True,
                    }
                ],
                "output": DONE,
            }
        ),
        encoding="utf-8",
    )
    gw, _ = make_gateway(mode="replay")
    kullanici = uuid4()
    result = _run(gw, tool_channel="asistan", caller_user_id=kullanici, ek={"kullanici_id": "u9"})
    assert result.output == DONE
    assert recorder.ai_calls[-1]["ek"]["kullanici_id"] == "u9"
    assert [(r["kanal"], r["cagiran_user_id"]) for r in recorder.tool_calls] == [
        ("asistan", kullanici)
    ]


# ------------------------------------------------------------------ süre ve durdurma


def test_bitis_tur_basinda_durdurur(make_gateway) -> None:
    saat = Saat()

    def arac(name: str, args: dict) -> str:
        saat.t = 80.0  # araç uzun sürdü: süre doldu
        return "sonuç"

    gw, provider = make_gateway(
        [tool_response(("search_code", {})), tool_response((FINAL_TOOL, DONE))], clock=saat
    )
    with pytest.raises(AgentDeadlineExceeded):
        _run(gw, arac, bitis=75.0)
    assert len(provider.requests) == 1  # ikinci (ücretli) tur açılmadı


def test_bitis_istek_zaman_asimini_kalan_sureyle_sinirlar(make_gateway) -> None:
    saat = Saat(70.0)
    gw, provider = make_gateway([tool_response((FINAL_TOOL, DONE))], clock=saat)
    _run(gw, bitis=75.0)
    assert provider.requests[0].timeout_s == pytest.approx(5.0)  # 300 sn yerine kalan 5 sn


def test_yeniden_deneme_beklemesi_kalan_sureye_sigmazsa_durur(make_gateway, sleeps) -> None:
    saat = Saat()

    def gec_hata(request: ProviderRequest):
        saat.t = 74.5
        raise ProviderTransientError("529", status=529)

    gw, provider = make_gateway([gec_hata, tool_response((FINAL_TOOL, DONE))], clock=saat)
    with pytest.raises(AgentDeadlineExceeded):
        _run(gw, bitis=75.0)
    assert sleeps == [] and len(provider.requests) == 1


def test_kalan_sureyle_kisilan_istek_zaman_asiminda_sure_doldu(make_gateway, recorder) -> None:
    gw, provider = make_gateway(
        [ProviderTransientError("zaman aşımı", timeout=True), tool_response((FINAL_TOOL, DONE))],
        clock=Saat(70.0),
    )
    with pytest.raises(AgentDeadlineExceeded):
        _run(gw, bitis=75.0)
    assert len(provider.requests) == 1
    assert recorder.ai_calls[-1]["hata"].startswith("AgentDeadlineExceeded")


def test_should_stop_tur_basinda(make_gateway, recorder) -> None:
    durdur = {"evet": False}

    def arac(name: str, args: dict) -> str:
        durdur["evet"] = True  # kullanıcı mesajı iptal etti
        return "sonuç"

    gw, provider = make_gateway(
        [tool_response(("search_code", {})), tool_response((FINAL_TOOL, DONE))]
    )
    with pytest.raises(AgentStopped):
        _run(gw, arac, should_stop=lambda: durdur["evet"])
    assert len(provider.requests) == 1
    assert len(recorder.ai_calls) == 1  # yazılan tur (maliyetiyle) kayıtta kalır


# ------------------------------------------------------------------ toparlama


def test_toparlama_sondan_bir_onceki_turdan_sonra(make_gateway, recorder) -> None:
    gw, provider = make_gateway(
        [
            tool_response(("search_code", {})),
            tool_response(("search_code", {})),
            tool_response((FINAL_TOOL, {"cevap": "eldekiyle"})),
        ]
    )
    result = _run(gw, max_turns=3, toparlama=True)
    assert result.output == {"cevap": "eldekiyle"}
    assert [TOPARLAMA_NUDGE in _texts(r) for r in provider.requests] == [False, False, True]
    assert [r["ek"].get("toparlama", False) for r in recorder.ai_calls] == [False, False, True]
    # Nudge araç sonuçlarıyla aynı kullanıcı mesajında (art arda iki kullanıcı mesajı yok).
    roles = [m["role"] for m in provider.requests[-1].messages]
    assert all(a != b for a, b in pairwise(roles))


def test_toparlama_girdi_tavaninin_yuzde_75i_ve_kalici(make_gateway) -> None:
    # consistency_check max_input_tokens 150000 → %75 = 112500.
    gw, provider = make_gateway(
        [
            tool_response(("search_code", {}), input_tokens=120_000),
            tool_response(("search_code", {}), input_tokens=1_000),
            tool_response((FINAL_TOOL, DONE), input_tokens=1_000),
        ]
    )
    _run(gw, max_turns=25, toparlama=True)
    flags = [TOPARLAMA_NUDGE in _texts(r) for r in provider.requests]
    assert flags == [False, True, True]  # bir kez eklenir, geçmişte kalır
    assert _texts(provider.requests[2]).count(TOPARLAMA_NUDGE) == 1


def test_toparlama_metin_yanitinda_da(make_gateway) -> None:
    gw, provider = make_gateway([text_response("düz metin"), tool_response((FINAL_TOOL, DONE))])
    _run(gw, max_turns=2, toparlama=True)
    assert TOPARLAMA_NUDGE in _texts(provider.requests[1])


# ------------------------------------------------------------------ PurposeConfig, yeniden deneme


def test_purpose_config_yeni_alanlar_yamldan(rules_dir: Path) -> None:
    _edit_purpose(rules_dir, PURPOSE, max_retries=1, max_timeout_retries=0, fallbacks="none")
    cfg = load_model_table(rules_dir).purpose(PURPOSE)
    assert (cfg.max_retries, cfg.max_timeout_retries, cfg.fallbacks) == (1, 0, "none")
    other = load_model_table(rules_dir).purpose("triage")
    assert (other.max_retries, other.max_timeout_retries, other.fallbacks) == (None, None, None)


def test_yaml_none_metni_string_olarak_okunur(rules_dir: Path) -> None:
    path = rules_dir / "models.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "  triage:\n", "  triage:\n    fallbacks: none\n", 1
        ),
        encoding="utf-8",
    )
    assert load_model_table(rules_dir).purpose("triage").fallbacks == "none"


@pytest.mark.parametrize(
    "fields",
    [
        {"max_retries": -1},
        {"max_retries": "iki"},
        {"max_timeout_retries": True},
        {"fallbacks": "x"},
    ],
)
def test_purpose_config_gecersiz_deger(rules_dir: Path, fields: dict) -> None:
    _edit_purpose(rules_dir, PURPOSE, **fields)
    with pytest.raises(GatewayConfigError):
        load_model_table(rules_dir)


def test_amac_max_retries_complete_tarafindan_okunur(make_gateway, rules_dir, sleeps) -> None:
    _edit_purpose(rules_dir, PURPOSE, max_retries=1)
    hata = ProviderTransientError("529", status=529)
    gw, provider = make_gateway([hata, hata, tool_response((FINAL_TOOL, DONE))])
    with pytest.raises(ProviderTransientError):
        _run(gw)
    assert len(provider.requests) == 2 and len(sleeps) == 1  # RetryPolicy 3 yerine amaç 1


def test_amac_max_timeout_retries_sifir(make_gateway, rules_dir, sleeps) -> None:
    _edit_purpose(rules_dir, PURPOSE, max_timeout_retries=0)
    gw, provider = make_gateway(
        [ProviderTransientError("zaman aşımı", timeout=True), tool_response((FINAL_TOOL, DONE))]
    )
    with pytest.raises(ProviderTransientError):
        _run(gw)
    assert len(provider.requests) == 1 and sleeps == []


def test_call_de_amac_ayarini_okur(make_gateway, rules_dir, sleeps) -> None:
    _edit_purpose(rules_dir, "triage", max_retries=0, fallbacks="none")
    gw, provider = make_gateway([ProviderTransientError("529", status=529)])
    with pytest.raises(ProviderTransientError):
        gw.call(
            "triage",
            "triage",
            [ModelMessage(role="user", content="x")],
            load_schema(rules_dir, "triage"),
            replay_key={"name": "x"},
        )
    assert len(provider.requests) == 1 and sleeps == []
    assert provider.requests[0].fallbacks == "none"


def test_fallbacks_istege_tasinir(make_gateway, rules_dir) -> None:
    _edit_purpose(rules_dir, PURPOSE, fallbacks="none")
    gw, provider = make_gateway([tool_response((FINAL_TOOL, DONE))])
    _run(gw)
    assert provider.requests[0].fallbacks == "none"


def _req(**kw: Any) -> ProviderRequest:
    return ProviderRequest(
        model="claude-sonnet-5-5",
        system="s",
        messages=[{"role": "user", "content": "x"}],
        **kw,
    )


def test_anthropic_fallbacks_none_gonderilmez() -> None:
    provider = AnthropicProvider(client=object())
    kw = provider.build_kwargs(_req(fallbacks="none"))
    assert "fallbacks" not in kw and "betas" not in kw
    varsayilan = provider.build_kwargs(_req())
    assert varsayilan["fallbacks"] == "default"  # eski davranış
    assert provider.build_kwargs(_req(fallbacks="default"))["fallbacks"] == "default"


# ------------------------------------------------------------------ maskeleme oturumu


class SahteDb(DemoDb):
    def __init__(self, eposta: str) -> None:
        super().__init__(None)
        self.eposta = eposta

    def query(self, sql: str) -> QueryResult:
        return QueryResult(sql, ["ad", "eposta"], [("Ali", self.eposta)], False)


def test_dis_maskeleme_oturumu_tek_ve_cevapta_acilir(make_gateway) -> None:
    oturum = PiiMasker(enabled=True).new_session()
    veri = DataTools(SahteDb("ali@ornek.com.tr"), PiiMasker(enabled=True), session=oturum)
    gw, provider = make_gateway(
        [
            tool_response(("db_query", {"sql": "SELECT 1"})),
            tool_response((FINAL_TOOL, {"cevap": "<<PII_EMAIL_1>> ve <<PII_EMAIL_2>>"})),
        ],
        masker=PiiMasker(enabled=True),
    )
    result = _run(
        gw,
        lambda name, args: veri.db_query(args),
        messages=[ModelMessage(role="user", content="ayse@ornek.com kimdir?")],
        masking_session=oturum,
    )
    ilk = _texts(provider.requests[0])
    assert "ayse@ornek.com" not in ilk and "<<PII_EMAIL_1>>" in ilk
    ikinci = _texts(provider.requests[1])
    assert "ali@ornek.com.tr" not in ikinci and "<<PII_EMAIL_2>>" in ikinci
    assert result.output == {"cevap": "ayse@ornek.com ve ali@ornek.com.tr"}


def test_datatools_oturumsuz_sorgu_basina_yeni_oturum() -> None:
    veri = DataTools(SahteDb("ali@ornek.com.tr"), PiiMasker(enabled=True))
    ilk = veri.db_query({"sql": "SELECT 1"})
    veri.db = SahteDb("veli@ornek.com.tr")
    ikinci = veri.db_query({"sql": "SELECT 1"})
    assert "<<PII_EMAIL_1>>" in ilk and "<<PII_EMAIL_1>>" in ikinci  # eski davranış


def test_datatools_oturumla_yer_tutucular_tekil() -> None:
    oturum = PiiMasker(enabled=True).new_session()
    oturum.mask_text("ayse@ornek.com")  # soru metni
    veri = DataTools(SahteDb("ali@ornek.com.tr"), PiiMasker(enabled=False), session=oturum)
    assert veri.masking is True  # açık/kapalı oturumdan okunur
    metin = veri.db_query({"sql": "SELECT 1"})
    assert "<<PII_EMAIL_2>>" in metin and "ali@ornek.com.tr" not in metin
    assert oturum.unmask("<<PII_EMAIL_2>>") == "ali@ornek.com.tr"


# ------------------------------------------------------------------ build_gateway


def _settings(rules_dir: Path, **env: Any) -> GatewaySettings:
    return GatewaySettings.model_validate({"TP_RULES_DIR": str(rules_dir), **env})


def test_mode_override_live_pipeline_replayde(rules_dir: Path) -> None:
    settings = _settings(rules_dir, TP_MODEL_MODE="replay", ANTHROPIC_API_KEY=_fake_key())
    assert build_gateway(InMemoryCallRecorder(), settings=settings).mode == "replay"
    gw = build_gateway(
        InMemoryCallRecorder(), settings=settings, mode_override="live", replay_fallback=False
    )
    assert gw.mode == "live" and gw.provider_name == "anthropic"
    assert gw.replay_fallback is False


def test_mode_override_auto_yedegini_acmaz(rules_dir: Path) -> None:
    settings = _settings(rules_dir, TP_MODEL_MODE="auto", ANTHROPIC_API_KEY=_fake_key())
    assert build_gateway(InMemoryCallRecorder(), settings=settings).replay_fallback is True
    gw = build_gateway(InMemoryCallRecorder(), settings=settings, mode_override="live")
    assert gw.replay_fallback is False
    gw = build_gateway(
        InMemoryCallRecorder(), settings=settings, mode_override="live", replay_fallback=True
    )
    assert gw.replay_fallback is True


def test_replay_fallback_false_canli_hatayi_yuzeye_cikarir(rules_dir: Path) -> None:
    settings = _settings(rules_dir, TP_MODEL_MODE="auto", ANTHROPIC_API_KEY=_fake_key())
    provider = FakeProvider([ProviderTransientError("400", status=None)] * 5)
    gw = build_gateway(
        InMemoryCallRecorder(),
        settings=settings,
        provider=provider,
        mode_override="live",
        replay_fallback=False,
    )
    gw._sleep = lambda _s: None
    with pytest.raises(ProviderTransientError):
        _run(gw)


def test_record_kipine_girmez_dosya_yazmaz(
    rules_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def yasak(self) -> None:
        raise AssertionError("record kipi denetimi çağrılmamalı")

    monkeypatch.setattr(ReplayStore, "ensure_writable", yasak)
    settings = _settings(rules_dir, TP_MODEL_MODE="record", ANTHROPIC_API_KEY=_fake_key())
    once = sorted(p for p in (rules_dir / "replay").rglob("*") if p.is_file())
    provider = FakeProvider([tool_response((FINAL_TOOL, DONE))])
    gw = build_gateway(
        InMemoryCallRecorder(),
        settings=settings,
        provider=provider,
        mode_override="live",
        replay_fallback=False,
    )
    assert gw.mode == "live"
    assert _run(gw).mode == "live"
    assert sorted(p for p in (rules_dir / "replay").rglob("*") if p.is_file()) == once


def test_budget_verilirse_kullanilir(rules_dir: Path) -> None:
    butce = Budget(workflow_cap_usd=0.01, daily_cap_usd=0.02)
    gw = build_gateway(InMemoryCallRecorder(), settings=_settings(rules_dir), budget=butce)
    assert gw.budget is butce
    varsayilan = build_gateway(InMemoryCallRecorder(), settings=_settings(rules_dir))
    assert varsayilan.budget is not butce


def test_gecersiz_mode_override(rules_dir: Path) -> None:
    with pytest.raises(GatewayConfigError):
        build_gateway(
            InMemoryCallRecorder(),
            settings=_settings(rules_dir),
            mode_override="auto",  # type: ignore[arg-type]
        )


# ------------------------------------------------------------------ araç izin listesi


def test_asistan_arac_izin_listesi() -> None:
    assistant = ALLOWED_AGENT_TOOLS["assistant"]
    assert assistant == ALLOWED_AGENT_TOOLS["assistant_deep"]
    assert len(assistant) == 13
    assert not assistant & FORBIDDEN_TOOLS
    assert ALLOWED_AGENT_TOOLS["consistency_check"] <= assistant
    assert {"product_search", "product_read", "jira_issue", "ci_log"} <= assistant
    assert {n for n in assistant if n.startswith("probe_")} == {
        "probe_get",
        "probe_list",
        "probe_jobs",
        "probe_audit",
        "probe_my_queue",
    }
    assert not any(n.startswith("browser_") for n in assistant)
