"""CI testleri: sahte toolchain-worker (httpx MockTransport), artefakt kökü, sahte forge."""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from tp_core.features.ci import jobs as _ci_jobs  # noqa: F401  (iş kaydı)
from tp_core.features.ci import services
from tp_core.features.ci.clients import ToolchainClient
from tp_core.ports import PullRequest
from tp_core.workflow.service import Principal

FIXTURES = Path(__file__).parent / "fixtures"
UZAK_KOK = "/artifacts"  # toolchain/test-runner'daki bağlama noktası (çekirdekte tmp_path)
SHA = "a" * 40


@dataclass
class FakeForge:
    head: str = SHA
    prs: dict[int, PullRequest] = field(default_factory=dict)

    def head_sha(self, ref: str = "main") -> str:
        return self.head

    def get_pr(self, number: int) -> PullRequest:
        return self.prs[number]


def kosu_yaz(
    kok: Path,
    run_dir: str,
    *,
    sha: str,
    junit: bytes | None = None,
    results: bytes | None = None,
    durum: str = "failed",
    conclusion: str = "failure",
    statik: dict[str, Any] | None = None,
    saglik_ok: bool = True,
    checks: bool = True,
    allure_rapor: bool = True,
) -> dict[str, Any]:
    """toolchain `/check` + test-runner'ın artefakt düzenini kurar ve `/check` yanıtını döndürür."""
    uzak = f"{UZAK_KOK}/runs/{run_dir}"
    yerel = kok / "runs" / run_dir
    sonuc_dizini = yerel / "src" / "e2e" / "results"
    (sonuc_dizini / "html").mkdir(parents=True, exist_ok=True)
    (sonuc_dizini / "allure-results").mkdir(parents=True, exist_ok=True)
    (sonuc_dizini / "artifacts" / "kampanya-6").mkdir(parents=True, exist_ok=True)
    (sonuc_dizini / "artifacts" / "a11y-sepet").mkdir(parents=True, exist_ok=True)
    (yerel / "src" / "e2e" / "tests").mkdir(parents=True, exist_ok=True)
    (yerel / "src" / "e2e" / "tests" / "gizli.spec.ts").write_text("// kaynak kod")
    if junit is None:
        junit = (FIXTURES / "junit.xml").read_bytes()
    if results is None:
        results = (FIXTURES / "results.json").read_bytes()
    if junit:
        (sonuc_dizini / "junit.xml").write_bytes(junit)
    if results:
        (sonuc_dizini / "results.json").write_bytes(results.replace(b"{KOSU}", uzak.encode()))
    (sonuc_dizini / "html" / "index.html").write_text("<html><script>1</script></html>")
    (sonuc_dizini / "allure-results" / "x-result.json").write_text("{}")
    if allure_rapor:
        (sonuc_dizini / "allure-report").mkdir(parents=True, exist_ok=True)
        (sonuc_dizini / "allure-report" / "index.html").write_text("<html>allure</html>")
    (sonuc_dizini / "artifacts" / "kampanya-6" / "test-failed-1.png").write_bytes(b"\x89PNG")
    (sonuc_dizini / "artifacts" / "kampanya-6" / "trace.zip").write_bytes(b"PK")
    shutil.copy(FIXTURES / "axe-sepet.json", sonuc_dizini / "artifacts" / "a11y-sepet")
    (yerel / "runner.log").write_text("$ playwright test\n")
    saglik = {
        "ok": saglik_ok,
        "zaman": "2026-10-31T10:00:00+00:00",
        "web": {},
        "api": {},
        "hata": None if saglik_ok else "Demo uygulaması sağlık kontrolü başarısız — web",
    }
    run = {
        "run_id": run_dir,
        "sha": sha,
        "status": durum,
        "error": None if saglik_ok else saglik["hata"],
        "duration_ms": 12000,
        "junit": f"{uzak}/src/e2e/results/junit.xml",
        "json": f"{uzak}/src/e2e/results/results.json",
        "junit_path": f"{uzak}/src/e2e/results/junit.xml",
        "json_path": f"{uzak}/src/e2e/results/results.json",
        "allure_dir": f"{uzak}/src/e2e/results/allure-results",
        "html_dir": f"{uzak}/src/e2e/results/html",
        "log": f"{uzak}/runner.log",
        "artifacts_dir": uzak,
        "artifacts_rel": f"runs/{run_dir}",
        "reports": {
            "allure_html": {
                "path": f"{uzak}/src/e2e/results/allure-report",
                "rel": f"runs/{run_dir}/src/e2e/results/allure-report",
                "exists": allure_rapor,
            }
        },
        "saglik": saglik,
        "ok": durum == "passed",
    }
    adimlar = statik or {
        "deps": {"ok": True},
        "tsc": {"ok": True},
        "eslint": {"ok": True},
        "ast_guard": {"ok": True, "mode": "pr"},
    }
    if checks:
        (kok / "checks").mkdir(exist_ok=True)
        (kok / "checks" / f"{sha}.json").write_text(
            json.dumps(
                {"checks": [{"name": "local-ci", "status": "completed", "conclusion": conclusion}]}
            )
        )
    return {
        "sha": sha,
        "conclusion": conclusion,
        "ok": conclusion == "success",
        "failed_steps": [] if conclusion == "success" else ["run"],
        "summary": "Yerel CI başarısız: run" if conclusion != "success" else "Yerel CI geçti",
        **adimlar,
        "run": run,
        "duration_ms": 15000,
        "checks_path": f"{UZAK_KOK}/checks/{sha}.json",
    }


