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
  5a. `allure-results/`'tan statik, tek dosyalık Allure raporu üretilir
     (`src/e2e/results/allure-report/index.html`; imajdaki sabit Allure 3 CLI, allure2 eklentisi,
     analitik kapalı, ağ yok, AI yok). Üretilemezse koşu sonucu değişmez; `allure_report.error`.
     Başarısız/kararsız her test için `failure` (hata türü, konum, adım, kanıt yolları) ve
     `failures` listesi: Faz 3 yerel kontrolü ve Faz 4 triage'ının deterministik girdileri.
  6. Temizlik: en yeni `TP_RUNS_KEEP` (50) koşu dizini kalır; süren koşular silinmez. `.keep`
     işaretli kanıt koşuları (istekte `keep: true`) bu sayıma girmez, ama sınırsız da büyümez:
     `TP_RUNS_KEEP_EVIDENCE_DAYS` (30) günden eskiler ve en yeni `TP_RUNS_KEEP_EVIDENCE_MAX` (200)
     dışındakiler silinir. Core, sahibi script kapanınca işareti toolchain-worker
     `POST /runs/release` ile daha erken kaldırabilir (ekran görüntüsü saklamasıyla aynı yaşam).

Eşzamanlılık: süreç içi `RUN_LOCK` + süreçler arası dosya kilidi (`TP_RUN_LOCK_PATH`, flock;
toolchain_common/runlock.py). Konteynerde elle başlatılan koşular (`make e2e-smoke`) aynı kilidi
`tp-run-lock` ile alır; böylece aynı bayilerle iki koşu asla üst üste binmez.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from runner.results import decide_status, failure_groups, failures_of, summarize
from toolchain_common import gitforge, proc, repos, runlock
from toolchain_common.artifacts import KEEP_MARKER, atomic_write_json, ensure_inside, run_dir
from toolchain_common.settings import Settings
from toolchain_common.validation import RUN_ID_RE

# Tek koşu: aynı bayi kullanıcılarıyla eşzamanlı iki koşu birbirinin verisini sıfırlar.
RUN_LOCK = threading.Lock()

PASS_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "PLAYWRIGHT_BROWSERS_PATH", "TMPDIR")
DAY_S = 86_400
# Rapor türü → config'teki yer (`results/` altında) ve varlığının işareti olan dosya.
REPORTS = {
    "html": ("html", "index.html"),
    "junit": ("junit.xml", None),
    "json": ("results.json", None),
    "allure": ("allure-results", None),
    "allure_html": ("allure-report", "index.html"),
}
ALLURE_REPORT_DIR = "allure-report"
# Üretilen raporda dış kaynak yüklemesi (analitik vb.) olmamalı: varsa rapor silinir.
EXTERNAL_LOAD = re.compile(
    rb"<(?:script|link|img|iframe)\b[^>]*\b(?:src|href)\s*=\s*[\"']?(?:https?:)?//", re.I
)


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
    keep: bool = False


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


def reports_of(cfg: Settings, results_dir: Path) -> dict[str, dict[str, Any]]:
    """Playwright raporları: yol, artefakt köküne göre yol ve üretilip üretilmediği."""
    out: dict[str, dict[str, Any]] = {}
    for name, (sub, marker) in REPORTS.items():
        path = results_dir / sub
        probe = path / marker if marker else path
        out[name] = {"path": str(path), "rel": _rel(cfg, path), "exists": probe.exists()}
    return out


