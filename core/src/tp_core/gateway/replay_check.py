"""REPLAY yığın kontrolü: her verify_and_map golden'ı canlı Playwright MCP'de N kez tekrarlanır.

Snapshot ref'leri oturuma özgüdür ve aynı yörüngede bile koşudan koşuya kayar (snapshot_refs).
Bu kontrol, golden'ların REPLAY'de ref'ten bağımsız olduğunu üretimdeki kod yoluyla kanıtlar:
`Gateway.run_agent` (replay kipi) + kod üretiminin `AgentBrowser` / `McpBrowserSession`'ı.
Her koşuda:

- kayıtlı her izinli adım bu oturumda **başarılı** çalışmalı (kod üretiminin REPLAY kuralı:
  bir adım bile başarısızsa case insana düşer — `_uygulama_goruldu_mu`);
- her `browser_generate_locator` sonucu kayıttaki locator'ın aynısı olmalı (yanlış eleman
  doğrulanmamalı; `REPLAY sapması` notu yok).

    # core-worker içinde (compose yığını ayakta; PLAYWRIGHT_MCP_URL, TP_DEMO_WEB_URL)
    python -m tp_core.gateway.replay_check --runs 5            # çıkış kodu 0 / 1
    python -m tp_core.gateway.replay_check --only f2-kod-hatasi/TPD-1-C3 --runs 10

Model çağrısı yoktur (REPLAY); tarayıcı adımları doğrulama bayisiyle (bayi3) koşar ve her golden'dan
önce ajan bayisinin sepeti boşaltılır (kod üretimiyle aynı).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tp_core.gateway.bundle import load_schema
from tp_core.gateway.config import find_rules_dir
from tp_core.gateway.core import (
    _GENERATED_LOCATOR,
    REPLAY_DRIFT,
    REPLAY_UNRESOLVED,
    Gateway,
)
from tp_core.gateway.demo_check import case_message
from tp_core.gateway.errors import GatewayError
from tp_core.gateway.replay import ReplayStore, golden_name
from tp_core.ports import AgentStep, ModelMessage, ToolExecutor, ToolSpec

PURPOSE = "verify_and_map"
BUNDLE = "verify-and-map"
GEN = "browser_generate_locator"


@dataclass
class RunResult:
    golden: str
    run: int
    mode: str = ""
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass(frozen=True)
class Session:
    """Bir koşunun tarayıcısı: araç yürütücüsü + adım sonucu (başarılı mı) + kapanış."""

    execute: ToolExecutor
    tools: list[ToolSpec]
    step_ok: Callable[[AgentStep], bool]
    close: Callable[[], None]


def verify_goldens(rules_dir: Path) -> list[tuple[str, dict[str, Any]]]:
    root = rules_dir / "replay" / PURPOSE / "golden"
    out = []
    for path in sorted(root.rglob("*.json")):
        golden = json.loads(path.read_text(encoding="utf-8"))
        if golden.get("kind") == "agent" and isinstance(golden.get("case"), dict):
            out.append((path.relative_to(root).with_suffix("").as_posix(), golden))
    return out


def _case_of(rules_dir: Path, golden: dict[str, Any]) -> dict[str, Any]:
    case = golden["case"]
    source = case.get("case_golden") or case["jira_key"]
    path = rules_dir / "replay" / "case_generation" / "golden" / f"{source}.json"
    cases = json.loads(path.read_text(encoding="utf-8"))["output"]["cases"]
    return cases[int(case["sira_no"]) - 1]


def check_run(
    gateway: Gateway, rules_dir: Path, name: str, golden: dict[str, Any], session: Session, run: int
) -> RunResult:
    result = RunResult(golden=name, run=run)
    story = golden["case"]["jira_key"]
    sira = int(golden["case"]["sira_no"])
    messages = [
        ModelMessage.model_validate(m)
        for m in case_message(story, sira, _case_of(rules_dir, golden))
    ]
    seen: list[tuple[AgentStep, bool]] = []

    def on_step(step: AgentStep) -> None:
        seen.append((step, session.step_ok(step) if step.allowed else True))

    try:
        out = gateway.run_agent(
            PURPOSE,
            BUNDLE,
            messages,
            session.tools,
            session.execute,
            load_schema(rules_dir, PURPOSE),
            replay_key={"name": golden_name(story, case_no=sira), "jira_key": story},
            on_step=on_step,
        )
    except GatewayError as exc:  # sıkı kipte REPLAY-MISS vb.
        result.problems.append(f"{type(exc).__name__}: {exc}")
        return result
    result.mode = out.mode
    if out.mode != "replay":
        result.problems.append(f"mod {out.mode} (beklenen replay; golden girdi beyanı eşleşmedi)")
    recorded = golden.get("steps") or []
    if len(seen) != len(recorded):
        result.problems.append(f"{len(seen)} adım aktı, kayıtta {len(recorded)}")
    for i, ((step, ok), rec) in enumerate(zip(seen, recorded, strict=False), start=1):
        summary = step.result_summary or ""
        if not ok or summary.startswith(REPLAY_UNRESOLVED):
            result.problems.append(f"adım {i} {step.tool}: başarısız — {summary[:160]}")
        elif summary.startswith(REPLAY_DRIFT):
            result.problems.append(f"adım {i} {step.tool}: {summary.splitlines()[0][:200]}")
        elif step.tool == GEN:
            want = _GENERATED_LOCATOR.findall(rec.get("result_summary") or "")
            if summary.startswith(REPLAY_DRIFT) or (want and want[-1] not in summary):
                result.problems.append(f"adım {i} {GEN}: {summary.splitlines()[0][:200]}")
    return result


def run_checks(
    gateway: Gateway,
    rules_dir: Path,
    goldens: Iterable[tuple[str, dict[str, Any]]],
    new_session: Callable[[], Session],
    runs: int,
    lock: Callable[[], AbstractContextManager[Any]] | None = None,
) -> list[RunResult]:
    """`lock`: her koşuyu (sepet sıfırlama + MCP oturumu + ajan) saran bayi kilidi; kod üretimiyle
    aynı ajan bayisini (bayi3) paylaştığımız için canlı yığında `ajan_bayisi_kilidi` verilir."""
    results = []
    for name, golden in goldens:
        for run in range(1, runs + 1):
            with lock() if lock is not None else nullcontext():
                session = new_session()
                try:
                    results.append(check_run(gateway, rules_dir, name, golden, session, run))
                finally:
                    session.close()
    return results


def report(results: list[RunResult]) -> str:
    lines = []
    by_golden: dict[str, list[RunResult]] = {}
    for r in results:
        by_golden.setdefault(r.golden, []).append(r)
    for name, rs in by_golden.items():
        bad = [r for r in rs if not r.ok]
        lines.append(f"  {name:<28} {len(rs) - len(bad)}/{len(rs)} temiz")
        for r in bad:
            lines.extend(f"      koşu {r.run}: {p}" for p in r.problems)
    total_bad = sum(not r.ok for r in results)
    head = (
        f"REPLAY yığın kontrolü: {len(by_golden)} golden × koşu, "
        f"{len(results) - total_bad}/{len(results)} temiz"
    )
    return "\n".join([head, *lines, "TAMAM" if not total_bad else "HATA: sapma/başarısız adım var"])


def _production_session() -> Session:  # pragma: no cover - canlı yığın
    from tp_core.config import get_settings
    from tp_core.features.codegen.browser import (
        AgentBrowser,
        AgentConfig,
        McpBrowserSession,
        reset_agent_cart,
    )

    cfg = AgentConfig.from_env()
    import time

    for deneme in range(3):  # başka bir oturum aynı bayiyle giriş yapmış olabilir
        if reset_agent_cart(cfg):
            break
        time.sleep(1 + deneme)
    else:
        raise SystemExit("ajan bayisinin sepeti boşaltılamadı")
    mcp = McpBrowserSession(get_settings().playwright_mcp_url)
    agent = AgentBrowser(mcp, config=cfg, case_dealers=["bayi1", "bayi2"])

    def step_ok(step: AgentStep) -> bool:
        sonuc = agent.pop_sonuc()
        return sonuc is not None and sonuc.ok

    return Session(agent, agent.tool_specs(), step_ok, mcp.close)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - canlı yığın
    from tp_core.gateway.config import load_model_table
    from tp_core.gateway.testing import InMemoryCallRecorder

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--only", action="append", default=[])
    args = ap.parse_args(argv)
    rules = find_rules_dir()
    gateway = Gateway(
        provider=None,
        recorder=InMemoryCallRecorder(),
        mode="replay",
        models=load_model_table(rules),
        rules_dir=rules,
        replay_store=ReplayStore(rules / "replay", strict=True),
    )
    from tp_core.features.codegen.browser import ajan_bayisi_kilidi

    goldens = [g for g in verify_goldens(rules) if not args.only or g[0] in args.only]
    results = run_checks(
        gateway, rules, goldens, _production_session, args.runs, lock=ajan_bayisi_kilidi
    )
    print(report(results))
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
