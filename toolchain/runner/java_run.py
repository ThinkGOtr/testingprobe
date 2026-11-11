"""Java (TestNG) koşusu (009 §2.7, 011 §2.6) — iki hedef proje, tek hat:

- uygulama: `demo-app/e2e-app` (Appium), platform android | ios | windows;
- web: `demo-app/e2e-java` (Playwright for Java), platform web — Appium YOK. Sağlık kontrolü
  TS koşusuyla aynıdır (web origin + demo API); ortam `BASE_URL`, `API_URL` (+ `DEMO_API_URL`),
  `DEMOAPP_TEST_TOKEN`; tarayıcı imajdaki `/ms-playwright` (`PLAYWRIGHT_BROWSERS_PATH`), indirme
  kapalı (`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`: Playwright Java sürücüsü `driver` +
  `driver-bundle` jar'larından geçici dizine açılır, ağa çıkmaz). Kanıt
  `target/kanit/<Sınıf>.<metot>/{ekran.png, trace.zip, sayfa.html}`. Aşağıdaki akış, sertleştirme
  ve tekrar düzeni iki projede aynıdır (kök/güvenilir pom/depo: `worker.java.java_kok`).

`ci/run-app-checks.sh`'in test-runner karşılığıdır; ama betik ve commit'teki `mvnw` ÇALIŞTIRILMAZ.
toolchain-worker'ın Java derleme yolundaki sertleştirme aynen uygulanır (worker/java.py):

- Maven imajdaki sabit dağıtımdır (`TP_MVN`, /opt/maven), `-o` (çevrimdışı); ısıtılmış depo salt
  okunur kuyruk (`maven.repo.local.tail`), yazılabilir baş deposu koşu başına geçici dizin.
- Commit'in `pom.xml`'i ve `.mvn/` yapılandırması imajdaki güvenilir kopyayla aynı olmalı
  (`worker.java.check_deps`; worker'da da denetlenir, burada savunma derinliği). `.mvn/jvm.config`
  vb. JVM'e ajan yükletebilirdi.
- Ortam izin listesidir: `MAVEN_*`, `JAVA_TOOL_OPTIONS` vb. geçmez; `MAVEN_SKIP_RC=1`
  (`/etc/mavenrc`, `~/.mavenrc` kaynaklanmaz). Açıklama işlemcisi kapalı (`-proc:none`).

Akış (run.py ile aynı kilit ve koşu dizini sözleşmesi):
  1. Sağlık: `DEMO_API_URL/health` + Appium `APPIUM_URL_<PLATFORM>/status`. Başarısızsa koşu
     yapılmaz, `error` (triage kuralı 1: `environment`).
  2. Commit'in proje ağacı `runs/<id>/src/<kök>`'e çıkarılır (koşan kodun kopyası).
  3. Tekrar başına (`repeat_each`) `mvn … [test-compile] surefire:test -Dplatform=<p>`; kapsam
     `test_files` → `-Dtest=<yol>` (testng.xml devre dışı), yoksa `testng.xml` (testler + uretilen).
     Birim testleri (cihazsız) burada koşmaz: GitHub iş akışı `run-app-checks.sh` ile koşar.
  4. Kırılma (BREAK_CAMPAIGN=1) web ile aynı yoldur: testin hazırlığı `/test/break` açar, koşu
     nasıl biterse bitsin her bayi için `restore_break` geri alır. Kırmızı adımın denetimi
     (`araclar/KirmiziDenetimi.java`: kırmızılar YALNIZCA assertion) çekirdekte, test bazındaki
     `failure.type` ile yapılır (runner/surefire.py aynı sınıflandırmayı üretir).
  5. Sonuç: Surefire `TEST-*.xml` → `results.summarize` biçiminde özet + tek `junit.xml`
     (`runs/<id>/results/junit.xml`), Allure raporu, kanıt `target/kanit/`.
  6. Extent raporu: e2e-app'in TestNG dinleyicisi (`altyapi/ExtentRaporu`) koşu sırasında tek
     dosyalık, dış kaynak yüklemeyen `target/extent-report/index.html` yazar
     (`reports.extent_html`). Ayrı üretim adımı yoktur; tekrarlar (`repeat_each`) aynı dizine
     yazar ve dinleyici önceki tekrarları rapora geri yükler (`-Dextent.tekrar=<i>/<n>` test
     adına eklenir).

Uygulama seçimi Appium hostundaki kurulu uygulamadır (`TP_APP_ID_<P>`; isteğe bağlı
`TP_APP_PATH_<P>` Appium hostundaki dosya yolu). Retries (`--retries`) Java'da yoktur (TestNG
yeniden deneme eklentisi kullanılmaz): istenirse yok sayılır ve raporda belirtilir.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from runner import surefire
from runner.results import decide_status, failure_groups, failures_of
from toolchain_common import gitforge, proc, repos
from toolchain_common.artifacts import KEEP_MARKER, atomic_write_json, run_dir
from toolchain_common.settings import Settings
from worker import java as javayol

if TYPE_CHECKING:
    from runner.run import RunRequest

PLATFORMS = javayol.APP_PLATFORMS
WEB = javayol.WEB
# Web + Java raporlarındaki `project`: TS koşusundaki Playwright projesiyle aynı ad.
WEB_PROJECT = "chromium"
# İmajdaki tarayıcı dizini (mcr.microsoft.com/playwright; Dockerfile `PLAYWRIGHT_BROWSERS_PATH`).
BROWSERS_PATH = "/ms-playwright"
# Uygulama kimliği varsayılanları (demo-app/mobile/app.json; Windows'ta zorunlu yapılandırma).
DEFAULT_APP_ID = {"android": "com.antreklabs.bayisiparis", "ios": "com.antreklabs.bayisiparis"}
DEFAULT_APP_ACTIVITY = {"android": ".MainActivity"}
# Platform başına ortam → e2e-app ortam adı (altyapi/Ayarlar.java ORTAM_KARSILIGI).
APP_ENV = {
    "TP_APP_ID": "APP_ID",
    "TP_APP_PATH": "APP_PATH",
    "TP_APP_ACTIVITY": "APP_ACTIVITY",
    "TP_APP_ARGS": "APP_ARGS",
    "TP_APP_WORKDIR": "APP_WORKDIR",
    "TP_DEVICE_NAME": "DEVICE_NAME",
    "TP_DEVICE_UDID": "DEVICE_UDID",
    "TP_PLATFORM_VERSION": "PLATFORM_VERSION",
}
PASS_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR", "JAVA_HOME")
SUREFIRE_DIR = "surefire-reports"
EXTENT_REPORT_DIR = "extent-report"


def appium_url(platform: str) -> str:
    return os.environ.get(f"APPIUM_URL_{platform.upper()}", "").strip().rstrip("/")


def app_settings(platform: str) -> dict[str, str]:
    """Platformun uygulama/cihaz ayarları (e2e-app ortam adlarıyla)."""
    p = platform.upper()
    out: dict[str, str] = {}
    for src, dst in APP_ENV.items():
        val = os.environ.get(f"{src}_{p}", "").strip()
        if not val and src == "TP_APP_ID":
            val = DEFAULT_APP_ID.get(platform, "")
        if not val and src == "TP_APP_ACTIVITY" and not os.environ.get(f"TP_APP_PATH_{p}"):
            val = DEFAULT_APP_ACTIVITY.get(platform, "")
        if val:
            out[dst] = val
    return out


def health_check(cfg: Settings, platform: str, client: httpx.Client | None = None) -> dict:
    """Koşu öncesi: demo API + Appium (uygulama) ya da web origin + demo API (web; Appium yok).
    `ok` yalnızca ikisi de 2xx dönerse doğrudur."""
    from runner.run import _probe, now_iso
    from runner.run import health_check as web_health_check

    if platform == WEB:
        # TS koşusuyla aynı kontrol ve aynı biçim; `appium` alanı (Java raporu) boş kalır.
        return {**web_health_check(cfg, client), "appium": None}

    own = client is None
    http = client or httpx.Client()
    url = appium_url(platform)
    try:
        api = _probe(http, f"{cfg.demo_api_url}/health", cfg.health_timeout_s)
        if url:
            appium = _probe(http, f"{url}/status", cfg.health_timeout_s)
        else:
            appium = {
                "url": None,
                "status": None,
                "ms": 0,
                "hata": f"APPIUM_URL_{platform.upper()} yapılandırılmamış",
            }
    finally:
        if own:
            http.close()
    problems = [
        f"{name} ({p['url']}): {p['hata']}"
        for name, p in (("api", api), ("appium", appium))
        if p["hata"]
    ]
    return {
        "ok": not problems,
        "zaman": now_iso(),
        "web": None,
        "api": api,
        "appium": appium,
        "hata": "Uygulama test ortamı sağlık kontrolü başarısız — " + "; ".join(problems)
        if problems
        else None,
    }


def test_selector(test_files: list[str]) -> str:
    """`src/test/java/a/b/XTest.java` → Surefire `-Dtest` deseni `a/b/XTest.java` (virgülle)."""
    out = []
    for f in test_files:
        javayol.validate_java_test_file(f)
        out.append(f.removeprefix("src/test/java/"))
    return ",".join(out)


def maven_argv(
    cfg: Settings,
    root: Path,
    head_repo: Path,
    platform: str,
    rep: surefire.Repeat,
    allure_dir: Path,
    test_files: list[str],
    *,
    compile_first: bool,
    repeat_count: int = 1,
    kok: javayol.JavaKok | None = None,
) -> list[str]:
    kok = kok or javayol.java_kok(cfg, platform)
    argv = [
        cfg.mvn,
        "-B",
        "-o",
        "-ntp",
        "-f",
        str(root / "pom.xml"),
        f"-Dmaven.repo.local={head_repo}",
        f"-Dmaven.repo.local.tail={kok.m2}",
        "-Dmaven.compiler.proc=none",
        f"-Dplatform={platform}",
        f"-Draporlar.dizini={rep.reports_dir}",
        f"-Dallure.results.directory={allure_dir}",
        f"-Dkanit.dizini={rep.kanit_dir}",
        # Extent raporu tekrarlar arasında ortak dizine yazılır (dinleyici birleştirir).
        f"-Dextent.rapor.dizini={allure_dir.parent / EXTENT_REPORT_DIR}",
    ]
    if repeat_count > 1:
        argv.append(f"-Dextent.tekrar={rep.index + 1}/{repeat_count}")
    if test_files:
        argv += [f"-Dtest={test_selector(test_files)}", "-Dsurefire.failIfNoSpecifiedTests=true"]
    argv += ["test-compile", "surefire:test"] if compile_first else ["surefire:test"]
    return argv


def maven_env(cfg: Settings, req: RunRequest, platform: str) -> dict[str, str]:
    """İzin listesi: sistem + proje ayarları (MAVEN_*/JVM seçenekleri geçmez)."""
    env = {k: os.environ[k] for k in PASS_ENV if k in os.environ}
    if platform == WEB:
        env.update(
            {
                "MAVEN_SKIP_RC": "1",
                "CI": "1",
                # TS e2e ile aynı hedef (compose'daki demo uygulaması). API kökü iki adla da
                # verilir: 011 §2.5 `API_URL`, TS e2e ve e2e-app `DEMO_API_URL`.
                "BASE_URL": cfg.base_url,
                "API_URL": cfg.demo_api_url,
                "DEMO_API_URL": cfg.demo_api_url,
                "DEMOAPP_TEST_TOKEN": cfg.demoapp_test_token,
                "BREAK_CAMPAIGN": "1" if req.break_campaign else "",
                "TP_RUN_ID": req.run_id,
                # Tarayıcı imajdan; sürücü (driver-bundle) açılırken `playwright install`
                # çalıştırmaz: koşu sırasında indirme yok (çevrimdışı).
                "PLAYWRIGHT_BROWSERS_PATH": os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
                or BROWSERS_PATH,
                "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
            }
        )
        return env
    env.update(app_settings(platform))
    env.update(
        {
            "MAVEN_SKIP_RC": "1",
            "CI": "1",
            "PLATFORM": platform,
            "APPIUM_URL": appium_url(platform),
            "DEMO_API_URL": cfg.demo_api_url,
            "DEMOAPP_TEST_TOKEN": cfg.demoapp_test_token,
            "BREAK_CAMPAIGN": "1" if req.break_campaign else "",
            "TP_RUN_ID": req.run_id,
        }
    )
    return env


def _repeats(target: Path, n: int) -> list[surefire.Repeat]:
    if n <= 1:
        return [surefire.Repeat(0, target / SUREFIRE_DIR, target / "kanit")]
    return [
        surefire.Repeat(
            i, target / SUREFIRE_DIR / f"tekrar-{i + 1}", target / "kanit" / f"tekrar-{i + 1}"
        )
        for i in range(n)
    ]


def execute_locked(
    cfg: Settings, req: RunRequest, loc: repos.Located, http: httpx.Client | None
) -> dict[str, Any]:
    from runner import run as runmod

    platform = req.platform or WEB
    if platform != WEB and platform not in PLATFORMS:
        raise runmod.RunRejected(f"Java koşusu platformu: {(WEB, *PLATFORMS)}")
    web = platform == WEB
    kok = javayol.java_kok(cfg, platform)
    dest = run_dir(cfg.artifacts_path, req.run_id)
    try:
        dest.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise runmod.RunConflict(f"run_id zaten kullanılmış: {req.run_id}") from exc
    started = runmod.now_iso()
    base: dict[str, Any] = {
        "run_id": req.run_id,
        "sha": loc.sha,
        "lang": "java",
        "platform": platform,
        "grep": None,
        "test_files": req.test_files,
        "repeat_each": req.repeat_each,
        "retries": req.retries,
        "break_campaign": req.break_campaign,
        "workers": None,
        "keep": req.keep,
        "base_url": cfg.base_url if web else None,
        "appium_url": None if web else (appium_url(platform) or None),
        "artifacts_dir": str(dest),
        "baslangic": started,
    }
    if req.keep:
        (dest / KEEP_MARKER).write_text(f"{started}\n", encoding="utf-8")
    atomic_write_json(dest / "run.json", {**base, "status": "running"})
    saglik = health_check(cfg, platform, http)

    root = dest / "src" / kok.root
    target = root / "target"
    repeats = _repeats(target, req.repeat_each)
    allure_dir = target / "allure-results"
    results_out = dest / "results"
    junit_out = results_out / "junit.xml"
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
                deps = javayol.check_deps(cfg, root, kok)
                if not deps["ok"]:
                    error = deps["error"]
                else:
                    # Commit'teki derleme çıktısı / sahte rapor yeni sonuçla karışmasın.
                    shutil.rmtree(target, ignore_errors=True)
                    if target.is_symlink():
                        target.unlink()
                    ran = True
                    exit_code, timed_out, duration_ms = _run_maven(
                        cfg, req, platform, root, repeats, allure_dir, log_parts, kok
                    )
    finally:
        if req.break_campaign and saglik["ok"]:
            restore = runmod.restore_break(cfg, http)

    summary: dict[str, Any] | None = None
    allure_report: dict[str, Any] | None = None
    if ran:
        (dest / "runner.log").write_text("\n".join(log_parts), encoding="utf-8")
        allure_report = runmod.generate_allure(cfg, target)
        summary = surefire.summarize(
            repeats, project=WEB_PROJECT if web else platform, rel_root=cfg.artifacts_path
        )
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
    diagnostics: list[dict[str, Any]] = []
    if ran and exit_code not in (0, None) and summary is not None and not summary["tests"]:
        # Rapor yok + Maven başarısız: büyük olasılıkla derleme hatası (javac tanıları günlükte).
        diagnostics = javayol.parse_compile("\n".join(log_parts), root)
        where = (
            f" — derleme hatası: {diagnostics[0]['file']}:{diagnostics[0]['line']}"
            if diagnostics
            else " (ayrıntı: runner.log)"
        )
        error = error or (
            f"Maven başarısız (çıkış kodu {exit_code}); Surefire raporu üretilmedi{where}"
        )
    if status == "error" and error is None:
        if summary and summary["errors"]:
            error = summary["errors"][0]
        elif summary and summary["stats"]["expected"] + summary["stats"]["flaky"] == 0:
            error = "Hiç test koşmadı (seçim eşleşmedi ya da yapılandırma hatası)."
        else:
            error = f"Maven çıkış kodu {exit_code}"
    if restore is not None and not restore["ok"]:
        status = "error"
        error = (error + " · " if error else "") + "Kampanya kırılması geri alınamadı."

    report = {
        **base,
        "status": status,
        "error": error,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "bitis": runmod.now_iso(),
        "junit": str(junit_out) if junit_out.is_file() else None,
        "json": None,
        "surefire_dir": str(target / SUREFIRE_DIR),
        "kanit_dir": str(target / "kanit"),
        "allure_dir": str(allure_dir),
        "html_dir": None,
        # Web + Java: Playwright izleri kanıt dizinindedir (`<Sınıf>.<metot>/trace.zip`).
        "traces_dir": str(target / "kanit") if web else None,
        "log": str(dest / "runner.log"),
        "artifacts_rel": runmod._rel(cfg, dest),
        "break_restore": restore,
        "saglik": saglik,
        "retries_yok_sayildi": req.retries > 0,
        "compile_diagnostics": diagnostics,
        # Kırarak doğrulamanın kırmızı adım denetimi (KirmiziDenetimi.java ile aynı kural).
        "kirmizi_denetimi": red_check(summary["tests"]) if summary and req.break_campaign else None,
        "stats": summary["stats"] if summary else None,
        "tests": summary["tests"] if summary else [],
        "failures": failures_of(summary["tests"]) if summary else [],
        "failure_groups": failure_groups(summary["tests"]) if summary else [],
        "report_errors": summary["errors"] if summary else [],
        "reports": _reports(cfg, target, junit_out),
        "allure_report": allure_report,
    }
    atomic_write_json(dest / "run.json", report)
    try:
        report["cleanup"] = runmod.prune_runs(cfg, req.run_id)
    except OSError as exc:
        report["cleanup"] = {"keep": cfg.runs_keep, "deleted": [], "deleted_evidence": [],
                             "errors": [str(exc)]}  # fmt: skip
    return report


def red_check(tests: list[dict[str, Any]]) -> dict[str, Any]:
    """`ci/break-verify-app.sh` 2. adımı (`KirmiziDenetimi.java`): BREAK_CAMPAIGN=1 koşusunda
    kırmızı testlerin HEPSİ doğrulama (assertion) hatası olmalı ve en az bir kırmızı olmalı.
    Kurulum (`test_data`), locator, diğer hatalar ve atlanan test kırmızı sayılmaz.

    Karar yine çekirdeğindir (kırarak doğrulama akışı); bu alan aynı kuralın deterministik özeti.
    """
    kirmizi = [t["title"] for t in tests if (t.get("failure") or {}).get("type") == "assertion"]
    kotu = [
        f"{t['title']} [{(t.get('failure') or {}).get('type') or t.get('status')}]"
        for t in tests
        if t.get("status") == "skipped"
        or (t.get("status") == "unexpected" and (t.get("failure") or {}).get("type") != "assertion")
    ]
    return {"ok": bool(kirmizi) and not kotu, "kirmizi": kirmizi, "kotu": kotu}


def _run_maven(
    cfg: Settings,
    req: RunRequest,
    platform: str,
    root: Path,
    repeats: list[surefire.Repeat],
    allure_dir: Path,
    log_parts: list[str],
    kok: javayol.JavaKok | None = None,
) -> tuple[int | None, bool, int]:
    """Tekrarları sırayla koşar; (son sıfırdan farklı çıkış kodu, süre aşımı, toplam süre)."""
    deadline = time.monotonic() + cfg.run_timeout_s
    exit_code: int | None = 0
    total_ms = 0
    env = maven_env(cfg, req, platform)
    with tempfile.TemporaryDirectory(prefix="tp-m2-run-") as head_repo:
        for i, rep in enumerate(repeats):
            left = deadline - time.monotonic()
            if left <= 1:
                return None, True, total_ms
            argv = maven_argv(
                cfg, root, Path(head_repo), platform, rep, allure_dir, req.test_files,
                compile_first=i == 0, repeat_count=len(repeats), kok=kok,
            )  # fmt: skip
            res = proc.run(argv, cwd=root, env=env, timeout_s=left)
            total_ms += res.duration_ms
            log_parts.append(
                f"$ {' '.join(res.argv)}\n\n--- stdout ---\n{res.stdout}\n"
                f"--- stderr ---\n{res.stderr}\n"
            )
            if res.timed_out:
                return None, True, total_ms
            if res.exit_code != 0:
                exit_code = res.exit_code
                # Derleme hatası (rapor yok): sonraki tekrarlar anlamsız.
                if not rep.reports_dir.is_dir():
                    break
    return exit_code, False, total_ms


def _reports(cfg: Settings, target: Path, junit: Path) -> dict[str, dict[str, Any]]:
    from runner.run import _rel

    out: dict[str, dict[str, Any]] = {}
    for name, path, marker in (
        ("junit", junit, None),
        ("surefire", target / SUREFIRE_DIR, None),
        ("allure", target / "allure-results", None),
        ("allure_html", target / "allure-report", "index.html"),
        ("extent_html", target / EXTENT_REPORT_DIR, "index.html"),
        ("kanit", target / "kanit", None),
    ):
        probe = path / marker if marker else path
        out[name] = {"path": str(path), "rel": _rel(cfg, path), "exists": probe.exists()}
    return out


def _export(
    cfg: Settings, loc: repos.Located, into: Path, kok: javayol.JavaKok | None = None
) -> None:
    """Commit'in Java proje ağacını `into/<kök>`'e çıkarır (kalıcı; koşu kanıtı)."""
    kok = kok or javayol.java_kok(cfg, "android")
    with gitforge.checkout(loc.repo, loc.sha, kok.root, cfg.git_timeout_s) as tree:
        dst = into / kok.root
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(tree, dst, symlinks=True)
