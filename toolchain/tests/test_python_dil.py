# ruff: noqa: E501  (JUnit XML fikstürleri gerçek tek satırlık mesajlar içerir)
"""Python dil eklentileri (Ş1): worker (kök, kilit, guard/compile/onarım, /check adımları), runner
(pytest argv/ortam, koşu akışı) ve pytest JUnit özeti. pytest ve tarayıcı gerçekten koşmaz:
venv python'u argv'yi kaydeden ve JUnit XML yazan sahte bir betiktir."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from runner.diller import _pytest_junit as pj
from runner.diller import python_run
from runner.run import RunRequest
from tests.conftest import REPO, TOOLCHAIN, Forge, make_fake_node
from tests.test_py_guard import GOOD_WEB
from tests.test_runner import DemoApi
from toolchain_common import repos
from toolchain_common.settings import settings
from worker.diller import python as pyyol

LOCK = TOOLCHAIN / "e2e-python-deps" / "requirements.lock"
GUARD = TOOLCHAIN / "py-guard" / "py_guard.py"
GEN = "tests/generated/test_tpd_1_c2_3f9b1c2e.py"
KIMLIKLER = 'LOGIN = {"submit": "login-submit"}\n'


@pytest.fixture
def py_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    deps = tmp_path / "e2e-python-deps"
    deps.mkdir()
    (deps / "requirements.lock").write_bytes(LOCK.read_bytes())
    monkeypatch.setenv("TP_E2E_PYTHON_DEPS", str(deps))
    monkeypatch.setenv("TP_PY_GUARD", str(GUARD))
    monkeypatch.setenv("TP_PY_GUARD_PYTHON", sys.executable)
    for k in ("TP_E2E_PYTHON_ROOT", "TP_E2E_APP_PYTHON_ROOT", "TP_E2E_APP_PYTHON_ROOT_IOS"):
        monkeypatch.delenv(k, raising=False)
    return deps


def _project(files: dict[str, str] | None = None) -> dict[str, str]:
    base = {
        "e2e-python/pyproject.toml": "[tool.pytest.ini_options]\npythonpath = ['.']\n",
        "e2e-python/requirements.lock": LOCK.read_text(encoding="utf-8"),
        "e2e-python/pages/__init__.py": "",
        "e2e-python/pages/kimlikler.py": KIMLIKLER,
        "e2e-python/pages/login_page.py": "class LoginPage:\n    def goto(self) -> None:\n        pass\n",
        f"e2e-python/{GEN}": GOOD_WEB,
    }
    base.update(files or {})
    return base


# ---------------------------------------------------------------------------- sözleşme


def test_kilit_playwright_surumu_ve_hash() -> None:
    text = LOCK.read_text(encoding="utf-8")
    pw = (REPO / ".playwright-version").read_text(encoding="utf-8").strip()
    assert f"\nplaywright=={pw} \\" in text
    for pkg in ("pytest==", "pytest-playwright==", "pytest-repeat==", "appium-python-client==",
                "allure-pytest=="):  # fmt: skip
        assert f"\n{pkg}" in text, pkg
    # --require-hashes: her paket satırının ardından en az bir hash.
    blocks = [b for b in text.split("\n") if b and not b.startswith((" ", "#"))]
    assert all(b.endswith("\\") for b in blocks)


@pytest.mark.parametrize("proje", ["e2e-python", "e2e-app-python"])
def test_demo_kilidi_guvenilir_kopyayla_bayt_esit(proje: str) -> None:
    demo = REPO / "demo-app" / proje / "requirements.lock"
    if not demo.exists():
        pytest.skip(f"demo-app/{proje}/requirements.lock henüz yok")
    assert demo.read_bytes() == LOCK.read_bytes()


@pytest.mark.parametrize(
    ("yol", "ok"),
    [
        ("tests/generated/test_tpd_1_c2_3f9b1c2e.py", True),
        ("tests/test_giris.py", True),
        ("tests/a/b/test_x.py", True),
        ("tests/../conftest.py", False),
        ("tests/generated/Test_x.py", False),
        ("/tests/test_x.py", False),
        ("pages/test_x.py", False),
        ("tests/test_x.py::test_y", False),
        ("tests/test_x.py --pdb", False),
    ],
)
def test_test_dosyasi_kalibi(yol: str, ok: bool) -> None:
    if ok:
        assert pyyol.validate_test_file(yol) == yol
    else:
        with pytest.raises(ValueError):
            pyyol.validate_test_file(yol)


def test_kok_cozumu(py_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace()
    assert pyyol.py_kok(cfg, "web").root == "e2e-python"
    assert pyyol.py_kok(cfg, None).platform == "web"
    assert pyyol.py_kok(cfg, "android").root == "e2e-app-python"
    monkeypatch.setenv("TP_E2E_APP_PYTHON_ROOT", "mobil/e2e-py")
    monkeypatch.setenv("TP_E2E_APP_PYTHON_ROOT_IOS", "ios-depo/testler")
    assert pyyol.py_kok(cfg, "android").root == "mobil/e2e-py"
    assert pyyol.py_kok(cfg, "ios").root == "ios-depo/testler"
    assert pyyol.py_kok(cfg, "ios").deps == py_env
    with pytest.raises(ValueError):
        pyyol.py_kok(cfg, "tv")
    e = pyyol.EKLENTI
    assert (e.ad, e.hat, e.steps) == ("python", "tam", ("app", "deps", "guard", "compile", "run"))
    assert e.platformlar == ("web", "android", "ios", "windows")
    from runner.diller.python_run import EKLENTI as R

    assert R.ad == "python" and R.validate_test_file(GEN) == GEN


# ------------------------------------------------------------------------------- deps


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "e2e-python"
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def test_check_deps(py_env: Path, tmp_path: Path) -> None:
    cfg = SimpleNamespace()
    kok = pyyol.py_kok(cfg, "web")
    root = _tree(tmp_path / "a", _project())
    assert pyyol.check_deps(cfg, root, kok)["ok"]
    (root / "requirements.lock").write_text("pytest==1\n", encoding="utf-8")
    r = pyyol.check_deps(cfg, root, kok)
    assert not r["ok"] and "güvenilir kilit" in r["error"]
    for bad, what in (
        ({"e2e-python/pytest.ini": "[pytest]\naddopts = -p kotu\n"}, "pytest.ini"),
        ({"e2e-python/setup.cfg": ""}, "setup.cfg"),
        ({"e2e-python/sitecustomize.py": ""}, "sitecustomize.py"),
        ({"e2e-python/pages/x.pth": "import os"}, "x.pth"),
    ):
        root = _tree(tmp_path / what, _project(bad))
        r = pyyol.check_deps(cfg, root, kok)
        assert not r["ok"] and what in r["error"], what
    root = _tree(tmp_path / "bag", _project())
    (root / "conftest.py").symlink_to("/etc/passwd")
    r = pyyol.check_deps(cfg, root, kok)
    assert not r["ok"] and "sembolik bağ" in r["error"]
    root = _tree(tmp_path / "pp", _project())
    (root / "pyproject.toml").unlink()
    assert "pyproject.toml" in pyyol.check_deps(cfg, root, kok)["error"]
    (py_env / "requirements.lock").unlink()
    assert "İmajda" in pyyol.check_deps(cfg, _tree(tmp_path / "z", _project()), kok)["error"]


# -------------------------------------------------------------------- guard / compile / symbols


def test_symbols_guard_compile_alt_surecle(py_env: Path, tmp_path: Path) -> None:
    cfg = SimpleNamespace(symbols_timeout_s=30, ast_guard_timeout_s=30)
    kok = pyyol.py_kok(cfg, "web")
    root = _tree(tmp_path, _project())
    t = pyyol.symbols_table(cfg, root, kok)
    assert t["lang"] == "python" and t["platform"] == "web"
    assert t["page_objects"][0]["class"] == "LoginPage"
    assert t["classes"] == [{"name": "LoginPage", "methods": [
        {"name": "goto", "kind": "action", "params": []}]}]  # fmt: skip
    g = pyyol.run_guard(cfg, root)
    assert g["ok"], g["violations"]
    assert g["files"] == [GEN] and g["kimlikler"] == ["pages/kimlikler.py"]
    c = pyyol.run_compile(cfg, root, kok)
    assert c["ok"] and c["files"] >= 4
    (root / "pages" / "login_page.py").write_text("def f(:\n", encoding="utf-8")
    c = pyyol.run_compile(cfg, root, kok)
    assert not c["ok"] and "pages/login_page.py:1" in c["error"]
    (root / GEN).write_text(GOOD_WEB + "eval('1')\n", encoding="utf-8")
    assert not pyyol.run_guard(cfg, root)["ok"]


def test_guard_araci_bozuksa_hata(
    py_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bozuk = make_fake_node(tmp_path, "print('çöp'); sys.exit(0)\n", name="bozuk-guard")
    monkeypatch.setenv("TP_PY_GUARD", str(bozuk))
    monkeypatch.setenv("TP_PY_GUARD_PYTHON", sys.executable)
    with pytest.raises(pyyol.PyAracError):
        pyyol.run_guard(SimpleNamespace(ast_guard_timeout_s=10), tmp_path)


def test_repair_guard_yalniz_kimlik_degisebilir(py_env: Path, forge: Forge) -> None:
    base = forge.commit("tp/py", _project())
    cfg = SimpleNamespace(git_timeout_s=30, ast_guard_timeout_s=30)
    kok = pyyol.py_kok(cfg, "web")
    ok = forge.commit(
        "tp/py",
        {"e2e-python/pages/kimlikler.py": KIMLIKLER.replace("login-submit", "login-gonder")},
    )
    rep = pyyol.repair_guard(cfg, forge.bare, base, ok, kok)
    assert rep["ok"], rep["violations"]
    assert rep["testid_changes"] == [
        {"key": "LOGIN.submit", "old": "login-submit", "new": "login-gonder"}
    ]
    bad = forge.commit("tp/py", {"e2e-python/pages/login_page.py": "class LoginPage:\n    pass\n"})
    rep = pyyol.repair_guard(cfg, forge.bare, ok, bad, kok)
    assert not rep["ok"] and rep["violations"][0]["code"] == "non_locator_file_changed"
    bad2 = forge.commit("tp/py", {"e2e-python/pages/kimlikler.py": "LOGIN = {}\n"})
    rep = pyyol.repair_guard(cfg, forge.bare, bad, bad2, kok)
    assert "locator_key_removed" in [v["code"] for v in rep["violations"]]
    # EKLENTI.guard: checkout + üretilen testler + repair.
    rep = pyyol.EKLENTI.guard(cfg, forge.bare, base, ok, "repair", "web")
    assert rep["ok"] and rep["tool"] == "py-guard" and rep["files"] == [GEN]


# ----------------------------------------------------------------------- /check run_static


class _Req(SimpleNamespace):
    def runner_env(self) -> dict[str, str]:
        return {"BREAK_CAMPAIGN": "1"} if self.break_campaign else {}


def test_run_static_adimlari_ve_runner_govdesi(
    py_env: Path, forge: Forge, env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from worker import check as checks

    head = forge.commit("tp/py", _project())
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(
        checks, "_call_runner", lambda cfg, body, client: sent.append(body) or {"ok": True}
    )
    cfg = settings()
    loc = repos.locate(cfg, head)
    req = _Req(platform="web", test_files=[GEN], ast_guard_mode="pr", run_id="r1", repeat_each=3,
               retries=0, keep=False, break_campaign=False)  # fmt: skip
    steps = pyyol.EKLENTI.run_static(cfg, req, loc, None, None, {})
    assert [k for k in steps] == ["app", "deps", "guard", "compile", "run"]
    assert all(s.get("ok") for s in steps.values()), steps
    (body,) = sent
    assert body["lang"] == "python" and body["platform"] == "web" and body["test_files"] == [GEN]
    assert body["repeat_each"] == 3 and body["run_id"] == "r1"
    # Kilit farklıysa koruma ve koşu yapılmaz.
    bad = forge.commit("tp/py2", _project({"e2e-python/requirements.lock": "x==1\n"}))
    steps = pyyol.run_static(cfg, req, repos.locate(cfg, bad), None, None, {})
    assert list(steps) == ["app", "deps"] and not steps["deps"]["ok"]
    # Commit'te olmayan test dosyası.
    req.test_files = ["tests/generated/test_yok.py"]
    steps = pyyol.run_static(cfg, req, loc, None, None, {})
    assert steps["deps"]["missing_test_files"] == ["tests/generated/test_yok.py"]


# ------------------------------------------------------------------------------ JUnit


JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="1" failures="4" skipped="1" tests="8" time="9">
<testcase classname="tests.generated.test_tpd_1_c2_3f9b1c2e" name="test_tpd_1_c2_3f9b1c2e" time="2.5"/>
<testcase classname="tests.test_sepet" name="test_toplam" time="1.0"><failure message="AssertionError: Locator expected to have text '150,00 TL'&#10;Actual value: 175,00 TL ">tests/test_sepet.py:12: in test_toplam
    sepet.expect_total("150,00 TL")
pages/cart_page.py:40: in expect_total
    expect(self.page.get_by_test_id("cart-total")).to_have_text(amount)
E   AssertionError: Locator expected to have text '150,00 TL'
E   Actual value: 175,00 TL
E   Call log:
E     - LocatorAssertions.to_have_text with timeout 5000ms
E     - waiting for get_by_test_id("cart-total")</failure></testcase>
<testcase classname="tests.test_giris" name="test_buton" time="30"><failure message="playwright._impl._errors.TimeoutError: Locator.click: Timeout 30000ms exceeded.&#10;Call log:&#10;  - waiting for get_by_test_id(&quot;login-submit&quot;)">E   playwright._impl._errors.TimeoutError: Locator.click: Timeout 30000ms exceeded.</failure></testcase>
<testcase classname="tests.test_giris" name="test_gorunur" time="5"><failure message="AssertionError: Locator expected to be visible&#10;Actual value: None&#10;Error: element(s) not found &#10;Call log:&#10;  - waiting for get_by_test_id(&quot;nav-cart&quot;)">x</failure></testcase>
<testcase classname="tests.test_kurulum" name="test_hazirlik" time="0.1"><error message="failed on setup with &quot;RuntimeError: POST /test/reset başarısız: 500&quot;">conftest.py:40: RuntimeError</error></testcase>
<testcase classname="tests.test_ekran" name="test_kimlik[android]" time="11"><failure message="selenium.common.exceptions.TimeoutException: Message: öğe görünmedi: kimlik 'product-card-P-001' içinde 'add-to-cart'">E   selenium.common.exceptions.TimeoutException</failure></testcase>
<testcase classname="tests.test_ekran" name="test_baglanti" time="1"><failure message="urllib3.exceptions.MaxRetryError: HTTPConnectionPool(host='appium', port=4723): Max retries exceeded">x</failure></testcase>
<testcase classname="tests.test_atla" name="test_atla" time="0"><skipped type="pytest.skip" message="TP_E2E_NO_RESET=1">atla</skipped></testcase>
</testsuite></testsuites>
"""


