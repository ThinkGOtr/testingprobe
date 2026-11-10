# ruff: noqa: E501  (gerçek Surefire XML fikstürleri tek satırda öznitelik taşır)
"""Sözleşme testi (009, Ş6b): test-runner'ın GERÇEK Java özeti (`toolchain/runner/surefire.py`)
→ çekirdek CI alımı (`ci.service.ingest_check_report`) → triage (`classify_run`).

El yapımı bir `run.json` değil, test-runner'ın kendi kodu kullanılır: Surefire XML + kanıt dizini
`java_run.execute_locked` düzeninde kurulur, `surefire.summarize` / `write_junit` /
`results.failures_of` çıktısı `run.json`'a ve toolchain `/check` raporuna yazılır. Böylece
alan adları (`failure.type`, `failure.locator`, `failure.evidence.page_source|screenshot.rel`,
`page_source_rel`, `page_location` → `ekranlar/`) iki tarafta ayrışırsa bu test kırılır.
"""

from __future__ import annotations

import importlib
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from tp_core.features.ci import service as ci_service
from tp_core.features.ci import services as ci_services
from tp_core.features.triage import classify_run
from tp_core.models import Failure, Run, Script, TestResult
from tp_core.models.triage_feature import FailureEk

from .conftest import SHA, FakeToolchain
from .test_java import ANDROID_KIRIK, JAVA_SEMBOLLER, _bugs_modulu

pytestmark = pytest.mark.usefixtures("triage_env")

TOOLCHAIN = Path(__file__).resolve().parents[5] / "toolchain"
SINIF = "TPD1AndroidC2_0a1b2c3dTest"
FQCN = f"com.antreklabs.bayi.uretilen.{SINIF}"
DOSYA = f"src/test/java/com/antreklabs/bayi/uretilen/{SINIF}.java"
ZINCIR = (
    "\n\tat com.antreklabs.bayi.altyapi.Bekle.kosul(Bekle.java:51)"
    "\n\tat com.antreklabs.bayi.ekranlar.KatalogEkrani.sepeteEkle(KatalogEkrani.java:38)"
    f"\n\tat {FQCN}.senaryo({SINIF}.java:21)"
    "\n\tat org.testng.internal.invokers.MethodInvocationHelper.invokeMethod(X.java:1)"
)
LOCATOR_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="TestSuite" tests="1" failures="0" errors="1" skipped="0">
  <properties><property name="java.version" value="17"/></properties>
  <testcase name="senaryo" classname="{FQCN}" time="12.5">
    <error type="org.openqa.selenium.TimeoutException"
      message="Expected condition failed: öğe görünmedi: kimlik 'product-card-P-001' içinde 'add-to-cart' (tried for 10 second(s) with 250 milliseconds interval)">org.openqa.selenium.TimeoutException: Expected condition failed{ZINCIR}</error>
  </testcase>
</testsuite>
"""
ASSERT_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="TestSuite" tests="1" failures="1" errors="0" skipped="0">
  <testcase name="senaryo" classname="{FQCN}" time="8">
    <failure type="java.lang.AssertionError"
      message="'cart-total' metni: beklenen &lt;150,00 TL&gt;, görülen &lt;175,00 TL&gt; (10000 ms)">java.lang.AssertionError: 'cart-total' metni{ZINCIR}</failure>
  </testcase>
</testsuite>
"""


@pytest.fixture
def runner_mod() -> Any:
    """toolchain/runner (yalnız stdlib) — test-runner'ın gerçek özet kodu."""
    if not (TOOLCHAIN / "runner" / "surefire.py").is_file():
        pytest.skip("toolchain/runner yok")
    sys.path.insert(0, str(TOOLCHAIN))
    try:
        surefire = importlib.import_module("runner.surefire")
        results = importlib.import_module("runner.results")
    finally:
        sys.path.remove(str(TOOLCHAIN))
    return surefire, results


