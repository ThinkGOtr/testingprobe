"""Faz 3 inceleme düzeltmeleri (toolchain şeridi).

1. Merge kapısı (`checks/`) test-runner'dan yalıtılır: ayrı dizin/volume (`TP_CHECKS_PATH`),
   ayrı değilse `TP_CHECKS_REQUIRE_MOUNT=1` ile yazılmaz; test-runner sağlığı kapı volume'ü
   bağlıysa hata verir.
2. GitHub modu: yerel forge'da olmayan sha uzak depodan (sahte "GitHub" = ayrı bare depo)
   aynaya çekilir; /symbols → /check → test-runner /run aynı yoldan geçer.
3. Uygulama eşleşmesi: çalışan uygulamanın ağacı commit'inkinden farklıysa /check koşmaz ve
   `local-ci` başarı yazmaz.
4. Allure: koşu sonrası statik tek dosyalık HTML raporu (dış kaynak yüklemez).
5. Toolchain imajı PID 1 olarak tini ile koşar (zombi Chromium süreçleri biçilir).
"""

from __future__ import annotations

import dataclasses
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from runner import run as runner
from runner.app import app as runner_app
from tests.conftest import (
    TOOLCHAIN,
    Forge,
    git,
    make_fake_node,
    requires_node,
    requires_symbols,
)
from tests.test_check import _localforge_parse, fake_tools, runner_client
from tests.test_runner import REPORT_PASSED, DemoApi, demo_api, fake_playwright  # noqa: F401
from toolchain_common import check_checks_hidden, check_checks_volume, gitforge, repos
from toolchain_common.settings import settings
from worker import app as worker_app
from worker import check as checks

# ----------------------------------------------------------------------------- yardımcılar


def _execute(**kw: Any) -> tuple[dict[str, Any], list]:
    client, calls = runner_client(kw.pop("response", None))
    return checks.execute(settings(), checks.CheckRequest(**kw), runner_client=client), calls


@pytest.fixture
def remote(forge: Forge, tmp_path: Path) -> dict[str, Any]:
    """Sahte GitHub: forge'dan klonlanmış ayrı bare depo; yerel forge'da olmayan commit'ler."""
    bare = tmp_path / "github" / "demo-app.git"
    bare.parent.mkdir()
    subprocess.run(["git", "clone", "-q", "--bare", str(forge.bare), str(bare)], check=True)
    work = tmp_path / "gh-work"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], check=True)
    (work / "e2e" / "tests" / "generated").mkdir(parents=True, exist_ok=True)
    (work / "e2e" / "tests" / "generated" / "gh.spec.ts").write_text("// github\n")
    git(work, "checkout", "-q", "-b", "tp/case-gh")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "github commit")
    git(work, "push", "-q", "origin", "tp/case-gh")
    pr_head = git(work, "rev-parse", "HEAD")
    git(work, "checkout", "-q", "main")
    (work / "README.md").write_text("github main ilerledi\n")
    git(work, "commit", "-q", "-am", "main ilerledi")
    git(work, "push", "-q", "origin", "main")
    gh_main = git(work, "rev-parse", "HEAD")
    return {"url": f"file://{bare}", "bare": bare, "pr_head": pr_head, "main": gh_main}


# ---------------------------------------------------------- 1. merge kapısı yalıtımı


def test_checks_written_to_separate_checks_path(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = tmp_path / "checks-volume"
    monkeypatch.setenv("TP_CHECKS_PATH", str(gate))
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path)))
    report, _ = _execute(sha=forge.main)
    assert report["check_recorded"] is True
    assert report["checks_path"] == str(gate / f"{forge.main}.json")
    assert _localforge_parse(gate / f"{forge.main}.json")[0]["conclusion"] == "success"
    # test-runner'ın gördüğü paylaşılan artefakt kökünde kapı dosyası yok.
    assert not (env / "checks").exists()


def test_require_mount_refuses_to_write_gate_on_shared_dir(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_CHECKS_REQUIRE_MOUNT", "1")
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path)))
    with pytest.raises(checks.ChecksNotIsolated):
        _execute(sha=forge.main)
    assert not (env / "checks").exists()
    # Kaydedilmeyen (kapsamlı) kontrol etkilenmez.
    report, _ = _execute(sha=forge.main, test_files=[], grep="@x")
    assert report["check_recorded"] is False and report["conclusion"] == "success"
    resp = TestClient(worker_app.app).post("/check", json={"sha": forge.main})
    assert resp.status_code == 503 and "ayrı bir volume değil" in resp.json()["detail"]


