"""`tp_session` çerezi: itsdangerous ile imzalı ve zaman damgalı; HttpOnly, SameSite=Lax.

Yük: ``{"uid": <kullanıcı uuid>, "pv": <parola hash'inin parmak izi>, "sid": <oturum uuid>}``.
`sid` sunucudaki `oturum` satırını gösterir: çıkış o satırı iptal eder, böylece çerezin bir kopyası
da artık kabul edilmez. Parola değişince (`pv`) kullanıcının tüm oturumları geçersiz olur.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from tp_core.models import AppUser, Oturum

COOKIE_NAME = "tp_session"
SALT = "tp-session-v2"  # v1 çerezlerinde sid yoktu; tuz değişince hepsi reddedilir

# Tanınan cihaz çerezi: başarılı girişte verilir; giriş deneme sınırı bu çerezi taşıyan istemciyi
# ayrı sayar. Böylece aynı IP'yi paylaşan (portal proxy'si, NAT) biri yanlış parolalarla adı geçen
# kullanıcıyı kendi tarayıcısından kilitleyemez. Oturum açmaz; yalnızca deneme sayacını ayırır.
DEVICE_COOKIE_NAME = "tp_cihaz"
DEVICE_SALT = "tp-cihaz-v1"
DEVICE_MAX_AGE_S = 30 * 24 * 3600


def password_fingerprint(parola_hash: str) -> str:
    return hashlib.sha256(parola_hash.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class SessionData:
    user_id: uuid.UUID
    pv: str
    sid: uuid.UUID


@dataclass(frozen=True)
class DeviceData:
    kullanici: str  # küçük harf kullanıcı adı
    cihaz: str


class SessionCodec:
    def __init__(self, secret: str, max_age_s: int) -> None:
        if len(secret) < 16:
            raise ValueError("TP_SESSION_SECRET en az 16 karakter olmalı")
        self._s = URLSafeTimedSerializer(secret, salt=SALT)
        self._d = URLSafeTimedSerializer(secret, salt=DEVICE_SALT)
        self.max_age_s = max_age_s

    def dumps_device(self, kullanici_adi: str, cihaz: str | None = None) -> str:
        return self._d.dumps({"u": kullanici_adi.strip().lower(), "c": cihaz or uuid.uuid4().hex})

    def loads_device(self, value: str) -> DeviceData | None:
        try:
            veri = self._d.loads(value, max_age=DEVICE_MAX_AGE_S)
            return DeviceData(str(veri["u"]), str(veri["c"]))
        except (BadSignature, KeyError, TypeError, ValueError):
            return None

    def dumps(self, user_id: uuid.UUID, parola_hash: str, sid: uuid.UUID) -> str:
        return self._s.dumps(
            {"uid": str(user_id), "pv": password_fingerprint(parola_hash), "sid": str(sid)}
        )

    def loads(self, value: str) -> SessionData | None:
        try:
            veri = self._s.loads(value, max_age=self.max_age_s)
            return SessionData(uuid.UUID(veri["uid"]), str(veri["pv"]), uuid.UUID(veri["sid"]))
        except (BadSignature, KeyError, TypeError, ValueError):
            return None


# ------------------------------------------------------------------ sunucu tarafı oturum kaydı


def open_session(session: Session, user_id: uuid.UUID, max_age_s: int) -> uuid.UUID:
    """Yeni `oturum` satırı açar; kullanıcının süresi dolmuş/iptal edilmiş satırlarını siler."""
    session.execute(
        delete(Oturum).where(
            Oturum.user_id == user_id,
            (Oturum.son_kullanma <= func.now()) | Oturum.iptal_zamani.is_not(None),
        )
    )
    o = Oturum(user_id=user_id, son_kullanma=datetime.now(UTC) + timedelta(seconds=max_age_s))
    session.add(o)
    session.flush()
    return o.id


def session_active(session: Session, veri: SessionData) -> bool:
    """Çerezdeki `sid` bu kullanıcıya ait, iptal edilmemiş ve süresi dolmamış bir oturum mu?"""
    return (
        session.scalar(
            select(Oturum.id).where(
                Oturum.id == veri.sid,
                Oturum.user_id == veri.user_id,
                Oturum.iptal_zamani.is_(None),
                Oturum.son_kullanma > func.now(),
            )
        )
        is not None
    )


def session_valid(session: Session, veri: SessionData) -> AppUser | None:
    """Çerez verisi hâlâ geçerli bir oturumu mu gösteriyor? Geçerliyse kullanıcı, değilse None.

    Kullanıcı silinmiş, parolası değişmiş (`pv`), oturum iptal edilmiş veya süresi dolmuşsa None.
    """
    user = session.get(AppUser, veri.user_id)
    if (
        user is None
        or password_fingerprint(user.parola_hash) != veri.pv
        or not session_active(session, veri)
    ):
        return None
    return user


def revoke_session(session: Session, veri: SessionData) -> bool:
    """Oturumu iptal eder (çıkış); etkin bir oturum iptal edildiyse True."""
    sonuc = session.execute(
        update(Oturum)
        .where(
            Oturum.id == veri.sid,
            Oturum.user_id == veri.user_id,
            Oturum.iptal_zamani.is_(None),
        )
        .values(iptal_zamani=func.now())
    )
    return sonuc.rowcount == 1
