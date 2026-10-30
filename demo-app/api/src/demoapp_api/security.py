"""Parola özeti ve oturum token'ları (yalnızca standart kütüphane)."""

import hashlib
import hmac
import secrets
from functools import lru_cache

_ITER = 100_000


@lru_cache(maxsize=64)
def parola_hash(parola: str, kullanici_adi: str) -> str:
    """PBKDF2-SHA256. Tuz kullanıcı adından türetilir: tohum verisi deterministik kalır."""
    tuz = hashlib.sha256(f"demoapp:{kullanici_adi}".encode()).hexdigest()[:32]
    ozet = hashlib.pbkdf2_hmac("sha256", parola.encode(), tuz.encode(), _ITER).hex()
    return f"pbkdf2_sha256${_ITER}${tuz}${ozet}"


def parola_dogru(parola: str, kayitli: str) -> bool:
    try:
        algo, iter_s, tuz, ozet = kayitli.split("$")
        if algo != "pbkdf2_sha256":
            return False
        hesap = hashlib.pbkdf2_hmac("sha256", parola.encode(), tuz.encode(), int(iter_s)).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(hesap, ozet)


def yeni_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
