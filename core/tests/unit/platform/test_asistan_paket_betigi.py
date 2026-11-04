"""scripts/asistan-bilgi-paketi.sh — paket güncel core imajıyla üretilmeli (AI-ASISTAN-PLANI §5.1).

core-worker'ın compose tanımında `build:` yok (x-core-image: pull_policy never); imajı yalnız
`migrate` derler. Bu yüzden `compose run --build core-worker` hiçbir şey derlemez: temiz kurulumda
imaj yoktur, `git pull && make up` akışında eski imajda paket modülü yoktur ve `make up` düşer.
Betik `run`dan ÖNCE `compose build migrate` çağırmalı.

Docker sahte: PATH'teki `docker` aldığı argümanları bir dosyaya satır satır yazar.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "scripts" / "asistan-bilgi-paketi.sh"
LIB = REPO / "scripts" / "lib.sh"
COMPOSE = REPO / "docker-compose.yml"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None or not SCRIPT.exists(),
    reason="bash / git / asistan-bilgi-paketi.sh yok",
)


def _kos(tmp_path: Path) -> list[str]:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / SCRIPT.name)
    shutil.copy(LIB, repo / "scripts" / "lib.sh")
    (repo / ".env").write_text("")
    env_git = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env_git)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i", "--allow-empty"],
        cwd=repo,
        check=True,
        env=env_git,
    )
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    kayit = tmp_path / "docker.log"
    sahte = bin_ / "docker"
    sahte.write_text(f'#!/bin/sh\necho "$*" >> "{kayit}"\nexit 0\n')
    sahte.chmod(0o755)
    env = {**env_git, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}"}
    subprocess.run(["bash", str(repo / "scripts" / SCRIPT.name)], cwd=repo, check=True, env=env)
    return kayit.read_text().splitlines()


def test_once_core_imaji_derlenir_sonra_paket_uretilir(tmp_path: Path) -> None:
    satirlar = _kos(tmp_path)
    assert satirlar[0] == "compose build migrate"
    assert len(satirlar) == 2
    run = satirlar[1]
    assert run.startswith("compose run --rm --no-deps ")
    # `--build` core-worker için hiçbir şey derlemez; yanıltıcı bayrak geri gelmesin.
    assert "--build" not in run.split()
    assert "core-worker python -m tp_core.features.assistant.paket" in run


def test_imaji_yalniz_migrate_derler() -> None:
    """Betiğin dayandığı compose varsayımı: derleme bölümü migrate'te, core-worker'da yok."""
    yaml = pytest.importorskip("yaml")
    servisler = yaml.safe_load(COMPOSE.read_text())["services"]
    assert "build" in servisler["migrate"]
    assert "build" not in servisler["core-worker"]
    assert servisler["migrate"]["image"] == servisler["core-worker"]["image"]
