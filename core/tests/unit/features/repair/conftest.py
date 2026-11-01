"""Onarım akışı testleri: gerçek Postgres + demo-app/e2e'den kurulan geçici LocalForge + sahte
toolchain-worker (httpx MockTransport). `enqueue_ci` sahtedir (çağrılar kaydedilir); geri kalan
paket gerçektir (yerel kontrol `run`'a gerçek `ingest_check_report` ile yazılır).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine, text

CORE = Path(__file__).resolve().parents[4]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import tp_core.features.repair.jobs  # noqa: E402, F401  (iş işleyicileri)
from tests.unit.features.cases.helpers import api, login  # noqa: E402, F401
from tp_core.config import get_settings  # noqa: E402
from tp_core.features.repair import service  # noqa: E402
from tp_core.features.repair.toolchain import RepairToolchain  # noqa: E402
from tp_core.integrations.forge_local import LocalForge  # noqa: E402
from tp_core.models import Failure, Run, TestResult, session_scope  # noqa: E402
from tp_core.workflow.jobs import REGISTRY, process_one  # noqa: E402

REPO = CORE.parent
SYMBOLS = json.loads((CORE / "tests/unit/features/codegen/symbols.json").read_text("utf-8"))
TOOLCHAIN = "http://toolchain-worker:8100"
LOCATOR_MSG = (
    "Error: locator.click: Timeout 5000ms exceeded.\nCall log:\n"
    "  - waiting for getByTestId('product-card-P-001').getByTestId('add-to-cart')"
)
YESIL_ARIA = """- main:
  - generic:
    - article "Portakal Gazozu 1L":
      - spinbutton "Adet"
      - button "Sepete ekle" [ref=e12]
    - article "Kola 330 ml":
      - spinbutton "Adet"
      - button "Sepete ekle" [ref=e17]
