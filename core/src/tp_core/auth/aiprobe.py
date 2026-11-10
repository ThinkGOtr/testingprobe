"""AI Probe ortak kimliği: `aiprobe-home` ile iki sunucu çağrısı ve TP tarafı kuralları.

ADR-0001 / constitution İlke XII: TP ortak kimliğe **yalnızca** belgelenmiş HTTP kimlik API'si
ile bağlanır (aiprobe-platform/docs/CONTRACT.md v1, "Ürün sunucusu uçları"):

- `POST {AIPROBE_HOME_RUN_URL}/v1/handoff/redeem {code}` — giriş devri kodunun tek kullanımlık
  takası.
- `POST {AIPROBE_HOME_RUN_URL}/v1/session/check {uid, auth_time}` — oturum hâlâ geçerli mi?

İkisi de TP'nin servis hesabının Google imzalı ID token'ıyla (`audience` = home adresi) çağrılır.
Firebase SDK'sı ve platform istemci paketi kullanılmaz; çağrılar burada, TP sahipliğindedir.

Ters yön (`aiprobe-home` → TP `/admin/kimlik-bagi`) Google ID token'ı `GoogleIdTokenDogrulayici`
ile doğrulanır. Token sağlayıcı, doğrulayıcı ve HTTP taşıyıcısı `configure(...)` ile
değiştirilebilir (testler sahte `aiprobe-home` kullanır).

`local` kipte bu modül hiçbir dış çağrı yapmaz: çağıranlar önce `sessions.aiprobe_acik()`'a bakar.
"""

from __future__ import annotations

import enum
import logging
import re
import secrets
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tp_core.audit import audit_on_commit
from tp_core.config import get_settings
from tp_core.models import AppUser, KimlikBagi, Oturum, enums, session_scope

log = logging.getLogger(__name__)

AKTOR = "aiprobe"
# JIT hesabının parola özeti: argon2 biçiminde değil → `verify_password` daima False; hesap yerel
# girişle açılamaz.
KULLANILAMAZ_PAROLA = "!aiprobe"
CONTINUE_MAX = 2048


class Kontrol(enum.Enum):
    GECERLI = "gecerli"
    GECERSIZ = "gecersiz"
    ULASILAMADI = "ulasilamadi"  # oturum korunur, yanıt `X-Aiprobe-Degraded: 1`


class HomeUlasilamaz(Exception):
    """aiprobe-home erişilemedi, 5xx döndü ya da TP'nin servis kimliğini reddetti."""


class GecersizKod(Exception):
    """Devir kodu yok / kullanılmış / süresi dolmuş / başka ürünün (home hepsine aynı yanıtı
    verir)."""


@dataclass(frozen=True)
class DevirYaniti:
    uid: str
    email: str
    name: str
    org: str | None
    roles: tuple[str, ...]
    auth_time: int
    acr: str
    state: str
    continue_: str
    locale: str | None = None


@dataclass(frozen=True)
class KontrolSonucu:
    valid: bool
    roles: frozenset[str] = frozenset()
    reason: str | None = None


# ------------------------------------------------------------------ servis kimliği (enjekte)


TokenSaglayici = Callable[[str], str]  # audience → Google ID token


class IdTokenDogrulayici(Protocol):
    def __call__(self, token: str, audience: str) -> Mapping[str, Any]: ...


class MetadataTokenSaglayici:
    """GCE metadata sunucusundan VM servis hesabının ID token'ı (50 dk önbellek).

    Metadata sunucusu yalnızca VM içinden, bağlantı yerel (169.254.169.254) adresle erişilir;
    TLS'i yoktur (Google'ın belgelediği tek yol).
    """

    URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity"
    SURE_S = 50 * 60

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport
        self._onbellek: dict[str, tuple[float, str]] = {}
        self._kilit = threading.Lock()

    def __call__(self, audience: str) -> str:
        with self._kilit:
            kayit = self._onbellek.get(audience)
            if kayit is not None and time.monotonic() - kayit[0] < self.SURE_S:
                return kayit[1]
        try:
            with httpx.Client(transport=self._transport, timeout=3.0) as c:
                r = c.get(
                    self.URL,
                    params={"audience": audience, "format": "full"},
                    headers={"Metadata-Flavor": "Google"},
                )
        except httpx.HTTPError as exc:
            raise HomeUlasilamaz("servis kimliği alınamadı") from exc
        if r.status_code != 200 or not r.text:
            raise HomeUlasilamaz("servis kimliği alınamadı")
        with self._kilit:
            self._onbellek[audience] = (time.monotonic(), r.text.strip())
        return r.text.strip()


