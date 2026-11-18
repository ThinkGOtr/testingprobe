"""C# (NUnit) koşusu (014 test dilleri §3.2, Ş2) — iki hedef proje, tek hat:

- web: `demo-app/e2e-csharp` (Playwright .NET); sağlık kontrolü TS koşusuyla aynı (web origin +
  demo API); tarayıcı imajdaki `/ms-playwright`, indirme kapalı.
- windows: `demo-app/e2e-app-csharp` (Appium .NET, NovaWindows); sağlık kontrolü demo API +
  `APPIUM_URL_WINDOWS/status` (`java_run.health_check` ile aynı). Uygulama/cihaz ayarları
  `java_run.app_settings("windows")` ile aynı kaynaktan (`TP_APP_*_WINDOWS`, proje bloğu).

Akış `runner/java_run.py` ile aynıdır (kilit, koşu dizini, kırılma geri alma, rapor biçimi):

  1. Sağlık başarısızsa koşu yapılmaz (`error`; triage kuralı 1: `environment`).
  2. Commit'in proje ağacı `runs/<id>/src/<kök>`'e çıkarılır; bağımlılık kilidi
     (`worker.diller.csharp.check_deps`) burada da denetlenir (savunma derinliği).
  3. Çevrimdışı kilitli restore + `dotnet build -warnaserror` bir kez (`restore_and_build`), sonra
     tekrar başına (`repeat_each`) `dotnet test --no-build` + JUnit günlükçüsü
     (`JunitXml.TestLogger`) → `results/tekrar-<n>/junit-ham.xml`; kapsam `test_files` →
     `--filter FullyQualifiedName~.<Sınıf>.` (birleşik `|`), yoksa `Category!=birim`.
  4. Ham JUnit normalleştirilir (`normalize_junit`): JunitXml.TestLogger hata türünü `type`
     özniteliğine yazmaz (hep `failure`), iletinin başına `<Tam.Tür> : ` koyar; NUnit
     `AssertionException` iletisi öneksizdir. Tür çıkarılır ve Surefire sınıflandırıcısının
     (`runner/surefire.classify`) bildiği karşılığa çevrilir; ileti öneksiz kalır. Böylece özet,
     `failure.type`, kırmızı adım denetimi ve tek `junit.xml` Java yoluyla aynı koddan çıkar.
     Test dosyası `Tests/…/<Sınıf>.cs` olur (Java `src/test/java/…` değil).
  5. Kırılma / ekilmiş hata geri alma ve kırmızı denetimi `java_run` ile aynıdır.

Tür eşlemesi (deneysel olarak doğrulandı: demo-app/e2e-csharp ve e2e-app-csharp README);
C# türü (ileti öneki) → Surefire sınıflandırıcısına verilen tür:

- önek yok / `NUnit.Framework.AssertionException`: web → `org.opentest4j.AssertionFailedError`
  (Playwright metni "Locator expected…"), windows → `java.lang.AssertionError` (Bekle: "beklenen
  <x>, görülen <y> (N ms)");
- `System.TimeoutException` (Playwright eylem zaman aşımı) →
  `com.microsoft.playwright.TimeoutError`;
- `Microsoft.Playwright.PlaywrightException` → `com.microsoft.playwright.PlaywrightException`;
- `OpenQA.Selenium.WebDriverTimeoutException` → `org.openqa.selenium.TimeoutException`;
- `OpenQA.Selenium.NoSuchElementException` → `org.openqa.selenium.NoSuchElementException`;
- `SetUp : …`: aynı tür; ileti `/test/`, `giriş başarısız`, `DEMOAPP_TEST_TOKEN` içerirse
  `test_data`.

Playwright .NET çağrı günlüğü `GetByTestId("x")` yazar; sınıflandırıcı Java/TS yazımını
(`getByTestId`) bekler: normalleştirmede `GetBy<Tür>(` → `getBy<Tür>(` çevrilir.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from runner import surefire
from runner.results import MAX_ERROR, MAX_FIELD, _clip, decide_status, failure_groups, failures_of
from runner.run import testveri_env
from toolchain_common import gitforge, proc, repos
from toolchain_common.artifacts import KEEP_MARKER, atomic_write_json, run_dir
from toolchain_common.settings import Settings, kosu_parola_env
from worker.diller import csharp as csyol

if TYPE_CHECKING:  # pragma: no cover
    from runner.run import RunRequest

WEB = csyol.WEB
WINDOWS = csyol.WINDOWS
WEB_PROJECT = "chromium"
BROWSERS_PATH = "/ms-playwright"
NAMESPACE_ONEKI = "Antreklabs.Bayi."
PASS_ENV = ("PATH", "LANG", "LC_ALL", "TZ")
SONUC_DIZINI = "results"
HAM_JUNIT = "junit-ham.xml"
NORMAL_JUNIT = "TEST-csharp.xml"
# "SetUp : Tür : ileti" / "Tür : ileti" (JunitXml.TestLogger; NUnit sonuç iletisi biçimi).
_ONEK_RE = re.compile(
    r"\A(?P<asama>(?:OneTime)?(?:SetUp|TearDown) : )?"
    r"(?P<tur>[A-Za-z_][\w.`]*(?:Exception|Error)) : ",
)
_GETBY_RE = re.compile(r"\bGetBy(TestId|Role|Text|Label|Placeholder|AltText|Title)\(")
_CS_FRAME_RE = re.compile(
    r"^\s*at (?P<yer>[\w.<>`+]+)\(.*?\) in (?P<dosya>.+?\.cs):line (?P<satir>\d+)", re.M
)
_TUR_ESLEME = {
    "System.TimeoutException": "com.microsoft.playwright.TimeoutError",
    "Microsoft.Playwright.PlaywrightException": "com.microsoft.playwright.PlaywrightException",
    "OpenQA.Selenium.WebDriverTimeoutException": "org.openqa.selenium.TimeoutException",
    "OpenQA.Selenium.NoSuchElementException": "org.openqa.selenium.NoSuchElementException",
}
_ASSERTION_TURLERI = frozenset(
    {"NUnit.Framework.AssertionException", "NUnit.Framework.MultipleAssertException"}
)


class CsRunRejected(ValueError):
    pass


def project_name(platform: str) -> str:
    return WEB_PROJECT if platform == WEB else platform


def test_filter(test_files: list[str]) -> str:
    """`Tests/Generated/XTests.cs` → `FullyQualifiedName~.XTests.` (birleşik `|`); boşsa birim
    testleri hariç tümü."""
    if not test_files:
        return "Category!=birim"
    parcalar = []
    for f in test_files:
        csyol.validate_test_file(f)
        parcalar.append(f"FullyQualifiedName~.{Path(f).stem}.")
    return "|".join(parcalar)


def cs_dosyasi(classname: str) -> str:
    """`Antreklabs.Bayi.Tests.Generated.XTests` → `Tests/Generated/XTests.cs` (kurala uymayan ad
    olduğu gibi kırpılır)."""
    if not re.fullmatch(r"(?:[A-Za-z_]\w*\.)*[A-Za-z_]\w*", classname or ""):
        return _clip(classname, MAX_FIELD)
    ad = classname.removeprefix(NAMESPACE_ONEKI)
    return ad.replace(".", "/") + ".cs"


def _tur_ve_ileti(message: str, platform: str) -> tuple[str, str, str | None]:
    """(sınıflandırıcı türü, öneksiz ileti, özgün C# türü)."""
    m = _ONEK_RE.match(message or "")
    if m is None:
        ozgun = "NUnit.Framework.AssertionException"
        govde = message or ""
    else:
        ozgun = m.group("tur")
        govde = message[m.end() :]
    if ozgun in _ASSERTION_TURLERI:
        tur = surefire.PLAYWRIGHT_ASSERTION if platform == WEB else surefire.ASSERTION
    else:
        tur = _TUR_ESLEME.get(ozgun, ozgun)
    return tur, _GETBY_RE.sub(lambda x: f"getBy{x.group(1)}(", govde), ozgun


def normalize_junit(
    ham: Path, hedef: Path, platform: str, kok: Path | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Ham JUnit (JunitXml.TestLogger) → Surefire biçimli `TEST-csharp.xml`. Dönen: başarısız
    testlerin (`<classname>.<name>`) proje köküne göre yığın konumları (`kok` verilmişse).
    Ham dosya test kodunun çıktısıdır: `surefire.parse_xml` (DTD reddi, boyut sınırı) ile okunur."""
    root = surefire.parse_xml(ham)
    out = ET.Element("testsuite", {"name": "csharp"})
    konumlar: dict[str, list[dict[str, Any]]] = {}
    for n, tc in enumerate(root.iter("testcase")):
        if n >= 2000:
            break
        attrs = {k: _clip(tc.get(k), MAX_FIELD) for k in ("classname", "name", "time") if tc.get(k)}
        yeni = ET.SubElement(out, "testcase", attrs)
        child = surefire._result_child(tc)
        if child is not None:
            if child.tag == "skipped":
                ET.SubElement(yeni, "skipped")
            else:
                tur, ileti, ozgun = _tur_ve_ileti(child.get("message") or "", platform)
                c = ET.SubElement(
                    yeni, "failure", {"type": _clip(tur, 200), "message": _clip(ileti, MAX_ERROR),
                                      "csharp-type": _clip(ozgun or "", 200)},
                )  # fmt: skip
                govde = (child.text or "").strip()
                c.text = _clip(_GETBY_RE.sub(lambda x: f"getBy{x.group(1)}(", govde), 8000) or None
                if kok is not None:
                    anahtar = f"{attrs.get('classname', '')}.{attrs.get('name', '')}"
                    metin = f"{child.get('message') or ''}\n{govde}"
                    konumlar[anahtar] = cs_cerceveler(metin, kok)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{hedef.name}.", suffix=".tmp", dir=hedef.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            ET.ElementTree(out).write(fh, encoding="utf-8", xml_declaration=True)
        os.replace(tmp, hedef)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return konumlar


def cs_cerceveler(metin: str, kok: Path) -> list[dict[str, Any]]:
    """.NET yığını (`at Ns.Sinif.Metot(...) in /yol/Dosya.cs:line 45`) → proje köküne göre konumlar
    (yalnız projenin kendi dosyaları; kök dışı yol atlanır)."""
    out: list[dict[str, Any]] = []
    for m in _CS_FRAME_RE.finditer(metin):
        try:
            rel = Path(m.group("dosya")).resolve().relative_to(kok.resolve()).as_posix()
        except (ValueError, OSError):
            continue
        out.append({"file": rel, "line": int(m.group("satir")), "column": 0, "yer": m.group("yer")})
        if len(out) >= 50:
            break
    return out


def _cs_konumlari(
    summary: dict[str, Any], konumlar: dict[int, dict[str, list[dict[str, Any]]]]
) -> None:
    """Özetteki Java varsayımlı alanları C#'a çevirir: `file` ve yığından konum."""
    for t in summary.get("tests") or []:
        temel, _, tekrar = t["id"].rpartition("#")
        classname = temel.rsplit(".", 1)[0]
        t["file"] = cs_dosyasi(classname)
        f = t.get("failure")
        if not f:
            continue
        try:
            rep = int(tekrar.split(".", 1)[0])
        except ValueError:
            rep = 0
        cerceveler = (konumlar.get(rep) or {}).get(temel) or []

        def konum(c: dict[str, Any] | None) -> dict[str, Any] | None:
            return {k: c[k] for k in ("file", "line", "column")} if c else None

        test_loc = konum(
            next(
                (c for c in cerceveler
                 if c["file"] == t["file"] or c.get("yer", "").startswith(f"{classname}.")),
                None,
            )
        )  # fmt: skip
        sayfa = konum(
            next((c for c in cerceveler if c["file"].startswith(("Pages/", "Ekranlar/"))), None)
        )
        f["test_location"] = test_loc
        f["location"] = sayfa or test_loc
        f["page_location"] = sayfa


def health_check(cfg: Settings, platform: str, client: httpx.Client | None = None) -> dict:
    from runner import java_run

    return java_run.health_check(cfg, platform, client)


def test_env(
    cfg: Settings,
    req: RunRequest,
    platform: str,
    kanit: Path,
    allure_cfg: Path,
    home: Path,
    pkgs: Path,
) -> dict[str, str]:
    """İzin listesi ortam (dotnet ortamı `csyol.dotnet_env`) + hedef proje ayarları."""
    from runner import java_run

    env = csyol.dotnet_env(home, pkgs, {k: os.environ[k] for k in PASS_ENV if k in os.environ})
    env.update(testveri_env())
    env.update(kosu_parola_env(cfg))  # hesap başına parola (iskelet `Bayiler.Sec` okur)
    env.update(
        {
            "CI": "1",
            "KANIT_DIZINI": str(kanit),
            "ALLURE_CONFIG": str(allure_cfg),
            "DEMO_API_URL": cfg.demo_api_url,
            "DEMOAPP_TEST_TOKEN": cfg.demoapp_test_token,
            "BREAK_CAMPAIGN": "1" if req.break_campaign else "",
            "TP_FAULT": req.fault or "",
            "TP_RUN_ID": req.run_id,
        }
    )
    if platform == WEB:
        env.update(
            {
                "BASE_URL": cfg.base_url,
                "API_URL": cfg.demo_api_url,
                "PLAYWRIGHT_BROWSERS_PATH": os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
                or BROWSERS_PATH,
                "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
                "HEADLESS": "true",
            }
        )
        return env
    env.update(java_run.app_settings(platform, cfg))
    # PLATFORM MSBuild özelliğine dönüşür; `dotnet test --no-build` yine de proje değerlendirir.
    # Proje `Platform=AnyCPU` sabitler; e2e-app-csharp Ayarlar `TP_PLATFORM`'u da okur.
    env.update({"TP_PLATFORM": platform, "APPIUM_URL": java_run.appium_url(platform)})
    return env


def test_argv(cfg: Settings, root: Path, kok: csyol.CsKok, filtre: str, sonuc: Path) -> list[str]:
    a = csyol.cs_ayarlari(cfg)
    return [
        a.dotnet,
        "test",
        str(root / kok.proje),
        "--no-build",
        "--no-restore",
        "-c",
        "Release",
        "--filter",
        filtre,
        "--logger",
        f"junit;LogFilePath={sonuc / HAM_JUNIT}",
        "--results-directory",
        str(sonuc / "trx"),
        "--disable-build-servers",
        "-nodeReuse:false",
        "-p:Platform=AnyCPU",
        "-nologo",
    ]


def _repeats(results: Path, n: int) -> list[surefire.Repeat]:
    if n <= 1:
        return [surefire.Repeat(0, results / "tekrar-1", results / "kanit")]
    return [
        surefire.Repeat(i, results / f"tekrar-{i + 1}", results / "kanit" / f"tekrar-{i + 1}")
        for i in range(n)
    ]


def red_check(tests: list[dict[str, Any]]) -> dict[str, Any]:
    from runner import java_run

    return java_run.red_check(tests)


def execute_locked(
    cfg: Settings, req: RunRequest, loc: repos.Located, http: httpx.Client | None
) -> dict[str, Any]:
    """Eklenti protokolü (TASARIM §1.3): `execute_locked(cfg, req, loc, http)`."""
    from runner import run as runmod

    platform = req.platform or WEB
    if platform not in csyol.PLATFORMS:
        raise runmod.RunRejected(f"C# koşusu platformu: {csyol.PLATFORMS}")
    if req.grep:
        raise runmod.RunRejected("C# koşusunda grep desteklenmiyor (test_files kullanın)")
    web = platform == WEB
    kok = csyol.cs_kok(cfg, platform)
    dest = run_dir(cfg.artifacts_path, req.run_id)
    try:
        dest.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise runmod.RunConflict(f"run_id zaten kullanılmış: {req.run_id}") from exc
    started = runmod.now_iso()
    base: dict[str, Any] = {
        "run_id": req.run_id,
        "sha": loc.sha,
        "lang": csyol.LANG,
        "platform": platform,
        "grep": None,
        "test_files": req.test_files,
        "repeat_each": req.repeat_each,
        "retries": req.retries,
        "break_campaign": req.break_campaign,
        "fault": req.fault,
        "workers": None,
        "keep": req.keep,
        "base_url": cfg.base_url if web else None,
        "appium_url": None,
        "artifacts_dir": str(dest),
        "baslangic": started,
    }
    if req.keep:
        (dest / KEEP_MARKER).write_text(f"{started}\n", encoding="utf-8")
    atomic_write_json(dest / "run.json", {**base, "status": "running"})
    saglik = health_check(cfg, platform, http)
    if not web:
        base["appium_url"] = (saglik.get("appium") or {}).get("url")

    root = dest / "src" / kok.root
    results = root / SONUC_DIZINI
    repeats = _repeats(results, req.repeat_each)
    allure_dir = results / "allure-results"
    junit_out = dest / "results" / "junit.xml"
    log_parts: list[str] = []
    error: str | None = None
    restore: dict[str, Any] | None = None
    exit_code: int | None = None
    timed_out = False
    duration_ms = 0
    ran = False
    build: dict[str, Any] | None = None
    work = dest / "tmp"
    try:
        if not saglik["ok"]:
            error = saglik["hata"]
        else:
            try:
                _export(cfg, loc, dest / "src", kok)
            except gitforge.ForgeError as exc:
                error = str(exc)
            else:
                deps = csyol.check_deps(cfg, root, kok)
                if not deps["ok"]:
                    error = deps["error"]
                else:
                    shutil.rmtree(results, ignore_errors=True)
                    build = csyol.restore_and_build(
                        cfg, root, kok, work, timeout_s=cfg.run_timeout_s,
                        base_env={k: os.environ[k] for k in PASS_ENV if k in os.environ},
                    )  # fmt: skip
                    log_parts.append(build.get("output") or "")
                    if not build["ok"]:
                        error = build.get("error") or "dotnet derleme başarısız"
                        exit_code = build.get("exit_code")
                    else:
                        ran = True
                        exit_code, timed_out, duration_ms = _run_tests(
                            cfg, req, platform, root, kok, repeats, allure_dir, log_parts, work
                        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if req.breaks_app and saglik["ok"]:
            restore = runmod.restore_break(cfg, http)

    summary: dict[str, Any] | None = None
    norm_errors: list[str] = []
    if ran:
        (dest / "runner.log").write_text("\n".join(log_parts), encoding="utf-8")
        konumlar: dict[int, dict[str, list[dict[str, Any]]]] = {}
        for rep in repeats:
            ham = rep.reports_dir / HAM_JUNIT
            if ham.is_file() and not ham.is_symlink():
                try:
                    konumlar[rep.index] = normalize_junit(
                        ham, rep.reports_dir / NORMAL_JUNIT, platform, root
                    )
                except (OSError, ValueError) as exc:
                    norm_errors.append(_clip(f"tekrar {rep.index + 1}: {exc}", MAX_ERROR))
        summary = surefire.summarize(
            repeats, project=project_name(platform), rel_root=cfg.artifacts_path
        )
        summary["errors"] = norm_errors + summary["errors"]
        _cs_konumlari(summary, konumlar)
        try:
            surefire.write_junit(repeats, junit_out, name=kok.ad)
        except OSError as exc:
            summary["errors"].append(f"junit.xml yazılamadı: {type(exc).__name__}")
        if timed_out:
            error = f"Koşu süre sınırını aştı ({int(cfg.run_timeout_s)} sn); süreç durduruldu."
    status = (
        "error"
        if not ran
        else decide_status(exit_code=exit_code, timed_out=timed_out, summary=summary)
    )
    if status == "error" and error is None:
        if summary and summary["errors"]:
            error = summary["errors"][0]
        elif summary and summary["stats"]["expected"] + summary["stats"]["flaky"] == 0:
            error = "Hiç test koşmadı (süzgeç eşleşmedi ya da yapılandırma hatası)."
        else:
            error = f"dotnet test çıkış kodu {exit_code}"
    if restore is not None and not restore["ok"]:
        status = "error"
        error = (error + " · " if error else "") + runmod.restore_error(req)

    report = {
        **base,
        "status": status,
        "error": error,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "bitis": runmod.now_iso(),
        "junit": str(junit_out) if junit_out.is_file() else None,
        "json": None,
        "surefire_dir": str(results),
        "kanit_dir": str(results / "kanit"),
        "allure_dir": str(allure_dir),
        "html_dir": None,
        "traces_dir": str(results / "kanit") if web else None,
        "log": str(dest / "runner.log"),
        "artifacts_rel": runmod._rel(cfg, dest),
        "break_restore": restore,
        "saglik": saglik,
        "retries_yok_sayildi": req.retries > 0,
        "compile_diagnostics": (build or {}).get("diagnostics") or [],
        "kirmizi_denetimi": red_check(summary["tests"]) if summary and req.breaks_app else None,
        "stats": summary["stats"] if summary else None,
        "tests": summary["tests"] if summary else [],
        "failures": failures_of(summary["tests"]) if summary else [],
        "failure_groups": failure_groups(summary["tests"]) if summary else [],
        "report_errors": summary["errors"] if summary else [],
        "reports": _reports(cfg, results, junit_out),
        "allure_report": None,
    }
    atomic_write_json(dest / "run.json", report)
    try:
        report["cleanup"] = runmod.prune_runs(cfg, req.run_id)
    except OSError as exc:
        report["cleanup"] = {"keep": cfg.runs_keep, "deleted": [], "deleted_evidence": [],
                             "errors": [str(exc)]}  # fmt: skip
    return report


def _run_tests(
    cfg: Settings,
    req: RunRequest,
    platform: str,
    root: Path,
    kok: csyol.CsKok,
    repeats: list[surefire.Repeat],
    allure_dir: Path,
    log_parts: list[str],
    work: Path,
) -> tuple[int | None, bool, int]:
    deadline = time.monotonic() + cfg.run_timeout_s
    exit_code: int | None = 0
    total_ms = 0
    filtre = test_filter(req.test_files)
    allure_cfg = work / "allureConfig.json"
    allure_dir.mkdir(parents=True, exist_ok=True)
    allure_cfg.write_text(
        f'{{"allure":{{"directory":"{allure_dir.as_posix()}"}}}}', encoding="utf-8"
    )
    for rep in repeats:
        left = deadline - time.monotonic()
        if left <= 1:
            return None, True, total_ms
        rep.reports_dir.mkdir(parents=True, exist_ok=True)
        env = test_env(cfg, req, platform, rep.kanit_dir, allure_cfg, work / "home", work / "nuget")
        res = proc.run(test_argv(cfg, root, kok, filtre, rep.reports_dir), cwd=root, env=env,
                       timeout_s=left)  # fmt: skip
        total_ms += res.duration_ms
        log_parts.append(
            f"$ {' '.join(res.argv)}\n\n--- stdout ---\n{res.stdout}\n"
            f"--- stderr ---\n{res.stderr}\n"
        )
        if res.timed_out:
            return None, True, total_ms
        if res.exit_code != 0:
            exit_code = res.exit_code
            if not (rep.reports_dir / HAM_JUNIT).is_file():
                break  # rapor yok: sonraki tekrarlar anlamsız
    return exit_code, False, total_ms


def _reports(cfg: Settings, results: Path, junit: Path) -> dict[str, dict[str, Any]]:
    from runner.run import _rel

    out: dict[str, dict[str, Any]] = {}
    for name, path in (
        ("junit", junit),
        ("junit_tekrarlar", results),
        ("allure", results / "allure-results"),
        ("kanit", results / "kanit"),
    ):
        out[name] = {"path": str(path), "rel": _rel(cfg, path), "exists": path.exists()}
    return out


def _export(cfg: Settings, loc: repos.Located, into: Path, kok: csyol.CsKok) -> None:
    """Commit'in C# proje ağacını `into/<kök>`'e çıkarır (kalıcı; koşu kanıtı)."""
    with gitforge.checkout(loc.repo, loc.sha, kok.root, cfg.git_timeout_s) as tree:
        dst = into / kok.root
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(tree, dst, symlinks=True)


class _CsharpKosusu:
    """plan.md §3.2 `RunnerDili` (Ş0 keşfi `EKLENTI`'yi okur; entegrasyon adaptörü)."""

    ad = csyol.LANG

    def validate_test_file(self, yol: str) -> str:
        return csyol.validate_test_file(yol)

    def execute_locked(
        self, cfg: Settings, req: RunRequest, loc: repos.Located, http: httpx.Client | None
    ) -> dict[str, Any]:
        return execute_locked(cfg, req, loc, http)


EKLENTI = _CsharpKosusu()
