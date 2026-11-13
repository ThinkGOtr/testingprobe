"""`POST /check`: yerel CI (`local-ci`) — CI ile aynı sıra, AI yok (TEKNIK-TASARIM §8.5).

  uygulama eşleşmesi → bağımlılık kilidi → tsc --noEmit → eslint --no-inline-config →
  ast-guard (pr) → test-runner /run

**Uygulama eşleşmesi (`app`):** testler compose'da çalışan demo-app-web'e karşı koşar (GitHub CI
uygulamayı checkout'tan başlatır). Çalışan uygulamanın kaynak ağacı (`web`, `api`) istenen
commit'inkinden farklıysa (ör. uygulama kodunu değiştiren bir PR) sonuç o commit'e ait olamaz:
adım `farkli` ile başarısız olur, koşu yapılmaz, `local-ci` `failure` yazılır. Çalışan uygulamanın
commit'i bilinmiyorsa (`dogrulanamadi`) adım uyarıyla geçer; `TP_CHECK_REQUIRE_APP_SHA=1` iken
başarısız olur (toolchain_common/appsha.py).

İlk başarısız adımda durulur (`run-checks.sh` gibi `set -e`); atlanan adımlar `skipped` olur.
Başta `checks/<sha>.json`'a `in_progress`, sonda `completed` + `success|failure` yazılır
(LocalForge.checks() bu dosyayı okur; merge kapısı `local-ci`'ı ister). Beklenmeyen bir hatada
da dosya `failure` ile kapatılır: yarım kalmış kontrol asla başarı sayılmaz.

**Tek yazar:** `checks/<sha>.json`'ı yalnızca bu modül yazar (core salt okur; LocalForge.checks()).

**Kontrol adı platform ve dil başınadır** (009 §2.7, 011 K-T1; core `platform.check_adi`'nın
aynası): web + TS `local-ci`, web + Java (Playwright for Java) `local-ci-web-java`, uygulamada
(Java/Appium) `local-ci-<platform>` (`local-ci-android`, `local-ci-ios`, `local-ci-windows`).
Dosya bir kontrol listesidir; her yazım YALNIZCA kendi adındaki girdiyi değiştirir, diğer
platform/dil girdileri korunur: aynı sha'nın TS ve Java kardeş koşuları birbirini ezmez.
`report` son yazılan kontrolün raporudur; `reports` ad → rapor eşlemesidir.

Hangi kontrol `local-ci` kaydı olur (`record_check`):

- varsayılan (`None`): yalnızca **tam kapsamlı** kontrol — `test_files` ve `grep` yok, kırılma
  ve ekilmiş hata yok. Bu, GitHub'daki PR CI'ının (tüm testler) yerel karşılığıdır; merge kapısı
  bunu okur.
- `True`: varsayılanla aynı; kapsamlı (test_files / grep) ya da kırılmalı bir kontrolle birlikte
  verilemez (API 422). Kapsamlı yeşil bir koşu head'in tüm testlerinin sonucunu temsil etmez;
  kayıt olsaydı merge kapısı onu `success` sayardı (LocalForge yalnızca `conclusion`'a bakar).
- `False`: hiç yazılmaz (ör. kod üretimindeki `--repeat-each=3` ön kontrolü).

Savunma derinliği: `records_check()` kapsamlı kontrolde her durumda False döner ve her CheckRun
girdisi `tam: true` taşır (core isterse yalnızca tam kapsamlıları sayabilir).

Kırılma istenen kontrol ("kırarak doğrula", BREAK_CAMPAIGN) ve ekilmiş hata koşusu (`fault`,
TP_FAULT; 012 §4.6) bilerek kırmızı beklenen denemelerdir; commit'in CI sonucu değildir, bu yüzden
asla yazılmaz (`local-ci` da `local-ci-<platform>` da).

Rapor, test-runner'ın test bazındaki `failure` girdilerini (`failures`) ve koşu öncesi sağlık
kontrolünü (`saglik`) üst düzeyde taşır: kod üretiminin "locator/eşleme → 1 düzeltme turu" ile
"assertion → defect adayı" ayrımı (TEKNIK-TASARIM §8.4 adım 5) ve Faz 4 triage bunları kullanır.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from toolchain_common import appsha, gitforge, repos
from toolchain_common.artifacts import atomic_write_json, checks_file
from toolchain_common.settings import Settings
from worker import affected, static
from worker import java as javayol
from worker.astguard import AstGuardError, run_ast_guard

CHECK_NAME = "local-ci"
# Java (Appium) kontrolleri platform başına ayrı kayıttır: `local-ci-<platform>`. Web + Java
# (Playwright for Java) ayrı kaydını yazar: `local-ci-web-java` (011 K-T1; GitHub `web-java`).
WEB_JAVA_CHECK_NAME = f"{CHECK_NAME}-web-java"
JAVA_PLATFORMS = javayol.APP_PLATFORMS
CHECK_LOCK = threading.Lock()
STEPS = ("app", "deps", "tsc", "eslint", "ast_guard", "run")


class CheckBusy(RuntimeError):
    """Başka bir kontrol sürüyor ve bekleme süresi doldu."""


class ChecksNotIsolated(RuntimeError):
    """`checks/` ayrı volume değil ve `TP_CHECKS_REQUIRE_MOUNT=1`: kapı dosyası yazılmaz."""


@dataclass(frozen=True)
class CheckRequest:
    sha: str
    test_files: list[str] = field(default_factory=list)
    repeat_each: int = 3
    retries: int = 0
    break_campaign: bool = False
    # Ekilmiş hata kodu (012 §4.6); test-runner'a env.TP_FAULT olarak iletilir.
    fault: str | None = None
    grep: str | None = None
    base_sha: str | None = None
    ast_guard_mode: str = "pr"
    run_id: str | None = None
    record_check: bool | None = None
    keep: bool = False
    # Etkilenen testler (Faz 4 onarım): e2e köküne göre değişen kaynaklar ya da ["@diff"]
    # (base_sha..sha farkı). İçe aktarma grafiğiyle spec dosyalarına çevrilir (worker/affected.py).
    affected_by: list[str] = field(default_factory=list)
    # Dil (009 §2.1, 011 §2.6): "ts" = Playwright/TypeScript (varsayılan, mevcut yol), "java" =
    # TestNG (worker/java.py): uygulama platformunda Appium (`e2e-app`), `web`de (ya da platform
    # yokken) Playwright for Java (`e2e-java`). `platform` Java koşusunda test-runner'a iletilir.
    lang: str = "ts"
    platform: str | None = None

    @property
    def step_names(self) -> tuple[str, ...]:
        return javayol.STEPS if self.lang == "java" else STEPS

    @property
    def check_name(self) -> str | None:
        """Merge kapısındaki kayıt adı: web + TS `local-ci`, web + Java `local-ci-web-java`,
        uygulama Java `local-ci-<platform>`; bilinmeyen platformda None (kayıt yazılmaz; API
        zaten reddeder)."""
        try:
            return check_name(self.lang, self.platform)
        except ValueError:
            return None

    @property
    def full_scope(self) -> bool:
        return not self.test_files and not self.grep and not self.affected_by

    @property
    def breaks_app(self) -> bool:
        """Kontrol demo uygulamayı bilerek bozuyor mu (kampanya kırılması ya da ekilmiş hata)."""
        return self.break_campaign or bool(self.fault)

    def runner_env(self) -> dict[str, str]:
        """test-runner `/run` gövdesindeki `env` (yalnızca istenen kırılma değişkenleri)."""
        env = {"BREAK_CAMPAIGN": "1"} if self.break_campaign else {}
        return {**env, "TP_FAULT": self.fault} if self.fault else env

    def records_check(self) -> bool:
        # Merge kapısına yalnızca tam kapsamlı, kırılmasız kontrol yazılır (record_check ne olursa).
        if self.breaks_app or not self.full_scope or self.check_name is None:
            return False
        return self.record_check is not False

    def scope(self) -> dict[str, Any]:
        return {
            "tam": self.full_scope,
            "test_files": list(self.test_files),
            "grep": self.grep,
            "repeat_each": self.repeat_each,
            "retries": self.retries,
            "break_campaign": self.break_campaign,
            "fault": self.fault,
            "affected_by": list(self.affected_by),
        }


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def default_run_id(sha: str) -> str:
    return f"check-{sha[:12]}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}"


def skipped(reason: str) -> dict[str, Any]:
    return {"ok": False, "skipped": True, "reason": reason}


def aggregate(
    sha: str, steps: dict[str, dict[str, Any]], names: tuple[str, ...] = STEPS
) -> dict[str, Any]:
    """Adım sonuçlarından tek rapor: hepsi tamam ve koşu `passed` ise `success`."""
    failed = [
        name
        for name in names
        if name in steps and not steps[name].get("skipped") and not steps[name].get("ok")
    ]
    run = steps.get("run") or {}
    run_tests = run.get("tests") if isinstance(run.get("tests"), list) else []
    complete = all(name in steps and not steps[name].get("skipped") for name in names)
    success = complete and not failed and run.get("status") == "passed"
    if success and names == javayol.STEPS:
        summary = (
            "Yerel CI (Java) geçti: uygulama eşleşmesi, bağımlılıklar, AST koruması, derleme ve "
            "testler yeşil."
        )
    elif success:
        summary = (
            "Yerel CI geçti: uygulama eşleşmesi, bağımlılıklar, tsc, eslint, AST koruması ve "
            "testler yeşil."
        )
    elif failed:
        summary = "Yerel CI başarısız: " + ", ".join(failed)
    else:
        summary = "Yerel CI tamamlanamadı."
    return {
        "sha": sha,
        "conclusion": "success" if success else "failure",
        "ok": success,
        "failed_steps": failed,
        "summary": summary,
        # Koşu öncesi sağlık kontrolü (koşu yapılmadıysa null): ok=false → `environment`.
        "saglik": run.get("saglik"),
        "failures": run.get("failures") if isinstance(run.get("failures"), list) else [],
        "failure_groups": (
            run.get("failure_groups") if isinstance(run.get("failure_groups"), list) else []
        ),
        "test_counts": _counts(run_tests),
        **{name: steps.get(name, skipped("önceki adım başarısız")) for name in names},
    }


def _counts(tests: list[dict[str, Any]]) -> dict[str, int]:
    out = {"toplam": len(tests), "expected": 0, "unexpected": 0, "flaky": 0, "skipped": 0}
    for t in tests:
        st = t.get("status") if isinstance(t, dict) else None
        if st in out:
            out[st] += 1
    return out


def check_name(lang: str, platform: str | None) -> str:
    """Koşunun check'i (core `platform.check_adi` ile aynı): web + TS `local-ci`, web + Java
    `local-ci-web-java`, uygulamada (Java) `local-ci-<platform>`. `lang=java` + platform yok =
    web + Java (011 §2.6)."""
    if lang != "java":
        return CHECK_NAME
    if platform in (None, javayol.WEB):
        return WEB_JAVA_CHECK_NAME
    if platform not in JAVA_PLATFORMS:
        raise ValueError(f"Java kontrolü platformu: {(javayol.WEB, *JAVA_PLATFORMS)}")
    return f"{CHECK_NAME}-{platform}"


def _existing_checks(path: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Dosyadaki kontrol girdileri ve raporları (okunamazsa boş: yalnızca bu kontrol yazılır).

    Dosyayı yalnızca bu modül yazar; yine de beklenmeyen biçimdeki girdiler atılır.
    """
    if path is None:
        return [], {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], {}
    if not isinstance(data, dict):
        return [], {}
    entries = [
        c
        for c in data.get("checks") or []
        if isinstance(c, dict) and isinstance(c.get("name"), str)
    ]
    reports = data.get("reports") if isinstance(data.get("reports"), dict) else {}
    return entries, reports


