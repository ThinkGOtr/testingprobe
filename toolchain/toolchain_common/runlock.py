"""Süreçler arası koşu kilidi (flock, `TP_RUN_LOCK_PATH`).

test-runner aynı anda tek koşu yürütür: koşular aynı bayileri (bayi1/bayi2) kullanır; eşzamanlı iki
koşu birbirinin sepetini sıfırlar ya da kampanya kırılmasını (BREAK_CAMPAIGN) öbürüne sızdırır.
`runner/run.py`'deki `RUN_LOCK` yalnızca aynı süreçteki istekleri sıralar; konteynerde
`docker compose exec` ile başlatılan bir koşu (`make e2e-smoke`) bu kilidi görmez. Bu modülün
dosya kilidi ikisini de kapsar: `/run` onu alır, `tp-run-lock` sarmalayıcısı da (bin/tp-run-lock)
aynı dosyayı kilitleyip komutu kilit altında çalıştırır.

flock çekirdekte tutulur: süreç ölünce kilit kendiliğinden bırakılır (bayat kilit dosyası yok).
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import time
from collections.abc import Iterator
from pathlib import Path


class RunLockTimeout(RuntimeError):
    """Kilit bekleme süresi içinde alınamadı."""


def acquire(path: Path, timeout_s: float, poll_s: float = 0.2) -> int:
    """Kilidi alır ve açık dosya tanımlayıcısını döndürür (bırakmak için `release`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
    deadline = time.monotonic() + max(0.0, timeout_s)
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RunLockTimeout(f"koşu kilidi alınamadı: {path}") from None
                time.sleep(poll_s)
    except BaseException:
        os.close(fd)
        raise


def release(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@contextlib.contextmanager
def held(path: Path, timeout_s: float) -> Iterator[None]:
    fd = acquire(path, timeout_s)
    try:
        yield
    finally:
        release(fd)
