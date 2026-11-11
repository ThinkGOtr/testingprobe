# ruff: noqa: E501  (Surefire XML fikstürleri gerçek tek satırlık mesajlar içerir)
"""test-runner Java yolu (009 §2.7, Ş8): Maven + Appium koşusu, Surefire özeti, platform kapısı.

Maven sahte bir betikle taklit edilir: argv/ortamı kaydeder ve `-Draporlar.dizini`'ne verilen
Surefire JUnit XML'ini, `-Dkanit.dizini`'ne kanıt dosyalarını yazar. Appium `/status` ve demo API
`/health` sahte HTTP sunucusudur (tests/test_runner.py DemoApi).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from runner import surefire
from runner.app import app
from tests.conftest import TOOLCHAIN, Forge, make_fake_node
from tests.test_runner import DemoApi
from worker import check as checks

TRUSTED_POM = TOOLCHAIN / "e2e-app-deps" / "pom.xml"
GEN = "src/test/java/com/antreklabs/bayi/uretilen/DEMO12C1_ab12cd34Test.java"

XML_PASSED = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="TestSuite" tests="2" failures="0" errors="0" skipped="0">
  <properties><property name="java.version" value="17"/></properties>
  <testcase name="girisYap" classname="com.antreklabs.bayi.testler.GirisTesti" time="3.5"/>
  <testcase name="senaryo" classname="com.antreklabs.bayi.uretilen.DEMO12C1_ab12cd34Test"
            time="4.25"/>
</testsuite>
"""

TRACE_EKRAN = (
    "\n\tat com.antreklabs.bayi.altyapi.Bekle.dogrula(Bekle.java:76)"
    "\n\tat com.antreklabs.bayi.ekranlar.SepetEkrani.dogrulaToplam(SepetEkrani.java:45)"
    "\n\tat com.antreklabs.bayi.testler.SepetTesti.kampanya(SepetTesti.java:30)"
    "\n\tat org.testng.internal.Invoker.invoke(Invoker.java:10)"
)
XML_FAILED = f"""<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="TestSuite" tests="4" failures="1" errors="2" skipped="1">
  <testcase name="kampanya" classname="com.antreklabs.bayi.testler.SepetTesti" time="5">
    <failure type="java.lang.AssertionError"
             message="'cart-total' metni: beklenen &lt;1.250,00 TL&gt;, görülen &lt;1.375,00 TL&gt; (10000 ms)">java.lang.AssertionError: 'cart-total' metni{TRACE_EKRAN}</failure>
  </testcase>
  <testcase name="ekle" classname="com.antreklabs.bayi.testler.SepetTesti" time="11">
    <error type="org.openqa.selenium.TimeoutException"
           message="Expected condition failed: öğe görünmedi: kimlik 'product-card-P-001' içinde 'add-to-cart' (tried for 10 second(s) with 250 milliseconds interval)">trace</error>
  </testcase>
  <testcase name="hazirlik" classname="com.antreklabs.bayi.testler.GirisTesti" time="1">
    <error type="java.lang.IllegalStateException" message="POST /test/reset başarısız: 500">x</error>
  </testcase>
  <testcase name="atla" classname="com.antreklabs.bayi.testler.GirisTesti" time="0">
    <skipped message="TP_E2E_NO_RESET=1"/>
  </testcase>
</testsuite>
"""