@dataclass
class FakeToolchain:
    kok: Path
    yanit: Callable[[dict[str, Any]], httpx.Response] | None = None
    istekler: list[dict[str, Any]] = field(default_factory=list)
    secenek: dict[str, Any] = field(default_factory=dict)

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/check"
        body = json.loads(request.content)
        self.istekler.append(body)
        if self.yanit is not None:
            return self.yanit(body)
        return httpx.Response(
            200, json=kosu_yaz(self.kok, body["run_id"], sha=body["sha"], **self.secenek)
        )

    def client(self) -> ToolchainClient:
        return ToolchainClient(
            "http://toolchain-worker:8100", transport=httpx.MockTransport(self.handler)
        )


@pytest.fixture
def artefakt_kok(tmp_path: Path) -> Path:
    kok = tmp_path / "artifacts"
    kok.mkdir()
    return kok


@pytest.fixture
def fake_forge() -> FakeForge:
    return FakeForge()


@pytest.fixture
def toolchain(artefakt_kok: Path) -> FakeToolchain:
    return FakeToolchain(artefakt_kok)


@pytest.fixture
def ci_env(
    artefakt_kok: Path,
    fake_forge: FakeForge,
    toolchain: FakeToolchain,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    monkeypatch.delenv("TP_MANUAL_BASELINE_S", raising=False)
    with services.override(
        mode=lambda: "local",
        forge=lambda: fake_forge,
        toolchain=toolchain.client,
        artifacts_root=lambda: artefakt_kok,
    ):
        yield


@pytest.fixture
def api(db: Any) -> Iterator[TestClient]:
    from tp_core.api.main import create_app

    with TestClient(create_app(), base_url="http://127.0.0.1:8000") as c:
        yield c


def login(client: TestClient, user: Principal, parola: str = "Parola-123!") -> None:
    r = client.post("/auth/login", json={"kullanici_adi": user.kullanici_adi, "parola": parola})
    assert r.status_code == 200, r.text


def run_jobs(engine: Any, limit: int = 20) -> list[Any]:
    from tp_core.workflow.jobs import process_one

    out = []
    for _ in range(limit):
        r = process_one(engine, "test-worker")
        if r is None:
            break
        out.append(r)
    return out


def yeni_uuid() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def make_requirement_case(engine: Any):
    """Gereksinim + case'i (ve istenirse script'i) doğrudan istenen durumda kurar (test verisi).

    Durum makinesi kuralı üretim kodu içindir; burada Kontrol Kulesi'nin okuduğu satırlar
    `allow_state_write()` ile hazırlanır (Kontrol Kulesi durum yazmaz).
    """
    from sqlalchemy.orm import Session

    from tp_core.models import Requirement, TestCase
    from tp_core.models.guard import allow_state_write

    reqs: dict[str, uuid.UUID] = {}
    sira: dict[uuid.UUID, int] = {}

    def _make(
        jira_key: str = "TPD-1",
        durum: str = "approved",
        title: str = "7 adet Portakal Gazozu → 1 adet bedava",
        ai: bool = True,
    ) -> uuid.UUID:
        with Session(engine) as s, s.begin(), allow_state_write():
            rid = reqs.get(jira_key)
            if rid is None:
                req = Requirement(
                    kaynak="jira",
                    jira_key=jira_key,
                    baslik=f"{jira_key} başlık",
                    kaynak_hash="h",
                    durum="cases_ready",
                )
                s.add(req)
                s.flush()
                rid = reqs[jira_key] = req.id
            sira[rid] = sira.get(rid, 0) + 1
            tc = TestCase(
                id=uuid.uuid4(),
                requirement_id=rid,
                sira_no=sira[rid],
                icerik={"title": title, "expected_result": title},
                icerik_hash=f"h{sira[rid]}",
                durum=durum,
                ai_generated=ai,
            )
            s.add(tc)
            s.flush()  # koruma flush'ta denetler: izin bağlamı içinde yazılmalı
            tc_id = tc.id
        return tc_id

    _make.reqs = reqs  # type: ignore[attr-defined]
    return _make