GOOGLE_ISS = frozenset({"accounts.google.com", "https://accounts.google.com"})


class GoogleIdTokenDogrulayici:
    """Google imzalı ID token'ı (RS256, Google JWKS) doğrular; iddiaları döner, hatada istisna."""

    JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"

    def __init__(self) -> None:
        self._jwks: Any = None
        self._kilit = threading.Lock()

    def __call__(self, token: str, audience: str) -> Mapping[str, Any]:
        import jwt

        with self._kilit:
            if self._jwks is None:
                self._jwks = jwt.PyJWKClient(self.JWKS_URL, cache_keys=True)
        anahtar = self._jwks.get_signing_key_from_jwt(token)
        iddialar = jwt.decode(
            token,
            anahtar.key,
            algorithms=["RS256"],
            audience=audience,
            options={"require": ["exp", "iat", "aud", "iss"]},
        )
        if iddialar.get("iss") not in GOOGLE_ISS:
            raise ValueError("iss Google değil")
        return iddialar


@dataclass
class _Yapi:
    transport: httpx.BaseTransport | None = None
    token_saglayici: TokenSaglayici | None = None
    dogrulayici: IdTokenDogrulayici | None = None
    saat: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))


_YAPI = _Yapi()
_VARSAYILAN_SAGLAYICI: MetadataTokenSaglayici | None = None
_VARSAYILAN_DOGRULAYICI: GoogleIdTokenDogrulayici | None = None


def configure(
    *,
    transport: httpx.BaseTransport | None = None,
    token_saglayici: TokenSaglayici | None = None,
    dogrulayici: IdTokenDogrulayici | None = None,
    saat: Callable[[], datetime] | None = None,
) -> None:
    """Testler ve özel kurulumlar için: home taşıyıcısı, ID token sağlayıcı/doğrulayıcı, saat."""
    if transport is not None:
        _YAPI.transport = transport
    if token_saglayici is not None:
        _YAPI.token_saglayici = token_saglayici
    if dogrulayici is not None:
        _YAPI.dogrulayici = dogrulayici
    if saat is not None:
        _YAPI.saat = saat


def reset() -> None:
    global _YAPI
    _YAPI = _Yapi()
    ONBELLEK.temizle()


def simdi() -> datetime:
    return _YAPI.saat()


def token_saglayici() -> TokenSaglayici:
    global _VARSAYILAN_SAGLAYICI
    if _YAPI.token_saglayici is not None:
        return _YAPI.token_saglayici
    if _VARSAYILAN_SAGLAYICI is None:
        _VARSAYILAN_SAGLAYICI = MetadataTokenSaglayici()
    return _VARSAYILAN_SAGLAYICI


def dogrulayici() -> IdTokenDogrulayici:
    global _VARSAYILAN_DOGRULAYICI
    if _YAPI.dogrulayici is not None:
        return _YAPI.dogrulayici
    if _VARSAYILAN_DOGRULAYICI is None:
        _VARSAYILAN_DOGRULAYICI = GoogleIdTokenDogrulayici()
    return _VARSAYILAN_DOGRULAYICI


# ------------------------------------------------------------------ aiprobe-home istemcisi


