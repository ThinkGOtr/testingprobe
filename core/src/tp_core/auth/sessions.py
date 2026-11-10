"""`tp_session` çerezi: itsdangerous ile imzalı ve zaman damgalı; HttpOnly, SameSite=Lax.

Yük: ``{"uid": <kullanıcı uuid>, "pv": <parola hash'inin parmak izi>, "sid": <oturum uuid>,
"ae": <app_user.auth_epoch>}``. `sid` sunucudaki `oturum` satırını gösterir: çıkış o satırı iptal
eder, böylece çerezin bir kopyası da artık kabul edilmez. Parola değişince (`pv`) ya da dış iptalde
epoch artınca (`ae`, AI Probe kipi) kullanıcının tüm oturumları geçersiz olur. `ae` taşımayan eski
çerezler epoch 0 sayılır (`local` kipte epoch hiç artmaz; davranış değişmez).

Çerez adı kipe bağlıdır (TEKNIK-TASARIM §8.14): `local` → `tp_session` (Secure yalnız
`TP_SESSION_COOKIE_SECURE`), `aiprobe`/`both` → `__Host-tp_session` (her zaman Secure, Path=/).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from tp_core.config import get_settings
from tp_core.models import AppUser, Oturum

COOKIE_NAME = "tp_session"
AIPROBE_COOKIE_NAME = "__Host-tp_session"
SALT = "tp-session-v2"  # v1 çerezlerinde sid yoktu; tuz değişince hepsi reddedilir

# Tanınan cihaz çerezi: başarılı girişte verilir; giriş deneme sınırı bu çerezi taşıyan istemciyi
# ayrı sayar. Böylece aynı IP'yi paylaşan (portal proxy'si, NAT) biri yanlış parolalarla adı geçen
# kullanıcıyı kendi tarayıcısından kilitleyemez. Oturum açmaz; yalnızca deneme sayacını ayırır.
DEVICE_COOKIE_NAME = "tp_cihaz"
DEVICE_SALT = "tp-cihaz-v1"
DEVICE_MAX_AGE_S = 30 * 24 * 3600


def aiprobe_acik() -> bool:
    """AI Probe ortak kimliği açık mı (`TP_AUTH_MODE` `aiprobe` ya da `both`)?"""
    return get_settings().auth_mode != "local"


def cookie_name() -> str:
    return AIPROBE_COOKIE_NAME if aiprobe_acik() else COOKIE_NAME


def cookie_secure() -> bool:
    """`__Host-` öneki Secure ister; yerel kipte yalnızca `TP_SESSION_COOKIE_SECURE`."""
    return aiprobe_acik() or get_settings().session_cookie_secure


def password_fingerprint(parola_hash: str) -> str:
    return hashlib.sha256(parola_hash.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class SessionData:
    user_id: uuid.UUID
    pv: str
    sid: uuid.UUID
    ae: int = 0


@dataclass(frozen=True)
class DeviceData:
    kullanici: str  # küçük harf kullanıcı adı
    cihaz: str


class SessionCodec:
    def __init__(self, secret: str, max_age_s: int) -> None:
        if len(secret) < 16:
            raise ValueError("TP_SESSION_SECRET en az 16 karakter olmalı")
        self._secret = secret
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

    def dumps(self, user_id: uuid.UUID, parola_hash: str, sid: uuid.UUID, ae: int = 0) -> str:
        yuk: dict[str, object] = {
            "uid": str(user_id),
            "pv": password_fingerprint(parola_hash),
            "sid": str(sid),
        }
        if ae:
            yuk["ae"] = ae
        return self._s.dumps(yuk)

    def loads(self, value: str) -> SessionData | None:
        try:
            veri = self._s.loads(value, max_age=self.max_age_s)
            return SessionData(
                uuid.UUID(veri["uid"]),
                str(veri["pv"]),
                uuid.UUID(veri["sid"]),
                int(veri.get("ae", 0)),
            )
        except (BadSignature, KeyError, TypeError, ValueError, AttributeError):
            return None

    def dumps_signed(self, salt: str, veri: object) -> str:
        """Kısa ömürlü yardımcı çerezler (AI Probe rol seçimi) için ayrı tuzlu imza."""
        return URLSafeTimedSerializer(self._secret, salt=salt).dumps(veri)

    def loads_signed(self, salt: str, value: str, max_age_s: int) -> object | None:
        try:
            return URLSafeTimedSerializer(self._secret, salt=salt).loads(value, max_age=max_age_s)
        except BadSignature:
            return None


# ------------------------------------------------------------------ sunucu tarafı oturum kaydı


def open_session(
    session: Session,
    user_id: uuid.UUID,
    max_age_s: int,
    *,
    external_uid: str | None = None,
    auth_time: int | None = None,
    acr: str | None = None,
    session_epoch_ms: int | None = None,
    urunler: dict[str, Any] | None = None,
) -> uuid.UUID:
    """Yeni `oturum` satırı açar; kullanıcının süresi dolmuş/iptal edilmiş satırlarını siler.

    AI Probe oturumunda (`external_uid` dolu) süre boşta sınırıdır (`AIPROBE_IDLE_S`, en çok
    mutlak sınır) ve `son_kontrol` şimdidir (devir kodu az önce sunucuda doğrulandı).
    """
    session.execute(
        delete(Oturum).where(
            Oturum.user_id == user_id,
            (Oturum.son_kullanma <= func.now()) | Oturum.iptal_zamani.is_not(None),
        )
    )
    simdi = datetime.now(UTC)
    if external_uid is None:
        o = Oturum(user_id=user_id, son_kullanma=simdi + timedelta(seconds=max_age_s))
    else:
        ayar = get_settings()
        sure = min(ayar.aiprobe_idle_s, ayar.aiprobe_absolute_s, max_age_s)
        o = Oturum(
            user_id=user_id,
            son_kullanma=simdi + timedelta(seconds=sure),
            external_uid=external_uid,
            auth_time=auth_time,
            acr=acr,
            session_epoch_ms=session_epoch_ms,
            urunler=urunler,
            son_kontrol=simdi,
        )
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


@dataclass
class OturumDurumu:
    """`session_valid`'in yan çıktısı: AI Probe kimlik servisine ulaşılamadı mı (oturum korundu)?"""

    degraded: bool = False
    external_uid: str | None = None
    # AI Probe oturumunun devirdeki `auth_time`, `acr`, `session_epoch_ms`'i (bu oturumdan üretilen
    # `tpt_` token'a kopyalanır) ve ürün→rol haritası (`/auth/me` `products`).
    auth_time: int | None = None
    acr: str | None = None
    session_epoch_ms: int | None = None
    urunler: dict[str, Any] | None = None


