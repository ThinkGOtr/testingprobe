"""scripts/forge-init.sh break|baseline|sync-web — demo-app-web derlemesinin idempotentliği.

Docker ve core-worker sahte: `TP_FORGE_EXEC` sahte bir yürütücüye, PATH'teki `docker` her çağrıyı
günlüğe yazan bir betiğe işaret eder. Çalışan uygulama main'i yansıtıyorsa (`forge_demo web-state`
`guncel=true`) ne `docker build` ne `compose up --force-recreate` çalışmalı: ikinci bir `make break`
süren push CI'ının altındaki uygulamayı öldürmemeli.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "scripts" / "forge-init.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or not SCRIPT.exists(), reason="bash / forge-init.sh yok"
)

MAIN = "b" * 40
BASE = "a" * 40
TREE = "c" * 40

FAKE_EXEC = r"""
import io, json, os, sys, tarfile
st = os.environ["FAKE_STATE"]
a = sys.argv[1:]
def log(line):
    with open(os.path.join(st, "exec.log"), "a") as f:
        f.write(line + "\n")
def cat(name):
    sys.stdout.write(open(os.path.join(st, name)).read())
if a[:2] == ["python", "-c"]:
    sys.exit(0)
if a[:3] == ["python", "-m", "tp_core.integrations.forge_demo"]:
    cmd = a[3]
    log("forge_demo " + " ".join(a[3:]))
    if cmd in ("break", "baseline"):
        print(json.dumps({"action": cmd, "changed": False}))
    elif cmd == "status":
        cat("status.json")
    elif cmd == "web-state":
        cat("web_state.json")
    elif cmd == "archive":
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as t:
            data = b"FROM scratch\n"
            ti = tarfile.TarInfo("Dockerfile"); ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
        sys.stdout.buffer.write(buf.getvalue())
    sys.exit(0)
if a[:2] == ["sh", "-c"]:
    if "demo-app-web.sha" in a[2]:
        open(os.path.join(st, "sha_file"), "w").write(a[4] + "\n")
        log("sha_file " + a[4])
    elif "TP_FORGE" in a[2]:
        sys.stdout.write("local")
    sys.exit(0)
sys.exit(97)
"""

FAKE_DOCKER = r"""
import os, sys
st = os.environ["FAKE_STATE"]
a = sys.argv[1:]
with open(os.path.join(st, "docker.log"), "a") as f:
    f.write(" ".join(a) + "\n")
img = os.path.join(st, "image_id")
if a[:2] == ["image", "inspect"]:
    if not os.path.exists(img):
        sys.exit(1)
    sys.stdout.write(open(img).read())
elif a[:1] == ["build"]:
    sys.stdin.buffer.read()
    n = int(open(img).read().split(":")[1]) + 1 if os.path.exists(img) else 1
    open(img, "w").write("sha256:%d" % n)
