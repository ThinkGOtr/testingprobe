"""Gereksinim özelliği testleri: gerçek Postgres (platform fikstürü), süreç içi jira-sim, demo-app/
dizininden kurulan geçici LocalForge deposu ve demo-app tablolarıyla kurulan salt okuma (demoapp_ro)
veritabanı. Model geçidi REPLAY modunda gerçek `rules/replay` golden kayıtlarını kullanır; golden
olmayan girdiler için FakeProvider'lı geçit kurulur.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

CORE_DIR = Path(__file__).resolve().parents[4]
REPO = CORE_DIR.parent
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))
SIM_SRC = REPO / "sims" / "jira-sim" / "src"
if str(SIM_SRC) not in sys.path:
    sys.path.insert(0, str(SIM_SRC))
DEMO_API_SRC = REPO / "demo-app" / "api" / "src"
if str(DEMO_API_SRC) not in sys.path:
    sys.path.insert(0, str(DEMO_API_SRC))

from jira_sim.app import create_app as create_sim  # noqa: E402

from tests.unit import conftest as _platform  # noqa: E402
from tp_core.audit import PgCallRecorder  # noqa: E402
from tp_core.features.requirements import jobs as _jobs  # noqa: E402, F401 — işleyici kaydı
from tp_core.features.requirements import services  # noqa: E402
from tp_core.features.requirements.datatools import DemoDb  # noqa: E402
from tp_core.features.requirements.settings import get_requirements_settings  # noqa: E402
from tp_core.gateway import Gateway, build_gateway, find_rules_dir, load_model_table  # noqa: E402
from tp_core.gateway.config import GatewaySettings  # noqa: E402
from tp_core.gateway.store import PgCallLookup  # noqa: E402
from tp_core.gateway.testing import FakeProvider  # noqa: E402
from tp_core.integrations.forge_local import LocalForge  # noqa: E402
from tp_core.integrations.jira import RestJira  # noqa: E402
from tp_core.workflow.jobs import process_one  # noqa: E402

# Platform fikstürleri (gerçek Postgres; pg/db/engine/make_user/session) tests/unit/conftest.py'de.
PAROLA = _platform.PAROLA
Db = _platform.Db
PgServer = _platform.PgServer

SIM_BASE = "http://jira-sim:8090"
PO_PASSWORD = "po-test-parola"
PO_AUTH = ("po@sim.local", PO_PASSWORD)
RULES = find_rules_dir()

GIT_ENV = {
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    "HOME": "/tmp",
    "LC_ALL": "C",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_AUTHOR_NAME": "seed",
    "GIT_AUTHOR_EMAIL": "seed@example.test",
    "GIT_COMMITTER_NAME": "seed",
    "GIT_COMMITTER_EMAIL": "seed@example.test",
}


def git(*args: str, cwd: Path | None = None) -> str:
    out = subprocess.run(
        ["git", *args], cwd=cwd, env=GIT_ENV, capture_output=True, check=True, text=True
    )
    return out.stdout.strip()


# ------------------------------------------------------------------ jira-sim


class SimTransport(httpx.BaseTransport):
    """Gerçek `httpx.Client` isteklerini süreç içindeki simülatöre iletir (ağ yok)."""

    def __init__(self, sim: TestClient) -> None:
        self.sim = sim

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        r = self.sim.request(
            request.method, str(request.url), headers=dict(request.headers), content=request.read()
        )
        return httpx.Response(r.status_code, headers=dict(r.headers), content=r.content)


@pytest.fixture
def sim() -> Iterator[TestClient]:
    with TestClient(
        create_sim(data_path="", base_url=SIM_BASE, po_password=PO_PASSWORD), base_url=SIM_BASE
    ) as client:
        yield client


@pytest.fixture
def jira(sim: TestClient) -> RestJira:
    return RestJira(
        SIM_BASE,
        ("reader@sim.local", "t"),
        ("writer@sim.local", "t"),
        http=httpx.Client(transport=SimTransport(sim)),
        sleep=lambda _s: None,
    )


class PoActions:
    """PO'nun jira-sim'de yaptıkları (REST, PO kimliğiyle)."""

    def __init__(self, sim: TestClient) -> None:
        self.sim = sim

    def _put(self, key: str, body: dict[str, Any]) -> None:
        r = self.sim.put(f"/rest/api/3/issue/{key}", json=body, auth=PO_AUTH)
        assert r.status_code in (200, 204), r.text

    def add_label(self, key: str, label: str = "tp-po-approved") -> None:
        self._put(key, {"update": {"labels": [{"add": label}]}})

    def remove_label(self, key: str, label: str = "tp-po-approved") -> None:
        self._put(key, {"update": {"labels": [{"remove": label}]}})

    def set_description(self, key: str, description: str, acs: list[str]) -> None:
        from tp_core.integrations.jira_adf import build_description

        self._put(key, {"fields": {"description": build_description(description, acs)}})

    def comment(self, key: str, body: str) -> None:
        from tp_core.integrations.jira_adf import text_to_adf

        r = self.sim.post(
            f"/rest/api/3/issue/{key}/comment", json={"body": text_to_adf(body)}, auth=PO_AUTH
        )
        assert r.status_code in (200, 201), r.text


@pytest.fixture
def po(sim: TestClient) -> PoActions:
    return PoActions(sim)


# ------------------------------------------------------------------ forge (demo-app/)


@pytest.fixture(scope="session")
def demo_forge_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """demo-app/ dizininin (izlenen + yok sayılmayan) dosyalarıyla bare forge deposu."""
    if shutil.which("git") is None:
        pytest.skip("git bulunamadı")
    kok = tmp_path_factory.mktemp("forge")
    work = kok / "work"
    work.mkdir()
    dosyalar = git("ls-files", "-co", "--exclude-standard", "--", "demo-app", cwd=REPO).splitlines()
    for rel in dosyalar:
        kaynak = REPO / rel
        if not kaynak.is_file():
            continue
        hedef = work / Path(rel).relative_to("demo-app")
        hedef.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(kaynak, hedef)
    git("init", "-q", "-b", "main", str(work))
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "demo-app", cwd=work)
    repo = kok / "demo-app.git"
    git("init", "-q", "--bare", "-b", "main", str(repo))
    git("push", "-q", str(repo), "main", cwd=work)
    return repo


@pytest.fixture
def forge(demo_forge_repo: Path, tmp_path: Path) -> LocalForge:
    return LocalForge(demo_forge_repo, tmp_path / "artifacts", tmp_path / "tp-prs.json")


# ------------------------------------------------------------- demoapp (salt okuma)

RO_PASSWORD = "ro-" + secrets.token_hex(8)


@pytest.fixture(scope="session")
def demoapp_ro_url(pg: PgServer) -> str:
    """demo-app tabloları + tohum verisi; `demoapp_ro` rolü uygulamanın kendi GRANT'larıyla."""
    from demoapp_api import seed as demo_seed
    from demoapp_api.db import grant_readonly
    from demoapp_api.models import Base as DemoBase
    from sqlalchemy.orm import Session as OrmSession

    ad = f"demoapp_{uuid.uuid4().hex[:8]}"
    with pg.super_conn() as c:
        if not c.execute("SELECT 1 FROM pg_roles WHERE rolname = 'demoapp_ro'").fetchone():
            c.execute(
                f"CREATE ROLE demoapp_ro LOGIN PASSWORD '{RO_PASSWORD}' "
                "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT"
            )
            c.execute("ALTER ROLE demoapp_ro SET default_transaction_read_only = on")
            c.execute("ALTER ROLE demoapp_ro SET statement_timeout = '5s'")
        c.execute(f'CREATE DATABASE "{ad}"')
        c.execute(f'GRANT CONNECT ON DATABASE "{ad}" TO demoapp_ro')
    eng = create_engine(pg.url("postgres", ad))
    DemoBase.metadata.create_all(eng)
    with eng.begin() as conn:
        assert grant_readonly(conn)
        conn.execute(text("REVOKE ALL ON SCHEMA public FROM PUBLIC"))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO demoapp_ro"))
    with OrmSession(eng) as s:
        demo_seed.seed(s)
        s.commit()
    eng.dispose()
    return f"postgresql+psycopg://demoapp_ro:{RO_PASSWORD}@127.0.0.1:{pg.port}/{ad}"


