"""scripts/demo-web-sync.sh — eşzamanlı kopyalar demo-app-web'i aynı anda yeniden oluşturmamalı.

Sunum boyunca açık `--watch` ile `make demo-break` / `make demo-reset`'in kendi `--wait`'i aynı
isteği görür. Kilit olmadan ikisi birden `compose up --force-recreate demo-app-web` çalıştırır ve
biri konteyner adı çakışmasıyla ("demo-app-web yeniden başlatılamadı") ölür.

Docker ve core-worker sahte: `TP_FORGE_EXEC` `sh -c` komutlarını gerçek `sh` ile, `/forge/`
yolunu geçici bir dizine çevirerek çalıştırır (kilit `mkdir`'i gerçek); PATH'teki sahte `docker`,
eşzamanlı iki `--force-recreate`'i gerçek Docker gibi çakışma hatasıyla reddeder.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
SCRIPT = REPO / "scripts" / "demo-web-sync.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("sh") is None or not SCRIPT.exists(),
    reason="bash / sh / demo-web-sync.sh yok",
)

BASE = "a" * 40
MAIN = "b" * 40
TREE = "c" * 40
LOCK = "demo-web-sync.lock"

FAKE_EXEC = r"""
import io, json, os, subprocess, sys, tarfile
st = os.environ["FAKE_STATE"]
forge = os.path.join(st, "forge")
a = sys.argv[1:]
def log(line):
    with open(os.path.join(st, "exec.log"), "a") as f:
        f.write(line + "\n")
# core-worker yeniden oluşturuluyor / yeniden başlıyor: `docker compose exec` başarısız olur.
if os.path.exists(os.path.join(st, "exec_down")):
    with open(os.path.join(st, "exec_down.log"), "a") as f:
        f.write("down\n")
    sys.stderr.write('service "core-worker" is not running\n')
    sys.exit(1)
if a[:2] == ["sh", "-c"]:
    script = a[2].replace("/forge/", forge + "/")
    sys.exit(subprocess.run(["sh", "-c", script, *a[3:]]).returncode)
if a[:3] == ["python", "-m", "toolchain_common.mirror_export"]:
    log("mirror_export " + " ".join(a[3:]))
    if a[3] == "tree":
        print(os.environ.get("FAKE_TREE", "d" * 40))
    else:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as t:
            data = b"FROM scratch\n"
            ti = tarfile.TarInfo("Dockerfile"); ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
        sys.stdout.buffer.write(buf.getvalue())
    sys.exit(0)
if a[:3] == ["python", "-m", "tp_core.features.demo"]:
    log("demo " + " ".join(a[3:]))
    req = {"istek_id": "9" * 32, "eylem": "sync", "sha": os.environ.get("FAKE_MAIN", "b" * 40),
           "zaman": "t", "isteyen": "x"}
    open(os.path.join(forge, "demo-web-refresh.json"), "w").write(json.dumps(req))
    print(json.dumps(req))
    sys.exit(0)
if a[:3] == ["python", "-m", "tp_core.integrations.forge_demo"]:
    cmd = a[3]
    log("forge_demo " + " ".join(a[3:]))
    if cmd == "web-path":
        yol = os.environ.get("FAKE_WEB_YOLU", "demo-app/web")
        print(json.dumps({"kip": "github", "web_yolu": yol}))
    elif cmd == "web-state":
        p = os.path.join(st, "running_sha")
        sha = open(p).read().strip() if os.path.exists(p) else None
        print(json.dumps({"calisan": {"sha": sha}}))
    elif cmd == "archive":
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as t:
            data = b"FROM scratch\n"
            ti = tarfile.TarInfo("Dockerfile"); ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
        sys.stdout.buffer.write(buf.getvalue())
    sys.exit(0)
if a and a[0] == "git":
    print(os.environ.get("FAKE_TREE", "c" * 40))
    sys.exit(0)
sys.exit(97)
"""

FAKE_DOCKER = r"""
import os, sys, time
st = os.environ["FAKE_STATE"]
a = sys.argv[1:]
with open(os.path.join(st, "docker.log"), "a") as f:
    f.write(" ".join(a) + "\n")
img = os.path.join(st, "image_id")
if a[:2] == ["image", "inspect"]:
    if not os.path.exists(img):
        sys.exit(1)
    sys.stdout.write(open(img).read())
elif a[:2] == ["image", "rm"]:
    pass
