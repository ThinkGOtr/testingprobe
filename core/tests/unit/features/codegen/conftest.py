"""CasesToCode akış testleri: gerçek Postgres + demo-app/e2e'den kurulan geçici LocalForge +
REPLAY golden'ları + sahte Playwright MCP oturumu + sahte toolchain-worker (httpx MockTransport).

Sahte toolchain `/check`'te gerçek toolchain-worker gibi kırılmasız koşuda
`TP_ARTIFACTS_PATH/checks/<sha>.json` (`local-ci`) yazar; LocalForge merge kapısı bunu okur.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine

CORE = Path(__file__).resolve().parents[4]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import tp_core.features.codegen.jobs  # noqa: E402, F401  (iş işleyicileri)
from tests.unit.features.cases.helpers import (  # noqa: E402, F401  (pytest fikstürleri)
    api,
    login,
    make_requirement,
    run_jobs,
)
from tests.unit.features.codegen.test_browser import FakeSession  # noqa: E402
from tp_core.audit import PgCallRecorder, content_hash  # noqa: E402
from tp_core.config import get_settings  # noqa: E402
from tp_core.features.codegen import platform as platformlar  # noqa: E402
from tp_core.features.codegen import service  # noqa: E402
from tp_core.features.codegen.toolchain import ToolchainClient, clear_symbol_cache  # noqa: E402
from tp_core.gateway import build_gateway  # noqa: E402
from tp_core.gateway.config import GatewaySettings  # noqa: E402
from tp_core.integrations.forge_local import LocalForge  # noqa: E402
from tp_core.models import Requirement, TestCase, case_id, session_scope  # noqa: E402
from tp_core.workflow.jobs import process_one  # noqa: E402
from tp_core.workflow.service import (  # noqa: E402
    SYSTEM,
    content_hash_of,
    record_approval,
    transition,
)

HERE = Path(__file__).resolve().parent
REPO = CORE.parent
RULES = REPO / "rules"
TOOLCHAIN = "http://toolchain-worker:8100"


def git(*args: str, cwd: Path | None = None) -> str:
    out = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
             "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
             "HOME": str(cwd or Path.cwd())},
    )  # fmt: skip
    return out.stdout.strip()


@pytest.fixture(scope="session")
def demo_bare(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """demo-app/e2e'nin (node_modules ve üretilmiş testler hariç) commit'lendiği bare depo."""
    kok = tmp_path_factory.mktemp("forge-src")
    work = kok / "work"
    shutil.copytree(
        REPO / "demo-app" / "e2e",
        work / "e2e",
        ignore=shutil.ignore_patterns("node_modules", "results", "*.spec.ts.tmp"),
    )
    for f in (work / "e2e" / "tests" / "generated").glob("*.spec.ts"):
        f.unlink()
    git("init", "-q", "-b", "main", str(work))
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "demo-app e2e", cwd=work)
    bare = kok / "demo-app.git"
    git("init", "-q", "--bare", "-b", "main", str(bare))
    git("push", "-q", str(bare), "main", cwd=work)
    return bare


@pytest.fixture
def forge_dirs(demo_bare: Path, tmp_path: Path) -> tuple[Path, Path]:
    bare = tmp_path / "forge" / "demo-app.git"
    shutil.copytree(demo_bare, bare)
    artifacts = tmp_path / "artifacts"
    (artifacts / "checks").mkdir(parents=True)
    return bare, artifacts


def gecti(n: int = 3) -> dict[str, Any]:
    return {
        "conclusion": "success",
        "summary": "Yerel CI geçti",
        "deps": {"ok": True},
        "tsc": {"ok": True},
        "eslint": {"ok": True},
        "ast_guard": {"ok": True},
        "run": {
            "run_id": f"run-{uuid.uuid4().hex[:6]}",
            "status": "passed",
            "saglik": {"ok": True},
            "tests": [{"title": "t", "status": "expected", "error": None}] * n,
        },
        "duration_ms": 1234,
    }


def kirmizi(mesaj: str, tur: str | None = None, n: int = 3) -> dict[str, Any]:
    r = gecti(n)
    r.update(conclusion="failure", summary="Yerel CI başarısız: run")
    r["run"]["status"] = "failed"
    r["run"]["tests"] = [
        {
            "title": "TPD-1 · C3 › 6 adet",
            "status": "unexpected",
            "error": mesaj,
            "failure": {"type": tur} if tur else None,
        }
    ] * n
    return r


ASSERT_MSG = (
    "Error: expect(locator).toHaveText(expected) failed\n\n"
    'Locator: getByTestId(\'cart-line-free-P-001\')\nExpected: "0"\nReceived: "1"'
)
LOCATOR_MSG = (
    "Error: locator.click: Timeout 5000ms exceeded.\nCall log:\n"
    "  - waiting for getByTestId('product-card-P-001').getByTestId('add-to-cart')"
)


class FakeToolchain:
    """toolchain-worker sahte uçları; `/check` yanıtları sıradan (kırılmalı/kırılmasız ayrı)."""

    def __init__(self, artifacts: Path) -> None:
        self.artifacts = artifacts
        self.symbols = json.loads((HERE / "symbols.json").read_text(encoding="utf-8"))
        self.kontroller: list[dict[str, Any] | Callable[[dict[str, Any]], Any]] = []
        self.kirik: list[dict[str, Any]] = []
        self.istekler: list[tuple[str, dict[str, Any]]] = []
        self.check_status: int = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.istekler.append((request.url.path, body))
        if request.url.path == "/symbols":
            return httpx.Response(200, json={"sha": body["sha"], **self.symbols})
        if request.url.path == "/check":
            if self.check_status != 200:
                return httpx.Response(self.check_status, json={"detail": "Commit bulunamadı"})
            kirma = body.get("env", {}).get("BREAK_CAMPAIGN") == "1"
            sira = self.kirik if kirma else self.kontroller
            rapor = sira.pop(0) if sira else gecti()
            if callable(rapor):
                rapor = rapor(body)
            rapor = {**rapor, "sha": body["sha"]}
            if not kirma:
                (self.artifacts / "checks" / f"{body['sha']}.json").write_text(
                    json.dumps(
                        {
                            "checks": [
                                {
                                    # toolchain `check_name(lang, platform)` ile aynı mantık
                                    # (sözleşme: toolchain/tests/data/core_sozlesme.json).
                                    "name": platformlar.check_adi(
                                        body.get("platform"), body.get("lang") or "ts"
                                    ),
                                    "status": "completed",
                                    "conclusion": rapor["conclusion"],
                                    "url": None,
                                }
                            ]
                        }
                    )
                )
            return httpx.Response(200, json=rapor)
        return httpx.Response(404, json={"detail": "yok"})

    def checks(self) -> list[dict[str, Any]]:
        return [b for p, b in self.istekler if p == "/check"]


@pytest.fixture
def ci_cagrilari(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """ci-runs şeridinin `enqueue_ci` sözleşmesi (sahte işlev). Paketin geri kalanı gerçektir:
    yerel kontrol / kırarak doğrulama koşuları gerçek `ingest_check_report` ile `run`'a yazılır."""
    import tp_core.features.ci as mod

    cagrilar: list[dict[str, Any]] = []

    def enqueue_ci(
        session: Any,
        sha: str,
        trigger: str,
        pr_number: int | None = None,
        *,
        isteyen: str = "system",
        script_id: Any = None,
        **_: Any,
    ) -> None:
        assert session is not None and script_id is not None
        cagrilar.append({"sha": sha, "trigger": trigger, "pr_number": pr_number})

    monkeypatch.setattr(mod, "enqueue_ci", enqueue_ci)
    return cagrilar


