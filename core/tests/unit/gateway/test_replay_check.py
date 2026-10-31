"""REPLAY yığın kontrolü (gateway.replay_check): sahte MCP ile ref kayması senaryosu.

Canlı yığındaki karşılığı: `python -m tp_core.gateway.replay_check --runs 5` (core-worker içinde).
Burada sayfa, kayıttaki snapshot'ın ref'leri `shift` kadar kaymış hali olarak sunulur (canlı
yığında gözlenen +1 kayma) ve generate_locator yalnızca doğru elemanın ref'inde kayıttaki
locator'ı döndürür.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tests.unit.gateway.test_codegen_goldens import snapshot_from_summary
from tp_core.gateway import Gateway, ReplayStore
from tp_core.gateway.config import find_rules_dir, load_model_table
from tp_core.gateway.replay_check import (
    GEN,
    RunResult,
    Session,
    check_run,
    report,
    run_checks,
    verify_goldens,
)
from tp_core.gateway.testing import InMemoryCallRecorder
from tp_core.ports import AgentStep, ToolSpec

RULES = find_rules_dir()
GOLDENS = dict(verify_goldens(RULES))
TOOLS = [
    ToolSpec(name=n, description=n, input_schema={"type": "object"})
    for n in (
        "browser_navigate",
        "browser_snapshot",
        GEN,
        "browser_type",
        "browser_click",
        "browser_wait_for",
    )
]


def _shift(text: str, by: int) -> str:
    return re.sub(r"\[ref=e(\d+)\]", lambda m: f"[ref=e{int(m.group(1)) + by}]", text)


class ShiftedPage:
    """Kayıttaki yörüngeyi oynatan sahte MCP; snapshot ref'leri `shift` kadar kaymış."""

    def __init__(self, golden: dict[str, Any], shift: int) -> None:
        self.shift = shift
        steps = golden["steps"]
        self.snaps = iter([s["result_summary"] for s in steps if s["tool"] == "browser_snapshot"])
        # doğru (kaymış) ref → kayıttaki locator
        self.locators = {
            f"e{int(s['args']['target'][1:]) + shift}": s["result_summary"]
            for s in steps
            if s["tool"] == GEN
        }

    def __call__(self, name: str, args: dict[str, Any]) -> str:
        if name == "browser_snapshot":
            return _shift(snapshot_from_summary(next(self.snaps)), self.shift)
        if name == GEN:
            return self.locators.get(args["target"], "getByTestId('baska-eleman')")
        return f"{name} tamam"


def _gateway() -> Gateway:
    return Gateway(
        provider=None,
        recorder=InMemoryCallRecorder(),
        mode="replay",
        models=load_model_table(RULES),
        rules_dir=RULES,
        replay_store=ReplayStore(RULES / "replay", strict=True),
    )


def _session(page: ShiftedPage) -> Session:
    return Session(page, TOOLS, lambda step: True, lambda: None)


def test_every_verify_golden_is_checked() -> None:
    assert "f2-kod-hatasi/TPD-1-C3" in GOLDENS and "TPD-1-C5" in GOLDENS
    assert len(GOLDENS) == 13


@pytest.mark.parametrize("name", sorted(GOLDENS))
@pytest.mark.parametrize("shift", [0, 1])
def test_goldens_replay_cleanly_whatever_the_ref_layout(name: str, shift: int) -> None:
    golden = GOLDENS[name]
    result = check_run(_gateway(), RULES, name, golden, _session(ShiftedPage(golden, shift)), 1)
    assert result.mode == "replay"
    assert result.ok, result.problems