class HomeIstemcisi:
    def __init__(
        self,
        base_url: str,
        saglayici: TokenSaglayici,
        transport: httpx.BaseTransport | None = None,
        timeout_s: float = 5.0,
    ) -> None:
        if not base_url:
            raise HomeUlasilamaz("AIPROBE_HOME_RUN_URL tanımlı değil")
        self.base_url = base_url.rstrip("/")
        self._saglayici = saglayici
        self._transport = transport
        self._timeout = timeout_s

    def _post(self, yol: str, govde: Mapping[str, Any]) -> httpx.Response:
        token = self._saglayici(self.base_url)
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout) as c:
                r = c.post(
                    self.base_url + yol,
                    json=dict(govde),
                    headers={"Authorization": f"Bearer {token}"},
                )
        except httpx.HTTPError as exc:
            raise HomeUlasilamaz(f"{yol}: ağ hatası") from exc
        if r.status_code >= 500 or r.status_code == 401:
            # 401 invalid_caller: TP'nin servis kimliği yanlış yapılandırılmış (kullanıcı
            # hatası değil).
            raise HomeUlasilamaz(f"{yol}: {r.status_code}")
        return r

    def redeem(self, code: str) -> DevirYaniti:
        r = self._post("/v1/handoff/redeem", {"code": code})
        if r.status_code != 200:
            raise GecersizKod()
        try:
            v = r.json()
            return DevirYaniti(
                uid=str(v["uid"]),
                email=str(v.get("email") or ""),
                name=str(v.get("name") or ""),
                org=v.get("org"),
                roles=tuple(str(x) for x in (v.get("roles") or [])),
                auth_time=int(v["auth_time"]),
                acr=str(v.get("acr") or "1"),
                state=str(v.get("state") or ""),
                continue_=str(v.get("continue") or "/"),
                locale=v.get("locale"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HomeUlasilamaz("redeem yanıtı sözleşmeye uymuyor") from exc

    def check(self, uid: str, auth_time: int) -> KontrolSonucu:
        r = self._post("/v1/session/check", {"uid": uid, "auth_time": auth_time})
        if r.status_code != 200:
            raise HomeUlasilamaz(f"/v1/session/check: {r.status_code}")
        try:
            v = r.json()
            if v.get("valid") is True:
                return KontrolSonucu(True, frozenset(str(x) for x in (v.get("roles") or [])))
            return KontrolSonucu(False, reason=str(v.get("reason") or "bilinmiyor"))
        except (TypeError, ValueError, AttributeError) as exc:
            raise HomeUlasilamaz("check yanıtı sözleşmeye uymuyor") from exc


def home() -> HomeIstemcisi:
    ayar = get_settings()
    return HomeIstemcisi(
        ayar.aiprobe_home_run_url,
        token_saglayici(),
        transport=_YAPI.transport,
        timeout_s=ayar.aiprobe_http_timeout_s,
    )


# ------------------------------------------------------------------ oturum kontrolü + önbellek


class _Onbellek:
    """Süreç içi `(uid, auth_time) → (zaman, sonuç)`; ömür `AIPROBE_SESSION_CHECK_S`.

    Yalnız başarılı yanıtlar saklanır (geçerli ya da geçersiz). Erişilemezlik ayrıca
    `ulasilamadi_s` boyunca hatırlanır: home kapalıyken her istek zaman aşımı beklemesin.
    """

    MAX = 10_000

    def __init__(self) -> None:
        self._k: dict[tuple[str, int], tuple[float, KontrolSonucu | None]] = {}
        self._kilit = threading.Lock()

    def al(self, anahtar: tuple[str, int], ttl_s: float) -> tuple[bool, KontrolSonucu | None]:
        with self._kilit:
            kayit = self._k.get(anahtar)
            if kayit is None or time.monotonic() - kayit[0] >= ttl_s:
                return False, None
            return True, kayit[1]

    def koy(self, anahtar: tuple[str, int], sonuc: KontrolSonucu | None) -> None:
        with self._kilit:
            if len(self._k) >= self.MAX:
                self._k.clear()
            self._k[anahtar] = (time.monotonic(), sonuc)

    def unut(self, uid: str) -> None:
        with self._kilit:
            for a in [a for a in self._k if a[0] == uid]:
                del self._k[a]

    def temizle(self) -> None:
        with self._kilit:
            self._k.clear()


ONBELLEK = _Onbellek()
ULASILAMADI_S = 15.0


def kontrol_et(uid: str, auth_time: int, *, taze: bool = False) -> KontrolSonucu:
    """Önbellekli `/v1/session/check`; erişilemezse `HomeUlasilamaz`."""
    ttl = float(get_settings().aiprobe_session_check_s)
    anahtar = (uid, int(auth_time))
    if not taze:
        var, sonuc = ONBELLEK.al(anahtar, ttl)
        if var and sonuc is not None:
            return sonuc
        var, _ = ONBELLEK.al(anahtar, min(ttl, ULASILAMADI_S))
        if var:  # yakın zamanda erişilemedi (sonuç None)
            raise HomeUlasilamaz("yakın zamanda erişilemedi")
    try:
        sonuc = home().check(uid, int(auth_time))
    except HomeUlasilamaz:
        ONBELLEK.koy(anahtar, None)
        log.warning("aiprobe-home oturum kontrolü yapılamadı; oturum korunuyor", exc_info=True)
        raise
    ONBELLEK.koy(anahtar, sonuc)
    return sonuc


def oturum_kontrol(session: Session, o: Oturum, user: AppUser) -> Kontrol:
    """AI Probe oturumunu gerekiyorsa kimlik servisine sorar (`session_valid` içinden)."""
    assert o.external_uid is not None
    ayar = get_settings()
    an = simdi()
    if o.son_kontrol is not None and an - o.son_kontrol < timedelta(
        seconds=ayar.aiprobe_session_check_s
    ):
        return Kontrol.GECERLI
    try:
        sonuc = kontrol_et(o.external_uid, int(o.auth_time or 0))
    except HomeUlasilamaz:
        return Kontrol.ULASILAMADI
    if not sonuc.valid:
        iptal_et(o.external_uid, None, sonuc.reason or "gecersiz")
        return Kontrol.GECERSIZ
    if user.rol not in sonuc.roles:
        iptal_et(o.external_uid, sonuc.roles, "rol_kaldirildi")
        return Kontrol.GECERSIZ
    session.execute(update(Oturum).where(Oturum.id == o.id).values(son_kontrol=an))
    return Kontrol.GECERLI


def sure_uzat(session: Session, o: Oturum) -> None:
    """Boşta süresini kaydırır (mutlak sınırı aşmadan); ≥ 60 sn fark yoksa yazmaz."""
    ayar = get_settings()
    an = simdi()
    hedef = min(
        o.olusturma + timedelta(seconds=ayar.aiprobe_absolute_s),
        an + timedelta(seconds=ayar.aiprobe_idle_s),
    )
    if hedef - o.son_kullanma >= timedelta(seconds=60):
        session.execute(update(Oturum).where(Oturum.id == o.id).values(son_kullanma=hedef))


def iptal_et(external_uid: str, kalan_roller: Iterable[str] | None, neden: str) -> int:
    """Kişinin bağlı hesaplarında `auth_epoch`'u artırır ve oturumlarını iptal eder.

    `kalan_roller` verilirse yalnız rolü artık listede olmayan hesaplar düşer (rol kaldırma).
    Ayrı işlemde commit edilir: istek 401 ile geri alınsa da iptal kalıcıdır.
    """
    with session_scope() as s:
        q = (
            select(AppUser.id, AppUser.kullanici_adi)
            .join(KimlikBagi, KimlikBagi.app_user_id == AppUser.id)
            .where(KimlikBagi.external_uid == external_uid)
        )
        if kalan_roller is not None:
            q = q.where(AppUser.rol.not_in(list(kalan_roller)))
        hesaplar = s.execute(q).all()
        ids = [h.id for h in hesaplar]
        if ids:
            epoch_artir(s, ids)
            audit_on_commit(
                s,
                AKTOR,
                "auth.aiprobe_revoked",
                f"kimlik:{external_uid}",
                {"neden": neden, "hesaplar": sorted(h.kullanici_adi for h in hesaplar)},
            )
    ONBELLEK.unut(external_uid)
    log.info("AI Probe iptali uygulandı (%s): %d hesap", neden, len(ids))
    return len(ids)


def epoch_artir(s: Session, ids: list[uuid.UUID]) -> None:
    s.execute(update(AppUser).where(AppUser.id.in_(ids)).values(auth_epoch=AppUser.auth_epoch + 1))
    s.execute(
        update(Oturum)
        .where(Oturum.user_id.in_(ids), Oturum.iptal_zamani.is_(None))
        .values(iptal_zamani=simdi())
    )


def bagli_uid(session: Session, user_id: uuid.UUID) -> str | None:
    return session.scalar(select(KimlikBagi.external_uid).where(KimlikBagi.app_user_id == user_id))


def token_kontrol(session: Session, user: AppUser, uretim: datetime) -> bool:
    """`tpt_` token'ı: sahip bir AI Probe kişisine bağlıysa önbellekli oturum kontrolü.

    `auth_time` olarak token'ın üretim anı kullanılır (token, o anda geçerli bir oturumdan
    üretilmiştir). Erişilemezse token korunur.
    """
    uid = bagli_uid(session, user.id)
    if uid is None:
        return True
    try:
        sonuc = kontrol_et(uid, int(uretim.timestamp()))
    except HomeUlasilamaz:
        return True
    if not sonuc.valid:
        iptal_et(uid, None, sonuc.reason or "gecersiz")
        return False
    if user.rol not in sonuc.roles:
        iptal_et(uid, sonuc.roles, "rol_kaldirildi")
        return False
    return True


# ------------------------------------------------------------------ giriş kuralları


_KONTROL_KARAKTERI = re.compile(r"[\x00-\x1f\x7f]")


def guvenli_continue(deger: str | None) -> str:
    """Yalnız `/` ile başlayan göreli yol; `//`, `\\`, şema, kontrol karakteri → `/`."""
    if not deger or len(deger) > CONTINUE_MAX:
        return "/"
    if (
        not deger.startswith("/")
        or deger.startswith("//")
        or "\\" in deger
        or _KONTROL_KARAKTERI.search(deger)
        or ":" in deger.split("?", 1)[0].split("#", 1)[0]
    ):
        return "/"
    return deger


def izinli_org(org: str | None) -> bool:
    izinli = {o.strip() for o in get_settings().aiprobe_allowed_orgs.split(",") if o.strip()}
    return bool(org) and org in izinli


def tp_rolleri(roller: Iterable[str]) -> tuple[str, ...]:
    """Devirdeki rollerden TP'nin tanıdıkları (sıra korunur, tekrarsız)."""
    gorulen: list[str] = []
    for r in roller:
        if r in enums.ROLLER and r not in gorulen:
            gorulen.append(r)
    return tuple(gorulen)


def bagli_hesaplar(session: Session, external_uid: str) -> list[AppUser]:
    return list(
        session.scalars(
            select(AppUser)
            .join(KimlikBagi, KimlikBagi.app_user_id == AppUser.id)
            .where(KimlikBagi.external_uid == external_uid)
            .order_by(AppUser.rol, AppUser.kullanici_adi)
        )
    )


_AD_DISI = re.compile(r"[^a-z0-9._-]+")


def _jit_ad(session: Session, email: str, rol: str) -> str:
    yerel = _AD_DISI.sub("", (email.split("@", 1)[0] or "").lower())[:40] or "kisi"
    aday = f"{yerel}-{rol}"
    while session.scalar(select(AppUser.id).where(AppUser.kullanici_adi == aday)) is not None:
        aday = f"{yerel}-{rol}-{secrets.token_hex(2)}"
    return aday


def jit_hesaplar(session: Session, devir: DevirYaniti, roller: Iterable[str]) -> list[AppUser]:
    """Bağlı hesabı olmayan her TP rolü için yeni `app_user` + `kimlik_bagi` (JIT)."""
    mevcut = {h.rol for h in bagli_hesaplar(session, devir.uid)}
    yeni: list[AppUser] = []
    for rol in roller:
        if rol in mevcut:
            continue
        u = AppUser(
            kullanici_adi=_jit_ad(session, devir.email, rol),
            rol=rol,
            parola_hash=KULLANILAMAZ_PAROLA,
            ad_soyad=devir.name[:120] or None,
        )
        session.add(u)
        session.flush()
        session.add(KimlikBagi(external_uid=devir.uid, app_user_id=u.id))
        session.flush()
        audit_on_commit(
            session,
            u.kullanici_adi,
            "auth.jit_user",
            f"app_user:{u.id}",
            {"rol": rol, "kimlik": devir.uid},
        )
        yeni.append(u)
    return yeni