def checks_document(
    sha: str,
    status: str,
    report: dict[str, Any] | None,
    name: str = CHECK_NAME,
    existing: Path | None = None,
) -> dict[str, Any]:
    """LocalForge.checks() biçimi: {"checks": [CheckRun…]} (+ rapor, ek alanlar yok sayılır).

    `existing` (aynı sha'nın kapı dosyası) verilirse diğer adlardaki girdiler korunur; bu adın
    girdisi değişir. Sıra kararlıdır: web `local-ci` başta, platformlar ad sırasıyla.
    """
    conclusion = None if report is None else report["conclusion"]
    # `tam`: yalnızca tam kapsamlı kontrol yazılır (CheckRequest.records_check); ek alan,
    # CheckRun onu yok sayar ama core kapıda doğrulayabilir.
    entry = {"name": name, "status": status, "conclusion": conclusion, "url": None, "tam": True}
    others, old_reports = _existing_checks(existing)
    entries = [c for c in others if c["name"] != name] + [entry]
    entries.sort(key=lambda c: (c["name"] != CHECK_NAME, c["name"]))
    names = {c["name"] for c in entries}
    reports = {k: v for k, v in old_reports.items() if k != name and k in names}
    reports[name] = report
    return {
        "schema_version": 1,
        "sha": sha,
        "guncelleme": now_iso(),
        "checks": entries,
        "report": report,
        "reports": reports,
    }