def _java_kosusu(
    engine: Engine, kok: Path, runner_mod: Any, xml: str, *, platform: str = "android"
) -> uuid.UUID:
    """`java_run.execute_locked` düzeni: runs/<id>/src/e2e-app/target/{surefire-reports,kanit},
    runs/<id>/results/junit.xml, runs/<id>/run.json; kanıt yolları artefakt köküne göre."""
    surefire, results = runner_mod
    rid = uuid.uuid4()
    run_id = f"ci-{rid}-1"
    dest = kok / "runs" / run_id
    target = dest / "src" / "e2e-app" / "target"
    rep = surefire.Repeat(0, target / "surefire-reports", target / "kanit")
    rep.reports_dir.mkdir(parents=True)
    (rep.reports_dir / "TEST-TestSuite.xml").write_text(xml, encoding="utf-8")
    kanit = rep.kanit_dir / f"{SINIF}.senaryo"
    kanit.mkdir(parents=True)
    (kanit / "sayfa-kaynagi.xml").write_text(ANDROID_KIRIK, encoding="utf-8")
    (kanit / "ekran.png").write_bytes(b"\x89PNG\r\n")
    ozet = surefire.summarize([rep], project=platform, rel_root=kok)
    junit = dest / "results" / "junit.xml"
    surefire.write_junit([rep], junit)
    rapor_run = {
        "run_id": run_id,
        "sha": SHA,
        "lang": "java",
        "platform": platform,
        "status": "failed",
        "error": None,
        "artifacts_dir": str(dest),
        "artifacts_rel": f"runs/{run_id}",
        "junit": str(junit),
        "json": None,
        "allure_dir": str(target / "allure-results"),
        "html_dir": None,
        "log": str(dest / "runner.log"),
        "saglik": {"ok": True},
        "kirmizi_denetimi": None,
        "stats": ozet["stats"],
        "tests": ozet["tests"],
        "failures": results.failures_of(ozet["tests"]),
        "failure_groups": results.failure_groups(ozet["tests"]),
    }
    (dest / "run.json").write_text(json.dumps(rapor_run, ensure_ascii=False), encoding="utf-8")
    rapor = {
        "sha": SHA,
        "lang": "java",
        "platform": platform,
        "check_name": f"local-ci-{platform}",
        "conclusion": "failure",
        "summary": "1 test kırmızı",
        "failed_steps": ["run"],
        "app": {"ok": True},
        "deps": {"ok": True},
        "guard": {"ok": True, "mode": "pr"},
        "compile": {"ok": True},
        "run": rapor_run,
        "duration_ms": 12500,
    }
    with Session(engine) as s, s.begin():
        s.add(
            Script(
                id=(sid := uuid.uuid4()),
                dosya_yolu=f"e2e-app/{DOSYA}",
                platform=platform,
            )
        )
        s.flush()
        run = Run(
            id=rid,
            script_id=sid,
            commit=SHA,
            kaynak="local",
            tetik="push",
            sonuc="running",
            ortam={"platform": platform},
            artefaktlar={},
        )
        s.add(run)
        s.flush()
        with ci_services.override(artifacts_root=lambda: kok, checks_root=lambda: kok / "checks"):
            assert ci_service.ingest_check_report(s, run, rapor) == "failed"
    return rid


def _tek(engine: Engine, rid: uuid.UUID) -> tuple[Failure, FailureEk]:
    with Session(engine) as s:
        return s.execute(
            select(Failure, FailureEk)
            .join(FailureEk, FailureEk.failure_id == Failure.id)
            .where(Failure.run_id == rid)
        ).one()