sys.exit(0)
"""


def _write_exe(path: Path, body: str) -> None:
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(0o755)


def _web_state(
    *,
    guncel: bool,
    calisan_sha: str | None = MAIN,
    mesgul: list[dict[str, str]] | None = None,
    sha_dosyasi_guncel: bool = True,
) -> dict[str, Any]:
    return {
        "main": MAIN,
        "main_web_tree": TREE,
        "calisan": {"sha": calisan_sha, "web_tree": None},
        "sha_dosyasi": MAIN if sha_dosyasi_guncel else BASE,
        "guncel": guncel,
        "neden": "aynı commit" if guncel else "farklı",
        "sha_dosyasi_guncel": sha_dosyasi_guncel,
        "mesgul": mesgul,
    }


@pytest.fixture
def harness(tmp_path: Path) -> Any:
    state = tmp_path / "state"
    state.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_exe(bin_dir / "fake-exec", FAKE_EXEC)
    _write_exe(bin_dir / "docker", FAKE_DOCKER)
    (state / "image_id").write_text("sha256:1")
    (state / "status.json").write_text(
        json.dumps({"main": MAIN, "baseline": BASE, "main_baseline_mi": False})
    )

    def run(
        *args: str, web_state: dict[str, Any], env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        (state / "web_state.json").write_text(json.dumps(web_state))
        base = {
            k: v
            for k, v in os.environ.items()
            if k not in ("TP_DEMO_WEB_FORCE", "TP_DEMO_WEB_DEPLOY", "TP_DEMO_WEB_IMAGE")
        }
        full_env = {
            **base,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_STATE": str(state),
            "TP_FORGE_EXEC": str(bin_dir / "fake-exec"),
            "TMPDIR": str(tmp_path),
            **(env or {}),
        }
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            env=full_env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def docker_log() -> str:
        p = state / "docker.log"
        return p.read_text() if p.exists() else ""

    def exec_log() -> str:
        p = state / "exec.log"
        return p.read_text() if p.exists() else ""

    run.docker_log = docker_log  # type: ignore[attr-defined]
    run.exec_log = exec_log  # type: ignore[attr-defined]
    run.state = state  # type: ignore[attr-defined]
    return run


def _built(log: str) -> bool:
    return any(line.startswith("build ") for line in log.splitlines())


def _recreated(log: str) -> bool:
    return "--force-recreate" in log


@pytest.mark.parametrize("mode", ["break", "baseline"])
def test_guncel_ise_derleme_ve_yeniden_olusturma_yok(harness: Any, mode: str) -> None:
    # Süren push CI sırasında ikinci `make break`: uygulama zaten main → dokunulmaz.
    busy = [{"id": "j1", "tur": "ci.run"}]
    res = harness(mode, web_state=_web_state(guncel=True, mesgul=busy))
    assert res.returncode == 0, res.stderr
    assert f"demo-app-web zaten {MAIN}" in res.stdout
    log = harness.docker_log()
    assert not _built(log) and not _recreated(log)
    assert f"forge_demo {mode}" in harness.exec_log()
    # sha dosyası zaten main: yazılmaz.
    assert "sha_file" not in harness.exec_log()


def test_guncel_ama_sha_dosyasi_eski_ise_yalnizca_dosya_yazilir(harness: Any) -> None:
    res = harness("break", web_state=_web_state(guncel=True, sha_dosyasi_guncel=False))
    assert res.returncode == 0, res.stderr
    assert not _built(harness.docker_log()) and not _recreated(harness.docker_log())
    assert (harness.state / "sha_file").read_text().strip() == MAIN


def test_guncel_degilse_derler_olusturur_eski_imaji_siler(harness: Any) -> None:
    res = harness("break", web_state=_web_state(guncel=False, calisan_sha=BASE, mesgul=[]))
    assert res.returncode == 0, res.stderr
    log = harness.docker_log()
    assert _built(log) and _recreated(log)
    assert f"DEMO_APP_BUILD_SHA={MAIN}" in log and f"DEMO_APP_WEB_TREE={TREE}" in log
    assert f"forge_demo archive --ref {MAIN} --path web" in harness.exec_log()
    assert (harness.state / "sha_file").read_text().strip() == MAIN
    # Etiketsiz kalan eski imaj temizlenir (dangling imaj birikmez).
    assert "image rm sha256:1" in log


def test_kosan_ci_varken_yeniden_olusturmayi_reddeder(harness: Any) -> None:
    busy = [{"id": "j9", "tur": "ci.run"}]
    res = harness("break", web_state=_web_state(guncel=False, calisan_sha=BASE, mesgul=busy))
    assert res.returncode == 1
    assert "ci.run j9" in res.stderr and "sync-web" in res.stderr
    log = harness.docker_log()
    assert not _built(log) and not _recreated(log)


@pytest.mark.parametrize(
    ("args", "env"), [(("break", "--force"), {}), (("break",), {"TP_DEMO_WEB_FORCE": "1"})]
)
def test_zorlama_kosan_isi_ve_guncelligi_gecer(
    harness: Any, args: tuple[str, ...], env: dict[str, str]
) -> None:
    busy = [{"id": "j9", "tur": "repair.fix"}]
    res = harness(*args, web_state=_web_state(guncel=True, mesgul=busy), env=env)
    assert res.returncode == 0, res.stderr
    log = harness.docker_log()
    assert _built(log) and _recreated(log)


def test_mesguliyet_okunamazsa_uyarir_ve_derler(harness: Any) -> None:
    res = harness("baseline", web_state=_web_state(guncel=False, calisan_sha=MAIN[:-1] + "0"))
    assert res.returncode == 0, res.stderr
    assert "okunamadı" in res.stderr
    assert _recreated(harness.docker_log())


def test_deploy_kapali_ise_mesgulken_yalnizca_derler(harness: Any) -> None:
    busy = [{"id": "j9", "tur": "ci.run"}]
    res = harness(
        "break",
        web_state=_web_state(guncel=False, calisan_sha=BASE, mesgul=busy),
        env={"TP_DEMO_WEB_DEPLOY": "0"},
    )
    assert res.returncode == 0, res.stderr
    log = harness.docker_log()
    assert _built(log) and not _recreated(log)


def test_sync_web_baseline_calisma_agaci_imaji_korunur(harness: Any) -> None:
    (harness.state / "status.json").write_text(
        json.dumps({"main": BASE, "baseline": BASE, "main_baseline_mi": True})
    )
    ws = _web_state(guncel=False, calisan_sha=None, mesgul=[], sha_dosyasi_guncel=False)
    ws["main"] = BASE
    res = harness("sync-web", web_state=ws)
    assert res.returncode == 0, res.stderr
    assert "çalışma ağacından derlendiği gibi kalır" in res.stdout
    log = harness.docker_log()
    assert not _built(log) and not _recreated(log)
    assert (harness.state / "sha_file").read_text().strip() == BASE


def test_sync_web_baseline_ama_kirik_imaj_calisiyorsa_yeniden_derler(harness: Any) -> None:
    (harness.state / "status.json").write_text(
        json.dumps({"main": BASE, "baseline": BASE, "main_baseline_mi": True})
    )
    ws = _web_state(guncel=False, calisan_sha=MAIN, mesgul=[])
    ws["main"] = BASE
    res = harness("sync-web", web_state=ws)
    assert res.returncode == 0, res.stderr
    log = harness.docker_log()
    assert _built(log) and _recreated(log)
    assert f"DEMO_APP_BUILD_SHA={BASE}" in log


def test_sync_web_kirik_main_guncelse_dokunmaz(harness: Any) -> None:
    res = harness("sync-web", web_state=_web_state(guncel=True, mesgul=[]))
    assert res.returncode == 0, res.stderr
    assert f"demo-app-web zaten {MAIN}" in res.stdout
    assert not _recreated(harness.docker_log())
    assert "forge_demo break" not in harness.exec_log()
