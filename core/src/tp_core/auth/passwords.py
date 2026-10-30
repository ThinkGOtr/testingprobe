"""argon2 parola doğrulama; bilinmeyen kullanıcıda da aynı maliyet (zamanlama sızıntısı yok)."""

from __future__ import annotations

from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(parola: str) -> str:
    return _hasher.hash(parola)


@lru_cache(maxsize=1)
def _sahte_hash() -> str:
    return _hasher.hash("tp-olmayan-kullanici-icin-sahte-parola")


def verify_password(parola_hash: str | None, parola: str) -> bool:
    """Hash yoksa (kullanıcı yok) sahte hash'e karşı doğrular ve False döner."""
    hedef = parola_hash or _sahte_hash()
    try:
        ok = _hasher.verify(hedef, parola)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return ok and parola_hash is not None