@pytest.fixture
def demo_db(demoapp_ro_url: str) -> DemoDb:
    return DemoDb(demoapp_ro_url)


# ------------------------------------------------------------------ model geçidi


@pytest.fixture
def replay_gateway(monkeypatch: pytest.MonkeyPatch) -> Callable[[Engine], Gateway]:
    """Gerçek fabrika (`build_gateway`), TP_MODEL_MODE=replay, gerçek rules/ (yazmaz)."""
    monkeypatch.setenv("TP_MODEL_MODE", "replay")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TP_REPLAY_STRICT", raising=False)

    def make(engine: Engine) -> Gateway:
        return build_gateway(PgCallRecorder(engine), engine=engine, settings=GatewaySettings())

    return make


def fake_gateway(script: list[Any]) -> tuple[Callable[[Engine], Gateway], FakeProvider]:
    provider = FakeProvider(script)

    def make(engine: Engine) -> Gateway:
        return Gateway(
            provider=provider,
            recorder=PgCallRecorder(engine),
            mode="live",
            models=load_model_table(RULES),
            rules_dir=RULES,
            call_lookup=PgCallLookup(engine),
            record_extras=True,
            sleep=lambda _s: None,
        )

    return make, provider


# ------------------------------------------------------------------ bağlama


@pytest.fixture
def req_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("JIRA_PROJECT", "TPD")
    monkeypatch.setenv("TP_PO_POLL_S", "15")
    get_requirements_settings.cache_clear()
    yield
    get_requirements_settings.cache_clear()


@pytest.fixture
def wired(
    db: Db,
    jira: RestJira,
    forge: LocalForge,
    demo_db: DemoDb,
    replay_gateway: Callable[[Engine], Gateway],
    req_settings: None,
) -> Iterator[dict[str, Any]]:
    """Tüm servisler: jira-sim, geçici forge, demoapp_ro, REPLAY geçidi."""
    ctx: dict[str, Any] = {"gateway": replay_gateway}
    with services.override(
        jira=lambda: jira,
        forge=lambda: forge,
        demo_db=lambda: demo_db,
        gateway=lambda engine: ctx["gateway"](engine),
        jira_url=lambda key: f"http://127.0.0.1:8090/browse/{key}",
    ):
        yield ctx


def run_jobs(engine: Engine, limit: int = 40) -> list[Any]:
    """Zamanı gelmiş işleri bitene kadar işler (worker'ın yaptığı gibi)."""
    out = []
    for _ in range(limit):
        sonuc = process_one(engine, worker="test-worker:1")
        if sonuc is None:
            break
        out.append(sonuc)
    return out


@pytest.fixture
def api(db: Db) -> Iterator[TestClient]:
    from tp_core.api.main import create_app
    from tp_core.auth.login import THROTTLE

    THROTTLE._kayit.clear()
    with TestClient(create_app()) as c:
        yield c
    THROTTLE._kayit.clear()


def login(client: TestClient, user: Any) -> None:
    r = client.post("/auth/login", json={"kullanici_adi": user.kullanici_adi, "parola": PAROLA})
    assert r.status_code == 200, r.text