def _call_runner(
    cfg: Settings, body: dict[str, Any], client: httpx.Client | None
) -> dict[str, Any]:
    timeout = cfg.run_timeout_s + cfg.run_queue_wait_s + 60
    http = client or httpx.Client(timeout=timeout)
    try:
        resp = http.post(f"{cfg.test_runner_url}/run", json=body, timeout=timeout)
    except httpx.HTTPError as exc:
        return {"ok": False, "status": "error", "error": f"test-runner'a ulaşılamadı: {exc}"}
    finally:
        if client is None:
            http.close()
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if not resp.is_success:
        detail = data.get("detail") if isinstance(data, dict) else None
        return {
            "ok": False,
            "status": "error",
            "error": f"test-runner HTTP {resp.status_code}: {detail or resp.text[:300]}",
        }
    return {
        **data,
        "ok": data.get("status") == "passed",
        # /check sözleşmesindeki adlar (MIMARI-SOZLESME §2)
        "junit_path": data.get("junit"),
        "json_path": data.get("json"),
    }


def execute(
    cfg: Settings, req: CheckRequest, *, runner_client: httpx.Client | None = None
) -> dict[str, Any]:
    head = repos.locate(cfg, req.sha, fetch=True)
    base = (
        repos.locate(cfg, req.base_sha, fetch=True, prefer=head.repo).sha if req.base_sha else None
    )
    if req.records_check() and cfg.checks_require_mount and not os.path.ismount(cfg.checks_dir):
        raise ChecksNotIsolated(
            f"{cfg.checks_dir} ayrı bir volume değil; merge kapısı dosyası yazılmaz "
            "(test-runner bu dizini görmemeli — MIMARI-SOZLESME §2)."
        )
    if not CHECK_LOCK.acquire(timeout=cfg.check_queue_wait_s):
        raise CheckBusy("Başka bir yerel CI kontrolü sürüyor; daha sonra yeniden deneyin.")
    try:
        return _execute_locked(cfg, req, head, base, runner_client)
    finally:
        CHECK_LOCK.release()


