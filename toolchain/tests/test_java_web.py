# ruff: noqa: E501  (Surefire XML fikstürleri gerçek tek satırlık sürücü mesajları içerir)
"""Web + Java hattı (011 §2.6): Playwright for Java + TestNG, `e2e-java` kökü.

- dil/platform çözümü ve gövde kuralları (`lang=java` + `platform=web` ya da platformsuz kabul;
  uygulama platformu bugünkü gibi `e2e-app`),
- toolchain-worker `/check` (`app → deps → guard → compile → run`, `local-ci` kaydı) ve
  `/symbols` (Java web kökü, kökü içeren önbellek anahtarı),
- test-runner Java web koşusu (Appium yok, web + API sağlık kontrolü, `repeat_each`, ortam,
  kanıt + rapor dizinleri), Playwright for Java hata sınıflandırması,
- güvenilir pom: `.playwright-version` ↔ Playwright for Java sürümü, e2e-app ile hizalı sürümler.

Maven sahte betiktir (tests/test_java.py, tests/test_runner_java.py ile aynı desen); gerçek
çevrimdışı derleme + tarayıcı açılışı imaj derlemesindeki duman testindedir (Dockerfile).
"""

from __future__ import annotations

import json
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from runner import java_run, surefire
from runner.app import RunBody
from runner.app import app as runner_app
from tests.conftest import TOOLCHAIN, Forge, make_fake_node
from tests.test_check import runner_client
from tests.test_java import GEN, KIMLIK, fixture_files, requires_jar
from tests.test_runner import DemoApi
from toolchain_common.settings import settings
from worker import app as worker_app
from worker import check as checks
from worker import java as javayol
from worker.app import CheckBody, SymbolsBody

REPO = TOOLCHAIN.parent
WEB_POM = TOOLCHAIN / "e2e-java-deps" / "pom.xml"
APP_POM = TOOLCHAIN / "e2e-app-deps" / "pom.xml"
DEMO_E2E_JAVA = REPO / "demo-app" / "e2e-java"
POM_NS = {"m": "http://maven.apache.org/POM/4.0.0"}


def web_files(drop: tuple[str, ...] = ()) -> dict[str, str]:
    """java-araclar fikstür ağacı `e2e-java/` altında, güvenilir web pom'uyla."""
    out = {}
    for path, text in fixture_files().items():
        rel = path.removeprefix("e2e-app/")
        if rel in drop:
            continue
        out[f"e2e-java/{rel}"] = WEB_POM.read_text(encoding="utf-8") if rel == "pom.xml" else text
    return out


def fake_mvn(tmp_path: Path, exit_code: int = 0) -> Path:
    return make_fake_node(
        tmp_path,
        f"""
        log = pathlib.Path({str(tmp_path / "mvn.log")!r})
        with log.open("a") as fh:
            fh.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd()}}) + "\\n")
        sys.exit({exit_code})
        """,
        name=f"fake-mvn-web-{exit_code}",
    )


def mvn_calls(tmp_path: Path) -> list[dict[str, Any]]:
    log = tmp_path / "mvn.log"
    return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []


