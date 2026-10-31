"""Forge (bare git) okuma: commit çözümü ve geçici checkout.

Depo başka bir uid'e aittir (core 10001); `safe.directory=*` olmadan git "dubious ownership"
verir. Checkout `git archive` + güvenli tar çıkarımıyla (`filter="data"`: mutlak yol, kök dışı
link, aygıt dosyası yok) yapılır; depoya hiçbir şey yazılmaz (test-runner'da volume salt okunur).
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from toolchain_common import proc
from toolchain_common.validation import validate_ref

SAFE_DIR_ENV = {
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "safe.directory",
    "GIT_CONFIG_VALUE_0": "*",
}


class ForgeError(RuntimeError):
    """Forge okunamadı (depo yok, git hatası, süre aşımı)."""


class CommitNotFound(LookupError):
    """Verilen sha/ref forge'da bir commit'e çözülmedi."""


def git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(SAFE_DIR_ENV)
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_LITERAL_PATHSPECS": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "LC_ALL": "C",
        }
    )
    return env


def _git_argv(repo: Path, *args: str) -> list[str]:
    return ["git", f"--git-dir={repo}", *args]


def _check_repo(repo: Path) -> None:
    if not (repo / "HEAD").is_file():
        raise ForgeError(f"forge deposu bulunamadı: {repo} (make forge-init)")


def resolve_commit(repo: Path, ref: str, timeout_s: float = 60) -> str:
    """`ref`'i tam commit sha'sına çözer; çözülmezse `CommitNotFound`."""
    validate_ref(ref)
    _check_repo(repo)
    res = proc.run(
        _git_argv(
            repo, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}"
        ),
        env=git_env(),
        timeout_s=timeout_s,
    )
    if res.timed_out:
        raise ForgeError("git rev-parse süre aşımı")
    sha = res.stdout.strip()
    if res.exit_code != 0 or not sha:
        raise CommitNotFound(f"commit bulunamadı: {ref}")
    return sha


def merge_base(repo: Path, a: str, b: str, timeout_s: float = 60) -> str | None:
    res = proc.run(
        _git_argv(repo, "merge-base", "--end-of-options", a, b), env=git_env(), timeout_s=timeout_s
    )
    sha = res.stdout.strip()
    return sha if res.ok and sha else None


def has_path(repo: Path, sha: str, path: str, timeout_s: float = 60) -> bool:
    res = proc.run(
        _git_argv(repo, "cat-file", "-e", f"{sha}:{path}"), env=git_env(), timeout_s=timeout_s
    )
    return res.ok


def extract_archive(data: bytes, dest: Path) -> None:
    """`git archive` tar'ını `dest`'e güvenli çıkarır."""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
        tar.extractall(dest, filter="data")


@contextmanager
def checkout(
    repo: Path, sha: str, subdir: str, timeout_s: float = 60, prefix: str = "tp-checkout-"
) -> Iterator[Path]:
    """`sha` commit'indeki `subdir`'i geçici dizine çıkarır, `<tmp>/<subdir>` verir; sonra siler."""
    _check_repo(repo)
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        try:
            out = subprocess.run(
                _git_argv(repo, "archive", "--format=tar", sha, "--", subdir),
                env=git_env(),
                capture_output=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ForgeError("git archive süre aşımı") from exc
        if out.returncode != 0:
            msg = out.stderr.decode("utf-8", "replace").strip()
            raise ForgeError(f"git archive başarısız ({sha[:12]}:{subdir}): {msg[:500]}")
        extract_archive(out.stdout, tmp)
        root = tmp / subdir
        if not root.is_dir():
            raise ForgeError(f"{sha[:12]} commit'inde '{subdir}' dizini yok")
        yield root
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def link_node_modules(e2e_dir: Path, node_modules: Path) -> None:
    """Commit'teki olası `node_modules`'u siler ve imajdaki bağımlılıklara bağlar.

    Depoya işlenmiş bir node_modules (ör. sahte `typescript`) imajın araçlarının yerine
    geçemez; bağımlılıklar yalnızca imajdan gelir (çevrimdışı, kilit dosyasıyla sabit).
    """
    target = e2e_dir / "node_modules"
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.exists():
        shutil.rmtree(target)
    target.symlink_to(node_modules, target_is_directory=True)