def test_junit_ozeti_ve_siniflandirma(tmp_path: Path) -> None:
    rd = tmp_path / "tekrar-1"
    rd.mkdir()
    (rd / pj.JUNIT_NAME).write_text(JUNIT, encoding="utf-8")
    kd = tmp_path / "kanit" / "test_toplam"
    kd.mkdir(parents=True)
    (kd / "ekran.png").write_bytes(b"png")
    (kd / "sayfa.html").write_text("<html/>", encoding="utf-8")
    rep = pj.Repeat(0, rd, tmp_path / "kanit", None)
    s = pj.summarize([rep], project="chromium", rel_root=tmp_path)
    assert s["errors"] == []
    assert s["stats"] == {"expected": 1, "unexpected": 6, "flaky": 0, "skipped": 1,
                          "duration_ms": 50600}  # fmt: skip
    by = {t["title"]: t for t in s["tests"]}
    gen = by["test_tpd_1_c2_3f9b1c2e › test_tpd_1_c2_3f9b1c2e"]
    assert gen["file"] == GEN and gen["status"] == "expected" and gen["project"] == "chromium"
    f = by["test_sepet › test_toplam"]["failure"]
    assert f["type"] == "assertion" and f["exception"] == "AssertionError"
    assert f["locator_test_id"] == "cart-total"
    assert f["expected"] == "150,00 TL" and f["received"] == "175,00 TL"
    assert f["timeout_ms"] == 5000
    assert f["test_location"] == {"file": "tests/test_sepet.py", "line": 12, "column": 0}
    assert f["location"] == {"file": "pages/cart_page.py", "line": 40, "column": 0}
    assert f["evidence"]["screenshot"]["rel"] == "kanit/test_toplam/ekran.png"
    assert f["page_html_rel"] == "kanit/test_toplam/sayfa.html" and f["trace_rel"] is None
    t = by["test_giris › test_buton"]["failure"]
    assert t["type"] == "locator_timeout" and t["locator_test_id"] == "login-submit"
    assert t["action"] == "Locator.click" and t["timeout_ms"] == 30000
    assert by["test_giris › test_gorunur"]["failure"]["type"] == "locator_not_found"
    assert by["test_kurulum › test_hazirlik"]["failure"]["type"] == "test_data"
    k = by["test_ekran › test_kimlik[android]"]["failure"]
    assert k["type"] == "locator_not_found"
    assert (k["locator_test_id"], k["locator_scope_test_id"]) == (
        "add-to-cart",
        "product-card-P-001",
    )
    o = by["test_ekran › test_baglanti"]["failure"]
    assert o["type"] == "other" and o["signals"][0].startswith("ortam")
    assert by["test_atla › test_atla"]["status"] == "skipped"
    # Kırarak doğrulama denetimi: yalnız assertion kırmızı sayılır.
    red = python_run.java_run.red_check(s["tests"])
    assert red["kirmizi"] == ["test_sepet › test_toplam"] and not red["ok"]