@pytest.fixture
def web_env(env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """İmajdaki /opt/e2e-java (+ /opt/e2e-app) karşılıkları ve sahte mvn."""
    for name, pom in (("e2e-java-deps", WEB_POM), ("e2e-app-deps", APP_POM)):
        deps = tmp_path / name
        (deps / "m2").mkdir(parents=True)
        shutil.copy(pom, deps / "pom.xml")
    monkeypatch.setenv("TP_E2E_JAVA_DEPS", str(tmp_path / "e2e-java-deps"))
    monkeypatch.setenv("TP_E2E_APP_DEPS", str(tmp_path / "e2e-app-deps"))
    monkeypatch.setenv(
        "TP_JAVA_ARACLAR_JAR", str(TOOLCHAIN / "java-araclar/target/java-araclar.jar")
    )
    monkeypatch.setenv("TP_MVN", str(fake_mvn(tmp_path)))
    monkeypatch.delenv("TP_E2E_JAVA_ROOT", raising=False)
    worker_app._SYMBOL_CACHE.clear()
    return tmp_path


# ---------------------------------------------------------------- dil / platform / gövde


def test_resolve_lang_and_platform() -> None:
    assert javayol.resolve_lang("java", "web") == "java"
    assert javayol.resolve_lang("java", None) == "java"
    assert javayol.resolve_lang(None, "web") == "ts"  # varsayılan değişmedi
    assert javayol.resolve_platform("java", None) == "web"
    assert javayol.resolve_platform(None, None) == "web"
    assert javayol.resolve_platform("java", "ios") == "ios"
    for lang, platform in (("ts", "android"), ("csharp", "web"), ("python", None)):
        with pytest.raises(ValueError):
            javayol.resolve_lang(lang, platform)


def test_java_kok_by_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_E2E_JAVA_ROOT", "demo-app/e2e-java")
    monkeypatch.setenv("TP_E2E_APP_ROOT", "demo-app/e2e-app")
    cfg = settings()
    for platform in (None, "web"):
        kok = javayol.java_kok(cfg, platform)
        assert (kok.platform, kok.root, kok.web, kok.ad) == (
            "web", "demo-app/e2e-java", True, "e2e-java",
        )  # fmt: skip
        assert kok.m2 == Path("/opt/e2e-java/m2")
    kok = javayol.java_kok(cfg, "android")
    assert (kok.root, kok.web, kok.m2) == ("demo-app/e2e-app", False, Path("/opt/e2e-app/m2"))
    with pytest.raises(ValueError):
        javayol.java_kok(cfg, "symbian")


def test_worker_bodies_accept_web_java() -> None:
    for extra in ({"lang": "java"}, {"lang": "java", "platform": "web"}):
        b = CheckBody.model_validate({"sha": "main", "test_files": [GEN], **extra})
        assert (b.dil, b.hedef_platform, b.test_files) == ("java", "web", [GEN])
        s = SymbolsBody.model_validate({"sha": "main", **extra})
        assert (s.dil, s.hedef_platform) == ("java", "web")
    # Uygulama Java'sı aynen; TS web gövdesi aynen.
    b = CheckBody.model_validate({"sha": "main", "platform": "ios"})
    assert (b.dil, b.hedef_platform) == ("java", "ios")
    assert CheckBody.model_validate({"sha": "main", "platform": "web"}).dil == "ts"
    for bad in (
        {"lang": "csharp"},
        {"lang": "python", "platform": "web"},
        {"lang": "java", "platform": "web", "test_files": ["tests/a.spec.ts"]},
        {"lang": "java", "platform": "web", "grep": "x"},
        {"lang": "java", "affected_by": ["@diff"]},
    ):
        with pytest.raises(ValueError):
            CheckBody.model_validate({"sha": "main", **bad})


def test_runner_body_web_java() -> None:
    for extra in ({"lang": "java"}, {"lang": "java", "platform": "web"}):
        req = RunBody.model_validate(
            {"sha": "main", "run_id": "w1", "test_files": [GEN], **extra}
        ).to_request()
        assert (req.lang, req.platform, req.test_files) == ("java", "web", [GEN])
    # TS gövdesi: platform=web serbest, istek platformu değişmez.
    assert RunBody.model_validate({"sha": "main", "run_id": "w1", "platform": "web"}).lang == "ts"
    c = TestClient(runner_app)
    for bad in ({"lang": "csharp"}, {"lang": "java", "workers": 2}, {"platform": "ios"}):
        resp = c.post("/run", json={"sha": "main", "run_id": "w1", **bad})
        assert resp.status_code == 422, bad


def test_check_name_web_java_is_local_ci_web_java() -> None:
    """011 K-T1: web + Java kendi kaydını yazar (core `platform.check_adi` ile aynı)."""
    req = checks.CheckRequest(sha="x", lang="java", platform="web")
    assert req.check_name == "local-ci-web-java"
    assert checks.CheckRequest(sha="x", lang="ts", platform="web").check_name == "local-ci"
    assert checks.CheckRequest(sha="x", lang="java", platform="ios").check_name == "local-ci-ios"


def test_ts_and_java_checks_on_same_sha_do_not_overwrite(tmp_path: Path) -> None:
    """Aynı sha'nın TS ve Java kardeş koşuları `checks/<sha>.json`'da ayrı girdilerdir: sonra
    yazan öncekini ezmez (MİM-Y3)."""
    sha = "b" * 40
    path = tmp_path / f"{sha}.json"
    ts = {"conclusion": "success", "lang": "ts"}
    java = {"conclusion": "failure", "lang": "java", "platform": "web"}
    path.write_text(json.dumps(checks.checks_document(sha, "completed", ts, "local-ci")))
    doc = checks.checks_document(sha, "completed", java, "local-ci-web-java", existing=path)
    path.write_text(json.dumps(doc))
    doc = json.loads(path.read_text())
    assert [(c["name"], c["conclusion"]) for c in doc["checks"]] == [
        ("local-ci", "success"),
        ("local-ci-web-java", "failure"),
    ]
    assert doc["reports"]["local-ci"] == ts and doc["reports"]["local-ci-web-java"] == java
    # TS yeniden koşsa Java girdisi korunur.
    doc = checks.checks_document(sha, "in_progress", None, "local-ci", existing=path)
    assert [(c["name"], c["status"]) for c in doc["checks"]] == [
        ("local-ci", "in_progress"),
        ("local-ci-web-java", "completed"),
    ]


# ------------------------------------------------------------------ worker /check, /symbols


@requires_jar
def test_check_web_java_full_scope_records_local_ci_web_java(
    web_env: Path, forge: Forge, env: Path
) -> None:
    head = forge.commit("tp/web-java", web_files())
    client, calls = runner_client()
    report = checks.execute(
        settings(), checks.CheckRequest(sha=head, lang="java", platform="web"), runner_client=client
    )
    assert report["conclusion"] == "success", report
    assert report["lang"] == "java" and report["platform"] == "web"
    assert report["check_name"] == "local-ci-web-java" and report["check_recorded"] is True
    assert [report[s]["ok"] for s in javayol.STEPS] == [True] * len(javayol.STEPS)
    assert report["guard"]["report"]["root"] == "e2e-java"
    assert report["guard"]["report"]["files"] == [GEN]
    (mvn,) = mvn_calls(web_env)
    assert f"-Dmaven.repo.local.tail={web_env / 'e2e-java-deps' / 'm2'}" in mvn["argv"]
    assert mvn["argv"][-1] == "test-compile"
    (call,) = calls
    assert call["body"]["lang"] == "java" and call["body"]["platform"] == "web"
    doc = json.loads((env / "checks" / f"{head}.json").read_text())
    assert [c["name"] for c in doc["checks"]] == ["local-ci-web-java"]
    assert doc["checks"][0]["conclusion"] == "success"
    assert doc["reports"]["local-ci-web-java"]["platform"] == "web"


@requires_jar
def test_check_web_java_trusted_pom_and_root(web_env: Path, forge: Forge) -> None:
    # Web kökünde uygulama pom'u: güvenilir web kopyasıyla eşleşmez (yanlış kilit).
    files = web_files()
    files["e2e-java/pom.xml"] = APP_POM.read_text(encoding="utf-8")
    head = forge.commit("tp/web-pom", files)
    report = checks.execute(settings(), checks.CheckRequest(sha=head, lang="java", platform="web"))
    assert report["failed_steps"] == ["deps"]
    assert "e2e-java/pom.xml" in report["deps"]["error"]
    assert "toolchain/e2e-java-deps/pom.xml" in report["deps"]["error"]
    assert mvn_calls(web_env) == []
    # Uygulama platformu web kökünü değil e2e-app'i okur (bugünkü davranış).
    head = forge.commit("tp/web-only", web_files())
    with pytest.raises(Exception, match="e2e-app"):
        checks.execute(settings(), checks.CheckRequest(sha=head, lang="java", platform="android"))


@requires_jar
def test_check_web_java_guard_blocks_raw_page(web_env: Path, forge: Forge) -> None:
    files = web_files()
    files[f"e2e-java/{GEN}"] = files[f"e2e-java/{GEN}"].replace(
        'girisEkrani().girisYap("bayi2", "Demo123!");', 'page().navigate("/giris");'
    )
    head = forge.commit("tp/web-raw", files)
    client, calls = runner_client()
    report = checks.execute(
        settings(), checks.CheckRequest(sha=head, lang="java"), runner_client=client
    )
    assert report["failed_steps"] == ["guard"] and report["platform"] == "web"
    assert "raw_driver" in {v["code"] for v in report["guard"]["report"]["violations"]}
    assert mvn_calls(web_env) == [] and calls == []


@requires_jar
def test_symbols_web_java_cache_key_has_root(web_env: Path, forge: Forge) -> None:
    files = {
        **{f"e2e-app/{k.removeprefix('e2e-java/')}": v for k, v in web_files().items()},
        **web_files(drop=("src/test/java/com/antreklabs/bayi/ekranlar/SepetEkrani.java",)),
    }
    files["e2e-app/pom.xml"] = APP_POM.read_text(encoding="utf-8")
    head = forge.commit("tp/iki-proje", files)
    c = TestClient(worker_app.app)
    web = c.post("/symbols", json={"sha": head, "lang": "java"}).json()
    assert web["lang"] == "java" and web["platform"] == "web"
    assert "SepetEkrani" not in [p["class"] for p in web["page_objects"]]
    assert web["page_objects"][0]["locators"]["Giris.KULLANICI_ADI"]["file"] == KIMLIK
    # Aynı sha, uygulama projesi: ayrı önbellek girdisi, platform alanı yok (009 biçimi).
    app_tab = c.post("/symbols", json={"sha": head, "platform": "android"}).json()
    assert "SepetEkrani" in [p["class"] for p in app_tab["page_objects"]]
    assert "platform" not in app_tab
    assert c.post("/symbols", json={"sha": head, "lang": "java", "platform": "web"}).json() == web
    assert {k[3] for k in worker_app._SYMBOL_CACHE} == {"e2e-java", "e2e-app"}


# ------------------------------------------------------------------- test-runner (web Java)

XML_WEB_PASSED = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="TestSuite" tests="1" failures="0" errors="0" skipped="0">
  <testcase name="senaryo" classname="com.antreklabs.bayi.uretilen.DEMO12C1_ab12cd34Test" time="2.5"/>
</testsuite>
"""

PW_TIMEOUT_MSG = (
    "Error {\n  message='Timeout 5000ms exceeded.\n  name='TimeoutError\n  stack='TimeoutError: "
    "Timeout 5000ms exceeded.\n    at _ProgressController.run (/tmp/playwright-java-1/package/lib/"
    'coreBundle.js:13004:32)\n}\nCall log:\n-   - waiting for getByTestId("product-card-P-001")'
    '.getByTestId("add-to-cart")\n'
)
PW_ASSERT_MSG = (
    "Locator expected to have text\nExpected: 1.250,00 TL\nReceived: 1.375,00 TL\n\nCall log:\n"
    '  - Assert "hasText" getByTestId("cart-total") with timeout 5000ms\n'
    '  - waiting for getByTestId("cart-total")\n'
    '    11 × locator resolved to <span data-testid="cart-total">1.375,00 TL</span>'
)
PW_TRACE = (
    "\n\tat com.microsoft.playwright.impl.AssertionsBase.expectImpl(AssertionsBase.java:81)"
    "\n\tat com.antreklabs.bayi.ekranlar.SepetEkrani.dogrulaToplam(SepetEkrani.java:45)"
    "\n\tat com.antreklabs.bayi.uretilen.DEMO12C1_ab12cd34Test.senaryo(DEMO12C1_ab12cd34Test.java:15)"
)


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        .replace("\n", "&#10;")
    )  # fmt: skip


XML_WEB_FAILED = f"""<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="TestSuite" tests="2" failures="2" errors="0" skipped="0">
  <testcase name="senaryo" classname="com.antreklabs.bayi.uretilen.DEMO12C1_ab12cd34Test" time="6">
    <failure type="org.opentest4j.AssertionFailedError" message="{_esc(PW_ASSERT_MSG)}">org.opentest4j.AssertionFailedError: {_esc(PW_ASSERT_MSG + PW_TRACE)}</failure>
  </testcase>
  <testcase name="ekle" classname="com.antreklabs.bayi.testler.SepetTesti" time="6">
    <failure type="com.microsoft.playwright.TimeoutError" message="{_esc(PW_TIMEOUT_MSG)}">x</failure>
  </testcase>
</testsuite>
"""


def fake_web_mvn(tmp_path: Path, xml: str) -> Path:
    """`mvn`: argv/ortamı kaydeder; Surefire XML'i, kanıtı (ekran.png, trace.zip, sayfa.html),
    Allure sonucu ve Extent raporunu yazar."""
    return make_fake_node(
        tmp_path,
        f"""
        args = sys.argv[1:]
        props = dict(a[2:].split("=", 1) for a in args if a.startswith("-D") and "=" in a)
        keys = ("BASE_URL", "API_URL", "DEMO_API_URL", "DEMOAPP_TEST_TOKEN", "BREAK_CAMPAIGN",
                "PLAYWRIGHT_BROWSERS_PATH", "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", "APPIUM_URL",
                "PLATFORM", "APP_ID", "MAVEN_SKIP_RC", "MAVEN_OPTS", "JAVA_TOOL_OPTIONS",
                "ANTHROPIC_API_KEY", "TP_RUN_ID", "CI")
        with pathlib.Path({str(tmp_path / "mvn.log")!r}).open("a") as fh:
            fh.write(json.dumps({{"argv": args, "cwd": os.getcwd(),
                                  "env": {{k: os.environ.get(k) for k in keys}},
                                  "tmp": [os.environ.get("TMPDIR"),
                                          os.path.isdir(os.environ.get("TMPDIR") or "")]}}) + "\\n")
        rd = pathlib.Path(props["raporlar.dizini"]); rd.mkdir(parents=True, exist_ok=True)
        (rd / "TEST-TestSuite.xml").write_text({xml!r}, encoding="utf-8")
        kd = pathlib.Path(props["kanit.dizini"]) / "DEMO12C1_ab12cd34Test.senaryo"
        kd.mkdir(parents=True, exist_ok=True)
        for ad in ("ekran.png", "trace.zip", "sayfa.html"):
            (kd / ad).write_bytes(b"x")
        ad = pathlib.Path(props["allure.results.directory"]); ad.mkdir(parents=True, exist_ok=True)
        (ad / ("r-" + props.get("extent.tekrar", "1").replace("/", "-") + ".json")).write_text("{{}}")
        ed = pathlib.Path(props["extent.rapor.dizini"]); ed.mkdir(parents=True, exist_ok=True)
        with (ed / "index.html").open("a") as fh:
            fh.write("Extent " + props.get("extent.tekrar", "tek") + ";")
        sys.exit(0 if "failures=\\"0\\"" in {xml!r} else 1)
        """,
        name="fake-mvn-web-run",
    )


@pytest.fixture
def web_runner(web_env: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    api = DemoApi()
    monkeypatch.setenv("DEMO_API_URL", api.url)
    monkeypatch.setenv("BASE_URL", f"{api.url}/web")
    monkeypatch.setenv("TP_HEALTH_TIMEOUT_S", "2")
    monkeypatch.setenv("APPIUM_URL_ANDROID", f"{api.url}/appium")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sızmamalı")
    monkeypatch.setenv("MAVEN_OPTS", "-javaagent:/kotu.jar")
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "-javaagent:/kotu.jar")
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    yield api
    api.server.shutdown()


def test_web_java_run_repeat_env_health_and_reports(
    web_runner: DemoApi, forge: Forge, env: Path, web_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_MVN", str(fake_web_mvn(web_env, XML_WEB_PASSED)))
    head = forge.commit("tp/web-run", web_files())
    resp = TestClient(runner_app).post(
        "/run",
        json={"run_id": "w1", "sha": head, "lang": "java", "test_files": [GEN], "repeat_each": 3},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "passed", data["error"]
    assert (data["lang"], data["platform"], data["appium_url"]) == ("java", "web", None)
    assert data["base_url"] == f"{web_runner.url}/web"
    # Sağlık: web origin + API (TS koşusuyla aynı); Appium'a hiç gidilmez.
    assert sorted(web_runner.gets) == ["/health", "/web/"]
    assert data["saglik"]["ok"] is True and data["saglik"]["appium"] is None
    assert data["saglik"]["web"]["status"] == 200
    # Tekrarlar ayrı Surefire dizinlerinde, testler tekrar başına ayrışır.
    calls = mvn_calls(web_env)
    assert [c["argv"][-1] for c in calls] == ["surefire:test"] * 3
    assert "test-compile" in calls[0]["argv"] and "test-compile" not in calls[1]["argv"]
    root = env / "runs" / "w1" / "src" / "e2e-java"
    for i, c in enumerate(calls):
        assert (
            f"-Draporlar.dizini={root / 'target' / 'surefire-reports' / f'tekrar-{i + 1}'}"
            in c["argv"]
        )
        assert f"-Dextent.tekrar={i + 1}/3" in c["argv"]
        assert f"-Dmaven.repo.local.tail={web_env / 'e2e-java-deps' / 'm2'}" in c["argv"]
        assert c["cwd"] == str(root)
    assert [t["repeat_index"] for t in data["tests"]] == [0, 1, 2]
    assert len({t["id"] for t in data["tests"]}) == 3
    assert {t["project"] for t in data["tests"]} == {"chromium"}
    assert ET.parse(data["junit"]).getroot().get("name") == "e2e-java"
    # Ortam: izin listesi; tarayıcı imajdan, indirme kapalı; Appium/uygulama ayarı yok.
    assert calls[0]["env"] == {
        "BASE_URL": f"{web_runner.url}/web",
        "API_URL": web_runner.url,
        "DEMO_API_URL": web_runner.url,
        "DEMOAPP_TEST_TOKEN": "test-belirteci",
        "BREAK_CAMPAIGN": "",
        "PLAYWRIGHT_BROWSERS_PATH": "/ms-playwright",
        "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
        "APPIUM_URL": None,
        "PLATFORM": None,
        "APP_ID": None,
        "MAVEN_SKIP_RC": "1",
        "MAVEN_OPTS": f"-Xmx384m -Djava.io.tmpdir={env / 'runs' / 'w1' / 'tmp'}",
        "JAVA_TOOL_OPTIONS": None,
        "ANTHROPIC_API_KEY": None,
        "TP_RUN_ID": "w1",
        "CI": "1",
    }
    # OPS-O6: geçici dosyalar koşu dizini altında (`<run>/tmp`); koşu sonunda silinir.
    tmp = env / "runs" / "w1" / "tmp"
    assert all(c["tmp"] == [str(tmp), True] for c in calls)
    assert not tmp.exists()
    # OPS-O2: Surefire çatalının java.io.tmpdir'i (pom argLine `${tp.java.tmpdir}`).
    assert all(f"-Dtp.java.tmpdir={tmp}" in c["argv"] for c in calls)
    # Artefakt listesi: kanıt (target/kanit/**), Allure, Extent, Surefire, junit.
    rep = data["reports"]
    assert rep["kanit"]["rel"] == "runs/w1/src/e2e-java/target/kanit" and rep["kanit"]["exists"]
    assert rep["extent_html"]["exists"] and rep["allure"]["exists"]
    assert (root / "target" / "extent-report" / "index.html").read_text().count("Extent ") == 3
    assert data["traces_dir"] == str(root / "target" / "kanit")


def test_web_java_run_failures_and_evidence(
    web_runner: DemoApi, forge: Forge, env: Path, web_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_MVN", str(fake_web_mvn(web_env, XML_WEB_FAILED)))
    head = forge.commit("tp/web-red", web_files())
    data = (
        TestClient(runner_app)
        .post("/run", json={"run_id": "w2", "sha": head, "lang": "java", "platform": "web"})
        .json()
    )
    assert data["status"] == "failed"
    by_title = {t["title"]: t for t in data["tests"]}
    gen = by_title["DEMO12C1_ab12cd34Test › senaryo"]["failure"]
    assert gen["type"] == "assertion"
    assert (gen["expected"], gen["received"]) == ("1.250,00 TL", "1.375,00 TL")
    assert gen["locator_test_id"] == "cart-total" and gen["timeout_ms"] == 5000
    assert gen["location"]["file"].endswith("ekranlar/SepetEkrani.java")
    kanit = "runs/w2/src/e2e-java/target/kanit/DEMO12C1_ab12cd34Test.senaryo"
    assert gen["trace_rel"] == f"{kanit}/trace.zip"
    assert gen["page_html_rel"] == f"{kanit}/sayfa.html"
    assert gen["evidence"]["screenshot"]["rel"] == f"{kanit}/ekran.png"
    assert gen["evidence"]["page_source"] is None
    loc = by_title["SepetTesti › ekle"]["failure"]
    assert loc["type"] == "locator_timeout"
    assert (loc["locator_scope_test_id"], loc["locator_test_id"]) == (
        "product-card-P-001", "add-to-cart",
    )  # fmt: skip
    assert loc["first_line"] == "Timeout 5000ms exceeded."
    assert sorted(t for g in data["failure_groups"] for t in g["types"]) == [
        "assertion",
        "locator_timeout",
    ]


def test_web_java_health_failure_skips_maven(
    web_runner: DemoApi, forge: Forge, web_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_MVN", str(fake_web_mvn(web_env, XML_WEB_PASSED)))
    head = forge.commit("tp/web-down", web_files())
    web_runner.get_status["/web/"] = 503
    data = (
        TestClient(runner_app)
        .post("/run", json={"run_id": "w3", "sha": head, "lang": "java"})
        .json()
    )
    assert data["status"] == "error" and "web" in data["error"]
    assert data["saglik"]["ok"] is False and mvn_calls(web_env) == []


# ---------------------------------------------------- Playwright for Java sınıflandırması


@pytest.mark.parametrize(
    ("exc", "message", "kind", "extra"),
    [
        (
            "com.microsoft.playwright.PlaywrightException",
            'Error {\n  message=\'Error: strict mode violation: getByRole(AriaRole.BUTTON, new Page.GetByRoleOptions().setName("Tamam")) resolved to 2 elements:\n  name=\'Error\n}\nCall log:\n-   - waiting for getByRole(AriaRole.BUTTON, new Page.GetByRoleOptions().setName("Tamam"))\n',
            "locator_ambiguous",
            {"locator_role": "button", "locator_name": "Tamam"},
        ),
        (
            "com.microsoft.playwright.PlaywrightException",
            'Error {\n  message=\'net::ERR_CONNECTION_REFUSED at http://demo-app-web:8080/giris\n  name=\'Error\n}\nCall log:\n-   - navigating to "http://demo-app-web:8080/giris", waiting until "load"\n',
            "navigation",
            {"first_line": "net::ERR_CONNECTION_REFUSED at http://demo-app-web:8080/giris"},
        ),
        (
            "org.opentest4j.AssertionFailedError",
            'Locator expected to be visible\nError: element(s) not found\nCall log:\n  - Assert "isVisible" getByTestId("yok") with timeout 1000ms\n  - waiting for getByTestId("yok")',
            "locator_not_found",
            {"locator_test_id": "yok", "timeout_ms": 1000},
        ),
        (
            "com.microsoft.playwright.TimeoutError",
            'Error {\n  message=\'Timeout 1500ms exceeded.\n  name=\'TimeoutError\n}\nCall log:\n-   - waiting for getByTestId("cart").getByRole(AriaRole.BUTTON, new Locator.GetByRoleOptions().setName("Sepete \\"ekle\\""))\n',
            "locator_timeout",
            {
                "locator_scope_test_id": "cart",
                "locator_test_id": None,
                "locator_role": "button",
                "locator_name": 'Sepete "ekle"',
            },
        ),
        (
            "org.opentest4j.AssertionFailedError",
            "POST /test/reset başarısız: 500",
            "test_data",
            {},
        ),
        (
            "com.microsoft.playwright.PlaywrightException",
            "Error {\n  message='Executable doesn't exist at /ms-playwright/chromium_headless_shell-1248/chrome-linux/headless_shell\n",
            "other",
            {"signals": ["tarayıcı başlatılamadı"]},
        ),
    ],
)
def test_classify_playwright_java(exc: str, message: str, kind: str, extra: dict) -> None:
    info = surefire.classify("failure", exc, message, "")
    assert info["type"] == kind, info
    assert info["exception"] == exc
    for k, v in extra.items():
        assert info[k] == v, (k, info)


def test_classify_app_java_unchanged() -> None:
    """Appium (e2e-app) hataları eski kurallarla: Bekle.dogrula → assertion."""
    info = surefire.classify(
        "failure",
        "java.lang.AssertionError",
        "'cart-total' metni: beklenen <1.250,00 TL>, görülen <1.375,00 TL> (10000 ms)",
        "",
    )
    assert info["type"] == "assertion" and info["expected"] == "1.250,00 TL"


# ---------------------------------------------------------------- güvenilir pom (web Java)


def _props(pom: Path) -> dict[str, str]:
    root = ET.parse(pom).getroot()
    return {
        el.tag.split("}", 1)[1]: (el.text or "").strip()
        for el in root.find("m:properties", POM_NS) or []
    }


def _plugins(pom: Path) -> dict[str, str]:
    root = ET.parse(pom).getroot()
    out = {}
    for p in root.iterfind("m:build/m:pluginManagement/m:plugins/m:plugin", POM_NS):
        version = p.findtext("m:version", "", POM_NS).strip()
        if version.startswith("${"):
            version = _props(pom)[version[2:-1]]
        out[p.findtext("m:artifactId", "", POM_NS)] = version
    return out


def test_playwright_java_matches_playwright_version() -> None:
    """Playwright for Java, `.playwright-version`'daki playwright-core ile AYNI tarayıcı
    derlemelerini kullanmalı: imajdaki /ms-playwright bu sürümündür ve indirme kapalıdır.

    Java yayınları yamasız (`1.64.0`) çıkar ve sürücüsü aynı ana.ara sürümün son yamasını
    paketler (Java 1.64.0 sürücüsü = playwright-core 1.64.1; browsers.json birebir aynı —
    Maven Central'dan doğrulandı). Kural: ana.ara sürüm eşit, Java yaması .0.
    """
    want = (REPO / ".playwright-version").read_text().strip()
    have = _props(WEB_POM)["playwright.version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", have), have
    assert have.split(".")[:2] == want.split(".")[:2], (have, want)
    assert have.split(".")[2] == "0", have
    root = ET.parse(WEB_POM).getroot()
    deps = {
        d.findtext("m:artifactId", "", POM_NS): d.findtext("m:version", "", POM_NS)
        for d in root.iterfind("m:dependencies/m:dependency", POM_NS)
    }
    assert deps["playwright"] == "${playwright.version}"


def test_web_pom_versions_aligned_with_app_pom() -> None:
    web, app = _props(WEB_POM), _props(APP_POM)
    for key in ("testng.version", "allure.version", "extent.version", "slf4j.version",
                "maven.compiler.release"):  # fmt: skip
        assert web[key] == app[key], key
    assert _plugins(WEB_POM) == _plugins(APP_POM)
    # TestNG sağlayıcısı açık; JUnit Platform sınıf yolunda değil (TestNG testleri koşmazdı).
    text = WEB_POM.read_text(encoding="utf-8")
    assert "<artifactId>surefire-testng</artifactId>" in text
    assert "<groupId>org.junit.platform</groupId>" in text  # dışlama
    # Aralık / SNAPSHOT yok: çevrimdışı, tekrarlanabilir.
    assert not re.search(r"<version>[\[(]|SNAPSHOT|LATEST|RELEASE", text)


@pytest.mark.skipif(
    not (DEMO_E2E_JAVA / "pom.xml").is_file(), reason="demo-app/e2e-java (Ş4) bu dalda yok"
)
def test_trusted_web_pom_matches_demo_app() -> None:
    """İmajdaki güvenilir kopya hedef projeninkiyle bayt bayt aynı (§2.6)."""
    assert WEB_POM.read_bytes() == (DEMO_E2E_JAVA / "pom.xml").read_bytes()


def test_dockerfile_warms_web_java_repo() -> None:
    text = (TOOLCHAIN / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY e2e-java-deps/pom.xml ./pom.xml" in text
    assert "COPY --from=javabuild /build/e2e-java-m2 /opt/e2e-java/m2" in text
    assert "COPY --chmod=444 e2e-java-deps/pom.xml /opt/e2e-java/pom.xml" in text
    assert "RUN --network=none" in text  # çevrimdışı duman testi


def test_runner_java_module_constants() -> None:
    assert java_run.WEB == "web" and java_run.BROWSERS_PATH == "/ms-playwright"