def test_checks_volume_health(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Ayrı bağlama noktası yok: varsayılan uyarı, zorunluysa hata (toolchain-worker).
    assert check_checks_volume().startswith("ok (uyarı:")
    monkeypatch.setenv("TP_CHECKS_REQUIRE_MOUNT", "1")
    assert check_checks_volume().startswith("error:")
    monkeypatch.setattr("os.path.ismount", lambda p: True)
    assert check_checks_volume() == "ok (ayrı volume)"
    # test-runner: kapı volume'ü bağlıysa hata.
    assert check_checks_hidden().startswith("error:")
    monkeypatch.setattr("os.path.ismount", lambda p: False)
    assert check_checks_hidden() == "ok"


def test_security_check_script_asserts_runner_cannot_reach_gate() -> None:
    script = (TOOLCHAIN / "security" / "checks-isolation.sh").read_text()
    assert "test-runner" in script and "/checks" in script and "touch" in script
    proc = subprocess.run(["bash", "-n", str(TOOLCHAIN / "security" / "checks-isolation.sh")])
    assert proc.returncode == 0


# ------------------------------------------------------------- 2. GitHub aynası


def test_sha_absent_from_local_forge_is_404_without_remote(
    env: Path, remote: dict[str, Any]
) -> None:
    resp = TestClient(worker_app.app).post("/symbols", json={"sha": remote["pr_head"]})
    assert resp.status_code == 404


def test_locate_fetches_missing_sha_into_mirror(
    env: Path, forge: Forge, remote: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_FORGE_REMOTE_URL", remote["url"])
    cfg = settings()
    with pytest.raises(gitforge.CommitNotFound):
        repos.locate(cfg, remote["pr_head"])  # fetch=False: test-runner hiç çekmez
    loc = repos.locate(cfg, remote["pr_head"], fetch=True)
    assert loc.kaynak == "ayna" and loc.sha == remote["pr_head"]
    assert loc.repo == cfg.forge_mirror_path
    # Yerel forge'a hiçbir şey yazılmadı (salt okunur bağlanır).
    with pytest.raises(gitforge.CommitNotFound):
        gitforge.resolve_commit(forge.bare, remote["pr_head"])
    # Artık test-runner (fetch=False) da bulur; yerel forge'daki sha'lar önce forge'dan.
    assert repos.locate(cfg, remote["pr_head"]).kaynak == "ayna"
    assert repos.locate(cfg, forge.main).kaynak == "forge"
    # Ad (main) uzak depo yapılandırılmışsa uzaktan tazelenir: yerel forge'un eski main'i değil.
    assert repos.locate(cfg, "main", fetch=True).sha == remote["main"] != forge.main


def test_fetch_token_goes_to_header_env_not_argv() -> None:
    env = gitforge.fetch_env("gizli-belirtec")
    assert env["GIT_ALLOW_PROTOCOL"] == "https:file"
    n = int(env["GIT_CONFIG_COUNT"])
    pairs = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"] for i in range(n)}
    assert pairs["safe.directory"] == "*"
    assert pairs["http.extraHeader"].startswith("Authorization: Basic ")
    assert "gizli-belirtec" not in pairs["http.extraHeader"]  # base64


@requires_node
@requires_symbols
def test_github_mode_symbols_check_and_run_same_path(
    env: Path,
    forge: Forge,
    remote: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    demo_api: DemoApi,  # noqa: F811
) -> None:
    """GitHubForge'un verdiği (yerel forge'da olmayan) sha: sembol → kontrol → koşu → kayıt."""
    monkeypatch.setenv("TP_FORGE_REMOTE_URL", remote["url"])
    monkeypatch.setenv("TP_NODE", "node")
    worker_app._SYMBOL_CACHE.clear()
    worker = TestClient(worker_app.app)

    resp = worker.post("/symbols", json={"sha": remote["main"]})
    assert resp.status_code == 200, resp.text
    table = resp.json()
    assert table["sha"] == remote["main"] and table["kaynak"] == "ayna"
    assert any(po["class"] == "CartPage" for po in table["page_objects"])

    # /check: statik araçlar sahte; test-runner gerçek uygulama (sahte Playwright) ve aynadan okur.
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path)))
    report, calls = _execute(sha=remote["pr_head"], test_files=["tests/generated/gh.spec.ts"])
    assert report["conclusion"] == "success", report["failed_steps"]
    assert report["kaynak"] == "ayna" and report["sha"] == remote["pr_head"]
    # Taban: aynadaki (GitHub) main ile merge-base, yerel forge'un main'i değil.
    assert report["ast_guard"]["base_sha"] == git(
        remote["bare"].parent.parent / "gh-work", "merge-base", remote["pr_head"], remote["main"]
    )
    assert calls[0]["body"]["sha"] == remote["pr_head"]

    pw = tmp_path / "pw"
    pw.mkdir()
    monkeypatch.setenv("TP_NODE", str(fake_playwright(pw, report=REPORT_PASSED)))
    run = TestClient(runner_app).post(
        "/run", json={"run_id": "gh-1", "sha": remote["pr_head"], "test_files": []}
    )
    assert run.status_code == 200, run.text
    assert run.json()["status"] == "passed"
    copied = env / "runs" / "gh-1" / "src" / "e2e" / "tests" / "generated" / "gh.spec.ts"
    assert copied.read_text() == "// github\n"