def test_junit_yok_ve_bag(tmp_path: Path) -> None:
    rep = pj.Repeat(0, tmp_path / "yok", tmp_path / "kanit", None)
    assert pj.summarize([rep], project="android")["errors"] == ["pytest rapor dizini yok"]
    rd = tmp_path / "r"
    rd.mkdir()
    (rd / pj.JUNIT_NAME).write_text(JUNIT, encoding="utf-8")
    dis = tmp_path / "dis"
    dis.mkdir()
    (dis / "ekran.png").write_bytes(b"x")
    (tmp_path / "kanit").mkdir()
    (tmp_path / "kanit" / "test_toplam").symlink_to(dis, target_is_directory=True)
    s = pj.summarize([pj.Repeat(0, rd, tmp_path / "kanit")], project="c", rel_root=tmp_path)
    f = next(t for t in s["tests"] if t["title"].endswith("test_toplam"))["failure"]
    assert f["evidence"]["screenshot"] is None  # kanıt yolu bağ üzerinden dışarı çıkamaz


def test_dtd_reddedilir(tmp_path: Path) -> None:
    rd = tmp_path / "r"
    rd.mkdir()
    (rd / pj.JUNIT_NAME).write_text(
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><testsuites/>', encoding="utf-8"
    )
    s = pj.summarize([pj.Repeat(0, rd, tmp_path)], project="c")
    assert s["errors"] and s["tests"] == []