@pytest.fixture
def codegen(
    engine: Engine,
    forge_dirs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    ci_cagrilari: list[dict[str, Any]],
) -> Iterator[Any]:
    bare, artifacts = forge_dirs
    monkeypatch.setenv("TP_ARTIFACTS_PATH", str(artifacts))
    monkeypatch.setenv("TP_FORGE", "local")
    monkeypatch.setenv("TP_MODEL_MODE", "replay")
    monkeypatch.setenv("TP_AGENT_DEALER", "bayi3")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TP_REPLAY_STRICT", raising=False)
    monkeypatch.delenv("TP_RULES_DIR", raising=False)
    monkeypatch.delenv("TP_REQUIRED_CHECKS", raising=False)
    get_settings.cache_clear()
    clear_symbol_cache()
    gw = build_gateway(PgCallRecorder(engine), settings=GatewaySettings(), engine=engine)
    tc = FakeToolchain(artifacts)
    oturumlar: list[FakeSession] = []

    def browser() -> FakeSession:
        s = FakeSession()
        oturumlar.append(s)
        return s

    forge = LocalForge(bare, artifacts)
    service.set_factories(
        gateway=lambda _e: gw,
        browser=browser,
        toolchain=lambda: ToolchainClient(TOOLCHAIN, transport=httpx.MockTransport(tc.handler)),
        forge=lambda: forge,
    )

    class Ortam:
        pass

    o = Ortam()
    o.gw, o.toolchain, o.forge, o.bare, o.artifacts = gw, tc, forge, bare, artifacts
    o.oturumlar, o.ci = oturumlar, ci_cagrilari
    yield o
    service.reset_factories()
    clear_symbol_cache()
    get_settings.cache_clear()


