"""Alt süreç çalıştırma: kabuk yok, süre sınırı, süreç grubu öldürme, kırpılmış çıktı."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

MAX_OUTPUT = 64 * 1024


@dataclass(frozen=True)
class ProcResult:
    argv: list[str]
    exit_code: int | None  # None = süre aşımı
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.exit_code == 0


def truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return (
        text[: limit // 2]
        + f"\n… [{len(text) - limit} karakter kırpıldı] …\n"
        + text[-limit // 2 :]
    )


def run(
    argv: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout_s: float,
    stdin: bytes | None = None,
    keep_full_stdout: bool = False,
) -> ProcResult:
    """`argv`'yi kendi süreç grubunda çalıştırır; süre aşılırsa tüm grubu öldürür.

    npx/playwright alt süreçler (işçiler, tarayıcılar) açar; yalnızca ebeveyni öldürmek onları
    yetim bırakırdı.
    """
    started = time.monotonic()
    proc = subprocess.Popen(
        list(argv),
        cwd=str(cwd) if cwd is not None else None,
        env=dict(env) if env is not None else None,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    timed_out = False
    try:
        out, err = proc.communicate(input=stdin, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_group(proc)
        out, err = proc.communicate()
    finally:
        if proc.poll() is None:
            _kill_group(proc)
            proc.wait()
    stdout = out.decode("utf-8", "replace")
    return ProcResult(
        argv=list(argv),
        exit_code=None if timed_out else proc.returncode,
        stdout=stdout if keep_full_stdout else truncate(stdout),
        stderr=truncate(err.decode("utf-8", "replace")),
        duration_ms=int((time.monotonic() - started) * 1000),
        timed_out=timed_out,
    )


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()
