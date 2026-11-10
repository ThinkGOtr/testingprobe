"""`verify_and_map_app` golden'ları (009 Ş6): üretici çıktısıyla aynı, sembol tablosuna dayalı,
REPLAY'de sahte app-mcp'de sıkı kipte yeniden yürütülür."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.unit.features.codegen.app_fakes import FakeAppSession
from tests.unit.gateway.build_app_goldens import build_all, dump, golden_path
from tests.unit.gateway.demo_sources import RULES, load_golden
from tp_core.features.codegen import checks
from tp_core.features.codegen.browser import AgentApp, AgentConfig
from tp_core.features.codegen.service import app_mapping_messages, case_ref, replay_key_for
from tp_core.gateway import ALLOWED_AGENT_TOOLS, Gateway, ReplayStore, load_schema
from tp_core.gateway.config import load_model_table
from tp_core.gateway.inputs import VERIFY_AGENT_DEALER
from tp_core.gateway.testing import InMemoryCallRecorder
from tp_core.ports import AgentStep

SYMBOLS = json.loads(
    (Path(__file__).resolve().parents[1] / "features/codegen/symbols-java.json").read_text("utf-8")
)
URETILEN = build_all()


@pytest.mark.parametrize("ad", sorted(URETILEN))
def test_golden_ureticiyle_ayni(ad: str) -> None:
    """Değiştiyse: `uv run python -m tests.unit.gateway.build_app_goldens`."""
    assert golden_path(ad).read_text(encoding="utf-8") == dump(URETILEN[ad])


@pytest.mark.parametrize("ad", sorted(URETILEN))
def test_golden_eslemesi_java_kontrollerinden_gecer(ad: str) -> None:
    g = load_golden("verify_and_map_app", ad)
    case = load_golden("case_generation", g["case"]["case_golden"])["output"]["cases"][
        g["case"]["sira_no"] - 1
    ]
    sonuc = checks.check_mapping(
        g["output"], case, checks.SymbolTable(SYMBOLS), fixtures=set(SYMBOLS["fixtures"])
    )
    assert sonuc.ok, sonuc.ozet()
    assert {s["tool"] for s in g["steps"]} <= ALLOWED_AGENT_TOOLS["verify_and_map_app"]
    assert g["steps"][0]["tool"] == "app_launch"
    assert g["output"]["platform"] == g["case"]["platform"]


def test_replay_sahte_app_mcp_de_siki_kipte_yurur(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_REPLAY_STRICT", "1")
    g = load_golden("verify_and_map_app", "TPD-1-C2-android")
    case = load_golden("case_generation", "TPD-1")["output"]["cases"][1]
    gw = Gateway(
        provider=None,
        recorder=InMemoryCallRecorder(),
        mode="replay",
        models=load_model_table(RULES),
        rules_dir=RULES,
        replay_store=ReplayStore(RULES / "replay", strict=True),
        replay_executes_tools=True,
    )
    oturum = FakeAppSession("android")
    ajan = AgentApp(oturum, platform="android", config=AgentConfig(), case_dealers=["bayi1"])
    adimlar: list[AgentStep] = []
    sonuc = gw.run_agent(
        "verify_and_map_app",
        "verify-and-map-app",
        app_mapping_messages(
            case,
            case_ref("TPD-1", 2),
            checks.SymbolTable(SYMBOLS),
            platform="android",
            agent_dealer=VERIFY_AGENT_DEALER,
        ),
        ajan.tool_specs(),
        ajan,
        load_schema(RULES, "verify_and_map_app"),
        replay_key=replay_key_for("TPD-1", 2, "android"),
        on_step=adimlar.append,
    )
    assert sonuc.mode == "replay" and sonuc.output == g["output"]
    assert [a.tool for a in adimlar] == [s["tool"] for s in g["steps"]]
    assert all(a.allowed for a in adimlar)
    assert not any("Araç hatası" in (a.result_summary or "") for a in adimlar)
    assert not any("REPLAY sapması" in (a.result_summary or "") for a in adimlar)
    assert oturum.ekran == "sepet" and oturum.sepet == {"P-001": 7}
    # Golden adı platforma bağlı: iOS isteği android golden'ını almaz.
    assert replay_key_for("TPD-1", 2, "ios")["name"] == "TPD-1-C2-ios"
    assert replay_key_for("TPD-1", 2)["name"] == "TPD-1-C2"