def session_valid(
    session: Session,
    veri: SessionData,
    *,
    uzat: bool = False,
    durum: OturumDurumu | None = None,
) -> AppUser | None:
    """Çerez verisi hâlâ geçerli bir oturumu mu gösteriyor? Geçerliyse kullanıcı, değilse None.

    Kullanıcı silinmiş, parolası değişmiş (`pv`), epoch'u artmış (`ae`), oturum iptal edilmiş veya
    süresi dolmuşsa None. AI Probe oturumunda ayrıca en geç `AIPROBE_SESSION_CHECK_S`'de bir
    kimlik servisine sorulur (`tp_core.auth.aiprobe.oturum_kontrol`); `uzat=True` yalnızca kullanıcı
    isteklerinde verilir ve boşta süresini kaydırır (SSE denetimi uzatmaz).
    """
    user = session.get(AppUser, veri.user_id)
    if (
        user is None
        or password_fingerprint(user.parola_hash) != veri.pv
        or veri.ae != user.auth_epoch
    ):
        return None
    o = session.scalar(
        select(Oturum).where(
            Oturum.id == veri.sid,
            Oturum.user_id == veri.user_id,
            Oturum.iptal_zamani.is_(None),
            Oturum.son_kullanma > func.now(),
        )
    )
    if o is None:
        return None
    if o.external_uid is not None:
        # Yerel kipe dönülmüşse ortak kimlikle açılmış oturum kabul edilmez (fail-closed).
        if not aiprobe_acik():
            return None
        from tp_core.auth import aiprobe

        sonuc = aiprobe.oturum_kontrol(session, o, user)
        if sonuc is aiprobe.Kontrol.GECERSIZ:
            return None
        if durum is not None:
            durum.external_uid = o.external_uid
            durum.auth_time = o.auth_time
            durum.acr = o.acr
            durum.session_epoch_ms = o.session_epoch_ms
            durum.urunler = o.urunler
            durum.degraded = sonuc is aiprobe.Kontrol.ULASILAMADI
        if uzat:
            aiprobe.sure_uzat(session, o)
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
