"""CI'ın üretim dili boyutu (011 §2.8, Ş5): web + Java (Playwright for Java + TestNG) PR koşusu
`/check`'e `{lang: java, platform: web}` gönderir, Surefire raporu alınır, check adı `local-ci`
kalır; paket koşuları repoda testi bulunan her tam hat dili için ayrı koşar ve koşu kaydı dili
`run.ortam.dil`'de taşır. Web + TS ve uygulama davranışı değişmez (test_ci_platform)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.unit.features.ci.helpers import SHA, UZAK_KOK, FakeForge, FakeToolchain, run_jobs
from tests.unit.features.ci.test_ci_platform import JUNIT
from tp_core.features.ci import clients, dil, enqueue_ci, service, services
from tp_core.models import Run, Script, TestResult

pytestmark = pytest.mark.usefixtures("ci_env")

WEB_JAVA_DOSYA = "e2e-java/src/test/java/com/antreklabs/bayi/uretilen/TPD1Web2_0a1b2c3dTest.java"


@dataclass
class DilliForge(FakeForge):
    dosyalar: list[str] = field(default_factory=list)
    hata: bool = False

    def list_files(self, prefix: str, ref: str) -> list[str]:
        if self.hata:
            raise RuntimeError("forge yok")
        return [d for d in self.dosyalar if d.startswith(prefix)]


def _web_script(engine: Engine, monkeypatch: pytest.MonkeyPatch, d: str) -> uuid.UUID:
    """`script.dil` kolonu Ş1'in (0021) — bu şeritte yok: dil `ci.dil.script_dili` üzerinden
    verilir (kod yolu `getattr(script, "dil")` ile aynı)."""
    sid = uuid.uuid4()
    with Session(engine) as s, s.begin():
        s.add(Script(id=sid, tur="test", dosya_yolu=WEB_JAVA_DOSYA, platform="web"))
    asil = dil.script_dili
    monkeypatch.setattr(dil, "script_dili", lambda sc: d if sc.id == sid else asil(sc))
    return sid


def _web_java_yaniti(kok: Path, *, lang_yok: bool = False):
    def yanit(body: dict[str, Any]) -> httpx.Response:
        run_dir = body["run_id"]
        yerel = kok / "runs" / run_dir
        (yerel / "results").mkdir(parents=True)
        (yerel / "results" / "junit.xml").write_bytes(JUNIT)
        (kok / "checks").mkdir(exist_ok=True)
        (kok / "checks" / f"{body['sha']}.json").write_text(
            json.dumps(
                {"checks": [{"name": "local-ci", "status": "completed", "conclusion": "failure"}]}
            )
        )
        uzak = f"{UZAK_KOK}/runs/{run_dir}"
        dil_alani = {} if lang_yok else {"lang": "java", "platform": "web"}
        return httpx.Response(
            200,
            json={
                "sha": body["sha"],
                **dil_alani,
                "check_name": "local-ci",
                "conclusion": "failure",
                "failed_steps": ["run"],
                "summary": "Yerel CI başarısız: run",
                "app": {"ok": True},
                "deps": {"ok": True},
                "guard": {"ok": True, "mode": "pr"},
                "compile": {"ok": True},
                "run": {
                    "run_id": run_dir,
                    **dil_alani,
                    "status": "failed",
                    "artifacts_dir": uzak,
                    "artifacts_rel": f"runs/{run_dir}",
                    "junit": f"{uzak}/results/junit.xml",
                    "json": None,
                    "html_dir": None,
                    "log": f"{uzak}/runner.log",
                    "saglik": {"ok": True},
                },
                "duration_ms": 20000,
            },
        )

    return yanit


# ------------------------------------------------------------------------------ PR koşusu


def test_web_java_pr_kosusu_check_govdesi_surefire_ve_local_ci(
    engine: Engine,
    toolchain: FakeToolchain,
    artefakt_kok: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = _web_script(engine, monkeypatch, "java")
    toolchain.yanit = _web_java_yaniti(artefakt_kok)
    with Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "pr", 7, script_id=sid)
    with Session(engine) as s:
        assert (s.get(Run, rid).ortam["platform"], s.get(Run, rid).ortam["dil"]) == ("web", "java")
    run_jobs(engine)
    body = toolchain.istekler[0]
    assert (body["lang"], body["platform"]) == ("java", "web")
    with Session(engine) as s:
        run = s.get(Run, rid)
        assert run.sonuc == "failed"
        assert (run.ortam["platform"], run.ortam["dil"], run.ortam["lang"]) == (
            "web",
            "java",
            "java",
        )
        a = run.artefaktlar
        assert set(a["adimlar"]) == {"app", "deps", "guard", "compile", "run"}
        # Web'de check adı dile bakmaz: koşunun kontrolü `local-ci`.
        assert (a["checks"]["durum"], a["checks"]["conclusion"]) == ("completed", "failure")
        assert a["raporlar"] == {"junit": True, "json": False}
        assert not any("results.json" in u for u in a["uyarilar"])
        k = service.serialize_runs(s, [run])[0]
        assert (k["platform"], k["dil"]) == ("web", "java")
        satirlar = {
            r.test_adi: r for r in s.scalars(select(TestResult).where(TestResult.run_id == rid))
        }
    # Surefire kimliği: `src/test/java/<paket>/<Sınıf>.java` + `<Sınıf> › <metot>`.
    assert "TPD1AndroidC2_0a1b2c3dTest › senaryo" in satirlar


def test_web_java_raporu_dil_bildirmese_kosunun_dili_kullanilir(
    engine: Engine,
    toolchain: FakeToolchain,
    artefakt_kok: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = _web_script(engine, monkeypatch, "java")
    toolchain.yanit = _web_java_yaniti(artefakt_kok, lang_yok=True)
    with Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "pr", 8, script_id=sid)
    run_jobs(engine)
    with Session(engine) as s:
        run = s.get(Run, rid)
        assert run.ortam["dil"] == "java" and run.ortam["platform"] == "web"
        assert set(run.artefaktlar["adimlar"]) == {"app", "deps", "guard", "compile", "run"}


def test_web_ts_scripti_govdesi_ve_kaydi_degismez(
    engine: Engine, toolchain: FakeToolchain, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = _web_script(engine, monkeypatch, "ts")
    with Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "pr", 9, script_id=sid)
    run_jobs(engine)
    assert all("lang" not in b and "platform" not in b for b in toolchain.istekler)
    with Session(engine) as s:
        run = s.get(Run, rid)
        assert run.ortam["dil"] == "ts" and "lang" not in run.ortam
        assert service.serialize_runs(s, [run])[0]["dil"] == "ts"


def test_dogrulanmamis_dil_ci_ye_giremez(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    sid = _web_script(engine, monkeypatch, "csharp")
    with Session(engine) as s, s.begin(), pytest.raises(service.CiError, match="csharp"):
        enqueue_ci(s, SHA, "pr", 10, script_id=sid)


def test_ayni_committe_ts_ve_java_kosulari_birbirini_yutmaz(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    java = _web_script(engine, monkeypatch, "java")
    with Session(engine) as s, s.begin():
        ts1 = enqueue_ci(s, SHA, "pr", 11)
        j1 = enqueue_ci(s, SHA, "pr", 11, script_id=java)
        j2 = enqueue_ci(s, SHA, "pr", 11, script_id=java)
        ts2 = enqueue_ci(s, SHA, "pr", 11)
    assert ts1 != j1 and j1 == j2 and ts1 == ts2


# ------------------------------------------------------------------------- paket koşuları


def test_paket_kosusu_repodaki_her_tam_hat_dili_icin_kosar(
    engine: Engine, toolchain: FakeToolchain
) -> None:
    forge = DilliForge(
        dosyalar=[
            "e2e/tests/cart.spec.ts",
            "e2e-java/src/test/java/com/antreklabs/bayi/testler/SepetTesti.java",
            "e2e-java/src/test/java/com/antreklabs/bayi/birim/KimlikBirimTest.java",
        ]
    )
    with services.override(forge=lambda: forge):
        with Session(engine) as s, s.begin():
            rid = enqueue_ci(s, SHA, "push")
        with Session(engine) as s:
            assert "dil" not in s.get(Run, rid).ortam  # dil işte çözülür
        run_jobs(engine)
        with Session(engine) as s:
            kosular = list(s.scalars(select(Run).where(Run.tetik == "push", Run.commit == SHA)))
    diller = {r.ortam["dil"]: r for r in kosular}
    assert set(diller) == {"ts", "java"} and diller["ts"].id == rid
    assert diller["java"].ortam["kardes_kosu"] == str(rid)
    assert diller["java"].ortam["platform"] == "web" and diller["java"].script_id is None
    govdeler = sorted(f"{b.get('lang')}/{b.get('platform')}" for b in toolchain.istekler)
    assert govdeler == ["None/None", "java/web"]
    # İş yeniden koşsa da dağıtım tekrarlanmaz (dil yazılmış).
    with Session(engine) as s, s.begin():
        run = s.get(Run, rid)
        assert service._paket_dillerini_dagit(s, run) == []


def test_paket_kosusu_yalniz_java_testi_varsa_tek_java_kosusu(
    engine: Engine, toolchain: FakeToolchain
) -> None:
    forge = DilliForge(dosyalar=["e2e-java/src/test/java/com/x/uretilen/AbcTest.java"])
    with services.override(forge=lambda: forge):
        with Session(engine) as s, s.begin():
            rid = enqueue_ci(s, SHA, "nightly", anahtar="nightly:2026-11-11")
        run_jobs(engine)
    with Session(engine) as s:
        assert s.get(Run, rid).ortam["dil"] == "java"
        assert s.scalar(select(Run).where(Run.id != rid, Run.tetik == "nightly")) is None
    assert [(b.get("lang"), b.get("platform")) for b in toolchain.istekler] == [("java", "web")]


def test_paket_kosusu_forge_okunamazsa_ts(engine: Engine, toolchain: FakeToolchain) -> None:
    forge = DilliForge(hata=True)
    with services.override(forge=lambda: forge):
        with Session(engine) as s, s.begin():
            rid = enqueue_ci(s, SHA, "deploy")
        run_jobs(engine)
    with Session(engine) as s:
        assert s.get(Run, rid).ortam["dil"] == "ts"
    assert all("lang" not in b for b in toolchain.istekler)


def test_repodaki_web_dilleri_saf() -> None:
    def lf(dosyalar: list[str]):
        return lambda p, r: [d for d in dosyalar if d.startswith(p)]

    kw = {"e2e": "demo-app/e2e", "e2e_java": "demo-app/e2e-java"}
    assert dil.repodaki_web_dilleri(lf([]), "main", **kw) == ("ts",)
    assert dil.repodaki_web_dilleri(
        lf(["demo-app/e2e-java/src/test/java/a/birim/XTest.java"]), "main", **kw
    ) == ("ts",)
    assert dil.repodaki_web_dilleri(
        lf(["demo-app/e2e/tests/a.spec.ts", "demo-app/e2e-java/src/test/java/a/YTesti.java"]),
        "main",
        **kw,
    ) == ("ts", "java")


# ------------------------------------------------------------------------------ GitHub kipi


def test_github_web_java_is_akisi_artefakt_ve_rapor_dili() -> None:
    web_java = Run(ortam={"platform": "web", "dil": "java"})
    web_ts = Run(ortam={"platform": "web", "dil": "ts"})
    android = Run(ortam={"platform": "android"})
    assert service.gh_is_akisi(web_java) == {"workflow": "web-java.yml"}
    assert service.gh_is_akisi(web_ts) == {} and service.gh_is_akisi(Run(ortam={})) == {}
    assert service.gh_sonuc_artefakti(web_java) == "web-java-results"
    assert service.gh_sonuc_artefakti(web_ts) == "test-local-results"
    assert service.java_kosusu_mu(web_java) and service.java_kosusu_mu(android)
    assert not service.java_kosusu_mu(web_ts)
    assert clients._is_akisi("web-java.yml") == "web-java.yml"
    # `/check` raporu: `lang=java, platform=web` web'dir; dil `java`.
    rapor = {"lang": "java", "platform": "web"}
    assert service.rapor_platformu(rapor) == "web" and service.rapor_dili(rapor) == "java"
    assert service.rapor_platformu({"lang": "java"}) is None
    assert service.rapor_platformu({}) == "web" and service.rapor_dili({}) is None
    assert service.check_body_platformu("web", "java") == {"lang": "java", "platform": "web"}
    assert service.check_body_platformu("web", "ts") == {}
    assert service.check_body_platformu("ios", "java") == {"lang": "java", "platform": "ios"}
    # Kendi iş akışı olan kardeş koşuya elle deploy `workflow_dispatch` ile gider.
    deploy_java = Run(
        tetik="deploy", ortam={"platform": "web", "dil": "java", "dispatch": "deploy"}
    )
    assert service._olaylar(deploy_java) == ("workflow_dispatch",)
    assert service._olaylar(Run(tetik="deploy", ortam={"dispatch": "deploy"})) == (
        "repository_dispatch",
    )