def _execute_locked(
    cfg: Settings,
    req: CheckRequest,
    head: repos.Located,
    base: str | None,
    runner_client: httpx.Client | None,
) -> dict[str, Any]:
    full = head.sha
    path = checks_file(cfg.artifacts_path, full, cfg.checks_dir) if req.records_check() else None
    if path is not None:
        atomic_write_json(
            path,
            checks_document(full, "in_progress", None, req.check_name or CHECK_NAME, existing=path),
        )
    started = time.monotonic()
    steps: dict[str, dict[str, Any]] = {}
    report: dict[str, Any] | None = None
    try:
        if req.lang == "java":
            steps = _run_java_steps(cfg, req, head, base, runner_client, steps)
        else:
            steps = _run_steps(cfg, req, head, base, runner_client, steps)
        report = aggregate(full, steps, req.step_names)
    except Exception as exc:  # dosya her durumda failure ile kapanır
        report = aggregate(full, steps, req.step_names)
        report.update(
            conclusion="failure",
            ok=False,
            summary=f"Yerel CI beklenmeyen hata: {type(exc).__name__}: {exc}",
        )
        raise
    finally:
        if report is not None:
            report["duration_ms"] = int((time.monotonic() - started) * 1000)
            report["checks_path"] = str(path) if path is not None else None
            report["break_campaign"] = req.break_campaign
            report["fault"] = req.fault
            report["kapsam"] = {**req.scope(), "etkilenen": steps.get("affected")}
            report["check_recorded"] = path is not None
            report["kaynak"] = head.kaynak
            report["check_name"] = req.check_name
            if req.lang != "ts":
                report["lang"] = req.lang
                report["platform"] = req.platform or javayol.WEB
            if path is not None:
                atomic_write_json(
                    path,
                    checks_document(
                        full, "completed", report, req.check_name or CHECK_NAME, existing=path
                    ),
                )
    return report


