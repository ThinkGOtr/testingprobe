"""Triage testleri: gerçek Postgres (platform fikstürü) + artefakt fikstürleri + sahte toolchain.

Koşu fikstürü test-runner'ın gerçek düzenini kurar: `runs/<dizin>/run.json` (`saglik`, `tests`,
`failures[].failure`), kanıt dosyaları (`error-context.md`, `trace.zip`) ve çekirdek satırları
(`run`, `test_result`, gerekirse `script` + `script_kontrol`).
"""

from __future__ import annotations

import io
import json
import sys
import uuid
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

CORE = Path(__file__).resolve().parents[4]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from tp_core.features.triage import jobs as _triage_jobs  # noqa: E402, F401  (iş kaydı)
from tp_core.features.triage import services  # noqa: E402
from tp_core.models import Run, Script, TestResult  # noqa: E402
from tp_core.models.codegen_feature import ScriptKontrol  # noqa: E402

SHA = "b" * 40
DENEME_FLAKY = [{"retry": 0, "status": "failed"}, {"retry": 1, "status": "passed"}]
UZAK = "/artifacts"

SEMBOLLER: dict[str, Any] = {
    "schema_version": 1,
    "page_objects": [
        {
            "class": "CatalogPage",
            "file": "pages/catalog/catalog.page.ts",
            "locators": {
                "catalog.addToCart": {
                    "testId": "add-to-cart",
                    "role": "button",
                    "name": "Sepete ekle",
                    "within": "product-card-",
                    "intent": "Ürün kartında sepete ekleme butonu",
                    "prefix": False,
                    "file": "pages/catalog/locators.ts",
                    "line": 9,
                },
                "catalog.productCard": {
                    "testId": "product-card-",
                    "role": "article",
                    "name": "",
                    "intent": "Tek bir ürünün kartı",
                    "prefix": True,
                    "file": "pages/catalog/locators.ts",
                    "line": 5,
                },
                "nav.cart": {
                    "testId": "nav-cart",
                    "role": "link",
                    "name": "Sepet",
                    "intent": "Üst menüde sepete giden bağlantı",
                    "prefix": False,
                    "file": "pages/common/locators.ts",
                    "line": 4,
                },
            },
        },
        {
            "class": "CartPage",
            "file": "pages/cart/cart.page.ts",
            "locators": {
                "cart.lineFree": {
                    "testId": "cart-line-free-",
                    "role": "generic",
                    "name": "",
                    "intent": "Sepet satırında kampanyayla bedava verilen adet",
                    "prefix": True,
                    "file": "pages/cart/locators.ts",
                    "line": 7,
                },
            },
        },
    ],
}

ARIA_KATALOG = """- banner:
  - link "Katalog"
  - link "Sepet"
- main:
  - article:
    - heading "Kola 330 ml" [level=3]
    - spinbutton "Adet"
    - button "Sepete ekle" [ref=e12]
  - article:
    - heading "Ayran 1 L" [level=3]
    - spinbutton "Adet"
    - button "Sepete ekle" [ref=e19]"""

ARIA_SEPET = """- main:
  - table "Sepetteki ürünler":
    - row "Kola 330 ml 6 1 125,00 TL"
  - definition: 125,00 TL"""


@dataclass
class FakeToolchain:
    probe: dict[str, Any] = field(
        default_factory=lambda: {
            "matches": 1,
            "test_id": "cart-add",
            "olculen": "calisan_uygulama",
            "uygulama_sha": SHA,
            "sha_eslesmesi": "eslesiyor",
            "uyari": None,
            "oneri_uretilebilir": True,
        }
    )
    semboller: dict[str, Any] = field(default_factory=lambda: SEMBOLLER)
    cagrilar: list[tuple[str, Any]] = field(default_factory=list)
    hata: Exception | None = None

    def symbols(self, sha: str) -> dict[str, Any]:
        self.cagrilar.append(("symbols", sha))
        if self.hata:
            raise self.hata
        return self.semboller

    def locator_probe(
        self, sha: str, role: str, name: str, url_path: str, scope_test_id: str | None
    ) -> dict[str, Any]:
        self.cagrilar.append(("probe", (sha, role, name, url_path, scope_test_id)))
        return dict(self.probe, scope_test_id=scope_test_id, sha=sha, url_path=url_path)


