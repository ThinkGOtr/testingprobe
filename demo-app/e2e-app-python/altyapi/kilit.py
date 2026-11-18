"""Bayiyi bir test süresince özel alır (web: tests/fixtures.ts `acquireDealer`; uygulama:
altyapi/BayiKilidi.java).

İşletim sistemi dosya kilidi kullanılır (POSIX `fcntl.flock`, Windows `msvcrt.locking`): süreç
ölünce kilit kendiliğinden düşer, bayat kilit temizliği gerekmez. Bekleme sorgulu ve süre
sınırlıdır (bloklayan kilit + kesme Windows'ta asılı kalabilir; BayiKilidi.java notu).
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from pathlib import Path

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]
    import msvcrt

KILIT_BEKLEME_S = 40.0


def dizin(onek: str, hedef: str) -> Path:
    """Aynı hedefe (uygulama adresi) karşı koşan süreçlerin paylaştığı kilit dizini."""
    ozet = hashlib.sha256(hedef.encode("utf-8")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"{onek}-{ozet}"


class BayiKilidi:
    def __init__(self, dosya: Path, fd: int) -> None:
        self._dosya = dosya
        self._fd: int | None = fd

    @classmethod
    def al(cls, kok: Path, kullanici_adi: str, bekleme_s: float = KILIT_BEKLEME_S) -> BayiKilidi:
        kok.mkdir(parents=True, exist_ok=True)
        dosya = kok / f"{kullanici_adi}.kilit"
        fd = os.open(dosya, os.O_RDWR | os.O_CREAT, 0o644)
        bitis = time.monotonic() + bekleme_s
        aralik = 0.02
        try:
            while not _dene(fd):
                if time.monotonic() >= bitis:
                    raise TimeoutError(
                        f"'{kullanici_adi}' bayisi {int(bekleme_s)} sn içinde serbest kalmadı "
                        f"(kilit: {dosya})"
                    )
                # Kilit yoklamasının bekleme aralığı; test akışında bekleme değildir.
                time.sleep(aralik)
                aralik = min(aralik * 2, 0.2)
        except BaseException:
            os.close(fd)
            raise
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        return cls(dosya, fd)

    def birak(self) -> None:
        """Kilidi bırakır (birden çok çağrı zararsız)."""
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
            else:  # pragma: no cover - Windows
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass  # dosya kapanınca kilit düşer
        finally:
            os.close(fd)


def _dene(fd: int) -> bool:
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:  # pragma: no cover - Windows
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    except OSError:
        return False
    return True