# ------------------------------------------------------------------------------ runner


def _cfg(**kw: Any) -> SimpleNamespace:
    base = dict(base_url="http://web:8080", demo_api_url="http://api:8000",
                demoapp_test_token="belirtec", app_ayarlari=None)  # fmt: skip
    return SimpleNamespace(**{**base, **kw})


def test_pytest_argv_web_ve_uygulama(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_PYTHON_E2E", "/opt/e2e-python/venv/bin/python")
    root = tmp_path / "e2e-python"
    rep = python_run._repeats(root / "results", 3, web=True)[1]
    argv = python_run.pytest_argv(_cfg(), root, "web", rep, [GEN])
    assert argv[:5] == ["/opt/e2e-python/venv/bin/python", "-I", "-B", "-m", "pytest"]
    assert argv[argv.index("-c") + 1] == str(root / "pyproject.toml")
    assert "no:cacheprovider" in argv and "junit_family=xunit2" in argv
    assert f"--junitxml={root / 'results' / 'tekrar-2' / pj.JUNIT_NAME}" in argv
    assert argv[argv.index("--base-url") + 1] == "http://web:8080"
    assert argv[argv.index("--output") + 1] == str(root / "results" / "kanit-pw" / "tekrar-2")
    assert argv[argv.index("-m", 5) + 1] == "not birim"
    assert argv[-2:] == ["--", GEN]
    app_rep = python_run._repeats(root / "results", 1, web=False)[0]
    app = python_run.pytest_argv(_cfg(), root, "android", app_rep, [])
    assert "--browser" not in app and app[-2:] == ["--", "tests"]
    assert app_rep.kanit_dir == root / "results" / "kanit" and app_rep.pw_output is None
    with pytest.raises(ValueError):
        python_run.pytest_argv(_cfg(), root, "web", rep, ["--pdb"])


def test_pytest_ortami_izin_listesi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONPATH", "/kotu")
    monkeypatch.setenv("PYTHONSTARTUP", "/kotu.py")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sızmamalı")
    monkeypatch.setenv("TP_TESTVERI_DEMO_PAROLA", "gizli")
    monkeypatch.setenv("APPIUM_URL_ANDROID", "http://appium:4723/")
    monkeypatch.setenv("TP_PYTHON_E2E", "/v/bin/python")
    for k in ("TP_APP_ID_ANDROID", "TP_APP_PATH_ANDROID", "TP_APP_ACTIVITY_ANDROID"):
        monkeypatch.delenv(k, raising=False)
    req = RunRequest(sha="a" * 40, run_id="r1", break_campaign=True, fault=None, lang="python",
                     platform="web")  # fmt: skip
    env = python_run.pytest_env(_cfg(), req, "web", tmp_path / "tmp", tmp_path / "kanit")
    for k in ("PYTHONPATH", "PYTHONSTARTUP", "ANTHROPIC_API_KEY", "APPIUM_URL"):
        assert k not in env
    assert env["TP_TESTVERI_DEMO_PAROLA"] == "gizli"
    assert env["BASE_URL"] == "http://web:8080" and env["API_URL"] == "http://api:8000"
    assert env["BREAK_CAMPAIGN"] == "1" and env["TP_PLATFORM"] == "web"
    assert env["PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD"] == "1" and env["TMPDIR"] == str(tmp_path / "tmp")
    assert env["TP_KANIT_DIZINI"] == str(tmp_path / "kanit") and env["PATH"].startswith("/v/bin:")
    app = python_run.pytest_env(_cfg(), req, "android", None, tmp_path / "k")
    assert app["APPIUM_URL"] == "http://appium:4723" and app["PLATFORM"] == "android"
    assert app["APP_ID"] == "com.antreklabs.bayisiparis" and "BASE_URL" not in app


FAKE_PYTEST = """
args = sys.argv[1:]
log = pathlib.Path({log!r})
with log.open("a") as fh:
    fh.write(json.dumps({{"argv": args, "cwd": os.getcwd(),
        "env": {{k: os.environ.get(k) for k in ("TP_PLATFORM", "PYTHONPATH", "ANTHROPIC_API_KEY",
                                                 "TP_KANIT_DIZINI", "BREAK_CAMPAIGN")}}}}) + "\\n")
junit = next(a.split("=", 1)[1] for a in args if a.startswith("--junitxml="))
pathlib.Path(junit).parent.mkdir(parents=True, exist_ok=True)
pathlib.Path(junit).write_text({xml!r}, encoding="utf-8")
sys.exit({code})
"""

PASSED = """<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="1">
<testcase classname="tests.generated.test_tpd_1_c2_3f9b1c2e" name="test_tpd_1_c2_3f9b1c2e" time="1.5"/>
</testsuite></testsuites>"""


@pytest.fixture
def py_runner(env: Path, py_env: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    api = DemoApi()
    monkeypatch.setenv("DEMO_API_URL", api.url)
    monkeypatch.setenv("BASE_URL", api.url)
    monkeypatch.setenv("TP_BASE_URL", api.url)
    monkeypatch.setenv("TP_HEALTH_TIMEOUT_S", "2")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sızmamalı")
    monkeypatch.setenv("PYTHONPATH", "/kotu")
    yield api
    api.server.shutdown()


def _fake_py(tmp_path: Path, xml: str, code: int = 0) -> Path:
    return make_fake_node(
        tmp_path, FAKE_PYTEST.format(log=str(tmp_path / "py.log"), xml=xml, code=code),
        name=f"fake-py-{code}",
    )  # fmt: skip


def test_kosu_gecti_ve_duzen(
    py_runner: DemoApi, forge: Forge, env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_PYTHON_E2E", str(_fake_py(tmp_path, PASSED)))
    head = forge.commit("tp/py", _project({"e2e-python/results/sahte.txt": "eski"}))
    cfg = settings()
    loc = repos.locate(cfg, head)
    req = RunRequest(sha=head, run_id="p1", repeat_each=2, test_files=[GEN], lang="python",
                     platform="web", retries=1)  # fmt: skip
    data = python_run.execute_locked(cfg, req, loc, None)
    assert data["status"] == "passed", data["error"]
    assert data["lang"] == "python" and data["platform"] == "web"
    assert data["stats"]["expected"] == 2 and data["retries_yok_sayildi"] is True
    run_dir = env / "runs" / "p1"
    src = run_dir / "src" / "e2e-python"
    assert (src / GEN).is_file() and not (src / "results" / "sahte.txt").exists()
    junit = Path(data["junit"])
    assert junit == run_dir / "results" / "junit.xml" and junit.read_text().count("<testcase") == 2
    calls = [json.loads(x) for x in (tmp_path / "py.log").read_text().splitlines()]
    assert len(calls) == 2 and calls[0]["cwd"] == str(src)
    assert calls[0]["argv"][-2:] == ["--", GEN]
    assert calls[1]["env"]["TP_KANIT_DIZINI"] == str(src / "results" / "kanit" / "tekrar-2")
    assert calls[0]["env"]["PYTHONPATH"] is None and calls[0]["env"]["ANTHROPIC_API_KEY"] is None
    assert calls[0]["env"]["TP_PLATFORM"] == "web"
    assert not (run_dir / "tmp").exists()
    assert json.loads((run_dir / "run.json").read_text())["status"] == "passed"


def test_kosu_kilit_farkliysa_kosmaz(
    py_runner: DemoApi, forge: Forge, env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_PYTHON_E2E", str(_fake_py(tmp_path, PASSED)))
    head = forge.commit("tp/py", _project({"e2e-python/requirements.lock": "x==1\n"}))
    cfg = settings()
    req = RunRequest(sha=head, run_id="p2", lang="python", platform="web")
    data = python_run.execute_locked(cfg, req, repos.locate(cfg, head), None)
    assert data["status"] == "error" and "güvenilir kilit" in data["error"]
    assert not (tmp_path / "py.log").exists()


def test_kosu_toplama_hatasi(
    py_runner: DemoApi, forge: Forge, env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = '<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="0"/></testsuites>'
    monkeypatch.setenv("TP_PYTHON_E2E", str(_fake_py(tmp_path, empty, code=2)))
    head = forge.commit("tp/py", _project())
    cfg = settings()
    req = RunRequest(sha=head, run_id="p3", repeat_each=3, lang="python", platform="web")
    data = python_run.execute_locked(cfg, req, repos.locate(cfg, head), None)
    assert data["status"] == "error" and "toplanamadı" in data["error"]
    assert len((tmp_path / "py.log").read_text().splitlines()) == 1  # sonraki tekrarlar koşmaz