elif a[:1] == ["build"]:
    sys.stdin.buffer.read()
    if os.environ.get("FAKE_BUILD_FAIL"):
        sys.exit(1)
    sha = next(x.split("=", 1)[1] for x in a if x.startswith("DEMO_APP_BUILD_SHA="))
    time.sleep(float(os.environ.get("FAKE_BUILD_SLEEP", "0")))
    n = int(open(img).read().split(":")[1]) + 1 if os.path.exists(img) else 1
    open(img, "w").write("sha256:%d" % n)
    open(os.path.join(st, "built_sha"), "w").write(sha)
elif a[:2] == ["compose", "up"]:
    busy = os.path.join(st, "recreating")
    try:
        os.mkdir(busy)
    except FileExistsError:
        sys.stderr.write('Conflict. The container name "/testingprobe-demo-app-web-1" is in use\n')
        sys.exit(1)
    try:
        time.sleep(float(os.environ.get("FAKE_UP_SLEEP", "0")))
        open(os.path.join(st, "running_sha"), "w").write(open(os.path.join(st, "built_sha")).read())
        with open(os.path.join(st, "recreate.log"), "a") as f:
            f.write("recreate\n")
    finally:
        os.rmdir(busy)
sys.exit(0)
"""


def _write_exe(path: Path, body: str) -> None:
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(0o755)


class Harness:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.state = tmp_path / "state"
        self.forge = self.state / "forge"
        self.forge.mkdir(parents=True)
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        _write_exe(self.bin / "fake-exec", FAKE_EXEC)
        _write_exe(self.bin / "docker", FAKE_DOCKER)
        (self.state / "image_id").write_text("sha256:1")
        (self.state / "running_sha").write_text(BASE)

    def istek(self, istek_id: str, eylem: str = "break", sha: str = MAIN) -> None:
        req = {"istek_id": istek_id, "eylem": eylem, "sha": sha, "zaman": "t", "isteyen": "x"}
        (self.forge / "demo-web-refresh.json").write_text(json.dumps(req))

    def done(self) -> str:
        p = self.forge / "demo-web-refresh.done"
        return p.read_text().strip() if p.exists() else ""

    def recreates(self) -> int:
        p = self.state / "recreate.log"
        return len(p.read_text().splitlines()) if p.exists() else 0

    def env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        base = {k: v for k, v in os.environ.items() if not k.startswith("TP_DEMO_")}
        return {
            **base,
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_STATE": str(self.state),
            "TP_FORGE_EXEC": str(self.bin / "fake-exec"),
            "TMPDIR": str(self.tmp),
            "TP_DEMO_SYNC_POLL_S": "0.2",
            "TP_DEMO_SYNC_WAIT_S": "30",
            **(extra or {}),
        }

    def popen(self, *args: str, env: dict[str, str] | None = None) -> subprocess.Popen[str]:
        return subprocess.Popen(
            ["bash", str(SCRIPT), *args],
            env=self.env(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

    def run(
        self, *args: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            env=self.env(env),
            capture_output=True,
            text=True,
            timeout=60,
        )


@pytest.fixture
def h(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def _bekle(p: subprocess.Popen[str], timeout: float = 60) -> tuple[int, str, str]:
    out, err = p.communicate(timeout=timeout)
    return p.returncode, out, err


def _durdur(p: subprocess.Popen[str]) -> tuple[str, str]:
    if p.poll() is None:
        os.killpg(p.pid, signal.SIGTERM)
    out, err = p.communicate(timeout=30)
    return out, err


def test_iki_wait_kopyasi_tek_yeniden_olusturma(h: Harness) -> None:
    # make demo-break'in --wait'i ile elle çalıştırılan ikinci bir --wait aynı isteği görür.
    h.istek("1" * 32)
    slow = {"FAKE_BUILD_SLEEP": "1.5", "FAKE_UP_SLEEP": "0.5"}
    p1 = h.popen("--wait", "break", env=slow)
    p2 = h.popen("--wait", "break", env=slow)
    r1, r2 = _bekle(p1), _bekle(p2)
    assert r1[0] == 0, r1
    assert r2[0] == 0, r2
    assert "Conflict" not in r1[2] + r2[2]
    assert h.recreates() == 1
    assert h.done() == "1" * 32
    assert (h.forge / "demo-app-web.sha").read_text().strip() == MAIN
    assert not (h.forge / LOCK).exists()


def test_watch_acikken_demo_break_wait_ayni_istegi_yeniden_derlemez(h: Harness) -> None:
    # Önceki (uygulanmış) sıfırlama isteği: --wait onu beklemez.
    h.istek("0" * 32, eylem="baseline", sha=BASE)
    (h.forge / "demo-web-refresh.done").write_text("0" * 32 + "\n")
    slow = {"FAKE_BUILD_SLEEP": "1.0", "FAKE_UP_SLEEP": "0.5"}
    watch = h.popen("--watch", env=slow)
    try:
        time.sleep(0.5)
        bekleyen = h.popen("--wait", "break", env=slow)
        time.sleep(0.3)
        h.istek("2" * 32)  # POST /demo/break-locator
        rc, out, err = _bekle(bekleyen)
        assert rc == 0, (out, err)
        deadline = time.time() + 20
        while h.done() != "2" * 32 and time.time() < deadline:
            time.sleep(0.1)
        time.sleep(1.0)  # izleyicinin bir tur daha dönmesine izin ver
    finally:
        _wout, werr = _durdur(watch)
    assert "Conflict" not in err + werr, werr
    assert "yeniden başlatılamadı" not in err + werr
    assert h.recreates() == 1
    assert h.done() == "2" * 32
    assert not (h.forge / LOCK).exists()


def test_wait_baska_kopya_uyguladiysa_basariyla_cikar(h: Harness) -> None:
    # İzleyici kilidi tutup isteği uygularken --wait yalnızca bekler ve .done ile çıkar.
    h.istek("3" * 32)
    kilit = h.forge / LOCK
    kilit.mkdir()
    (kilit / "owner").write_text(f"{int(time.time())} izleyici:1\n")
    p = h.popen("--wait", "break")
    time.sleep(1.0)
    assert p.poll() is None
    (h.forge / "demo-web-refresh.done").write_text("3" * 32 + "\n")
    rc, out, err = _bekle(p)
    assert rc == 0, (out, err)
    assert "başka bir eşitleyici" in out
    assert "Başka bir demo-web-sync kopyası" in err
    assert h.recreates() == 0
    assert kilit.exists()  # başkasının kilidine dokunulmaz


def test_tek_sefer_mesgul_kilitte_derlemez_ve_zaman_asiminda_hata(h: Harness) -> None:
    h.istek("4" * 32)
    kilit = h.forge / LOCK
    kilit.mkdir()
    (kilit / "owner").write_text(f"{int(time.time())} baska:2\n")
    res = h.run(env={"TP_DEMO_SYNC_WAIT_S": "1"})
    assert res.returncode == 1
    assert "kilidi boşalmadı" in res.stderr
    assert h.recreates() == 0 and h.done() == ""
    assert (kilit / "owner").read_text().strip().endswith("baska:2")


def test_eski_kilit_devralinir(h: Harness) -> None:
    h.istek("5" * 32)
    kilit = h.forge / LOCK
    kilit.mkdir()
    (kilit / "owner").write_text(f"{int(time.time()) - 3600} coken:3\n")
    res = h.run(env={"TP_DEMO_SYNC_LOCK_STALE_S": "600"})
    assert res.returncode == 0, res.stderr
    assert "eski kilit devralındı" in res.stderr
    assert h.recreates() == 1 and h.done() == "5" * 32
    assert not kilit.exists()


def test_derleme_hatasinda_kilit_birakilir(h: Harness) -> None:
    h.istek("6" * 32)
    res = h.run(env={"FAKE_BUILD_FAIL": "1"})
    assert res.returncode == 1
    assert "derlenemedi" in res.stderr
    assert not (h.forge / LOCK).exists()
    assert h.done() == ""
    # Kilit bırakıldığı için sonraki deneme uygular.
    res = h.run()
    assert res.returncode == 0, res.stderr
    assert h.recreates() == 1 and h.done() == "6" * 32


def test_istek_yoksa_tek_sefer_bilgi_verir(h: Harness) -> None:
    res = h.run()
    assert res.returncode == 0, res.stderr
    assert "Bekleyen demo uygulaması yenileme isteği yok." in res.stdout
    assert not (h.forge / LOCK).exists()


def test_zaten_uygulanmis_istek_tekrar_derlenmez(h: Harness) -> None:
    h.istek("7" * 32)
    assert h.run().returncode == 0
    res = h.run()
    assert res.returncode == 0, res.stderr
    assert "Bekleyen demo uygulaması yenileme isteği yok." in res.stdout
    assert h.recreates() == 1


def _down_sayisi(h: Harness) -> int:
    p = h.state / "exec_down.log"
    return len(p.read_text().splitlines()) if p.exists() else 0


def test_watch_core_worker_ulasilamazken_cikmaz_ve_geri_gelince_uygular(h: Harness) -> None:
    # make demo-prova / make reset / make up core-worker'ı yeniden oluşturur: exec başarısız olur.
    # Sunum boyunca açık izleyici çıkmamalı; core-worker gelince bekleyen isteği uygulamalı.
    (h.state / "exec_down").write_text("1")
    watch = h.popen("--watch")
    try:
        deadline = time.time() + 20
        while _down_sayisi(h) < 5 and time.time() < deadline:
            assert watch.poll() is None, _durdur(watch)
            time.sleep(0.1)
        assert _down_sayisi(h) >= 5  # en az 5 tur denendi
        time.sleep(0.5)
        assert watch.poll() is None  # hâlâ açık
        h.istek("8" * 32)
        (h.state / "exec_down").unlink()
        deadline = time.time() + 20
        while h.done() != "8" * 32 and time.time() < deadline:
            assert watch.poll() is None, _durdur(watch)
            time.sleep(0.1)
        time.sleep(1.5)  # "yeniden erişilebilir" bildirimi uygulamadan sonraki turda yazılır
        assert watch.poll() is None
    finally:
        out, err = _durdur(watch)
    assert h.done() == "8" * 32, (out, err)
    assert h.recreates() == 1
    # Uyarı bir kez yazılır (her turda değil), geri gelince bildirilir; die mesajı yok.
    assert err.count("core-worker'a ulaşılamıyor") == 1, err
    assert "yeniden erişilebilir" in err
    assert "HATA" not in err, err
    assert not (h.forge / LOCK).exists()


def test_tek_sefer_ve_wait_core_worker_ulasilamazsa_hata_verir(h: Harness) -> None:
    (h.state / "exec_down").write_text("1")
    res = h.run()
    assert res.returncode == 1
    assert "eşitleme kilidi alınamadı" in res.stderr
    # --wait: istek okunamaz → hata (sessizce beklemez).
    res = h.run("--wait", "break", env={"TP_DEMO_SYNC_WAIT_S": "2"})
    assert res.returncode != 0


# ------------------------------------------------------------- GitHub kipi (TP_FORGE=github)


def _gh_env(h: Harness, **extra: str) -> dict[str, str]:
    return {
        "TP_FORGE": "github",
        "TP_TOOLCHAIN_EXEC": str(h.bin / "fake-exec"),
        "TP_FORGE_REMOTE_URL": "https://github.com/ThinkGOtr/testingprobe-demo-app.git",
        **extra,
    }


def _exec_log(h: Harness) -> str:
    p = h.state / "exec.log"
    return p.read_text() if p.exists() else ""


def test_github_kipinde_web_aynadan_derlenir(h: Harness) -> None:
    h.istek("2" * 32)
    r = h.run(env=_gh_env(h))
    assert r.returncode == 0, r.stderr
    log = _exec_log(h)
    assert f"mirror_export archive --ref {MAIN} --path demo-app/web" in log
    assert f"mirror_export tree --ref {MAIN} --path demo-app/web" in log
    assert "forge_demo archive" not in log  # yerel forge arşivi kullanılmaz
    docker = (h.state / "docker.log").read_text()
    assert f"DEMO_APP_BUILD_SHA={MAIN}" in docker and "DEMO_APP_WEB_TREE=" + "d" * 40 in docker
    assert h.recreates() == 1 and h.done() == "2" * 32
    assert (h.forge / "demo-app-web.sha").read_text().strip() == MAIN
    assert "GitHub aynası" in r.stdout


def test_github_kipinde_uzak_depo_yoksa_acik_hata(h: Harness) -> None:
    h.istek("3" * 32)
    r = h.run(env=_gh_env(h, TP_FORGE_REMOTE_URL=""))
    assert r.returncode != 0 and "TP_FORGE_REMOTE_URL" in r.stderr
    assert h.recreates() == 0 and h.done() == ""


def test_github_kipinde_gecersiz_web_yolu_reddedilir(h: Harness) -> None:
    h.istek("4" * 32)
    r = h.run(env=_gh_env(h, FAKE_WEB_YOLU="../x"))
    assert r.returncode != 0 and "geçersiz web yolu" in r.stderr
    assert "mirror_export" not in _exec_log(h)


def test_main_secenegi_guncel_main_icin_istek_yazar_ve_uygular(h: Harness) -> None:
    r = h.run("--main", env=_gh_env(h))
    assert r.returncode == 0, r.stderr
    assert "demo web-istek --eylem sync" in _exec_log(h)
    assert h.done() == "9" * 32 and h.recreates() == 1