def test_surefire_ozeti_alim_ve_triage_locator_onerisi(
    engine: Engine, artefakt_kok: Path, toolchain: FakeToolchain, runner_mod: Any
) -> None:
    toolchain.java_semboller = JAVA_SEMBOLLER
    rid = _java_kosusu(engine, artefakt_kok, runner_mod, LOCATOR_XML)
    with Session(engine) as s:
        run = s.get(Run, rid)
        assert run.ortam["platform"] == "android" and run.ortam["lang"] == "java"
        a = run.artefaktlar
        assert set(a["adimlar"]) == {"app", "deps", "guard", "compile", "run"}
        assert a["junit"] == "results/junit.xml" and a["raporlar"]["junit"] is True
        # Java yolunda JSON rapor yoktur: "JSON yok" uyarısı düşer.
        assert not any("results.json" in u for u in a["uyarilar"])
        tr = s.scalars(select(TestResult).where(TestResult.run_id == rid)).one()
        # Çekirdek test kimliği test-runner özetiyle aynı (`<Sınıf> › <metot>`, kaynak yolu).
        assert (tr.test_adi, tr.dosya, tr.sonuc) == (f"{SINIF} › senaryo", DOSYA, "failed")
    classify_run(engine, rid)
    f, ek = _tek(engine, rid)
    assert (f.sinif, f.alt_tur, f.oneri_turu) == ("test_maintenance", "locator", "locator_fix")
    o = ek.oneri
    assert (o["old_testid"], o["new_testid"], o["scope_test_id"]) == (
        "add-to-cart",
        "cart-add",
        "product-card-P-001",
    )
    assert o["platform"] == "android" and o["kaynak"] == "sayfa_kaynagi"
    # Kanıt: failure.evidence.*.rel (artefakt köküne göre) → koşu dizinine göre yol.
    yollar = {lk["tur"]: lk["yol"] for lk in ek.kanit_linkleri}
    assert yollar["page_source"] == f"src/e2e-app/target/kanit/{SINIF}.senaryo/sayfa-kaynagi.xml"
    assert yollar["screenshot"] == f"src/e2e-app/target/kanit/{SINIF}.senaryo/ekran.png"
    assert o["sayfa_kaynagi"]["rel"] == yollar["page_source"]
    # API görünümü (portal Ş7): öneri kaynağı/platformu/sayfa kaynağı + hatanın platformu.
    from tp_core.features.triage.service import get_failure

    with Session(engine) as s:
        g = get_failure(s, f.id)
    assert g is not None and g["platform"] == "android"
    assert (g["oneri"]["kaynak"], g["oneri"]["platform"]) == ("sayfa_kaynagi", "android")
    assert g["oneri"]["sayfa_kaynagi"]["rel"] == yollar["page_source"]


def test_surefire_ozeti_assertion_urun_hatasi(
    engine: Engine,
    artefakt_kok: Path,
    runner_mod: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bugs_modulu(monkeypatch)
    rid = _java_kosusu(engine, artefakt_kok, runner_mod, ASSERT_XML)
    classify_run(engine, rid)
    f, ek = _tek(engine, rid)
    assert f.sinif == "product_defect" and f.karar_kaynagi == "rule"
    assert (ek.kanit["beklenen"], ek.kanit["gerceklesen"]) == ("150,00 TL", "175,00 TL")


def test_surefire_failure_alanlari_cekirdegin_okudugu_adlar(
    runner_mod: Any, tmp_path: Path
) -> None:
    """Çekirdeğin okuduğu `failure` alanları test-runner çıktısında var (ad sözleşmesi)."""
    surefire, _results = runner_mod
    target = tmp_path / "runs" / "x" / "src" / "e2e-app" / "target"
    rep = surefire.Repeat(0, target / "surefire-reports", target / "kanit")
    rep.reports_dir.mkdir(parents=True)
    (rep.reports_dir / "TEST-TestSuite.xml").write_text(LOCATOR_XML, encoding="utf-8")
    (rep.kanit_dir / f"{SINIF}.senaryo").mkdir(parents=True)
    (rep.kanit_dir / f"{SINIF}.senaryo" / "sayfa-kaynagi.xml").write_text("<h/>")
    t = surefire.summarize([rep], project="android", rel_root=tmp_path)["tests"][0]
    f = t["failure"]
    assert (t["title"], t["file"]) == (f"{SINIF} › senaryo", DOSYA)
    assert f["type"] == "locator_not_found" and f["locator_test_id"] == "add-to-cart"
    assert f["locator"].startswith("kimlik 'product-card-P-001' içinde")
    assert f["page_source_rel"] == f["evidence"]["page_source"]["rel"]
    assert f["page_location"]["file"].endswith("/ekranlar/KatalogEkrani.java")
    assert f["test_location"]["file"] == DOSYA
    from tp_core.features.ci.parse import java_test_kimligi

    assert java_test_kimligi(FQCN, "senaryo") == (DOSYA, t["title"])