def generate_allure(cfg: Settings, results_dir: Path) -> dict[str, Any]:
    """`allure-results/`'tan statik tek dosyalık Allure raporu (`allure-report/index.html`).

    Deterministik araç adımı (AI yok): imajdaki sabit sürüm Allure CLI'ı, güvenilir yapılandırma
    (`TP_ALLURE_CONFIG`, commit'ten değil) ve geçici bir çalışma dizini (commit'teki olası
    `allurerc` okunmaz). Analitik kapalıdır (ALLURE_NO_ANALYTICS); çıktıda yine de dış kaynak
    yüklemesi varsa rapor silinir. Hata koşu sonucunu değiştirmez.
    """
    source = results_dir / "allure-results"
    out = results_dir / ALLURE_REPORT_DIR
    base: dict[str, Any] = {"ok": False, "index": str(out / "index.html"), "error": None}
    if results_dir.is_symlink() or not results_dir.is_dir():
        return {**base, "error": "results/ dizini yok ya da bağlantı; rapor üretilmedi."}
    # Koşan test kodu `results/` altına (bağlantı dahil) bir şey bırakmış olabilir: çıktı yolu
    # önce temizlenir, böylece rapor bir symlink üzerinden başka yere yazılamaz.
    if out.is_symlink() or out.is_file():
        out.unlink()
    elif out.is_dir():
        shutil.rmtree(out)
    if not source.is_dir() or source.is_symlink() or not any(source.iterdir()):
        return {**base, "error": "allure-results boş ya da yok; rapor üretilmedi."}
    if not cfg.allure_cli.is_file() or not cfg.allure_config.is_file():
        return {**base, "error": "Allure CLI imajda yok (toolchain imajı yeniden derlenmeli)."}
    env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "TZ") if k in os.environ}
    env.update({"ALLURE_NO_ANALYTICS": "true", "CI": "1", "FORCE_COLOR": "0", "NO_COLOR": "1"})
    with tempfile.TemporaryDirectory(prefix="tp-allure-") as work:
        res = proc.run(
            [
                cfg.node,
                str(cfg.allure_cli),
                "generate",
                "--config",
                str(cfg.allure_config),
                "--output",
                str(out),
                str(source),
            ],
            cwd=Path(work),
            env=env,
            timeout_s=cfg.allure_timeout_s,
        )
    index = out / "index.html"
    if res.timed_out:
        error = f"Allure raporu süre sınırını aştı ({int(cfg.allure_timeout_s)} sn)."
    elif res.exit_code != 0 or not index.is_file():
        error = f"Allure raporu üretilemedi: {(res.stderr or res.stdout).strip()[:300]}"
    else:
        try:
            external = EXTERNAL_LOAD.search(index.read_bytes()) is not None
        except OSError as exc:
            external, error = False, f"Allure raporu okunamadı: {type(exc).__name__}"
        else:
            error = (
                "Allure raporu dış kaynak yüklüyor (analitik?); rapor silindi."
                if external
                else None
            )
    if error is not None:
        shutil.rmtree(out, ignore_errors=True)
        return {**base, "error": error, "duration_ms": res.duration_ms}
    return {
        **base,
        "ok": True,
        "rel": _rel(cfg, index),
        "duration_ms": res.duration_ms,
    }


def prune_runs(cfg: Settings, current: str) -> dict[str, Any]:
    """Eski koşu dizinlerini siler (`run.json` zamanına göre); iki ayrı havuz:

    - işaretsiz koşular: en yeni `cfg.runs_keep` kalır (0 = bu havuzun temizliği kapalı);
    - `.keep` işaretli kanıt koşuları: `cfg.runs_keep_evidence_days` günden eskiler ve en yeni
      `cfg.runs_keep_evidence_max` dışındakiler silinir (her biri 0 = o sınır kapalı).

    Silinmeyenler: bu koşu, `running` durumundaki ve süre sınırının iki katından genç olanlar
    (çökmüş koşu ancak bundan sonra silinir), adı koşu kimliği olmayan ya da bağlantı (symlink)
    olan girdiler. Hata koşuyu düşürmez; raporlanır.
    """
    keep_days, keep_max = cfg.runs_keep_evidence_days, cfg.runs_keep_evidence_max
    out: dict[str, Any] = {
        "keep": cfg.runs_keep,
        "keep_evidence_days": keep_days,
        "keep_evidence_max": keep_max,
        "deleted": [],
        "deleted_evidence": [],
        "errors": [],
    }
    if cfg.runs_keep <= 0 and keep_days <= 0 and keep_max <= 0:
        return out
    root = cfg.artifacts_path / "runs"
    now = time.time()
    candidates: list[tuple[float, Path]] = []
    evidence: list[tuple[float, Path]] = []
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        out["errors"].append(f"{type(exc).__name__}")
        return out
    for d in entries:
        if d.name == current or d.is_symlink() or not d.is_dir() or not RUN_ID_RE.match(d.name):
            continue
        kept = (d / KEEP_MARKER).exists()
        meta = d / "run.json"
        try:
            mtime = (meta if meta.exists() else d).stat().st_mtime
        except OSError:
            continue
        try:
            status = json.loads(meta.read_text(encoding="utf-8")).get("status")
        except (OSError, ValueError, AttributeError):
            status = None
        if status == "running" and now - mtime < 2 * cfg.run_timeout_s:
            continue
        (evidence if kept else candidates).append((mtime, d))

    doomed: list[Path] = []
    if cfg.runs_keep > 0:
        candidates.sort(key=lambda c: c[0], reverse=True)
        # Bu koşu da sayılır: toplamda en çok `runs_keep` (işaretsiz) koşu kalır.
        doomed += [d for _m, d in candidates[max(0, cfg.runs_keep - 1) :]]
    doomed_evidence: list[Path] = []
    if keep_days > 0 or keep_max > 0:
        evidence.sort(key=lambda c: c[0], reverse=True)
        for i, (mtime, d) in enumerate(evidence):
            too_old = keep_days > 0 and now - mtime > keep_days * DAY_S
            # Bu koşu da kanıt olabilir; sayım yaklaşıktır (bu koşu en yenidir ve hiç silinmez).
            too_many = keep_max > 0 and i >= keep_max
            if too_old or too_many:
                doomed_evidence.append(d)
    for d in [*doomed, *doomed_evidence]:
        try:
            ensure_inside(root, d)
            shutil.rmtree(d)
            out["deleted_evidence" if d in doomed_evidence else "deleted"].append(d.name)
        except (OSError, ValueError) as exc:
            out["errors"].append(f"{d.name}: {type(exc).__name__}")
    return out