def app_step(cfg: Settings, head: repos.Located) -> dict[str, Any]:
    """Çalışan uygulama istenen commit'in uygulamasıyla aynı mı (bkz. modül belgesi)."""
    uyum = appsha.match(cfg, head)
    ok = uyum.eslesme == "eslesiyor" or (
        uyum.eslesme == "dogrulanamadi" and not cfg.check_require_app_sha
    )
    error = None
    if uyum.eslesme == "farkli":
        error = (
            "Uygulama commit ile eşleşmiyor: testler çalışan demo-app-web'e karşı koşar, "
            f"ancak bu commit uygulama kodunu değiştiriyor ({', '.join(uyum.farkli_yollar)}). "
            "Sonuç bu commit'e ait olamayacağı için koşu yapılmadı; doğrulama GitHub CI'ında "
            "(webServer) ya da uygulama bu commit'ten derlendikten sonra yapılmalı."
        )
    elif not ok:
        error = "Çalışan uygulamanın commit'i bilinmiyor (TP_CHECK_REQUIRE_APP_SHA=1)."
    return {"ok": ok, **uyum.as_dict(), "error": error}


DIFF_MARKER = "@diff"


def _affected(
    cfg: Settings, req: CheckRequest, head: repos.Located, base: str | None, e2e: Any
) -> dict[str, Any]:
    changed = [c for c in req.affected_by if c != DIFF_MARKER]
    if DIFF_MARKER in req.affected_by:
        base_sha = base or gitforge.merge_base(head.repo, head.sha, "main", cfg.git_timeout_s)
        if base_sha:
            changed += affected.changed_files(
                head.repo, base_sha, head.sha, cfg.e2e_root, cfg.git_timeout_s
            )
    changed = list(dict.fromkeys(changed))
    if not changed:
        return {
            "yontem": "import_grafi",
            "kaynak": [],
            "test_files": [],
            "tam_kapsam": True,
            "tam_kapsam_nedeni": "değişen e2e dosyası yok",
            "dosya_sayisi": 0,
        }
    return affected.affected_tests(e2e, changed)