"""
SOZLESME_GIRIS = "locators.ts rol/ad sözleşmesi › giriş sayfası"
SOZLESME_KATALOG = "locators.ts rol/ad sözleşmesi › menü, katalog, sepet ve sipariş sayfaları"
VARSAYILAN_ONERI: dict[str, Any] = {
    "locator_key": "catalog.addToCart",
    "old_testid": "add-to-cart",
    "new_testid": "cart-add",
}
_VARSAYILAN = object()
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
    "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
    "HOME": "/tmp",
}


def git(*args: str, cwd: Path | None = None) -> str:
    out = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=GIT_ENV
    )
    return out.stdout.strip()


@pytest.fixture(scope="session")
def e2e_bare(tmp_path_factory: pytest.TempPathFactory) -> Path:
    kok = tmp_path_factory.mktemp("repair-forge")
    work = kok / "work"
    shutil.copytree(
        REPO / "demo-app" / "e2e",
        work / "e2e",
        ignore=shutil.ignore_patterns("node_modules", "results"),
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


SPEC_DOSYALARI = sorted(
    f"tests/{p.name}" for p in (REPO / "demo-app" / "e2e" / "tests").glob("*.spec.ts")
)


def gecti(n: int = 12, *, dosyalar: list[str] | None = None) -> dict[str, Any]:
    """Yeşil tam paket raporu; varsayılan olarak e2e/tests altındaki her spec dosyası koşmuş."""
    dosyalar = SPEC_DOSYALARI if dosyalar is None else dosyalar
    return {
        "conclusion": "success",
        "summary": "Yerel CI geçti",
        "failed_steps": [],
        "saglik": {"ok": True},
        "app": {"ok": True},
        "deps": {"ok": True},
        "tsc": {"ok": True},
        "eslint": {"ok": True},
        "ast_guard": {"ok": True, "mode": "repair"},
        "run": {
            "run_id": f"run-{uuid.uuid4().hex[:6]}",
            "status": "passed",
            "saglik": {"ok": True},
            "tests": [
                {"title": f"t{i}", "file": dosyalar[i % len(dosyalar)], "status": "expected"}
                for i in range(max(n, len(dosyalar)))
            ]
            if dosyalar
            else [],
        },
        "test_counts": {"toplam": n, "expected": n, "unexpected": 0, "flaky": 0, "skipped": 0},
    }


class FakeToolchain:
    def __init__(self, artifacts: Path) -> None:
        self.artifacts = artifacts
        self.probe: dict[str, Any] = {
            "matches": 1,
            "test_id": "cart-add",
            "test_ids": ["cart-add"],
            "scope_test_id": "product-card-P-001",
            "scope_matches": 1,
            "olculen": "calisan_uygulama",
            "uygulama_sha": "a" * 40,
            "sha_eslesmesi": "eslesiyor",
            "uyari": None,
            "oneri_uretilebilir": True,
        }
        self.ast: dict[str, Any] = {"ok": True, "violations": [], "mode": "repair"}
        self.kontrol: dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]] = gecti()
        self.istekler: list[tuple[str, dict[str, Any]]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.istekler.append((request.url.path, body))
        yol = request.url.path
        if yol == "/symbols":
            return httpx.Response(200, json={"sha": body["sha"], **SYMBOLS})
        if yol == "/locator-probe":
            return httpx.Response(200, json={**self.probe, "sha": body["sha"]})
        if yol == "/ast-guard":
            return httpx.Response(
                200, json={**self.ast, "base_sha": body["base_sha"], "head_sha": body["head_sha"]}
            )
        if yol == "/check":
            rapor = self.kontrol(body) if callable(self.kontrol) else dict(self.kontrol)
            rapor = {**rapor, "sha": body["sha"]}
            (self.artifacts / "checks" / f"{body['sha']}.json").write_text(
                json.dumps(
                    {
                        "checks": [
                            {
                                "name": "local-ci",
                                "status": "completed",
                                "conclusion": rapor["conclusion"],
                            }
                        ]
                    }
                )
            )
            return httpx.Response(200, json=rapor)
        return httpx.Response(404, json={"detail": "yok"})

    def yollar(self) -> list[str]:
        return [p for p, _ in self.istekler]


class Ortam:
    toolchain: FakeToolchain
    forge: LocalForge
    bare: Path
    artifacts: Path
    ci: list[dict[str, Any]]


@pytest.fixture
def ortam(
    engine: Engine, e2e_bare: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Ortam]:
    bare = tmp_path / "forge" / "demo-app.git"
    shutil.copytree(e2e_bare, bare)
    artifacts = tmp_path / "artifacts"
    (artifacts / "checks").mkdir(parents=True)
    monkeypatch.setenv("TP_ARTIFACTS_PATH", str(artifacts))
    monkeypatch.setenv("TP_FORGE", "local")
    monkeypatch.delenv("TP_CHECKS_PATH", raising=False)
    monkeypatch.delenv("TP_REQUIRED_CHECKS", raising=False)
    monkeypatch.delenv("TP_FORGE_APP_ROOT", raising=False)
    monkeypatch.delenv(service.ARIA_FALLBACK_ENV, raising=False)
    get_settings.cache_clear()
    tc = FakeToolchain(artifacts)
    forge = LocalForge(bare, artifacts)
    service.set_factories(
        forge=lambda: forge,
        toolchain=lambda: RepairToolchain(
            TOOLCHAIN, transport=httpx.MockTransport(tc.handler), check_timeout_s=30
        ),
        artifacts_root=lambda: artifacts,
    )
    import tp_core.features.ci as ci_mod

    cagrilar: list[dict[str, Any]] = []

    def enqueue_ci(session: Any, sha: str, trigger: str, pr_number: Any = None, **kw: Any):
        cagrilar.append({"sha": sha, "trigger": trigger, "pr_number": pr_number, **kw})
        return uuid.uuid4()

    monkeypatch.setattr(ci_mod, "enqueue_ci", enqueue_ci)
    o = Ortam()
    o.toolchain, o.forge, o.bare, o.artifacts, o.ci = tc, forge, bare, artifacts, cagrilar
    yield o
    service.reset_factories()
    get_settings.cache_clear()


def run_jobs(engine: Engine, limit: int = 10) -> list[Any]:
    """Yalnızca kayıtlı işleyicileri olan işleri işler (sahte CI kuyruğa iş eklemez)."""
    out = []
    for _ in range(limit):
        s = process_one(engine, "test-repair", REGISTRY)
        if s is None:
            break
        out.append(s)
    return out


def yesil_kosu(
    engine: Engine,
    *,
    aria_dosyasi: str | None = None,
    sozlesme: bool = False,
    artifacts: Path | None = None,
) -> uuid.UUID:
    """Kırıktan önceki yeşil koşu (aria dosyası ve/veya locators.spec sözleşme testiyle)."""
    rid = uuid.uuid4()
    dizin = f"runs/yesil-{rid.hex[:8]}"
    if aria_dosyasi is not None and artifacts is not None:
        p = artifacts / dizin / "results" / "katalog.aria.yml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(aria_dosyasi, encoding="utf-8")
    with session_scope() as s:
        s.add(
            Run(
                id=rid,
                commit="b" * 40,
                kaynak="local",
                tetik="push",
                sonuc="passed",
                ortam={"saglik": {"ok": True}},
                artefaktlar={"dizin": dizin},
            )
        )
        s.flush()
        if sozlesme:
            # İki sözleşme testi: "giriş sayfası" catalog.addToCart'a dokunmaz (kanıt değildir);
            # kanıt olan "menü, katalog, sepet ve sipariş sayfaları"dır.
            for ad in (SOZLESME_GIRIS, SOZLESME_KATALOG):
                s.add(
                    TestResult(
                        run_id=rid,
                        test_adi=ad,
                        dosya="tests/locators.spec.ts",
                        sonuc="passed",
                        tetik="push",
                        kaynak="local",
                    )
                )
    return rid


def kirik_hata(
    engine: Engine,
    *,
    sinif: str = "test_maintenance",
    alt_tur: str | None = "locator",
    saglik_ok: bool = True,
    mesaj: str = LOCATOR_MSG,
    oneri: Any = _VARSAYILAN,
    karar_kaynagi: str = "rule",
    run_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Kırık koşu + `test_maintenance/locator` hatası. Varsayılan: triage kural önerisi
    (`failure_ek.oneri`, kapsam/url hata metninden çıkarılır); `oneri=None` öneri yazmaz."""
    if oneri is _VARSAYILAN:
        oneri = dict(VARSAYILAN_ONERI) if sinif == "test_maintenance" else None
    yeni_kosu = run_id is None
    rid = run_id or uuid.uuid4()
    fid = uuid.uuid4()
    with session_scope() as s:
        if yeni_kosu:
            s.add(
                Run(
                    id=rid,
                    commit="c" * 40,
                    kaynak="local",
                    tetik="push",
                    sonuc="failed" if saglik_ok else "error",
                    ortam={"saglik": {"ok": saglik_ok}},
                )
            )
            s.flush()
        tr = TestResult(
            id=uuid.uuid4(),
            run_id=rid,
            test_adi="Sepet › kampanya 7 adet",
            dosya="tests/cart.spec.ts",
            sonuc="failed",
            tetik="push",
            kaynak="local",
            hata_mesaji=mesaj,
        )
        s.add(tr)
        s.flush()
        s.add(
            Failure(
                id=fid,
                run_id=rid,
                test_result_id=tr.id,
                test_adi=tr.test_adi,
                hata_imzasi="locator:getByTestId(add-to-cart):0-match",
                sinif=sinif,
                alt_tur=alt_tur,
                eslesen_sinyaller=[
                    {"kod": "locator_zero", "aciklama": "0 eleman", "kaynak": "playwright-json"}
                ],
                karar_kaynagi=karar_kaynagi,
                oneri_turu="locator_fix" if sinif == "test_maintenance" and oneri else "none",
                oneri_durumu="proposed" if sinif == "test_maintenance" and oneri else "none",
            )
        )
        s.flush()
        if oneri is not None:
            var = s.execute(text("SELECT to_regclass('failure_ek') IS NOT NULL")).scalar()
            if var:
                s.execute(
                    text(
                        "INSERT INTO failure_ek (failure_id, anahtar, oneri) "
                        "VALUES (:f, :a, CAST(:o AS jsonb))"
                    ),
                    {"f": fid, "a": f"{rid}:{fid}", "o": json.dumps(oneri)},
                )
    return fid