def golden_cases() -> list[dict[str, Any]]:
    d = json.loads((RULES / "replay/case_generation/golden/TPD-1.json").read_text("utf-8"))
    return d["output"]["cases"]


def tpd1_acs() -> list[str]:
    d = json.loads((RULES / "replay/case_generation/golden/TPD-1.json").read_text("utf-8"))
    return list(d["input_match"]["acceptance_criteria"])


@pytest.fixture
def hazir(engine: Engine, make_requirement: Any, make_user: Any) -> dict[str, Any]:  # noqa: F811
    """PO onaylı TPD-1 (cases_ready) + golden case'ler (C1–C10) analist onaylı."""
    rid = make_requirement(
        "TPD-1",
        "Kampanyalı sepet ve sipariş onayı",
        "Bayi, katalogdan ürünleri sepete ekleyip kampanya indirimiyle siparişini "
        "onaylayabilmelidir.",
        tpd1_acs(),
    )
    analist = make_user("analyst")
    with session_scope() as s:
        req = s.get(Requirement, rid)
        transition(s, req, "generating", SYSTEM, "po_approved")
        transition(s, req, "cases_ready", SYSTEM, "generating")
    ids: dict[int, uuid.UUID] = {}
    for n, icerik in enumerate(golden_cases(), start=1):
        with session_scope() as s:
            req = s.get(Requirement, rid)
            tc = TestCase(
                id=case_id(req, n, 1),
                requirement_id=rid,
                sira_no=n,
                uretim_no=1,
                icerik=icerik,
                icerik_hash=content_hash(icerik),
                uretim_modu="replay",
            )
            s.add(tc)
            s.flush()
            record_approval(s, tc, analist, "approve", beklenen_hash=content_hash_of(tc))
            transition(s, tc, "approved", analist, "draft")
            ids[n] = tc.id
    return {"requirement_id": rid, "cases": ids, "analist": analist}


@contextmanager
def arka_plan_worker(engine: Engine) -> Iterator[None]:
    dur = threading.Event()

    def dongu() -> None:
        while not dur.is_set():
            if process_one(engine, "test-worker-bg") is None:
                time.sleep(0.05)

    t = threading.Thread(target=dongu, daemon=True)
    t.start()
    try:
        yield
    finally:
        dur.set()
        t.join(timeout=10)