def _gateway_yasak(_engine: Any) -> Any:
    raise AssertionError("bu senaryoda model çağrılmamalı (kural kararı)")


@pytest.fixture
def artefakt_kok(tmp_path: Path) -> Path:
    kok = tmp_path / "artifacts"
    kok.mkdir()
    return kok


@pytest.fixture
def toolchain() -> FakeToolchain:
    return FakeToolchain()


@pytest.fixture
def triage_env(artefakt_kok: Path, toolchain: FakeToolchain, db: Any) -> Iterator[dict[str, Any]]:
    ctx: dict[str, Any] = {"gateway": _gateway_yasak}
    with services.override(
        artifacts_root=lambda: artefakt_kok,
        toolchain=lambda: toolchain,
        gateway=lambda engine: ctx["gateway"](engine),
        sweep_s=lambda: 0,
    ):
        yield ctx


def trace_zip(url: str, testidler: list[tuple[str, str, str]]) -> bytes:
    """Playwright trace.zip benzeri: `trace.trace` NDJSON (goto + frame-snapshot)."""
    html: list[Any] = ["HTML", {}, ["BODY", {}]]
    govde = html[2]
    for etiket, tid, metin in testidler:
        govde.append([etiket, {"data-testid": tid}, metin])
    satirlar = [
        {"type": "before", "method": "goto", "params": {"url": url}},
        {"type": "frame-snapshot", "snapshot": {"frameUrl": url, "html": html}},
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("trace.trace", "\n".join(json.dumps(s) for s in satirlar))
        zf.writestr("trace.network", "")
    return buf.getvalue()


@dataclass
class KTest:
    title: str
    file: str = "tests/cart.spec.ts"
    sonuc: str = "failed"  # test_result.sonuc
    statuses: list[str] = field(default_factory=lambda: ["unexpected"])  # tekrar başına
    failure: dict[str, Any] | None = None
    trace: bytes | None = None
    error_context: str | None = None
    test_result: bool = True
    denemeler: list[dict[str, Any]] | None = None  # attempt_results (yoksa durumdan türetilir)


def _denemeler(st: str) -> list[dict[str, Any]]:
    if st == "flaky":
        return DENEME_FLAKY
    return [{"retry": 0, "status": "failed" if st == "unexpected" else "passed"}]


def kosu_kur(
    engine: Engine,
    kok: Path,
    *,
    tetik: str = "push",
    sonuc: str = "failed",
    testler: list[KTest] | None = None,
    saglik_ok: bool | None = True,
    run_json: bool = True,
    ortam: dict[str, Any] | None = None,
    artefaktlar: dict[str, Any] | None = None,
    script_id: uuid.UUID | None = None,
    commit: str = SHA,
) -> uuid.UUID:
    rid = uuid.uuid4()
    dizin = f"runs/ci-{rid.hex[:12]}"
    yerel = kok / dizin
    sonuclar = yerel / "src" / "e2e" / "results"
    sonuclar.mkdir(parents=True)
    saglik = (
        None
        if saglik_ok is None
        else {
            "ok": saglik_ok,
            "zaman": "2026-10-31T10:00:00+00:00",
            "web": {"url": "http://demo-app-web:8080/", "status": 200 if saglik_ok else None,
                    "ms": 12, "hata": None if saglik_ok else "bağlantı reddedildi"},
            "api": {"url": "http://demo-app-api:8000/health", "status": 200, "ms": 8,
                    "hata": None},
            "hata": None if saglik_ok else "Demo uygulaması sağlık kontrolü başarısız — web",
        }
    )  # fmt: skip
    tests_json: list[dict[str, Any]] = []
    failures_json: list[dict[str, Any]] = []
    for i, t in enumerate(testler or []):
        kanit: dict[str, Any] = {
            "trace": None,
            "error_context": None,
            "screenshot": None,
            "video": None,
        }
        ek_dizin = sonuclar / "artifacts" / f"t{i}"
        ek_dizin.mkdir(parents=True)
        if t.trace is not None:
            (ek_dizin / "trace.zip").write_bytes(t.trace)
            kanit["trace"] = {
                "path": f"{UZAK}/{dizin}/src/e2e/results/artifacts/t{i}/trace.zip",
                "rel": f"{dizin}/src/e2e/results/artifacts/t{i}/trace.zip",
                "exists": True,
            }
        if t.error_context is not None:
            (ek_dizin / "error-context.md").write_text(t.error_context)
            kanit["error_context"] = {
                "path": f"{UZAK}/{dizin}/src/e2e/results/artifacts/t{i}/error-context.md",
                "rel": f"{dizin}/src/e2e/results/artifacts/t{i}/error-context.md",
                "exists": True,
            }
        (ek_dizin / "test-failed-1.png").write_bytes(b"\x89PNG")
        kanit["screenshot"] = {
            "path": f"{UZAK}/{dizin}/src/e2e/results/artifacts/t{i}/test-failed-1.png",
            "rel": f"{dizin}/src/e2e/results/artifacts/t{i}/test-failed-1.png",
            "exists": True,
        }
        for r, st in enumerate(t.statuses):
            failure = (
                {**t.failure, "evidence": kanit, "status": "failed"}
                if t.failure is not None and st in ("unexpected", "flaky")
                else None
            )
            giris = {
                "id": f"id{i}",
                "title": t.title,
                "file": t.file,
                "line": 10,
                "status": st,
                "repeat_index": r,
                "attempts": 1,
                "attempt_results": t.denemeler or _denemeler(st),
                "failure": failure,
            }  # fmt: skip
            tests_json.append(giris)
            if st in ("unexpected", "flaky"):
                failures_json.append(giris)
    if run_json:
        (yerel / "run.json").write_text(
            json.dumps(
                {
                    "run_id": dizin.split("/")[1],
                    "sha": commit,
                    "status": "error" if sonuc == "error" else "failed",
                    "error": None if saglik_ok in (True, None) else (saglik or {}).get("hata"),
                    "saglik": saglik,
                    "tests": tests_json,
                    "failures": failures_json,
                    "artifacts_rel": dizin,
                },
                ensure_ascii=False,
            )
        )
    with Session(engine) as s, s.begin():
        s.add(
            Run(
                id=rid,
                script_id=script_id,
                commit=commit,
                kaynak="local",
                tetik=tetik,
                sonuc=sonuc,
                ortam={"saglik": saglik, **(ortam or {})},
                artefaktlar={"dizin": dizin, **(artefaktlar or {})},
            )
        )
        s.flush()
        for t in testler or []:
            if not t.test_result:
                continue
            s.add(
                TestResult(
                    run_id=rid,
                    test_adi=t.title,
                    dosya=t.file,
                    sonuc=t.sonuc,
                    commit=commit,
                    tetik=tetik,
                    kaynak="local",
                    hata_mesaji=(t.failure or {}).get("message"),
                )
            )
    return rid


def script_kur(engine: Engine) -> uuid.UUID:
    sid = uuid.uuid4()
    with Session(engine) as s, s.begin():
        s.add(Script(id=sid, dosya_yolu="e2e/tests/generated/TPD-1-c3-abcd1234.spec.ts"))
    return sid


def kontrol_kur(engine: Engine, sid: uuid.UUID, run_id: uuid.UUID, sinif: str) -> None:
    with Session(engine) as s, s.begin():
        s.add(
            ScriptKontrol(
                script_id=sid,
                tur="local_check",
                sha=SHA,
                run_id=str(run_id),
                sonuc="failure",
                sinif=sinif,
                ozet={"sinif": sinif},
            )
        )


def run_jobs(engine: Any, limit: int = 20) -> list[Any]:
    from tp_core.workflow.jobs import process_one

    out = []
    for _ in range(limit):
        r = process_one(engine, "test-worker")
        if r is None:
            break
        out.append(r)
    return out