def fake_mvn(tmp_path: Path, xml: str | None, exit_code: int = 0, extent: bool = True) -> Path:
    """`mvn` yerine: argv/ortamı kaydeder, raporu ve (başarısızlıkta) kanıtı yazar. `extent`:
    e2e-app'in Extent dinleyicisi gibi `extent.rapor.dizini/index.html` yazar (tekrarlar eklenir)."""
    return make_fake_node(
        tmp_path,
        f"""
        args = sys.argv[1:]
        props = dict(a[2:].split("=", 1) for a in args if a.startswith("-D") and "=" in a)
        log = pathlib.Path({str(tmp_path / "mvn.log")!r})
        keys = ("PLATFORM", "APPIUM_URL", "APP_ID", "APP_ACTIVITY", "DEMO_API_URL",
                "DEMOAPP_TEST_TOKEN", "BREAK_CAMPAIGN", "MAVEN_SKIP_RC", "MAVEN_OPTS",
                "JAVA_TOOL_OPTIONS", "ANTHROPIC_API_KEY", "TP_RUN_ID", "CI")
        with log.open("a") as fh:
            fh.write(json.dumps({{"argv": args, "cwd": os.getcwd(),
                                  "env": {{k: os.environ.get(k) for k in keys}}}}) + "\\n")
        xml = {xml!r}
        if xml is not None and "surefire:test" in args:
            rd = pathlib.Path(props["raporlar.dizini"]); rd.mkdir(parents=True, exist_ok=True)
            (rd / "TEST-TestSuite.xml").write_text(xml, encoding="utf-8")
            kd = pathlib.Path(props["kanit.dizini"]) / "SepetTesti.kampanya"
            kd.mkdir(parents=True, exist_ok=True)
            (kd / "ekran.png").write_bytes(b"png")
            (kd / "sayfa-kaynagi.xml").write_text("<hierarchy/>")
            if {extent!r}:
                ed = pathlib.Path(props["extent.rapor.dizini"]); ed.mkdir(parents=True, exist_ok=True)
                with (ed / "index.html").open("a", encoding="utf-8") as fh:
                    fh.write("<html>Extent " + props.get("extent.tekrar", "tek") + "</html>")
        sys.exit({exit_code})
        """,
        name=f"fake-mvn-{exit_code}-{int(extent)}",
    )


def mvn_calls(tmp_path: Path) -> list[dict[str, Any]]:
    log = tmp_path / "mvn.log"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


def e2e_app_files(pom: str | None = None) -> dict[str, str]:
    return {
        "e2e-app/pom.xml": pom if pom is not None else TRUSTED_POM.read_text(encoding="utf-8"),
        f"e2e-app/{GEN}": "class DEMO12C1_ab12cd34Test {}\n",
    }