def test_recorded_refs_alone_would_verify_the_wrong_element(tmp_path: Path) -> None:
    """Hedefsiz (yalnızca kayıttaki ref'li) yörünge +1 kaymada yanlış elemanı doğrular; kontrol
    bunu sapma olarak yakalar (bulgu: e71 → product-status-P-002)."""
    import shutil

    rules = tmp_path / "rules"
    shutil.copytree(RULES, rules)
    path = rules / "replay" / "verify_and_map" / "golden" / "TPD-1-C5.json"
    golden = json.loads(path.read_text(encoding="utf-8"))
    for s in golden["steps"]:
        s.pop("hedef", None)
    path.write_text(json.dumps(golden, ensure_ascii=False), encoding="utf-8")
    gw = Gateway(
        provider=None,
        recorder=InMemoryCallRecorder(),
        mode="replay",
        models=load_model_table(rules),
        rules_dir=rules,
        replay_store=ReplayStore(rules / "replay", strict=True),
    )
    result = check_run(gw, rules, "TPD-1-C5", golden, _session(ShiftedPage(golden, 1)), 1)
    assert not result.ok
    assert all(GEN in p and "REPLAY sapması" in p for p in result.problems), result.problems


def test_failed_step_and_report() -> None:
    golden = GOLDENS["TPD-4-C1"]

    def failing(step: AgentStep) -> bool:
        return step.tool != "browser_click"

    session = Session(ShiftedPage(golden, 0), TOOLS, failing, lambda: None)
    result = check_run(_gateway(), RULES, "TPD-4-C1", golden, session, 1)
    assert [p.split(":")[0] for p in result.problems] == ["adım 8 browser_click"]
    text = report([result, RunResult("TPD-4-C2", 1)])
    assert "1/2 temiz" in text and "HATA" in text
    closed: list[int] = []

    def new_session() -> Session:
        return Session(ShiftedPage(golden, 1), TOOLS, lambda s: True, lambda: closed.append(1))

    results = run_checks(_gateway(), RULES, [("TPD-4-C1", golden)], new_session, runs=3)
    assert [r.ok for r in results] == [True, True, True] and len(closed) == 3
    assert report(results).endswith("TAMAM")


def test_run_checks_her_kosuyu_bayi_kilidiyle_sarar() -> None:
    """Kod üretimi ile aynı ajan bayisini paylaşır: oturum açma/kapama kilit içinde olmalı."""
    import contextlib

    golden = GOLDENS["TPD-4-C1"]
    olaylar: list[str] = []

    @contextlib.contextmanager
    def kilit():  # type: ignore[no-untyped-def]
        olaylar.append("kilit")
        yield
        olaylar.append("birak")

    def new_session() -> Session:
        olaylar.append("oturum")
        return Session(
            ShiftedPage(golden, 0), TOOLS, lambda s: True, lambda: olaylar.append("kapa")
        )

    run_checks(_gateway(), RULES, [("TPD-4-C1", golden)], new_session, runs=2, lock=kilit)
    assert olaylar == ["kilit", "oturum", "kapa", "birak"] * 2


def test_replay_url_sapmasi_yakalanir() -> None:
    """TPD-4-C2: hatalı parola girişte kalmalı; canlı oturum kataloğa geçtiyse sapmadır."""
    from tp_core.gateway.core import REPLAY_DRIFT, _replay_drift

    click = AgentStep(
        tool="browser_click",
        args={},
        result_summary="await page.locator('x').click(); · URL /giris",
        allowed=True,
    )
    canli = "### Page state\n- Page URL: http://demo-app-web:8080/katalog\n"
    notu = _replay_drift(click, canli)
    assert notu and notu.startswith(REPLAY_DRIFT) and "/giris" in notu and "/katalog" in notu
    assert _replay_drift(click, "- Page URL: http://demo-app-web:8080/giris?x=1") is None
    assert _replay_drift(click, "sayfa adresi yok") is None
    siparis = click.model_copy(update={"result_summary": "ok · URL /siparis/SP-000056"})
    assert _replay_drift(siparis, "Page URL: http://h/siparis/SP-000091") is None
    assert _replay_drift(siparis, "Page URL: http://h/sepet")
    snap = click.model_copy(update={"tool": "browser_snapshot", "result_summary": "URL /sepet | x"})
    assert _replay_drift(snap, "- Page URL: http://h/sepet\n- Page Title: x") is None
