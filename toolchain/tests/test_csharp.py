"""C# hattı (014 Ş2): worker eklentisi (kilit, koruma, derleme argümanları, ortam), runner eklentisi
(JUnit normalleştirme, sınıflandırma, koşu akışı sahte `dotnet` ile) ve gerçek araçla duman.

`data/csharp/junit-ham.xml` gerçek JunitXml.TestLogger 8.1.0 çıktısıdır (NUnit 4.6.1; assertion,
System.TimeoutException, SetUp hatası, atlanan ve geçen test); `@KOK@` proje köküdür.
Gerçek `cs-araclar` testleri `dotnet` + yayımlanmış araç (`TP_CS_ARACLAR_DLL`) yoksa atlanır.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from runner import surefire
from runner.diller import csharp_run as csr
from runner.run import RunRequest
from tests.conftest import REPO, TOOLCHAIN, Forge, make_fake_node
from tests.test_runner import DemoApi
from toolchain_common.settings import settings
from worker.diller import csharp as cs

DATA = Path(__file__).resolve().parent / "data" / "csharp"
DEMO_WEB = REPO / "demo-app" / "e2e-csharp"
DEMO_WIN = REPO / "demo-app" / "e2e-app-csharp"
DEPS = TOOLCHAIN / "e2e-csharp-deps"
GEN_WEB = "Tests/Generated/TPD1WebC2_3f9b1c2eTests.cs"
GEN_WIN = "Tests/Generated/TPD1WindowsC2_3f9b1c2eTests.cs"


@pytest.fixture
def deps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "e2e-csharp-deps"
    shutil.copytree(DEPS, d)
    (d / "nuget").mkdir()
    monkeypatch.setenv("TP_E2E_CSHARP_DEPS", str(d))
    return d


def _proje_kopyasi(kaynak: Path, hedef: Path) -> Path:
    shutil.copytree(
        kaynak, hedef, ignore=shutil.ignore_patterns("bin", "obj", "results", "TestResults")
    )
    return hedef


# ----------------------------------------------------------------------------- ayarlar


def test_ayarlar_varsayilan_ve_ortam(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("TP_E2E_CSHARP_ROOT", "TP_E2E_APP_CSHARP_ROOT", "TP_E2E_CSHARP_DEPS", "TP_DOTNET"):
        monkeypatch.delenv(k, raising=False)
    a = cs.cs_ayarlari(settings())
    assert (a.e2e_csharp_root, a.e2e_app_csharp_root) == ("e2e-csharp", "e2e-app-csharp")
    assert a.deps == Path("/opt/e2e-csharp") and a.dotnet == "/usr/share/dotnet/dotnet"
    monkeypatch.setenv("TP_E2E_CSHARP_ROOT", "demo-app/e2e-csharp")
    kok = cs.cs_kok(settings(), "web")
    assert kok.root == "demo-app/e2e-csharp" and kok.proje == "Antreklabs.Bayi.E2e.csproj"
    win = cs.cs_kok(settings(), "windows")
    assert (
        win.kilitli[0] == "Antreklabs.Bayi.E2eApp.csproj"
        and win.kimlikler == "Ekranlar/Kimlikler.cs"
    )
    with pytest.raises(ValueError):
        cs.cs_kok(settings(), "android")


def test_check_adi_ve_test_dosyasi() -> None:
    assert cs.check_name("web") == "local-ci-web-csharp"
    assert cs.check_name(None) == "local-ci-web-csharp"
    assert cs.check_name("windows") == "local-ci-windows-csharp"
    with pytest.raises(ValueError):
        cs.check_name("ios")
    assert cs.validate_test_files([GEN_WEB, GEN_WEB, "Tests/GirisTests.cs"]) == [
        GEN_WEB, "Tests/GirisTests.cs",
    ]  # fmt: skip
    for kotu in ("Birim/XTests.cs", "Tests/../x/YTests.cs", "Tests/X.java", "/Tests/XTests.cs",
                 "Tests/XTests.cs\n"):  # fmt: skip
        with pytest.raises(ValueError):
            cs.validate_test_file(kotu)


def test_dotnet_ortami_izin_listesi(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DOTNET_STARTUP_HOOKS", "/kotu.dll")
    monkeypatch.setenv("MSBuildExtensionsPath", "/kotu")
    monkeypatch.setenv("NUGET_PLUGIN_PATHS", "/kotu")
    monkeypatch.setenv("PLATFORM", "windows")
    monkeypatch.setenv("CORECLR_PROFILER", "{x}")
    env = cs.dotnet_env(tmp_path / "h", tmp_path / "n")
    for k in ("DOTNET_STARTUP_HOOKS", "MSBuildExtensionsPath", "NUGET_PLUGIN_PATHS", "PLATFORM",
              "CORECLR_PROFILER"):  # fmt: skip
        assert k not in env
    assert env["NUGET_PACKAGES"] == str(tmp_path / "n") and env["MSBUILDDISABLENODEREUSE"] == "1"
    assert env["DOTNET_CLI_TELEMETRY_OPTOUT"] == "1" and env["HOME"] == str(tmp_path / "h")


def test_restore_ve_build_argumanlari(deps: Path, tmp_path: Path) -> None:
    kok = cs.cs_kok(settings(), "web")
    r = cs.restore_argv(settings(), tmp_path, kok)
    assert r[1] == "restore" and "--locked-mode" in r
    assert r[r.index("--source") + 1] == str(deps / "nuget")
    assert f"-p:RestoreFallbackFolders={deps / 'nuget'}" in r
    b = cs.build_argv(settings(), tmp_path, kok)
    assert b[1] == "build" and "--no-restore" in b and "-warnaserror" in b
    assert "-p:UseSharedCompilation=false" in b and "-nodeReuse:false" in b


def test_derleme_tanilari() -> None:
    root = Path("/k/e2e-csharp")
    cikti = (
        "/k/e2e-csharp/Tests/Generated/XTests.cs(12,9): error CS0117: 'LoginPage' does not "
        "contain a definition for 'GirisAsync' [/k/e2e-csharp/Antreklabs.Bayi.E2e.csproj]\n"
        "/k/e2e-csharp/Tests/Generated/XTests.cs(12,9): error CS0117: 'LoginPage' does not "
        "contain a definition for 'GirisAsync' [/k/e2e-csharp/Antreklabs.Bayi.E2e.csproj]\n"
        "Pages/Ekran.cs(3,1): warning CS8618: alan null [/k/e2e-csharp/x.csproj]\n"
    )
    d = cs.parse_compile(cikti, root)
    assert len(d) == 2
    assert d[0] == {
        "file": "Tests/Generated/XTests.cs", "line": 12, "column": 9, "severity": "error",
        "code": "CS0117", "message": "'LoginPage' does not contain a definition for 'GirisAsync'",
    }  # fmt: skip
    assert d[1]["severity"] == "warning"


# -------------------------------------------------------------------------------- deps


@pytest.mark.parametrize(("kaynak", "platform"), [(DEMO_WEB, "web"), (DEMO_WIN, "windows")])
def test_deps_demo_projeleri_gecer(deps: Path, tmp_path: Path, kaynak: Path, platform: str) -> None:
    root = _proje_kopyasi(kaynak, tmp_path / "p")
    r = cs.check_deps(settings(), root, cs.cs_kok(settings(), platform))
    assert r["ok"], r
    assert set(r["sha256"]) == set(cs.cs_kok(settings(), platform).kilitli)


@pytest.mark.parametrize(
    ("degisiklik", "beklenen"),
    [
        (
            lambda r: (r / "Antreklabs.Bayi.E2e.csproj").write_text("<Project/>"),
            "güvenilir kopyadan farklı",
        ),
        (lambda r: (r / "packages.lock.json").unlink(), "yok"),
        (lambda r: (r / "Directory.Build.props").write_text("<Project/>"), "Directory.Build.props"),
        (lambda r: (r / "Directory.Build.rsp").write_text("-p:x=1"), "Directory.Build.rsp"),
        (lambda r: (r / "Tests" / "kotu.targets").write_text("<Project/>"), "kotu.targets"),
        (lambda r: (r / "E2e.slnx").write_text("<Solution/>"), "E2e.slnx"),
        (lambda r: (r / "global.json").write_text("{}"), "global.json"),
        (lambda r: (r / "Tests" / "NuGet.Config").write_text("<configuration/>"), "NuGet.Config"),
        (
            lambda r: (
                (r / "obj").mkdir() or (r / "obj" / "x.nuget.g.props").write_text("<Project/>")
            ),
            "obj",
        ),
        (lambda r: (r / "lib.dll").write_bytes(b"MZ"), "lib.dll"),
        (lambda r: (r / "Tests" / "bag.cs").symlink_to("/etc/passwd"), "sembolik bağ"),
    ],
)
def test_deps_reddeder(deps: Path, tmp_path: Path, degisiklik: Any, beklenen: str) -> None:
    root = _proje_kopyasi(DEMO_WEB, tmp_path / "p")
    degisiklik(root)
    r = cs.check_deps(settings(), root, cs.cs_kok(settings(), "web"))
    assert not r["ok"] and beklenen in r["error"], r


def test_deps_imajda_kopya_yoksa(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_E2E_CSHARP_DEPS", str(tmp_path / "yok"))
    root = _proje_kopyasi(DEMO_WEB, tmp_path / "p")
    r = cs.check_deps(settings(), root, cs.cs_kok(settings(), "web"))
    assert not r["ok"] and "toolchain imajı hatalı" in r["error"]


def test_guvenilir_kopyalar_demo_ile_bayt_esit() -> None:
    for proje, d in ((DEMO_WEB, "web"), (DEMO_WIN, "windows")):
        for f in sorted((DEPS / d).iterdir()):
            assert f.read_bytes() == (proje / f.name).read_bytes(), f


def test_run_static_eksik_test_dosyasi(deps: Path, tmp_path: Path) -> None:
    root = _proje_kopyasi(DEMO_WEB, tmp_path / "p")
    steps = cs.run_static(
        settings(), tmp_path, "h", "b", root, cs.cs_kok(settings(), "web"),
        test_files=["Tests/Generated/YokTests.cs"],
    )  # fmt: skip
    assert list(steps) == ["deps"] and steps["deps"]["missing_test_files"]


# ------------------------------------------------------------------ gerçek araç (isteğe bağlı)


def _arac() -> Path | None:
    dll = os.environ.get("TP_CS_ARACLAR_DLL")
    if dll and Path(dll).is_file() and shutil.which("dotnet"):
        return Path(dll)
    return None


@pytest.fixture
def gercek_arac(monkeypatch: pytest.MonkeyPatch) -> Path:
    dll = _arac()
    if dll is None:
        pytest.skip("cs-araclar yayımlanmamış (TP_CS_ARACLAR_DLL) ya da dotnet yok")
    monkeypatch.setenv("TP_DOTNET", shutil.which("dotnet") or "dotnet")
    return dll


@pytest.mark.parametrize(
    ("kaynak", "platform", "gen"), [(DEMO_WEB, "web", GEN_WEB), (DEMO_WIN, "windows", GEN_WIN)]
)
def test_gercek_guard_ve_semboller(
    gercek_arac: Path, tmp_path: Path, kaynak: Path, platform: str, gen: str
) -> None:
    root = _proje_kopyasi(kaynak, tmp_path / "p")
    kok = cs.cs_kok(settings(), platform)
    rapor = cs.run_guard(settings(), root, kok)
    assert rapor["ok"], rapor["violations"]
    t = cs.symbols(settings(), root, kok)
    assert t["lang"] == "csharp" and t["errors"] == [] and t["fixtures"]
    # Bozuk üretilen test yakalanır.
    p = root / gen
    p.write_text(
        p.read_text(encoding="utf-8").replace('("bayi1"', "(System.Environment.UserName"),
        encoding="utf-8",
    )
    rapor = cs.run_guard(settings(), root, kok)
    assert not rapor["ok"]


# ------------------------------------------------------------------- runner: normalleştirme


def _ham(tmp_path: Path, kok: Path) -> Path:
    p = tmp_path / "junit-ham.xml"
    p.write_text((DATA / "junit-ham.xml").read_text(encoding="utf-8").replace("@KOK@", str(kok)))
    return p


def test_normalize_ve_siniflandirma(tmp_path: Path) -> None:
    kok = tmp_path / "kok"
    (kok / "Tests" / "Generated").mkdir(parents=True)
    rep = surefire.Repeat(0, tmp_path / "r", tmp_path / "kanit")
    konumlar = csr.normalize_junit(
        _ham(tmp_path, kok), rep.reports_dir / csr.NORMAL_JUNIT, "web", kok
    )
    ozet = surefire.summarize([rep], project="chromium")
    csr._cs_konumlari(ozet, {0: konumlar})
    testler = {t["title"]: t for t in ozet["tests"]}
    assert ozet["stats"]["expected"] == 1 and ozet["stats"]["unexpected"] == 3
    assert ozet["stats"]["skipped"] == 1
    a = testler["TPD1WebC2_3f9b1c2eTests › Senaryo"]
    assert a["file"] == GEN_WEB
    assert a["failure"]["type"] == "assertion"
    assert a["failure"]["locator_test_id"] == "cart-total"
    assert a["failure"]["test_location"] == {
        "file": "Tests/Generated/OrnekTests.cs",
        "line": 7,
        "column": 0,
    }
    assert a["failure"]["location"] == a["failure"]["test_location"]
    z = testler["ZamanTests › Tikla"]["failure"]
    assert z["type"] == "locator_timeout" and z["locator_test_id"] == "add-to-cart"
    k = testler["KurulumTests › Senaryo"]["failure"]
    assert k["type"] == "test_data"
    assert k["message"].startswith("demo API /test/reset")  # önek kaldırıldı
    xml = (rep.reports_dir / csr.NORMAL_JUNIT).read_text(encoding="utf-8")
    assert 'csharp-type="System.TimeoutException"' in xml and "GetByTestId" not in xml


def test_windows_assertion_bekle_bicimi(tmp_path: Path) -> None:
    ham = tmp_path / "h.xml"
    ham.write_text(
        "<testsuites><testsuite>"
        '<testcase classname="Antreklabs.Bayi.Tests.SepetTests" name="Kampanya">'
        '<failure type="failure" message="sepet toplamı: beklenen &lt;150,00 TL&gt;, görülen '
        '&lt;175,00 TL&gt; (5000 ms)">at x</failure></testcase>'
        '<testcase classname="Antreklabs.Bayi.Tests.GirisTests" name="Giris">'
        '<failure type="failure" message="OpenQA.Selenium.WebDriverTimeoutException : Expected '
        "condition failed: öğe görünmedi: kimlik 'login-username' (tried for 5 second(s) with 250 "
        'milliseconds interval)">at y</failure></testcase></testsuite></testsuites>',
        encoding="utf-8",
    )
    rep = surefire.Repeat(0, tmp_path / "r", tmp_path / "kanit")
    csr.normalize_junit(ham, rep.reports_dir / csr.NORMAL_JUNIT, "windows")
    ozet = surefire.summarize([rep], project="windows")
    t = {x["title"]: x["failure"] for x in ozet["tests"]}
    assert t["SepetTests › Kampanya"]["type"] == "assertion"
    assert t["SepetTests › Kampanya"]["expected"] == "150,00 TL"
    assert t["GirisTests › Giris"]["type"] == "locator_not_found"
    assert t["GirisTests › Giris"]["locator_test_id"] == "login-username"
    assert csr.red_check(ozet["tests"])["ok"] is False  # locator kırmızısı sayılmaz


def test_normalize_dtd_reddeder(tmp_path: Path) -> None:
    ham = tmp_path / "h.xml"
    ham.write_text('<!DOCTYPE x [<!ENTITY e "y">]><testsuites/>', encoding="utf-8")
    with pytest.raises(ValueError):
        csr.normalize_junit(ham, tmp_path / "o.xml", "web")


def test_suzgec_ve_dosya_yolu() -> None:
    assert csr.test_filter([]) == "Category!=birim"
    assert csr.test_filter([GEN_WEB, "Tests/GirisTests.cs"]) == (
        "FullyQualifiedName~.TPD1WebC2_3f9b1c2eTests.|FullyQualifiedName~.GirisTests."
    )
    with pytest.raises(ValueError):
        csr.test_filter(["Tests/x|y.cs"])
    assert csr.cs_dosyasi("Antreklabs.Bayi.Tests.Generated.XTests") == "Tests/Generated/XTests.cs"
    assert csr.cs_dosyasi("Baska.Ns.YTests") == "Baska/Ns/YTests.cs"


# --------------------------------------------------------------- runner: sahte dotnet ile akış


def _sahte_dotnet(tmp_path: Path, ham: str, exit_code: int = 1) -> Path:
    return make_fake_node(
        tmp_path,
        f"""
        args = sys.argv[1:]
        log = pathlib.Path({str(tmp_path / "dotnet.log")!r})
        keys = ("APPIUM_URL", "APP_ID", "DEMO_API_URL", "DEMOAPP_TEST_TOKEN", "BREAK_CAMPAIGN",
                "KANIT_DIZINI", "NUGET_PACKAGES", "PLATFORM", "DOTNET_STARTUP_HOOKS",
                "ANTHROPIC_API_KEY", "TP_FAULT", "ALLURE_CONFIG", "TP_TESTVERI_BAYI1_PAROLA")
        with log.open("a") as fh:
            fh.write(json.dumps({{"argv": args, "cwd": os.getcwd(),
                                  "env": {{k: os.environ.get(k) for k in keys}}}}) + "\\n")
        if args[0] == "test":
            lf = next(a.split("LogFilePath=", 1)[1] for a in args if a.startswith("junit;"))
            p = pathlib.Path(lf); p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text({ham!r}.replace("@KOK@", os.getcwd()), encoding="utf-8")
            kd = pathlib.Path(os.environ["KANIT_DIZINI"]) / "TPD1WebC2_3f9b1c2eTests.Senaryo"
            kd.mkdir(parents=True, exist_ok=True)
            (kd / "ekran.png").write_bytes(b"png")
            sys.exit({exit_code})
        sys.exit(0)
        """,
        name=f"fake-dotnet-{exit_code}",
    )


def _calls(tmp_path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in (tmp_path / "dotnet.log").read_text().splitlines()]


@pytest.fixture
def cs_runner(env: Path, deps: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    api = DemoApi()
    monkeypatch.setenv("DEMO_API_URL", api.url)
    monkeypatch.setenv("APPIUM_URL_WINDOWS", f"{api.url}/appium")
    monkeypatch.setenv("TP_APP_ID_WINDOWS", "Antreklabs.BayiSiparis")
    monkeypatch.setenv("TP_HEALTH_TIMEOUT_S", "2")
    monkeypatch.setenv("DOTNET_STARTUP_HOOKS", "/kotu.dll")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sızmamalı")
    monkeypatch.setenv("TP_TESTVERI_BAYI1_PAROLA", "gizli")
    yield api
    api.server.shutdown()


def _win_dosyalari() -> dict[str, str]:
    out = {}
    for f in (DEPS / "windows").iterdir():
        out[f"e2e-app-csharp/{f.name}"] = f.read_text(encoding="utf-8")
    out[f"e2e-app-csharp/{GEN_WIN}"] = (DEMO_WIN / GEN_WIN).read_text(encoding="utf-8")
    return out


def test_csharp_kosu_akisi_windows(
    cs_runner: DemoApi, forge: Forge, env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from runner import run as runmod
    from toolchain_common import repos

    monkeypatch.setenv(
        "TP_DOTNET", str(_sahte_dotnet(tmp_path, (DATA / "junit-ham.xml").read_text()))
    )
    head = forge.commit("tp/cs", _win_dosyalari())
    cfg = settings()
    loc = repos.locate(cfg, head)
    req = RunRequest(
        sha=head, run_id="cs1", test_files=[GEN_WIN], lang="csharp", platform="windows"
    )
    data = csr.execute_locked(cfg, req, loc, None)
    assert data["lang"] == "csharp" and data["platform"] == "windows"
    assert data["status"] == "failed", data["error"]
    assert data["stats"]["unexpected"] == 3 and data["stats"]["expected"] == 1
    assert cs_runner.gets == ["/health", "/appium/status"]
    komutlar = [c["argv"][0] for c in _calls(tmp_path)]
    assert komutlar == ["restore", "build", "test"]
    test_cagrisi = _calls(tmp_path)[-1]
    assert "--no-build" in test_cagrisi["argv"]
    filt = test_cagrisi["argv"][test_cagrisi["argv"].index("--filter") + 1]
    assert filt == "FullyQualifiedName~.TPD1WindowsC2_3f9b1c2eTests."
    e = test_cagrisi["env"]
    assert (
        e["DOTNET_STARTUP_HOOKS"] is None
        and e["ANTHROPIC_API_KEY"] is None
        and e["PLATFORM"] is None
    )
    assert e["APPIUM_URL"] == f"{cs_runner.url}/appium" and e["APP_ID"] == "Antreklabs.BayiSiparis"
    assert e["TP_TESTVERI_BAYI1_PAROLA"] == "gizli" and e["DEMOAPP_TEST_TOKEN"] == "test-belirteci"
    run = env / "runs" / "cs1"
    assert e["KANIT_DIZINI"] == str(run / "src" / "e2e-app-csharp" / "results" / "kanit")
    assert e["NUGET_PACKAGES"].startswith(str(run / "tmp"))
    assert not (run / "tmp").exists()  # geçici ev / paket dizini silindi
    junit = Path(data["junit"])
    assert junit == run / "results" / "junit.xml" and junit.read_text().count("<testcase") == 5
    dosyalar = {t["title"]: t["file"] for t in data["tests"]}
    assert (
        dosyalar["TPD1WebC2_3f9b1c2eTests › Senaryo"]
        == "Tests/Generated/TPD1WebC2_3f9b1c2eTests.cs"
    )
    hata = next(t for t in data["tests"] if t["title"] == "TPD1WebC2_3f9b1c2eTests › Senaryo")
    assert hata["failure"]["evidence"]["screenshot"]["exists"] is True
    assert hata["failure"]["test_location"]["line"] == 7
    assert runmod  # içe aktarma (RunRejected vb.) kullanılabilir


def test_csharp_kosu_kilit_ihlalinde_kosmaz(
    cs_runner: DemoApi, forge: Forge, env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from toolchain_common import repos

    monkeypatch.setenv("TP_DOTNET", str(_sahte_dotnet(tmp_path, "<testsuites/>")))
    dosyalar = _win_dosyalari()
    dosyalar["e2e-app-csharp/Directory.Build.targets"] = "<Project><Target Name='x'/></Project>"
    head = forge.commit("tp/cs2", dosyalar)
    cfg = settings()
    data = csr.execute_locked(
        cfg, RunRequest(sha=head, run_id="cs2", lang="csharp", platform="windows"),
        repos.locate(cfg, head), None,
    )  # fmt: skip
    assert data["status"] == "error" and "Directory.Build.targets" in data["error"]
    assert not (tmp_path / "dotnet.log").exists()


def test_csharp_kosu_platform_ve_grep_reddi(env: Path, forge: Forge) -> None:
    from runner import run as runmod
    from toolchain_common import repos

    cfg = settings()
    loc = repos.locate(cfg, forge.main)
    with pytest.raises(runmod.RunRejected):
        csr.execute_locked(
            cfg, RunRequest(sha=forge.main, run_id="x1", lang="csharp", platform="ios"), loc, None
        )
    with pytest.raises(runmod.RunRejected):
        csr.execute_locked(
            cfg, RunRequest(sha=forge.main, run_id="x2", lang="csharp", grep="a"), loc, None
        )


def test_dotnet_kurulu_ise_surum_10() -> None:
    if not shutil.which("dotnet"):
        pytest.skip("dotnet yok")
    out = subprocess.run(["dotnet", "--list-sdks"], capture_output=True, text=True, check=False)
    assert "10." in out.stdout


def test_eklenti_kaydi_ve_kontrol_adi() -> None:
    """Entegrasyon: Ş0 keşfi C# worker/runner eklentisini bulur; `lang=csharp` gövdeleri ve check
    adı eklentiden."""
    from runner import diller as runner_diller
    from worker import check as checkmod
    from worker import diller as worker_diller

    e = worker_diller.eklenti("csharp")
    assert e is not None and e.steps == cs.STEPS and e.platformlar == ("web", "windows")
    assert runner_diller.eklenti("csharp") is not None
    assert worker_diller.resolve_lang("csharp", "windows") == "csharp"
    with pytest.raises(ValueError):
        worker_diller.resolve_lang("csharp", "android")
    assert checkmod.check_name("csharp", "windows") == "local-ci-windows-csharp"
    assert checkmod.check_name("csharp", None) == cs.check_name(None)
