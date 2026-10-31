"""Bir commit'in e2e testlerini compose'daki demo uygulamasına karşı koşturur.

Akış (tek seferde bir koşu; bayi kullanıcıları bayi1/bayi2 koşular arasında paylaşılır):
  1. `runs/<run_id>/` oluşturulur (varsa 409: koşu kanıtı değiştirilemez).
  1a. Koşu öncesi sağlık kontrolü: `GET BASE_URL/` ve `GET DEMO_API_URL/health` (kısa zaman aşımı).
     Sonuç `saglik` alanında raporlanır (TEKNIK-TASARIM §8.6 triyaj kuralı 1: sağlık kontrolü
     başarısız → `environment`). Başarısızsa Playwright hiç başlatılmaz, koşu `error` olur.
  2. Commit'in `e2e/` ağacı forge'dan `runs/<run_id>/src/e2e`'ye çıkarılır (koşan kodun birebir
     kopyası kanıt olarak kalır); commit'teki `results/` ve `node_modules` silinir, bağımlılıklar
     imajdan (`/opt/e2e/node_modules`) bağlanır.
  3. `playwright test --project=chromium` (BASE_URL, DEMO_API_URL, DEMOAPP_TEST_TOKEN; kırılma
     istenirse BREAK_CAMPAIGN=1 → e2e fixture'ı koşunun bayisi için `/test/break` açar/kapatır).
  4. Kırılma istendiyse koşu nasıl biterse bitsin (hata, süre aşımı) her bayi için
     `/test/break {kampanya:false}` ile geri alınır (fixture teardown'ı koşmamış olabilir).
  5. Raporlar config'teki yerlerinde kalır: `src/e2e/results/{junit.xml,results.json,
     allure-results/,html/,artifacts/}`; özet `run.json`, süreç çıktısı `runner.log`.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from runner.results import decide_status, summarize
from toolchain_common import gitforge, proc
from toolchain_common.artifacts import atomic_write_json, run_dir
from toolchain_common.settings import Settings

# Tek koşu: aynı bayi kullanıcılarıyla eşzamanlı iki koşu birbirinin verisini sıfırlar.
RUN_LOCK = threading.Lock()

PASS_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "PLAYWRIGHT_BROWSERS_PATH", "TMPDIR")


class RunConflict(RuntimeError):
    """Aynı run_id ile koşu zaten var."""


class RunnerBusy(RuntimeError):
    """Başka bir koşu sürüyor ve bekleme süresi doldu."""


class RunRejected(ValueError):
    """İstek bu ortamda yürütülemez (ör. kırılma için test belirteci yok)."""


@dataclass(frozen=True)
class RunRequest:
    sha: str
    run_id: str
    grep: str | None = None
    repeat_each: int = 1
    retries: int = 0
    break_campaign: bool = False
    test_files: list[str] = field(default_factory=list)
    workers: int | None = None


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def playwright_argv(cfg: Settings, e2e: Path, req: RunRequest) -> list[str]:
    cli = e2e / "node_modules" / "@playwright" / "test" / "cli.js"
    argv = [
        cfg.node,
        str(cli),
        "test",
        "--project=chromium",
        f"--repeat-each={req.repeat_each}",
        f"--retries={req.retries}",
    ]
    if req.workers is not None:
        argv.append(f"--workers={req.workers}")
    if req.grep:
        argv.append(f"--grep={req.grep}")  # `=` biçimi: değer seçenek olarak yorumlanamaz
    argv.extend(req.test_files)  # doğrulanmış: tests/**.spec.ts
    return argv


def playwright_env(cfg: Settings, req: RunRequest) -> dict[str, str]:
    env = {k: os.environ[k] for k in PASS_ENV if k in os.environ}
    env.update(
        {
            "CI": "1",
            "FORCE_COLOR": "0",
            "BASE_URL": cfg.base_url,
            "DEMO_API_URL": cfg.demo_api_url,
            "DEMOAPP_TEST_TOKEN": cfg.demoapp_test_token,
            "BREAK_CAMPAIGN": "1" if req.break_campaign else "",
            "TP_RUN_ID": req.run_id,
        }
    )
    return env


def restore_break(cfg: Settings, client: httpx.Client | None = None) -> dict[str, Any]:
    """Her koşu bayisi için kampanya kırılmasını kapatır (idempotent)."""
    results: dict[str, str] = {}
    own = client is None
    http = client or httpx.Client(timeout=10)
    try:
        for dealer in cfg.run_dealers:
            try:
                resp = http.post(
                    f"{cfg.demo_api_url}/test/break",
                    json={"kullanici_adi": dealer, "kampanya": False},
                    headers={"X-Demoapp-Test-Token": cfg.demoapp_test_token},
                )
                results[dealer] = "ok" if resp.is_success else f"HTTP {resp.status_code}"
            except httpx.HTTPError as exc:
                results[dealer] = f"hata: {type(exc).__name__}"
    finally:
        if own:
            http.close()
    return {"ok": all(v == "ok" for v in results.values()), "bayiler": results}


def _probe(http: httpx.Client, url: str, timeout_s: float) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        resp = http.get(url, timeout=timeout_s, follow_redirects=True)
    except httpx.HTTPError as exc:
        return {
            "url": url,
            "status": None,
            "ms": int((time.monotonic() - t0) * 1000),
            "hata": f"{type(exc).__name__}",
        }
    return {
        "url": url,
        "status": resp.status_code,
        "ms": int((time.monotonic() - t0) * 1000),
        "hata": None if resp.is_success else f"HTTP {resp.status_code}",
    }


def health_check(cfg: Settings, client: httpx.Client | None = None) -> dict[str, Any]:
    """Koşu öncesi demo uygulaması sağlık kontrolü (deterministik `environment` sinyali).

    `ok` yalnızca hem web (`BASE_URL/`) hem API (`DEMO_API_URL/health`) 2xx dönerse doğrudur.
    """
    own = client is None
    http = client or httpx.Client()
    try:
        web = _probe(http, f"{cfg.base_url}/", cfg.health_timeout_s)
        api = _probe(http, f"{cfg.demo_api_url}/health", cfg.health_timeout_s)
    finally:
        if own:
            http.close()
    problems = [
        f"{name} ({p['url']}): {p['hata']}" for name, p in (("web", web), ("api", api)) if p["hata"]
    ]
    return {
        "ok": not problems,
        "zaman": now_iso(),
        "web": web,
        "api": api,
        "hata": "Demo uygulaması sağlık kontrolü başarısız — " + "; ".join(problems)
        if problems
        else None,
    }


def _rel(cfg: Settings, path: Path) -> str:
    return str(path.relative_to(cfg.artifacts_path))


def execute(cfg: Settings, req: RunRequest, *, http: httpx.Client | None = None) -> dict[str, Any]:
    if req.break_campaign and not cfg.demoapp_test_token:
        raise RunRejected("Kırarak doğrulama için DEMOAPP_TEST_TOKEN gerekir (test-runner ortamı).")
    full_sha = gitforge.resolve_commit(cfg.forge_path, req.sha, cfg.git_timeout_s)
    if not RUN_LOCK.acquire(timeout=cfg.run_queue_wait_s):
        raise RunnerBusy("Başka bir test koşusu sürüyor; daha sonra yeniden deneyin.")
    try:
        return _execute_locked(cfg, req, full_sha, http)
    finally:
        RUN_LOCK.release()


def _execute_locked(
    cfg: Settings, req: RunRequest, full_sha: str, http: httpx.Client | None
) -> dict[str, Any]:
    dest = run_dir(cfg.artifacts_path, req.run_id)
    try:
        dest.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise RunConflict(f"run_id zaten kullanılmış: {req.run_id}") from exc
    started = now_iso()
    base: dict[str, Any] = {
        "run_id": req.run_id,
        "sha": full_sha,
        "grep": req.grep,
        "test_files": req.test_files,
        "repeat_each": req.repeat_each,
        "retries": req.retries,
        "break_campaign": req.break_campaign,
        "base_url": cfg.base_url,
        "artifacts_dir": str(dest),
        "baslangic": started,
    }
    atomic_write_json(dest / "run.json", {**base, "status": "running"})
    saglik = health_check(cfg, http)

    e2e = dest / "src" / cfg.e2e_root
    results_dir = e2e / "results"
    res: proc.ProcResult | None = None
    error: str | None = None
    restore: dict[str, Any] | None = None
    try:
        if not saglik["ok"]:
            # Ortam hazır değil: Playwright başlatılmaz (locator zaman aşımları yanıltıcı olurdu).
            error = saglik["hata"]
        else:
            try:
                _export(cfg, full_sha, dest / "src")
            except gitforge.ForgeError as exc:
                error = str(exc)
            else:
                shutil.rmtree(results_dir, ignore_errors=True)  # commit'teki sahte rapor silinir
                gitforge.link_node_modules(e2e, cfg.e2e_node_modules)
                res = proc.run(
                    playwright_argv(cfg, e2e, req),
                    cwd=e2e,
                    env=playwright_env(cfg, req),
                    timeout_s=cfg.run_timeout_s,
                )
    finally:
        # Playwright hiç başlamadıysa kırılma da uygulanmamıştır; geri alma gerekmez.
        if req.break_campaign and saglik["ok"]:
            restore = restore_break(cfg, http)
        nm = e2e / "node_modules"
        if nm.is_symlink():
            nm.unlink()

    summary: dict[str, Any] | None = None
    if res is not None:
        (dest / "runner.log").write_text(
            f"$ {' '.join(res.argv)}\n\n--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}",
            encoding="utf-8",
        )
        try:
            summary = summarize(results_dir / "results.json", dest)
        except ValueError as exc:
            error = str(exc)
        if res.timed_out:
            error = f"Koşu süre sınırını aştı ({int(cfg.run_timeout_s)} sn); süreç durduruldu."
    status = (
        "error"
        if res is None
        else decide_status(exit_code=res.exit_code, timed_out=res.timed_out, summary=summary)
    )
    if status == "error" and error is None:
        if summary and summary["errors"]:
            error = summary["errors"][0]
        elif summary and summary["stats"]["expected"] + summary["stats"]["flaky"] == 0:
            error = "Hiç test koşmadı (filtre eşleşmedi ya da yapılandırma hatası)."
        else:
            error = f"Playwright çıkış kodu {res.exit_code if res else None}"
    if restore is not None and not restore["ok"]:
        # Kırılma geri alınamadıysa uygulama durumu belirsizdir: koşu "error", ayrıntı kayıtta.
        status = "error"
        error = (error + " · " if error else "") + "Kampanya kırılması geri alınamadı."

    report = {
        **base,
        "status": status,
        "error": error,
        "exit_code": res.exit_code if res else None,
        "duration_ms": res.duration_ms if res else 0,
        "bitis": now_iso(),
        "junit": str(results_dir / "junit.xml"),
        "json": str(results_dir / "results.json"),
        "allure_dir": str(results_dir / "allure-results"),
        "html_dir": str(results_dir / "html"),
        "traces_dir": str(results_dir / "artifacts"),
        "log": str(dest / "runner.log"),
        "artifacts_rel": _rel(cfg, dest),
        "break_restore": restore,
        "saglik": saglik,
        "stats": summary["stats"] if summary else None,
        "tests": summary["tests"] if summary else [],
        "report_errors": summary["errors"] if summary else [],
    }
    atomic_write_json(dest / "run.json", report)
    return report


def _export(cfg: Settings, sha: str, into: Path) -> None:
    """Commit'in e2e ağacını `into/<e2e_root>`'a çıkarır (kalıcı; koşu kanıtı)."""
    with gitforge.checkout(cfg.forge_path, sha, cfg.e2e_root, cfg.git_timeout_s) as e2e:
        target = into / cfg.e2e_root
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(e2e, target, symlinks=True)
