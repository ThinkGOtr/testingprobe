# ruff: noqa: E501  (gerçek Surefire XML fikstürleri tek satırda öznitelik taşır)
"""Yerel CI'ın platform boyutu (009 §2.9, Ş6b): `enqueue_ci(script_id)` platformu script'ten
alır, `ci.run` toolchain `/check`'e `lang=java` + `platform` gönderir, Java raporu (JSON'suz,
Surefire'dan birleşik `run.junit`) alınır; GitHub kipinde platformun iş akışı ve artefaktı."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.unit.features.ci.helpers import SHA, UZAK_KOK, FakeToolchain, login, run_jobs
from tp_core.features.ci import clients, enqueue_ci, service
from tp_core.features.ci.parse import java_test_kimligi, surefire_ayristir
from tp_core.models import Run, Script, TestResult

pytestmark = pytest.mark.usefixtures("ci_env")

FQCN = "com.antreklabs.bayi.uretilen.TPD1AndroidC2_0a1b2c3dTest"
DOSYA = "src/test/java/com/antreklabs/bayi/uretilen/TPD1AndroidC2_0a1b2c3dTest.java"
JUNIT = f"""<?xml version='1.0' encoding='utf-8'?>
<testsuites name="e2e-app"><testsuite name="e2e-app" tests="2">
<testcase classname="com.antreklabs.bayi.testler.GirisTesti" name="girisYap" time="3.5" />
<testcase classname="{FQCN}" name="senaryo" time="8">
<failure type="java.lang.AssertionError" message="'cart-total' metni: beklenen &lt;150,00 TL&gt;, görülen &lt;175,00 TL&gt; (10000 ms)">x</failure>
</testcase></testsuite></testsuites>
""".encode()


def _script(engine: Engine, platform: str) -> uuid.UUID:
    sid = uuid.uuid4()
    with Session(engine) as s, s.begin():
        s.add(Script(id=sid, tur="test", dosya_yolu=f"e2e-app/{DOSYA}", platform=platform))
    return sid


EXTENT_HTML = "<html><head><title>Extent</title></head><body>Extent raporu</body></html>"


def _java_yaniti(kok: Path, platform: str = "android", kirmizi: Any = None, raporlar: bool = False):
    """`raporlar`: test-runner'ın Java koşusunda bıraktığı Maven `target/` düzeni (Extent + Allure
    raporu, derleme çıktısı) diske yazılır ve `run.reports` ile bildirilir."""

    def yanit(body: dict[str, Any]) -> httpx.Response:
        run_dir = body["run_id"]
        yerel = kok / "runs" / run_dir
        (yerel / "results").mkdir(parents=True)
        (yerel / "results" / "junit.xml").write_bytes(JUNIT)
        uzak_target = f"{UZAK_KOK}/runs/{run_dir}/src/e2e-app/target"
        ek: dict[str, Any] = {}
        if raporlar:
            target = yerel / "src" / "e2e-app" / "target"
            for dizin, icerik in (
                ("extent-report", EXTENT_HTML),
                ("allure-report", "<html>A</html>"),
            ):
                (target / dizin).mkdir(parents=True)
                (target / dizin / "index.html").write_text(icerik, encoding="utf-8")
            (target / "extent-report" / "extent.json").write_text("[]")
            (target / "allure-results").mkdir()
            (target / "allure-results" / "x-result.json").write_text("{}")
            (target / "classes").mkdir()
            (target / "classes" / "Gizli.class").write_bytes(b"\xca\xfe")
            (target / "surefire-reports").mkdir()
            (target / "surefire-reports" / "TEST-TestSuite.xml").write_bytes(JUNIT)
            ek = {
                "allure_dir": f"{uzak_target}/allure-results",
                "reports": {
                    ad: {"path": f"{uzak_target}/{dizin}", "rel": "", "exists": True}
                    for ad, dizin in (
                        ("allure_html", "allure-report"),
                        ("extent_html", "extent-report"),
                    )
                },
            }
        (kok / "checks").mkdir(exist_ok=True)
        (kok / "checks" / f"{body['sha']}.json").write_text(
            json.dumps(
                {
                    "checks": [
                        {"name": "local-ci", "status": "completed", "conclusion": "success"},
                        {
                            "name": f"local-ci-{platform}",
                            "status": "completed",
                            "conclusion": "failure",
                        },
                    ]
                }
            )
        )
        uzak = f"{UZAK_KOK}/runs/{run_dir}"
        return httpx.Response(
            200,
            json={
                "sha": body["sha"],
                "lang": "java",
                "platform": platform,
                "check_name": f"local-ci-{platform}",
                "conclusion": "failure",
                "failed_steps": ["run"],
                "summary": "Yerel CI başarısız: run",
                "app": {"ok": True},
                "deps": {"ok": True},
                "guard": {"ok": True, "mode": "pr"},
                "compile": {"ok": True},
                "run": {
                    "run_id": run_dir,
                    "lang": "java",
                    "platform": platform,
                    "status": "failed",
                    "artifacts_dir": uzak,
                    "artifacts_rel": f"runs/{run_dir}",
                    "junit": f"{uzak}/results/junit.xml",
                    "json": None,
                    "html_dir": None,
                    "log": f"{uzak}/runner.log",
                    "saglik": {"ok": True},
                    "kirmizi_denetimi": kirmizi,
                    **ek,
                },
                "duration_ms": 30000,
            },
        )

    return yanit


def test_enqueue_platformu_scriptten_ve_check_govdesi_java(
    engine: Engine, toolchain: FakeToolchain, artefakt_kok: Path
) -> None:
    sid = _script(engine, "android")
    toolchain.yanit = _java_yaniti(artefakt_kok)
    with Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "pr", 7, script_id=sid)
    with Session(engine) as s:
        assert s.get(Run, rid).ortam["platform"] == "android"
    run_jobs(engine)
    body = toolchain.istekler[0]
    # Tam kapsamlı Java koşusu → toolchain `local-ci-android` kaydını yazar.
    assert body["lang"] == "java" and body["platform"] == "android"
    assert body["test_files"] == [] and body["repeat_each"] == 1
    with Session(engine) as s:
        run = s.get(Run, rid)
        assert run.sonuc == "failed"
        assert (run.ortam["platform"], run.ortam["lang"], run.ortam["ast_guard_mode"]) == (
            "android",
            "java",
            "pr",
        )
        a = run.artefaktlar
        assert set(a["adimlar"]) == {"app", "deps", "guard", "compile", "run"}
        # Koşunun kendi kontrolü local-ci-android (web local-ci değil).
        assert (a["checks"]["durum"], a["checks"]["conclusion"]) == ("completed", "failure")
        assert a["raporlar"] == {"junit": True, "json": False}
        assert set(a["checks"]["platformlar"]) == {"local-ci", "local-ci-android"}
        assert a["checks"]["platformlar"]["local-ci-android"]["details_url"] is None
        # Koşu listesi / Kontrol Kulesi platformu taşır.
        assert service.serialize_runs(s, [run])[0]["platform"] == "android"
        assert not any("results.json" in u for u in a["uyarilar"])
        satirlar = {
            r.test_adi: r for r in s.scalars(select(TestResult).where(TestResult.run_id == rid))
        }
    assert set(satirlar) == {"GirisTesti › girisYap", "TPD1AndroidC2_0a1b2c3dTest › senaryo"}
    kirmizi = satirlar["TPD1AndroidC2_0a1b2c3dTest › senaryo"]
    assert (kirmizi.dosya, kirmizi.sonuc) == (DOSYA, "failed")


def test_java_kosusunun_extent_raporu_allure_yaninda_sunulur(
    api: TestClient, make_user, engine: Engine, toolchain: FakeToolchain, artefakt_kok: Path
) -> None:
    """Java koşusu raporları Maven `target/` altına yazar: Extent raporu `extent_url` ile bildirilir
    ve sandbox'lı, oturumlu artefakt ucundan açılır; `target/`'ın geri kalanı sunulmaz."""
    sid = _script(engine, "android")
    toolchain.yanit = _java_yaniti(artefakt_kok, raporlar=True)
    with Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "pr", 7, script_id=sid)
    run_jobs(engine)
    with Session(engine) as s:
        assert s.get(Run, rid).artefaktlar["extent_html"] == (
            "src/e2e-app/target/extent-report/index.html"
        )
    temel = f"/artifacts/runs/{rid}"
    assert api.get(f"{temel}/src/e2e-app/target/extent-report/index.html").status_code == 401
    login(api, make_user("analyst"))
    k = next(x for x in api.get("/runs").json() if x["id"] == str(rid))
    assert k["extent_url"] == f"/api{temel}/src/e2e-app/target/extent-report/index.html"
    assert k["allure_url"] == f"/api{temel}/src/e2e-app/target/allure-report/index.html"
    assert k["allure_rapor"] is True
    rapor = api.get(k["extent_url"].removeprefix("/api"))
    assert rapor.status_code == 200 and rapor.headers["content-type"].startswith("text/html")
    # Rapor tek dosyadır ve depo kullanmaz: içerik değişmeden (şimsiz) sunulur, opak kökende çalışır.
    assert rapor.text == EXTENT_HTML
    csp = rapor.headers["content-security-policy"]
    assert csp.startswith("sandbox ") and "allow-scripts" in csp
    assert "allow-same-origin" not in csp
    assert rapor.headers["x-content-type-options"] == "nosniff"
    assert api.get(k["allure_url"].removeprefix("/api")).status_code == 200
    assert api.get(k["allure_sonuclari_url"].removeprefix("/api")).json()["dosyalar"] == [
        {"ad": "x-result.json", "dizin": False, "boyut": 2}
    ]
    # `target/`'ın tamamı açılmaz: yalnızca rapor dizinleri (derleme çıktısı, kaynak, Surefire yok).
    for yol in (
        "src/e2e-app/target/classes/Gizli.class",
        "src/e2e-app/target/surefire-reports/TEST-TestSuite.xml",
        "src/e2e-app/target",
        "src/e2e-app/extent-report/index.html",
        "target/extent-report/index.html",
        "src/e2e-app/target/extent-report/../classes/Gizli.class",
    ):
        assert api.get(f"{temel}/{yol}").status_code in (400, 404), yol
    assert api.get(f"{temel}/src/e2e-app/target/classes/Gizli.class").status_code == 400


def test_extent_raporu_uretilmediyse_baglanti_yok(
    engine: Engine, toolchain: FakeToolchain, artefakt_kok: Path
) -> None:
    """Dinleyicisi olmayan eski commit / raporsuz koşu: `extent_url` null, anahtar yazılmaz."""
    sid = _script(engine, "android")
    toolchain.yanit = _java_yaniti(artefakt_kok)
    with Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "pr", 7, script_id=sid)
    run_jobs(engine)
    with Session(engine) as s:
        run = s.get(Run, rid)
        assert "extent_html" not in run.artefaktlar
        assert service.serialize_runs(s, [run])[0]["extent_url"] is None


def test_izinli_mi_target_rapor_dizinleri() -> None:
    from tp_core.features.ci.artifacts import izinli_mi

    for yol in (
        "src/e2e-app/target/extent-report/index.html",
        "src/e2e-app/target/extent-report",
        "src/e2e-app/target/allure-report/index.html",
        "src/e2e-app/target/allure-results/a-result.json",
        "src/demo-app/e2e-app/target/extent-report/index.html",
        "src/e2e/results/junit.xml",
        "run.json",
    ):
        assert izinli_mi(tuple(yol.split("/"))), yol
    for yol in (
        "src/e2e-app/target/classes/A.class",
        "src/e2e-app/target/test-classes/extent-report",
        "src/e2e-app/target",
        "src/e2e-app/extent-report/index.html",
        "src/extent-report/target/index.html",
        "target/extent-report/index.html",
        "extent-report/index.html",
        "src/e2e-app/src/test/java/A.java",
    ):
        assert not izinli_mi(tuple(yol.split("/"))), yol


def test_izinli_mi_target_kanit_yalniz_goruntu() -> None:
    """O-1: Extent'in göreli `../kanit/tekrar-N/<Sınıf>.<metot>/ekran.png` bağlantıları sunulur;
    aynı dizindeki trace / sayfa dökümü (hassas olabilir) sunulmaz."""
    from tp_core.features.ci.artifacts import izinli_mi

    for yol in (
        "src/e2e-java/target/kanit/tekrar-1/LoginTest.girisYapar/ekran.png",
        "src/demo-app/e2e-java/target/kanit/tekrar-2/A.b/ekran.PNG",
        "src/e2e-app/target/kanit/tekrar-1/A.b/ekran.jpg",
        "src/e2e-app/target/kanit/x.jpeg",
    ):
        assert izinli_mi(tuple(yol.split("/"))), yol
    for yol in (
        "src/e2e-java/target/kanit/tekrar-1/LoginTest.girisYapar/trace.zip",
        "src/e2e-java/target/kanit/tekrar-1/LoginTest.girisYapar/sayfa.html",
        "src/e2e-java/target/kanit/tekrar-1/LoginTest.girisYapar",
        "src/e2e-java/target/kanit",
        "src/e2e-java/kanit/tekrar-1/A.b/ekran.png",
        "src/e2e-java/target/classes/kanit.png",
        "target/kanit/a.png",
    ):
        assert not izinli_mi(tuple(yol.split("/"))), yol


def test_serialize_runs_platformu_eski_kayitta_scriptten(engine: Engine) -> None:
    sid = _script(engine, "ios")
    with Session(engine) as s, s.begin():
        eski = Run(id=uuid.uuid4(), script_id=sid, commit=SHA, kaynak="local", tetik="push",
                   sonuc="passed", ortam={}, artefaktlar={})  # fmt: skip
        web = Run(id=uuid.uuid4(), commit=SHA, kaynak="local", tetik="push", sonuc="passed",
                  ortam={}, artefaktlar={})  # fmt: skip
        s.add_all([eski, web])
        s.flush()
        assert [k["platform"] for k in service.serialize_runs(s, [eski, web])] == ["ios", "web"]


def test_web_scripti_ve_scriptsiz_koşu_govdesi_degismez(
    engine: Engine, toolchain: FakeToolchain
) -> None:
    sid = _script(engine, "web")
    with Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "pr", 9, script_id=sid)
        rid2 = enqueue_ci(s, SHA, "push")
    with Session(engine) as s:
        assert s.get(Run, rid).ortam["platform"] == "web"
        assert s.get(Run, rid2).ortam["platform"] == "web"
    run_jobs(engine)
    assert all("lang" not in b and "platform" not in b for b in toolchain.istekler)


def test_ayni_committe_web_ve_uygulama_kosulari_birbirini_yutmaz(engine: Engine) -> None:
    sid = _script(engine, "android")
    with Session(engine) as s, s.begin():
        web = enqueue_ci(s, SHA, "push")
        android = enqueue_ci(s, SHA, "push", script_id=sid)
        android2 = enqueue_ci(s, SHA, "push", script_id=sid)
        web2 = enqueue_ci(s, SHA, "push")
    assert web != android and android == android2 and web == web2


def test_kirmizi_denetimi_kirpilarak_kosuya_yazilir(
    engine: Engine, toolchain: FakeToolchain, artefakt_kok: Path
) -> None:
    sid = _script(engine, "android")
    toolchain.yanit = _java_yaniti(
        artefakt_kok, kirmizi={"ok": "evet", "kirmizi": ["x" * 500], "kotu": "bozuk"}
    )
    with Session(engine) as s, s.begin():
        rid = enqueue_ci(s, SHA, "pr", 11, script_id=sid)
    run_jobs(engine)
    with Session(engine) as s:
        kd = s.get(Run, rid).artefaktlar["kirmizi_denetimi"]
    assert kd["ok"] is False and kd["kotu"] == [] and len(kd["kirmizi"][0]) <= 201


def test_java_test_kimligi() -> None:
    assert java_test_kimligi(FQCN, "senaryo") == (
        DOSYA,
        "TPD1AndroidC2_0a1b2c3dTest › senaryo",
    )
    # İç sınıf ve varsayılan paket: test-runner (`surefire._src_file` + `simple`) ile aynı.
    assert java_test_kimligi("a.b.Dis$Ic", "m") == ("src/test/java/a/b/Dis.java", "Dis$Ic › m")
    assert java_test_kimligi("Paketsiz", "m") == ("src/test/java/Paketsiz.java", "Paketsiz › m")
    assert java_test_kimligi(FQCN, "TPD1AndroidC2_0a1b2c3dTest › senaryo")[1].count("›") == 1
    assert java_test_kimligi("tests/generated/x.spec.ts", "t") == ("tests/generated/x.spec.ts", "t")
    assert java_test_kimligi(None, "t") == (None, "t")


# ------------------------------------------------------------------------------- GitHub kipi


def test_github_is_akisi_ve_artefakt_adi_platformdan() -> None:
    web = Run(ortam={"platform": "web"})
    eski = Run(ortam={})
    android = Run(ortam={"platform": "android"})
    windows = Run(ortam={"platform": "windows"})
    assert service.gh_is_akisi(web) == {} and service.gh_is_akisi(eski) == {}
    assert service.gh_is_akisi(android) == {"workflow": "mobil-android.yml"}
    assert service.gh_is_akisi(windows) == {"workflow": "masaustu-windows.yml"}
    assert service.gh_sonuc_artefakti(eski) == "test-local-results"
    assert service.gh_sonuc_artefakti(android) == "mobil-android-results"
    with pytest.raises(clients.GitHubCiError):
        clients._is_akisi("../../dispatches")


class _Forge:
    repo = "o/r"

    def __init__(self) -> None:
        self.istekler: list[tuple[str, str, Any]] = []

    def request(self, method: str, path: str, ne: str, **kw: Any) -> httpx.Response:
        self.istekler.append((method, path, kw))
        return httpx.Response(200, json={"workflow_runs": []}, request=httpx.Request(method, path))


def test_github_istemcisi_platform_is_akisina_gider() -> None:
    f = _Forge()
    gh = clients.GitHubCi(f)
    gh.workflow_runs(head_sha=SHA, event="pull_request")
    gh.workflow_runs(head_sha=SHA, event="pull_request", workflow="mobil-android.yml")
    gh.workflow_dispatch("main", {"tetik": "nightly"}, workflow="masaustu-windows.yml")
    yollar = [p for _m, p, _k in f.istekler]
    assert yollar == [
        "/repos/o/r/actions/workflows/ci.yml/runs",
        "/repos/o/r/actions/workflows/mobil-android.yml/runs",
        "/repos/o/r/actions/workflows/masaustu-windows.yml/dispatches",
    ]


def test_surefire_artefakti_ayristirilir() -> None:
    xml = JUNIT.replace(b"<testsuites", b"<testsuites").replace(b"e2e-app", b"TestSuite")
    bozuk = b"<!DOCTYPE x [<!ENTITY a 'b'>]><testsuite/>"
    birim = JUNIT.replace(FQCN.encode(), b"com.antreklabs.bayi.birim.KimlikBirimTesti")
    ayr = surefire_ayristir(
        {
            "tp-results/surefire-reports/TEST-TestSuite.xml": xml,
            "tp-results/surefire-reports/TEST-Kotu\x1b[31m.xml": bozuk,
            # Cihazsız birim testleri cihaz koşusu sayılmaz.
            "tp-results/birim-raporlari/TEST-Birim.xml": birim,
            "tp-results/ci-meta.json": b"{}",
        }
    )
    adlar = {t.test_adi: t for t in ayr.testler}
    assert set(adlar) == {"GirisTesti › girisYap", "TPD1AndroidC2_0a1b2c3dTest › senaryo"}
    assert adlar["TPD1AndroidC2_0a1b2c3dTest › senaryo"].dosya == DOSYA
    assert any("TEST-Kotu" in u and "\x1b" not in u for u in ayr.uyarilar)
    assert ayr.raporlar == {"junit": True, "json": False}
    assert "Surefire" in surefire_ayristir({}).uyarilar[0]


def test_github_alimi_uygulama_artefaktindan(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`github_ingest`: uygulama koşusu `<job>-results` zip'indeki TEST-*.xml'leri okur."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("surefire-reports/TEST-TestSuite.xml", JUNIT)
        z.writestr("birim-raporlari/TEST-Birim.xml", JUNIT.replace(b"GirisTesti", b"BirimTesti"))
        z.writestr("ci-meta.json", json.dumps({"platform": "android", "sha": SHA}))

    class _Gh:
        def artifacts(self, _rid: Any) -> list[dict[str, Any]]:
            return [{"id": 5, "name": "mobil-android-results", "size_in_bytes": 10}]

        def jobs(self, _rid: Any) -> list[dict[str, Any]]:
            return [{"name": "mobil-android", "conclusion": "failure"}]

        def artifact_zip(self, art: Any) -> bytes:
            assert art["name"] == "mobil-android-results"
            return buf.getvalue()

    from tp_core.features.ci import services

    sid = _script(engine, "android")
    with services.override(github=lambda: _Gh()), Session(engine) as s, s.begin():
        run = Run(
            id=uuid.uuid4(),
            script_id=sid,
            pr_no=3,
            commit=SHA,
            kaynak="github",
            tetik="pr",
            sonuc="running",
            ortam={"platform": "android"},
            artefaktlar={},
        )
        s.add(run)
        s.flush()
        sonuc = service.github_ingest(
            s, run, {"id": 77, "conclusion": "failure", "head_sha": SHA, "html_url": None}
        )
        assert sonuc == "failed"
        satirlar = s.scalars(select(TestResult).where(TestResult.run_id == run.id)).all()
        assert {r.test_adi for r in satirlar} == {
            "GirisTesti › girisYap",
            "TPD1AndroidC2_0a1b2c3dTest › senaryo",
        }


def test_gh_dizin_ve_url_yolu_fullmatch() -> None:
    """Kalıntı (GÜV-Y7 devamı): `GH_DIR_RE` / `URL_PATH_RE` sondaki satır sonunu kabul etmez."""
    from tp_core.features.ci import github_artifacts
    from tp_core.features.triage import evidence

    assert github_artifacts.yol("gh/12-1\n") is None
    assert github_artifacts.GH_DIR_RE.fullmatch("gh/12-1")
    assert evidence._url_yolu("https://x.test/a/b") == "/a/b"
    assert evidence.URL_PATH_RE.fullmatch("/a/b\n") is None