def execute(cfg: Settings, req: RunRequest, *, http: httpx.Client | None = None) -> dict[str, Any]:
    if req.break_campaign and not cfg.demoapp_test_token:
        raise RunRejected("Kırarak doğrulama için DEMOAPP_TEST_TOKEN gerekir (test-runner ortamı).")
    # Yerel forge ya da (GitHub modunda toolchain-worker'ın çektiği) ayna; test-runner çekmez.
    loc = repos.locate(cfg, req.sha)
    deadline = time.monotonic() + cfg.run_queue_wait_s
    if not RUN_LOCK.acquire(timeout=cfg.run_queue_wait_s):
        raise RunnerBusy("Başka bir test koşusu sürüyor; daha sonra yeniden deneyin.")
    try:
        # Süreçler arası kilit: konteynerde elle başlatılan koşu (`tp-run-lock`, make e2e-smoke).
        try:
            fd = runlock.acquire(cfg.run_lock_path, deadline - time.monotonic())
        except runlock.RunLockTimeout as exc:
            raise RunnerBusy(
                "Başka bir test koşusu sürüyor (konteynerde elle başlatılmış olabilir: "
                "make e2e-smoke); daha sonra yeniden deneyin."
            ) from exc
        try:
            return _execute_locked(cfg, req, loc, http)
        finally:
            runlock.release(fd)
    finally:
        RUN_LOCK.release()


def _execute_locked(
    cfg: Settings, req: RunRequest, loc: repos.Located, http: httpx.Client | None
) -> dict[str, Any]:
    full_sha = loc.sha
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
        "workers": req.workers,
        "keep": req.keep,
        "base_url": cfg.base_url,
        "artifacts_dir": str(dest),
        "baslangic": started,
    }
    if req.keep:
        (dest / KEEP_MARKER).write_text(f"{started}\n", encoding="utf-8")
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
                _export(cfg, loc, dest / "src")
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
    allure_report: dict[str, Any] | None = None
    if res is not None:
        allure_report = generate_allure(cfg, results_dir)
        (dest / "runner.log").write_text(
            f"$ {' '.join(res.argv)}\n\n--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}",
            encoding="utf-8",
        )
        try:
            summary = summarize(
                results_dir / "results.json", dest, e2e_dir=e2e, rel_root=cfg.artifacts_path
            )
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
        "failures": failures_of(summary["tests"]) if summary else [],
        "failure_groups": failure_groups(summary["tests"]) if summary else [],
        "report_errors": summary["errors"] if summary else [],
        "reports": reports_of(cfg, results_dir),
        "allure_report": allure_report,
    }
    atomic_write_json(dest / "run.json", report)
    try:
        report["cleanup"] = prune_runs(cfg, req.run_id)
    except OSError as exc:  # temizlik koşu sonucunu değiştirmez
        report["cleanup"] = {
            "keep": cfg.runs_keep,
            "deleted": [],
            "deleted_evidence": [],
            "errors": [str(exc)],
        }
    return report


def _export(cfg: Settings, loc: repos.Located, into: Path) -> None:
    """Commit'in e2e ağacını `into/<e2e_root>`'a çıkarır (kalıcı; koşu kanıtı)."""
    with gitforge.checkout(loc.repo, loc.sha, cfg.e2e_root, cfg.git_timeout_s) as e2e:
        target = into / cfg.e2e_root
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(e2e, target, symlinks=True)