# ---------------------------------------------------------- 3. uygulama eşleşmesi


def test_check_refuses_when_running_app_differs_from_commit(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uygulama kodunu değiştiren PR (ör. F2 düzeltmesi) eski uygulamaya karşı koşturulmaz."""
    sha_file = tmp_path / "demo-app-web.sha"
    sha_file.write_text(forge.main + "\n")
    monkeypatch.setenv("TP_APP_BUILD_SHA_FILE", str(sha_file))
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path)))
    fix = forge.commit("fix/f2", {"api/src/kampanya.py": "free = qty // 7\n"})
    report, calls = _execute(sha=fix)
    assert report["conclusion"] == "failure" and report["failed_steps"] == ["app"]
    assert report["app"]["sha_eslesmesi"] == "farkli"
    assert report["app"]["farkli_yollar"] == ["api"]
    assert "Uygulama commit ile eşleşmiyor" in report["app"]["error"]
    assert calls == [] and report["run"]["skipped"] is True
    doc = _localforge_parse(env / "checks" / f"{fix}.json")
    assert doc[0]["conclusion"] == "failure"

    # Yalnızca e2e değiştiren dal (kod üretimi): uygulama ağacı aynı → koşulur.
    gen = forge.commit("tp/case-c1", {"e2e/tests/generated/c1.spec.ts": "// c1\n"})
    report, calls = _execute(sha=gen)
    assert report["conclusion"] == "success" and len(calls) == 1
    assert report["app"]["sha_eslesmesi"] == "eslesiyor"
    assert report["app"]["uygulama_sha_kaynagi"] == "dosya"


def test_unknown_app_sha_warns_or_fails_when_required(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path)))
    report, _ = _execute(sha=forge.main)
    assert report["conclusion"] == "success"
    assert report["app"]["sha_eslesmesi"] == "dogrulanamadi" and report["app"]["uyari"]
    monkeypatch.setenv("TP_CHECK_REQUIRE_APP_SHA", "1")
    report, calls = _execute(sha=forge.main)
    assert report["conclusion"] == "failure" and report["failed_steps"] == ["app"]
    assert calls == []


# ----------------------------------------------------------------------- 4. Allure


def _allure_fake(tmp_path: Path, html: str, exit_code: int = 0) -> Path:
    """Playwright + Allure CLI yerine: Playwright allure-results yazar; Allure index.html üretir."""
    return make_fake_node(
        tmp_path,
        f"""
        argv = sys.argv[1:]
        if argv[0].endswith("allure-cli.js"):
            assert argv[1] == "generate" and "--config" in argv
            assert os.environ.get("ALLURE_NO_ANALYTICS") == "true"
            out = pathlib.Path(argv[argv.index("--output") + 1])
            pathlib.Path({str(tmp_path / "allure-argv.json")!r}).write_text(
                json.dumps({{"argv": argv, "cwd": os.getcwd()}}))
            out.mkdir(parents=True, exist_ok=True)
            (out / "index.html").write_text({html!r})
            sys.exit({exit_code})
        cwd = pathlib.Path.cwd()
        res = cwd / "results"
        (res / "allure-results").mkdir(parents=True, exist_ok=True)
        (res / "allure-results" / "a-result.json").write_text("{{}}")
        # Test kodu rapor yoluna bağlantı bırakmaya çalışır: üzerine yazılmamalı.
        (res / "allure-report").symlink_to("/tmp", target_is_directory=True)
        (res / "results.json").write_text({json.dumps(json.dumps(REPORT_PASSED))})
        sys.exit(0)
        """,
        name="fake-allure-node",
    )


def _with_allure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, html: str) -> None:
    cli = tmp_path / "allure" / "allure-cli.js"
    cli.parent.mkdir()
    cli.write_text("// sahte\n")
    (tmp_path / "allure" / "allurerc.mjs").write_text("export default {};\n")
    monkeypatch.setenv("TP_ALLURE_CLI", str(cli))
    monkeypatch.setenv("TP_ALLURE_CONFIG", str(tmp_path / "allure" / "allurerc.mjs"))
    monkeypatch.setenv("TP_NODE", str(_allure_fake(tmp_path, html)))


def test_run_generates_static_allure_report(
    env: Path,
    forge: Forge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    demo_api: DemoApi,  # noqa: F811
) -> None:
    _with_allure(tmp_path, monkeypatch, "<html><body>Allure</body></html>")
    resp = TestClient(runner_app).post("/run", json={"run_id": "al-1", "sha": forge.main})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "passed"
    rel = "runs/al-1/src/e2e/results/allure-report/index.html"
    assert data["allure_report"]["ok"] is True and data["allure_report"]["rel"] == rel
    assert data["reports"]["allure_html"] == {
        "path": str(env / "runs" / "al-1" / "src" / "e2e" / "results" / "allure-report"),
        "rel": "runs/al-1/src/e2e/results/allure-report",
        "exists": True,
    }
    index = env / rel
    assert not index.parent.is_symlink() and index.read_text().startswith("<html>")
    called = json.loads((tmp_path / "allure-argv.json").read_text())
    # Commit dizininde değil, geçici dizinde ve güvenilir yapılandırmayla çağrılır.
    assert "/src/e2e" not in called["cwd"]
    assert called["argv"][called["argv"].index("--config") + 1].endswith("allurerc.mjs")


def test_allure_report_with_external_script_is_dropped(
    env: Path,
    forge: Forge,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    demo_api: DemoApi,  # noqa: F811
) -> None:
    html = '<html><script async src="https://www.googletagmanager.com/gtag/js"></script></html>'
    _with_allure(tmp_path, monkeypatch, html)
    data = TestClient(runner_app).post("/run", json={"run_id": "al-2", "sha": forge.main}).json()
    assert data["status"] == "passed"  # rapor hatası koşu sonucunu değiştirmez
    assert data["allure_report"]["ok"] is False and "dış kaynak" in data["allure_report"]["error"]
    assert data["reports"]["allure_html"]["exists"] is False


ALLURE_PKG = TOOLCHAIN / "allure"


@requires_node
@pytest.mark.skipif(
    not (ALLURE_PKG / "node_modules" / "allure" / "cli.js").is_file(),
    reason="toolchain/allure/node_modules yok (cd toolchain/allure && npm ci --ignore-scripts)",
)
def test_real_allure_cli_produces_offline_single_file(tmp_path: Path) -> None:
    results = tmp_path / "results"
    src = results / "allure-results"
    src.mkdir(parents=True)
    (src / "0f-result.json").write_text(
        json.dumps(
            {
                "uuid": "0f",
                "historyId": "h1",
                "name": "7 adet Portakal Gazozu → 1 adet bedava",
                "fullName": "tests/generated/tpd-1-c1.spec.ts#c1",
                "status": "passed",
                "stage": "finished",
                "start": 1,
                "stop": 2,
                "labels": [{"name": "tag", "value": "@TPD-1"}],
                "steps": [],
                "attachments": [],
                "parameters": [],
            }
        )
    )
    cfg = dataclasses.replace(
        settings(),
        node=shutil.which("node") or "node",
        artifacts_path=tmp_path,
        allure_cli=ALLURE_PKG / "node_modules" / "allure" / "cli.js",
        allure_config=ALLURE_PKG / "allurerc.mjs",
    )
    out = runner.generate_allure(cfg, results)
    assert out["ok"] is True, out
    html = (results / "allure-report" / "index.html").read_text(encoding="utf-8")
    assert "Portakal Gazozu" in html or "allure" in html.lower()
    assert re.search(r"<script[^>]*src=[\"']?https?://", html) is None


def test_allure_package_pinned_and_config_disables_external_loads() -> None:
    pkg = json.loads((ALLURE_PKG / "package.json").read_text())
    assert re.fullmatch(r"\d+\.\d+\.\d+", pkg["dependencies"]["allure"])
    lock = json.loads((ALLURE_PKG / "package-lock.json").read_text())
    assert lock["packages"]["node_modules/allure"]["version"] == pkg["dependencies"]["allure"]
    # awesome eklentisi analitiği koşulsuz ekler; allure2 eklentisi ALLURE_NO_ANALYTICS'e uyar.
    rc = (ALLURE_PKG / "allurerc.mjs").read_text()
    assert "allure2" in rc and "singleFile: true" in rc and "awesome" not in rc.split("//")[0]


# ------------------------------------------------------------------- 5. imaj: tini


def test_toolchain_image_runs_under_init_and_ships_allure() -> None:
    dockerfile = (TOOLCHAIN / "Dockerfile").read_text()
    assert re.search(r'^ENTRYPOINT \["/usr/bin/tini", "-s", "-g", "--"\]$', dockerfile, re.M)
    assert "tini" in dockerfile.split("ENTRYPOINT")[0]  # kurulum ENTRYPOINT'ten önce
    assert "/opt/allure" in dockerfile and "allure/package-lock.json" in dockerfile
    # Kapı volume'ünün bağlama noktası pwuser'ın (boş volume ilk bağlamada sahipliği alır).
    assert re.search(r"mkdir -p [^\n]*/checks", dockerfile)