@pytest.fixture
def java_runner(env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    api = DemoApi()
    deps = tmp_path / "e2e-app-deps"
    (deps / "m2").mkdir(parents=True)
    (deps / "pom.xml").write_text(TRUSTED_POM.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("TP_E2E_APP_DEPS", str(deps))
    monkeypatch.setenv("DEMO_API_URL", api.url)
    monkeypatch.setenv("APPIUM_URL_ANDROID", f"{api.url}/appium")
    monkeypatch.setenv("TP_HEALTH_TIMEOUT_S", "2")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sızmamalı")
    monkeypatch.setenv("MAVEN_OPTS", "-javaagent:/kotu.jar")
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "-javaagent:/kotu.jar")
    for k in ("TP_APP_ID_ANDROID", "TP_APP_PATH_ANDROID", "TP_APP_ACTIVITY_ANDROID"):
        monkeypatch.delenv(k, raising=False)
    yield api
    api.server.shutdown()


def _run(**body: Any) -> Any:
    return TestClient(app).post(
        "/run", json={"run_id": "j1", "lang": "java", "platform": "android", **body}
    )


def test_java_run_passed_hardening_and_layout(
    java_runner: DemoApi, forge: Forge, env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_MVN", str(fake_mvn(tmp_path, XML_PASSED)))
    head = forge.commit("tp/case-j", e2e_app_files())
    resp = _run(sha=head, test_files=[GEN])
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "passed", data["error"]
    assert data["lang"] == "java" and data["platform"] == "android"
    assert data["stats"] == {
        "expected": 2, "unexpected": 0, "flaky": 0, "skipped": 0, "duration_ms": 7750,
    }  # fmt: skip
    titles = [t["title"] for t in data["tests"]]
    assert titles == ["GirisTesti › girisYap", "DEMO12C1_ab12cd34Test › senaryo"]
    assert data["tests"][1]["file"] == GEN and data["tests"][1]["project"] == "android"
    # Sağlık: demo API + Appium /status
    assert java_runner.gets == ["/health", "/appium/status"]
    assert data["saglik"]["ok"] is True and data["saglik"]["appium"]["status"] == 200
    # Tek, temiz junit.xml (koşu dizininde; <properties> taşınmaz) — core JUnit girdisi.
    run_dir = env / "runs" / "j1"
    junit = Path(data["junit"])
    assert junit == run_dir / "results" / "junit.xml"
    text = junit.read_text()
    assert "<testsuites" in text and "java.version" not in text and text.count("<testcase") == 2
    assert data["json"] is None
    # Koşan kodun kopyası kanıt olarak kalır.
    assert (run_dir / "src" / "e2e-app" / GEN).is_file()
    (call,) = mvn_calls(tmp_path)
    argv = call["argv"]
    assert argv[0:4] == ["-B", "-o", "-ntp", "-f"]
    assert "-Dplatform=android" in argv and "-Dmaven.compiler.proc=none" in argv
    assert f"-Dtest={GEN.removeprefix('src/test/java/')}" in argv
    assert argv[-2:] == ["test-compile", "surefire:test"]
    assert any(a.startswith("-Dmaven.repo.local.tail=") for a in argv)
    assert call["cwd"] == str(run_dir / "src" / "e2e-app")
    # Extent raporu: dinleyici koşu dizinindeki target/extent-report'a yazar; tek koşuda tekrar
    # etiketi verilmez. Rapor `reports.extent_html` ile bildirilir (Allure ile aynı biçim).
    extent_dir = run_dir / "src" / "e2e-app" / "target" / "extent-report"
    assert f"-Dextent.rapor.dizini={extent_dir}" in argv
    assert not any(a.startswith("-Dextent.tekrar=") for a in argv)
    assert data["reports"]["extent_html"] == {
        "path": str(extent_dir),
        "rel": "runs/j1/src/e2e-app/target/extent-report",
        "exists": True,
    }
    assert (extent_dir / "index.html").read_text() == "<html>Extent tek</html>"
    assert call["env"] == {
        "PLATFORM": "android",
        "APPIUM_URL": f"{java_runner.url}/appium",
        "APP_ID": "com.antreklabs.bayisiparis",
        "APP_ACTIVITY": ".MainActivity",
        "DEMO_API_URL": java_runner.url,
        "DEMOAPP_TEST_TOKEN": "test-belirteci",
        "BREAK_CAMPAIGN": "",
        "MAVEN_SKIP_RC": "1",
        "MAVEN_OPTS": None,
        "JAVA_TOOL_OPTIONS": None,
        "ANTHROPIC_API_KEY": None,
        "TP_RUN_ID": "j1",
        "CI": "1",
    }


def test_java_run_failures_classified_and_break_restored(
    java_runner: DemoApi, forge: Forge, env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_MVN", str(fake_mvn(tmp_path, XML_FAILED, exit_code=1)))
    head = forge.commit("tp/case-k", e2e_app_files())
    data = _run(sha=head, env={"BREAK_CAMPAIGN": "1"}, keep=True).json()
    assert data["status"] == "failed"
    assert data["stats"]["unexpected"] == 3 and data["stats"]["skipped"] == 1
    by = {t["title"]: t for t in data["tests"]}
    a = by["SepetTesti › kampanya"]["failure"]
    assert a["type"] == "assertion"
    assert (a["expected"], a["received"], a["timeout_ms"]) == ("1.250,00 TL", "1.375,00 TL", 10000)
    assert a["locator_test_id"] == "cart-total"
    assert a["page_location"] == {
        "file": "src/test/java/com/antreklabs/bayi/ekranlar/SepetEkrani.java",
        "line": 45,
        "column": 0,
    }
    assert a["test_location"]["file"].endswith("testler/SepetTesti.java")
    assert a["evidence"]["screenshot"]["exists"] is True
    assert (
        a["page_source_rel"]
        == "runs/j1/src/e2e-app/target/kanit/SepetTesti.kampanya/sayfa-kaynagi.xml"
    )
    t = by["SepetTesti › ekle"]["failure"]
    assert t["type"] == "locator_not_found"
    assert (t["locator_test_id"], t["locator_scope_test_id"]) == (
        "add-to-cart",
        "product-card-P-001",
    )
    assert by["GirisTesti › hazirlik"]["failure"]["type"] == "test_data"
    assert by["GirisTesti › atla"]["status"] == "skipped"
    assert len(data["failures"]) == 3
    # Kırılma her bayi için geri alındı (web yoluyla aynı).
    assert [c["body"] for c in java_runner.calls] == [
        {"kullanici_adi": "bayi1", "kampanya": False},
        {"kullanici_adi": "bayi2", "kampanya": False},
    ]
    assert data["break_restore"]["ok"] is True
    # KirmiziDenetimi kuralı: assertion dışı kırmızı (locator, kurulum) ve atlanan test → geçmez.
    red = data["kirmizi_denetimi"]
    assert red["ok"] is False and red["kirmizi"] == ["SepetTesti › kampanya"]
    assert len(red["kotu"]) == 3
    (call,) = mvn_calls(tmp_path)
    assert call["env"]["BREAK_CAMPAIGN"] == "1"
    assert not any(a.startswith("-Dtest=") for a in call["argv"])  # tam kapsam: testng.xml
    assert (env / "runs" / "j1" / ".keep").is_file()


def test_java_run_repeat_each(
    java_runner: DemoApi, forge: Forge, env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_MVN", str(fake_mvn(tmp_path, XML_PASSED)))
    head = forge.commit("tp/case-r", e2e_app_files())
    data = _run(sha=head, test_files=[GEN], repeat_each=3).json()
    assert data["status"] == "passed"
    calls = mvn_calls(tmp_path)
    assert [c["argv"][-1] for c in calls] == ["surefire:test"] * 3
    assert "test-compile" in calls[0]["argv"] and "test-compile" not in calls[1]["argv"]
    assert [t["repeat_index"] for t in data["tests"]] == [0, 0, 1, 1, 2, 2]
    assert data["failure_groups"] == []
    # Extent: tekrarlar AYNI rapor dizinine yazar (dinleyici birleştirir), her biri etiketiyle.
    extent_dir = env / "runs" / "j1" / "src" / "e2e-app" / "target" / "extent-report"
    for i, c in enumerate(calls):
        assert f"-Dextent.rapor.dizini={extent_dir}" in c["argv"]
        assert f"-Dextent.tekrar={i + 1}/3" in c["argv"]
    assert (extent_dir / "index.html").read_text().count("Extent ") == 3
    assert data["reports"]["extent_html"]["exists"] is True


def test_java_run_without_extent_report(
    java_runner: DemoApi, forge: Forge, env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dinleyicisi olmayan (eski) commit rapor yazmaz: koşu sonucu değişmez, bağlantı bildirilmez."""
    monkeypatch.setenv("TP_MVN", str(fake_mvn(tmp_path, XML_PASSED, extent=False)))
    head = forge.commit("tp/case-e", e2e_app_files())
    data = _run(sha=head, test_files=[GEN]).json()
    assert data["status"] == "passed", data["error"]
    assert data["reports"]["extent_html"]["exists"] is False
    assert data["reports"]["allure_html"]["exists"] is False


def test_java_run_environment_errors(
    java_runner: DemoApi, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_MVN", str(fake_mvn(tmp_path, XML_PASSED)))
    head = forge.commit("tp/case-e", e2e_app_files())
    # Appium adresi yok → koşu yapılmaz, sağlık hatası (environment).
    monkeypatch.setenv("APPIUM_URL_ANDROID", "")
    data = _run(sha=head).json()
    assert data["status"] == "error" and "APPIUM_URL_ANDROID" in data["error"]
    assert data["saglik"]["ok"] is False and mvn_calls(tmp_path) == []
    # Appium yanıt vermiyor (/status 503).
    monkeypatch.setenv("APPIUM_URL_ANDROID", f"{java_runner.url}/appium")
    java_runner.get_status["/appium/status"] = 503
    data = (
        TestClient(app)
        .post("/run", json={"run_id": "j2", "sha": head, "lang": "java", "platform": "android"})
        .json()
    )
    assert data["status"] == "error" and "appium" in data["error"]
    java_runner.get_status.clear()
    # Güvenilmeyen pom → Maven hiç çalışmaz.
    bad = forge.commit("tp/case-p", e2e_app_files(pom="<project/>"))
    data = (
        TestClient(app)
        .post("/run", json={"run_id": "j3", "sha": bad, "lang": "java", "platform": "android"})
        .json()
    )
    assert data["status"] == "error" and "pom.xml" in data["error"]
    assert mvn_calls(tmp_path) == []
    # Maven rapor üretmedi (derleme hatası) → error.
    monkeypatch.setenv("TP_MVN", str(fake_mvn(tmp_path, None, exit_code=1)))
    data = (
        TestClient(app)
        .post("/run", json={"run_id": "j4", "sha": head, "lang": "java", "platform": "android"})
        .json()
    )
    assert data["status"] == "error" and "Surefire raporu üretilmedi" in data["error"]


def test_run_body_lang_rules(env: Path) -> None:
    c = TestClient(app)
    for body in (
        {"lang": "java"},  # platform yok
        {"lang": "java", "platform": "android", "grep": "kampanya"},
        {"lang": "java", "platform": "android", "workers": 1},
        {"lang": "java", "platform": "android", "test_files": ["tests/a.spec.ts"]},
        {"lang": "java", "platform": "web"},
        {"platform": "android"},  # lang=ts ile platform
        {"lang": "java", "platform": "android", "test_files": ["src/test/java/../x/YTest.java"]},
        {"lang": "kotlin"},
    ):
        resp = c.post("/run", json={"sha": "main", "run_id": "v1", **body})
        assert resp.status_code == 422, body
    # TS gövdesi aynen: Java test dosyası TS yolunda reddedilir.
    resp = c.post("/run", json={"sha": "main", "run_id": "v1", "test_files": [GEN]})
    assert resp.status_code == 422


def test_surefire_rejects_dtd(tmp_path: Path) -> None:
    rd = tmp_path / "r"
    rd.mkdir()
    (rd / "TEST-x.xml").write_text(
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><testsuite>&a;</testsuite>'
    )
    out = surefire.summarize([surefire.Repeat(0, rd, tmp_path / "k")], project="ios")
    assert out["tests"] == [] and "DTD" in out["errors"][0]


# ------------------------------------------------------------------ merge kapısı dosyası


def test_checks_document_keeps_other_platforms(tmp_path: Path) -> None:
    sha = "a" * 40
    path = tmp_path / f"{sha}.json"
    rep = {"conclusion": "success"}
    doc = checks.checks_document(sha, "completed", rep, "local-ci", existing=path)
    path.write_text(json.dumps(doc))
    doc = checks.checks_document(sha, "in_progress", None, "local-ci-android", existing=path)
    path.write_text(json.dumps(doc))
    doc = checks.checks_document(
        sha, "completed", {"conclusion": "failure"}, "local-ci-android", existing=path
    )
    assert [(c["name"], c["status"], c["conclusion"]) for c in doc["checks"]] == [
        ("local-ci", "completed", "success"),
        ("local-ci-android", "completed", "failure"),
    ]
    assert doc["reports"] == {"local-ci": rep, "local-ci-android": {"conclusion": "failure"}}
    # Web yeniden koşunca platform girdisi korunur; bozuk dosya yalnızca bu kontrolle yazılır.
    path.write_text(json.dumps(doc))
    doc = checks.checks_document(sha, "completed", rep, "local-ci", existing=path)
    assert [c["name"] for c in doc["checks"]] == ["local-ci", "local-ci-android"]
    path.write_text("{bozuk")
    doc = checks.checks_document(sha, "completed", rep, "local-ci-ios", existing=path)
    assert [c["name"] for c in doc["checks"]] == ["local-ci-ios"]


def test_check_names() -> None:
    assert checks.check_name("ts", None) == "local-ci"
    assert checks.check_name("java", "ios") == "local-ci-ios"
    with pytest.raises(ValueError):
        checks.check_name("java", None)
    req = checks.CheckRequest(sha="x", lang="java", platform=None)
    assert req.check_name is None and req.records_check() is False
    assert checks.CheckRequest(sha="x", lang="java", platform="windows").records_check() is True


def test_app_settings_windows_args_and_workdir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows: TP_APP_*_WINDOWS → e2e-app APP_PATH / APP_ARGS / APP_WORKDIR (NovaWindows
    appArguments / appWorkingDir); varsayılan uygulama kimliği yok, Android ayarı sızmaz."""
    import os

    from runner import java_run

    for k in list(os.environ):
        if k.startswith(("TP_APP_", "TP_DEVICE_", "TP_PLATFORM_VERSION_")):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TP_APP_PATH_WINDOWS", r"C:\tp\bayi\win-arm64\BayiSiparis.exe")
    monkeypatch.setenv("TP_APP_ARGS_WINDOWS", " --api-url http://192.168.64.1:18081/api ")
    monkeypatch.setenv("TP_APP_WORKDIR_WINDOWS", r"C:\tp\bayi\win-arm64")
    monkeypatch.setenv("TP_APP_ARGS_ANDROID", "--yanlis")
    assert java_run.app_settings("windows") == {
        "APP_PATH": r"C:\tp\bayi\win-arm64\BayiSiparis.exe",
        "APP_ARGS": "--api-url http://192.168.64.1:18081/api",
        "APP_WORKDIR": r"C:\tp\bayi\win-arm64",
    }