def _run_steps(
    cfg: Settings,
    req: CheckRequest,
    head: repos.Located,
    base: str | None,
    runner_client: httpx.Client | None,
    steps: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Adımları sırayla `steps`'e yazar (beklenmeyen hatada o ana kadarki adımlar raporda kalır)."""
    full = head.sha
    steps["app"] = app_step(cfg, head)
    if not steps["app"]["ok"]:
        return steps
    test_files = list(req.test_files)
    with gitforge.checkout(head.repo, full, cfg.e2e_root, cfg.git_timeout_s) as e2e:
        if req.affected_by:
            steps["affected"] = _affected(cfg, req, head, base, e2e)
            # Belirsizse (tam_kapsam) tüm testler koşar: yanlış yeşil yerine fazla test.
            test_files = [] if steps["affected"]["tam_kapsam"] else steps["affected"]["test_files"]
        missing = [f for f in test_files if not (e2e / f).is_file()]
        if missing:
            # Playwright "No tests found" ile `error` dönerdi; neden burada açıkça söylenir.
            steps["deps"] = {
                "ok": False,
                "error": "Test dosyası commit'te yok: " + ", ".join(missing),
                "missing_test_files": missing,
            }
            return steps
        steps["deps"] = static.check_deps(cfg, e2e)
        if not steps["deps"]["ok"]:
            return steps
        gitforge.link_node_modules(e2e, cfg.e2e_node_modules)
        steps["tsc"] = static.run_tsc(cfg, e2e)
        if not steps["tsc"]["ok"]:
            return steps
        steps["eslint"] = static.run_eslint(cfg, e2e)
        if not steps["eslint"]["ok"]:
            return steps

    base_sha = base or gitforge.merge_base(head.repo, full, "main", cfg.git_timeout_s) or full
    try:
        guard = run_ast_guard(cfg, base_sha, full, req.ast_guard_mode, head.repo)
        steps["ast_guard"] = {
            "ok": bool(guard.get("ok")),
            "mode": req.ast_guard_mode,
            "base_sha": base_sha,
            "report": guard,
        }
    except AstGuardError as exc:
        steps["ast_guard"] = {"ok": False, "mode": req.ast_guard_mode, "error": str(exc)}
    if not steps["ast_guard"]["ok"]:
        return steps

    body: dict[str, Any] = {
        "sha": full,
        "run_id": req.run_id or default_run_id(full),
        "repeat_each": req.repeat_each,
        "retries": req.retries,
        "test_files": test_files,
        "env": req.runner_env(),
        "keep": req.keep,
    }
    if req.grep:
        body["grep"] = req.grep
    steps["run"] = _call_runner(cfg, body, runner_client)
    return steps


def _run_java_steps(
    cfg: Settings,
    req: CheckRequest,
    head: repos.Located,
    base: str | None,
    runner_client: httpx.Client | None,
    steps: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Java yolu (009 §2.3–2.5, 011 §2.6): app → deps (pom kilidi) → guard → compile → run.

    Koruma derlemeden ÖNCE koşar: yalnızca ayrıştırır; Maven ise (güvenilir pom'la da olsa)
    derleyici eklentilerini çalıştırır. Kapsam (`test_files`) proje köküne göredir: uygulama
    platformunda `e2e-app`, web'de `e2e-java` (worker/java.py `java_kok`).
    """
    full = head.sha
    kok = javayol.java_kok(cfg, req.platform)
    steps["app"] = app_step(cfg, head)
    if not steps["app"]["ok"]:
        return steps
    base_sha = base or gitforge.merge_base(head.repo, full, "main", cfg.git_timeout_s) or full
    with gitforge.checkout(head.repo, full, kok.root, cfg.git_timeout_s) as root:
        missing = [f for f in req.test_files if not (root / f).is_file()]
        if missing:
            steps["deps"] = {
                "ok": False,
                "error": "Test dosyası commit'te yok: " + ", ".join(missing),
                "missing_test_files": missing,
            }
            return steps
        steps["deps"] = javayol.check_deps(cfg, root, kok)
        if not steps["deps"]["ok"]:
            return steps
        try:
            guard = javayol.guard_report(
                cfg, head.repo, base_sha, full, req.ast_guard_mode, root, kok
            )
            steps["guard"] = {
                "ok": bool(guard.get("ok")),
                "mode": req.ast_guard_mode,
                "base_sha": base_sha,
                "report": guard,
            }
        except javayol.JavaAracError as exc:
            steps["guard"] = {"ok": False, "mode": req.ast_guard_mode, "error": str(exc)}
        if not steps["guard"]["ok"]:
            return steps
        steps["compile"] = javayol.run_test_compile(cfg, root, kok)
        if not steps["compile"]["ok"]:
            return steps

    body: dict[str, Any] = {
        "sha": full,
        "run_id": req.run_id or default_run_id(full),
        "repeat_each": req.repeat_each,
        "retries": req.retries,
        "test_files": list(req.test_files),
        "env": req.runner_env(),
        "keep": req.keep,
        # test-runner'ın Java yolu (Ş8): dil + platform (Appium sürücüsü seçimi; web = Playwright
        # for Java, Appium yok).
        "lang": "java",
        "platform": kok.platform,
    }
    steps["run"] = _call_runner(cfg, body, runner_client)
    return steps
