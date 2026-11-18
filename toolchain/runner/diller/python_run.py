"""Python (pytest) koşusu — Ş1 (TASARIM §3.1; plan.md §3.2). runner/java_run.py'nin karşılığı.

İki hedef proje, tek hat (`worker.diller.python.py_kok`): web (`e2e-python`, pytest + Playwright;
Appium yok) ve uygulama (`e2e-app-python`, pytest + Appium; android | ios | windows).

Sertleştirme (java_run ile aynı ilke):

- Koşu imajdaki venv'dir (`TP_PYTHON_E2E`, /opt/e2e-python/venv); commit hiçbir paket kuramaz.
  Commit'in `requirements.lock`'u güvenilir kilitle bayt eşit olmalı ve kökte sembolik bağ /
  `sitecustomize.py` / `.pth` / ek pytest yapılandırması olamaz (`check_deps`; worker'da da
  denetlenir, burada savunma derinliği).
- `python -I -B -m pytest`: yalıtılmış kip (PYTHON* ortamı ve kullanıcı site-packages okunmaz),
  bayt kodu yazılmaz. `-c <kök>/pyproject.toml --rootdir <kök>`: üst dizinlerdeki yapılandırma
  okunmaz. `-p no:cacheprovider`.
- Ortam izin listesidir (java_run.maven_env karşılığı): sistem + gizli test verisi
  `TP_TESTVERI_*` (K19) + koşu ayarları; `TMPDIR` koşu dizini altıdır (`<run>/tmp`, sonda silinir).
  Tarayıcılar imajdan (`/ms-playwright`), indirme kapalı.

Akış: sağlık (web: origin + API; uygulama: API + Appium) → commit'in proje ağacı
`runs/<id>/src/<kök>`'e çıkarılır → tekrar başına (`repeat_each`) ayrı pytest koşusu
(`results/tekrar-<i>/TEST-pytest.xml`, kanıt `results/kanit[/tekrar-<i>]/<test>/…`,
pytest-playwright izi `results/kanit-pw/tekrar-<i>`) → kırılma geri alınır → özet
(`_pytest_junit.summarize`, Java ile aynı biçim) + tek `runs/<id>/results/junit.xml` +
Allure (`results/allure-results`).
Retries yoktur (yeniden deneme eklentisi kurulmaz): istenirse yok sayılır ve raporda belirtilir.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from runner import java_run, surefire
from runner.diller import _pytest_junit as pj
from runner.results import decide_status, failure_groups, failures_of
from toolchain_common import gitforge, proc, repos
from toolchain_common.artifacts import KEEP_MARKER, atomic_write_json, run_dir
from worker.diller import python as pyyol

if TYPE_CHECKING:  # pragma: no cover
    from runner.run import RunRequest
    from toolchain_common.settings import Settings

DIL = pyyol.DIL
WEB = pyyol.WEB
WEB_PROJECT = "chromium"
BROWSERS_PATH = "/ms-playwright"
PASS_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TZ")
RUN_TMP_DIR = "tmp"
RESULTS_DIR = "results"
KANIT_ENV = "TP_KANIT_DIZINI"


def _repeats(results: Path, n: int, web: bool) -> list[pj.Repeat]:
    def one(i: int, suffix: str) -> pj.Repeat:
        return pj.Repeat(
            i,
            results / f"tekrar-{i + 1}",
            results / "kanit" / suffix if suffix else results / "kanit",
            (results / "kanit-pw" / f"tekrar-{i + 1}") if web else None,
        )

    if n <= 1:
        return [one(0, "")]
    return [one(i, f"tekrar-{i + 1}") for i in range(n)]


def pytest_argv(
    cfg: Settings, root: Path, platform: str, rep: pj.Repeat, test_files: list[str]
) -> list[str]:
    argv = [
        pyyol.venv_python(cfg),
        "-I",
        "-B",
        "-m",
        "pytest",
        "-c",
        str(root / "pyproject.toml"),
        "--rootdir",
        str(root),
        "-p",
        "no:cacheprovider",
        "-o",
        "junit_family=xunit2",
        f"--junitxml={rep.reports_dir / pj.JUNIT_NAME}",
        f"--alluredir={root / RESULTS_DIR / 'allure-results'}",
        "-m",
        "not birim",
        "-q",
        "-rA",
    ]
    if platform == WEB:
        argv += [
            "--browser",
            "chromium",
            "--base-url",
            cfg.base_url,
            "--tracing",
            "retain-on-failure",
            "--screenshot",
            "only-on-failure",
            "--output",
            str(rep.pw_output),
        ]
    for f in test_files:
        pyyol.validate_test_file(f)
    # `--` sonrası yalnız doğrulanmış yollar: seçenek olarak yorumlanamaz.
    return [*argv, "--", *(test_files or ["tests"])]


def pytest_env(
    cfg: Settings, req: RunRequest, platform: str, tmp_dir: Path | None, kanit_dir: Path
) -> dict[str, str]:
    from runner.run import testveri_env

    env = {k: os.environ[k] for k in PASS_ENV if k in os.environ}
    env.update(testveri_env())
    venv_bin = str(Path(pyyol.venv_python(cfg)).parent)
    env["PATH"] = f"{venv_bin}:{env.get('PATH', '/usr/bin:/bin')}"
    env.update(
        {
            "CI": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONIOENCODING": "utf-8",
            "DEMO_API_URL": cfg.demo_api_url,
            "API_URL": cfg.demo_api_url,
            "DEMOAPP_TEST_TOKEN": cfg.demoapp_test_token,
            "BREAK_CAMPAIGN": "1" if req.break_campaign else "",
            "TP_FAULT": req.fault or "",
            "TP_RUN_ID": req.run_id,
            "TP_PLATFORM": platform,
            KANIT_ENV: str(kanit_dir),
        }
    )
    if tmp_dir is not None:
        env["TMPDIR"] = str(tmp_dir)
    if platform == WEB:
        env.update(
            {
                "BASE_URL": cfg.base_url,
                "PLAYWRIGHT_BROWSERS_PATH": os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
                or BROWSERS_PATH,
                "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
            }
        )
        return env
    env.update(java_run.app_settings(platform, cfg))
    env.update({"PLATFORM": platform, "APPIUM_URL": java_run.appium_url(platform)})
    return env


def _export(cfg: Settings, loc: repos.Located, into: Path, kok: pyyol.PyKok) -> None:
    with gitforge.checkout(loc.repo, loc.sha, kok.root, cfg.git_timeout_s) as tree:
        dst = into / kok.root
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(tree, dst, symlinks=True)


def _run_repeats(
    cfg: Settings,
    req: RunRequest,
    platform: str,
    root: Path,
    repeats: list[pj.Repeat],
    log_parts: list[str],
    tmp_dir: Path | None,
) -> tuple[int | None, bool, int]:
    deadline = time.monotonic() + cfg.run_timeout_s
    exit_code: int | None = 0
    total_ms = 0
    for rep in repeats:
        left = deadline - time.monotonic()
        if left <= 1:
            return None, True, total_ms
        rep.reports_dir.mkdir(parents=True, exist_ok=True)
        rep.kanit_dir.mkdir(parents=True, exist_ok=True)
        res = proc.run(
            pytest_argv(cfg, root, platform, rep, req.test_files),
            cwd=root,
            env=pytest_env(cfg, req, platform, tmp_dir, rep.kanit_dir),
            timeout_s=left,
        )
        total_ms += res.duration_ms
        log_parts.append(
            f"$ {' '.join(res.argv)}\n\n--- stdout ---\n{res.stdout}\n"
            f"--- stderr ---\n{res.stderr}\n"
        )
        if res.timed_out:
            return None, True, total_ms
        if res.exit_code != 0:
            exit_code = res.exit_code
            # Toplama/kullanım hatası (2, 3, 4): rapor anlamsız, sonraki tekrarlar da aynı biter.
            if res.exit_code in (2, 3, 4):
                break
    return exit_code, False, total_ms


def _reports(cfg: Settings, results: Path, junit: Path) -> dict[str, dict[str, Any]]:
    from runner.run import _rel

    out: dict[str, dict[str, Any]] = {}
    for name, path, marker in (
        ("junit", junit, None),
        ("allure", results / "allure-results", None),
        ("allure_html", results / "allure-report", "index.html"),
        ("kanit", results / "kanit", None),
        ("playwright_output", results / "kanit-pw", None),
    ):
        probe = path / marker if marker else path
        out[name] = {"path": str(path), "rel": _rel(cfg, path), "exists": probe.exists()}
    return out


def execute_locked(
    cfg: Settings, req: RunRequest, loc: repos.Located, http: httpx.Client | None
) -> dict[str, Any]:
    from runner import run as runmod

    platform = req.platform or WEB
    if platform not in pyyol.PLATFORMLAR:
        raise runmod.RunRejected(f"Python koşusu platformu: {pyyol.PLATFORMLAR}")
    if req.grep:
        raise runmod.RunRejected("Python koşusunda grep desteklenmiyor (test_files kullanın)")
    web = platform == WEB
    kok = pyyol.py_kok(cfg, platform)
    dest = run_dir(cfg.artifacts_path, req.run_id)
    try:
        dest.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise runmod.RunConflict(f"run_id zaten kullanılmış: {req.run_id}") from exc
    started = runmod.now_iso()
    base: dict[str, Any] = {
        "run_id": req.run_id,
        "sha": loc.sha,
        "lang": DIL,
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
        "appium_url": None if web else (java_run.appium_url(platform) or None),
        "artifacts_dir": str(dest),
        "baslangic": started,
    }
    if req.keep:
        (dest / KEEP_MARKER).write_text(f"{started}\n", encoding="utf-8")
    atomic_write_json(dest / "run.json", {**base, "status": "running"})
    saglik = java_run.health_check(cfg, platform, http)

    root = dest / "src" / kok.root
    results = root / RESULTS_DIR
    repeats = _repeats(results, req.repeat_each, web)
    junit_out = dest / "results" / "junit.xml"
    log_parts: list[str] = []
    error: str | None = None
    restore: dict[str, Any] | None = None
    exit_code: int | None = None
    timed_out = False
    duration_ms = 0
    ran = False
    try:
        if not saglik["ok"]:
            error = saglik["hata"]
        else:
            try:
                _export(cfg, loc, dest / "src", kok)
            except gitforge.ForgeError as exc:
                error = str(exc)
            else:
                deps = pyyol.check_deps(cfg, root, kok)
                if not deps["ok"]:
                    error = deps["error"]
                else:
                    # Commit'teki sahte rapor / önbellek yeni sonuçla karışmasın.
                    for stale in (results, root / ".pytest_cache"):
                        shutil.rmtree(stale, ignore_errors=True)
                    tmp_dir = dest / RUN_TMP_DIR
                    tmp_dir.mkdir(parents=True, exist_ok=True)
                    ran = True
                    try:
                        exit_code, timed_out, duration_ms = _run_repeats(
                            cfg, req, platform, root, repeats, log_parts, tmp_dir
                        )
                    finally:
                        shutil.rmtree(tmp_dir, ignore_errors=True)
    finally:
        if req.breaks_app and saglik["ok"]:
            restore = runmod.restore_break(cfg, http)

    summary: dict[str, Any] | None = None
    allure_report: dict[str, Any] | None = None
    if ran:
        (dest / "runner.log").write_text("\n".join(log_parts), encoding="utf-8")
        allure_report = runmod.generate_allure(cfg, results)
        summary = pj.summarize(
            repeats, project=WEB_PROJECT if web else platform, rel_root=cfg.artifacts_path
        )
        try:
            surefire.write_junit(
                [surefire.Repeat(r.index, r.reports_dir, r.kanit_dir) for r in repeats],
                junit_out,
                name=kok.ad,
            )
        except OSError as exc:
            summary["errors"].append(f"junit.xml yazılamadı: {type(exc).__name__}")
        if timed_out:
            error = f"Koşu süre sınırını aştı ({int(cfg.run_timeout_s)} sn); süreç durduruldu."
    status = (
        "error"
        if not ran
        else decide_status(exit_code=exit_code, timed_out=timed_out, summary=summary)
    )
    if ran and exit_code not in (0, None) and summary is not None and not summary["tests"]:
        # Rapor yok + pytest başarısız: toplama hatası (içe aktarma / sözdizimi; ayrıntı günlükte).
        error = error or (
            f"pytest başarısız (çıkış kodu {exit_code}); test toplanamadı (ayrıntı: runner.log)"
        )
    if status == "error" and error is None:
        if summary and summary["errors"]:
            error = summary["errors"][0]
        elif summary and summary["stats"]["expected"] + summary["stats"]["flaky"] == 0:
            error = "Hiç test koşmadı (seçim eşleşmedi ya da yapılandırma hatası)."
        else:
            error = f"pytest çıkış kodu {exit_code}"
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
        "surefire_dir": None,
        "pytest_dir": str(results),
        "kanit_dir": str(results / "kanit"),
        "allure_dir": str(results / "allure-results"),
        "html_dir": None,
        "traces_dir": str(results / "kanit-pw") if web else None,
        "log": str(dest / "runner.log"),
        "artifacts_rel": runmod._rel(cfg, dest),
        "break_restore": restore,
        "saglik": saglik,
        "retries_yok_sayildi": req.retries > 0,
        "compile_diagnostics": [],
        "kirmizi_denetimi": (
            java_run.red_check(summary["tests"]) if summary and req.breaks_app else None
        ),
        "stats": summary["stats"] if summary else None,
        "tests": summary["tests"] if summary else [],
        "failures": failures_of(summary["tests"]) if summary else [],
        "failure_groups": failure_groups(summary["tests"]) if summary else [],
        "report_errors": summary["errors"] if summary else [],
        "reports": _reports(cfg, results, junit_out),
        "allure_report": allure_report,
    }
    atomic_write_json(dest / "run.json", report)
    try:
        report["cleanup"] = runmod.prune_runs(cfg, req.run_id)
    except OSError as exc:
        report["cleanup"] = {"keep": cfg.runs_keep, "deleted": [], "deleted_evidence": [],
                             "errors": [str(exc)]}  # fmt: skip
    return report


class _PythonKosusu:
    """plan.md §3.2 `RunnerDili` (Ş0 keşfi `EKLENTI`'yi okur)."""

    ad = DIL

    def validate_test_file(self, yol: str) -> str:
        return pyyol.validate_test_file(yol)

    def execute_locked(
        self, cfg: Settings, req: RunRequest, loc: repos.Located, http: httpx.Client | None
    ) -> dict[str, Any]:
        return execute_locked(cfg, req, loc, http)


EKLENTI = _PythonKosusu()
