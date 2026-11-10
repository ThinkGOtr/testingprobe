"""GCP Windows VM (tp-windows) yolu — compose sözleşmesi ve Mac tünel betiği (docs/WINDOWS-GCP.md).

tp-demo'da `mobil-windows` profili: app-mcp ve test-runner Windows Appium'a YALNIZCA
appium-gw-windows (socat, tek hedef TP_WINDOWS_VM_APPIUM) üzerinden ulaşır. Yönlendirici internal
olmayan cihaz-net'tedir (Linux Docker Engine'de çıkış host IP'sine NAT'lanır → VM'in güvenlik duvarı
yalnızca tp-demo iç IP'sine izin verir); test-runner cihaz-net'e GİRMEZ, hosta port açılmaz.
Ortam değişkenleri compose'dan boş varsayılanla geçer (specs/009-mobil-masaustu/windows-gcp.md).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
COMPOSE = REPO / "docker-compose.yml"
TUNEL = REPO / "scripts" / "cihaz" / "windows-gcp-tunel.sh"


@pytest.fixture(scope="module")
def compose() -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(COMPOSE.read_text())


def test_ag_yalitimi_windows_yolu(compose: dict) -> None:
    ag = compose["networks"]
    s = compose["services"]
    # Yönlendiricinin VPC'ye çıkışı için cihaz-net internal OLMAMALI; appium-net internal kalmalı.
    assert not (ag["cihaz-net"] or {}).get("internal")
    assert ag["appium-net"]["internal"] is True
    assert sorted(s["appium-gw-windows"]["networks"]) == ["appium-net", "cihaz-net"]
    assert sorted(s["app-mcp"]["networks"]) == ["app-mcp-net", "cihaz-net"]
    # test-runner yalnızca internal ağlarda: VM'e (ve internete) doğrudan çıkamaz.
    assert "cihaz-net" not in s["test-runner"]["networks"]
    assert all(ag[n].get("internal") for n in s["test-runner"]["networks"])
    for ad in ("appium-gw-windows", "app-mcp", "test-runner"):
        assert not s[ad].get("ports"), f"{ad} hosta port açmamalı"


def test_profiller(compose: dict) -> None:
    s = compose["services"]
    assert s["appium-gw-windows"]["profiles"] == ["mobil-windows"]
    # tp-demo'da hostta Appium yok: yalnız `mobil-windows` ile de ajan aracı başlar.
    assert set(s["app-mcp"]["profiles"]) == {"mobil", "mobil-windows"}
    assert "profiles" not in s["test-runner"]


def test_yonlendirici_sertlestirme(compose: dict) -> None:
    gw = compose["services"]["appium-gw-windows"]
    assert gw["environment"]["HEDEF"] == "${TP_WINDOWS_VM_APPIUM:-192.168.64.2:4723}"
    assert gw["read_only"] is True
    assert gw["cap_drop"] == ["ALL"]
    assert gw["user"] == "65534:65534"
    assert "no-new-privileges:true" in gw["security_opt"]


@pytest.mark.parametrize(
    ("servis", "beklenen"),
    [
        (
            "app-mcp",
            {
                "APPIUM_URL_WINDOWS": "${APPIUM_URL_WINDOWS:-}",
                "APP_WINDOWS_APP": "${APP_WINDOWS_APP:-}",
                "APP_WINDOWS_ARGS": "${APP_WINDOWS_ARGS:-}",
                "APP_WINDOWS_WORKDIR": "${APP_WINDOWS_WORKDIR:-}",
            },
        ),
        (
            "test-runner",
            {
                "APPIUM_URL_WINDOWS": "${TP_RUNNER_APPIUM_URL_WINDOWS:-}",
                "TP_APP_ID_WINDOWS": "${TP_APP_ID_WINDOWS:-}",
                "TP_APP_PATH_WINDOWS": "${TP_APP_PATH_WINDOWS:-}",
                "TP_APP_ARGS_WINDOWS": "${TP_APP_ARGS_WINDOWS:-}",
                "TP_APP_WORKDIR_WINDOWS": "${TP_APP_WORKDIR_WINDOWS:-}",
                # /test/* sıfırlaması bu yığının API'sine (uygulama aynı API'ye dış kapıdan).
                "DEMO_API_URL": "http://demo-app-api:8000",
            },
        ),
    ],
)
def test_windows_ortami_bos_varsayilanla_gecer(compose: dict, servis: str, beklenen: dict) -> None:
    ortam = compose["services"][servis]["environment"]
    for anahtar, deger in beklenen.items():
        assert ortam.get(anahtar) == deger, anahtar


def test_env_ornegi_gcp_blogu() -> None:
    metin = (REPO / ".env.example").read_text()
    for satir in (
        "# COMPOSE_PROFILES=mobil-windows",
        "# TP_WINDOWS_VM_APPIUM=<tp-windows-ic-ip>:4723",
        "# TP_RUNNER_APPIUM_URL_WINDOWS=http://appium-gw-windows:4723",
        "# APPIUM_URL_WINDOWS=http://appium-gw-windows:4723",
        "# APP_WINDOWS_APP=C:\\tp\\uygulama\\BayiSiparis.exe",
        "# TP_APP_PATH_WINDOWS=C:\\tp\\uygulama\\BayiSiparis.exe",
    ):
        assert satir in metin.splitlines(), satir


# --- scripts/cihaz/windows-gcp-tunel.sh (DRY_RUN: gcloud çağrılmaz) ------------------------------

needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash yok")


def _tunel(
    tmp_path: Path, env: dict[str, str], vm_sh: str | None = None
) -> subprocess.CompletedProcess:
    kok = tmp_path / "repo"
    (kok / "scripts" / "cihaz").mkdir(parents=True)
    shutil.copy(TUNEL, kok / "scripts" / "cihaz" / TUNEL.name)
    if vm_sh is not None:
        d = kok / "deploy" / "gcp" / "windows-vm"
        d.mkdir(parents=True)
        (d / "vm.sh").write_text(vm_sh)
        (d / "vm.sh").chmod(0o755)
    temiz = {k: v for k, v in os.environ.items() if not k.startswith(("TP_", "DRY_RUN"))}
    return subprocess.run(
        ["bash", str(kok / "scripts" / "cihaz" / TUNEL.name)],
        env={**temiz, "DRY_RUN": "1", **env},
        capture_output=True,
        text=True,
        check=False,
    )


@needs_bash
def test_tunel_ortamdan_ip(tmp_path: Path) -> None:
    r = _tunel(tmp_path, {"TP_WINDOWS_VM_IP": "10.132.0.7"})
    assert r.returncode == 0, r.stderr
    k = r.stdout.split()
    assert k[:4] == ["gcloud", "compute", "ssh", "tp-demo"]
    assert "--tunnel-through-iap" in k
    assert k[k.index("--zone") + 1] == "europe-west3-a"
    # Yerel uç yalnızca loopback'te.
    assert k[k.index("-L") + 1] == "127.0.0.1:14723:10.132.0.7:4723"


@needs_bash
def test_tunel_vm_sh_ip(tmp_path: Path) -> None:
    vm_sh = "#!/bin/sh\n[ \"$1\" = ip ] && echo 'tp-windows iç IP: 10.132.0.9'\n"
    r = _tunel(tmp_path, {}, vm_sh=vm_sh)
    assert r.returncode == 0, r.stderr
    assert "127.0.0.1:14723:10.132.0.9:4723" in r.stdout


@needs_bash
@pytest.mark.parametrize("ip", ["8.8.8.8", "10.300.0.1", "10.1.2.3:22", "10.0.0.1 -R x"])
def test_tunel_yalniz_vpc_ic_adresi(tmp_path: Path, ip: str) -> None:
    r = _tunel(tmp_path, {"TP_WINDOWS_VM_IP": ip})
    assert r.returncode != 0
    assert "gcloud" not in r.stdout


@needs_bash
def test_tunel_ip_yoksa_aciklayici_hata(tmp_path: Path) -> None:
    r = _tunel(tmp_path, {})
    assert r.returncode != 0
    assert "TP_WINDOWS_VM_IP" in r.stderr
