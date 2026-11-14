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
from sqlalchemy import or_, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from tp_core.audit import audit_on_commit
from tp_core.auth import yetki
from tp_core.config import get_settings
from tp_core.models import ApiToken, AppUser, KimlikBagi, Oturum, enums, session_scope

log = logging.getLogger(__name__)

AKTOR = "aiprobe"
# JIT hesabının parola özeti: argon2 biçiminde değil → `verify_password` daima False; hesap yerel
# girişle açılamaz.
KULLANILAMAZ_PAROLA = "!aiprobe"
CONTINUE_MAX = 2048
# `products/testing-probe.yaml` `code`: ürün→rol haritalarında TP'nin anahtarı.
URUN_KODU = "tp"
# `app_user.ad_kaynak`: ad AI Probe devrindeki `name`'den (JIT) geldi.
AD_KAYNAGI = "aiprobe"


class Kontrol(enum.Enum):
    GECERLI = "gecerli"
    GECERSIZ = "gecersiz"
    ULASILAMADI = "ulasilamadi"  # oturum korunur, yanıt `X-Aiprobe-Degraded: 1`


class HomeUlasilamaz(Exception):
    """aiprobe-home erişilemedi (ağ hatası / zaman aşımı), 5xx, 408 ya da 429 döndü ya da yanıtı
    anlaşılmadı. Yalnız bu durum "degraded"dır; diğer 4xx yanıtları fail-closed işlenir."""


# Geçici sayılan 4xx'ler (platform kitaplığı `_TRANSIENT_4XX` ile aynı).
GECICI_4XX = frozenset({408, 429})
# Oturum / token başına kesintisiz degraded üst sınırı (platform `DEGRADED_MAX_SECONDS`).
DEGRADED_MAX_S = 600
# TP'nin AI Probe `admin_roles`'u (`products/testing-probe.yaml`); yalnız `acr="2"` (MFA) ile.
# specs/012-rol-yetki §7: Sistem Yöneticisi ve PO.
ADMIN_ROLLERI = frozenset({yetki.ADMIN, yetki.PO})


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
    # CONTRACT v1.2: devir kodunun üretildiği an (ms); oturumda saklanır, her kontrolde gönderilir.
    session_epoch_ms: int | None = None
    # Tüm ürünlerdeki roller (`{"tp": [...], "ap": [...]}`; değiştirici için).
    products: dict[str, list[str]] | None = None


@dataclass(frozen=True)
class KontrolSonucu:
    valid: bool
    roles: frozenset[str] = frozenset()
    reason: str | None = None
    products: dict[str, list[str]] | None = None


@dataclass(frozen=True)
class OturumKimligi:
    """`/v1/session/check`'e giden oturum alanları (CONTRACT v1.2): devirdeki `auth_time` (MFA
    tazeliği), `acr` ("2" = MFA; "1"de home ürünün `admin_roles`'unu — TP'de `admin`, `po` —
    çıkarır) ve `session_epoch_ms` (iptal kuralı; yoksa eski `V > auth_time` kuralı)."""

    auth_time: int
    acr: str = "1"
    session_epoch_ms: int | None = None

    @classmethod
    def of(cls, kaynak: Any) -> OturumKimligi:
        """`oturum` ya da `api_token` satırından (alanlar boşsa güvenli varsayılan)."""
        epoch = getattr(kaynak, "session_epoch_ms", None)
        return cls(
            int(getattr(kaynak, "auth_time", None) or 0),
            str(getattr(kaynak, "acr", None) or "1"),
            int(epoch) if epoch else None,
        )


def _urun_haritasi(deger: Any) -> dict[str, list[str]] | None:
    if not isinstance(deger, Mapping):
        return None
    return {
        str(k): [str(x) for x in v]
        for k, v in deger.items()
        if isinstance(k, str) and isinstance(v, list)
    }


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


_KID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class GoogleIdTokenDogrulayici:
    """Google imzalı ID token'ı (RS256, Google JWKS) doğrular; iddiaları döner, hatada istisna.

    Ağdan önce başlık denetlenir (`alg` RS256, `kid` biçimi): bozuk token JWKS çekimi tetiklemez.
    Anahtarlar önbellekte (`YENILE_S`); bilinmeyen `kid` en çok `MIN_CEKIM_S`'de bir yeniden
    çekime yol açar (uydurma `kid`'lerle Google'a istek yağdırılamaz).
    """

    JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
    YENILE_S = 3600.0
    MIN_CEKIM_S = 300.0
    HATA_SONRASI_S = 30.0

    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        saat: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transport = transport
        self._saat = saat
        self._anahtarlar: dict[str, Any] = {}
        self._cekim: float | None = None
        self._kilit = threading.Lock()

    def _cek(self) -> None:
        import jwt

        basla = self._saat()
        self._cekim = basla
        try:
            with httpx.Client(transport=self._transport, timeout=3.0) as c:
                r = c.get(self.JWKS_URL)
            r.raise_for_status()
            kume = jwt.PyJWKSet.from_dict(r.json())
        except (httpx.HTTPError, ValueError, jwt.PyJWKSetError, jwt.PyJWKError) as exc:
            # Geçici hata: yeniden deneme MIN_CEKIM_S yerine HATA_SONRASI_S sonra.
            self._cekim = basla - self.MIN_CEKIM_S + self.HATA_SONRASI_S
            raise ValueError("JWKS alınamadı") from exc
        self._anahtarlar = {k.key_id: k.key for k in kume.keys if k.key_id}

    def _anahtar(self, kid: str) -> Any:
        with self._kilit:
            an = self._saat()
            gecen = float("inf") if self._cekim is None else an - self._cekim
            bilinmiyor = kid not in self._anahtarlar
            if gecen >= self.YENILE_S or (bilinmiyor and gecen >= self.MIN_CEKIM_S):
                self._cek()
            anahtar = self._anahtarlar.get(kid)
        if anahtar is None:
            raise ValueError("bilinmeyen kid")
        return anahtar

    def __call__(self, token: str, audience: str) -> Mapping[str, Any]:
        import jwt

        baslik = jwt.get_unverified_header(token)
        kid = baslik.get("kid")
        if baslik.get("alg") != "RS256" or not isinstance(kid, str) or not _KID.match(kid):
            raise ValueError("token başlığı geçersiz")
        iddialar = jwt.decode(
            token,
            self._anahtar(kid),
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
    DEGRADED_KABUL.temizle()
    INVALID_CALLER.temizle()


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
        if r.status_code >= 500 or r.status_code in GECICI_4XX:
            raise HomeUlasilamaz(f"{yol}: {r.status_code}")
        return r

    def redeem(self, code: str) -> DevirYaniti:
        r = self._post("/v1/handoff/redeem", {"code": code})
        if r.status_code == 401:
            # 401 invalid_caller: TP'nin servis kimliği yanlış yapılandırılmış (kullanıcı hatası
            # değil); giriş yine reddedilir, yalnız hata 503 "kimlik servisi yok" olur.
            log.error("aiprobe-home devir takasını reddetti: 401 (servis kimliği?)")
            raise HomeUlasilamaz("/v1/handoff/redeem: 401")
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
                session_epoch_ms=int(v["session_epoch_ms"]) if v.get("session_epoch_ms") else None,
                products=_urun_haritasi(v.get("products")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HomeUlasilamaz("redeem yanıtı sözleşmeye uymuyor") from exc

    def check(self, uid: str, kimlik: OturumKimligi) -> KontrolSonucu:
        govde: dict[str, Any] = {"uid": uid, "auth_time": kimlik.auth_time, "acr": kimlik.acr}
        if kimlik.session_epoch_ms:
            govde["session_epoch_ms"] = kimlik.session_epoch_ms
        r = self._post("/v1/session/check", govde)
        if r.status_code == 401:
            # invalid_caller: TP'nin servis kimliği/audience'ı yanlış (yapılandırma hatası); ayrı
            # olay olarak görünür kılınır, karar yine fail-closed.
            INVALID_CALLER.kaydet()
        if r.status_code != 200:
            # 5xx/408/429 `_post`'ta degraded'e çevrildi; kalan 4xx (400 bad_request, 401
            # invalid_caller, 403, 404 …) fail-closed: home oturumu onaylamıyor → geçersiz.
            log.error("aiprobe-home oturum kontrolünü reddetti: %s", r.status_code)
            return KontrolSonucu(False, reason=f"check_rejected_{r.status_code}")
        try:
            v = r.json()
            if v.get("valid") is True:
                return KontrolSonucu(
                    True,
                    frozenset(str(x) for x in (v.get("roles") or [])),
                    products=_urun_haritasi(v.get("products")),
                )
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


_Anahtar = tuple[str, OturumKimligi]


class _Onbellek:
    """Süreç içi `(uid, OturumKimligi) → (zaman, sonuç)`; ömür `AIPROBE_SESSION_CHECK_S`.

    Yalnız başarılı yanıtlar saklanır (geçerli ya da geçersiz). Erişilemezlik ayrıca
    `ulasilamadi_s` boyunca hatırlanır: home kapalıyken her istek zaman aşımı beklemesin.
    """

    MAX = 10_000

    def __init__(self) -> None:
        self._k: dict[_Anahtar, tuple[float, KontrolSonucu | None]] = {}
        self._kilit = threading.Lock()

    def al(self, anahtar: _Anahtar, ttl_s: float) -> tuple[bool, KontrolSonucu | None]:
        with self._kilit:
            kayit = self._k.get(anahtar)
            if kayit is None or time.monotonic() - kayit[0] >= ttl_s:
                return False, None
            return True, kayit[1]

    def koy(self, anahtar: _Anahtar, sonuc: KontrolSonucu | None) -> None:
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


class _Sayac:
    """Süreç içi sayaç (degraded kabuller): `{"oturum": n, "token": n}`. Her artış ayrıca
    sayıyla birlikte WARNING loglanır (log tabanlı metrik: `aiprobe_degraded_kabul`)."""

    def __init__(self) -> None:
        self._n: dict[str, int] = {}
        self._kilit = threading.Lock()

    def artir(self, tur: str) -> int:
        with self._kilit:
            self._n[tur] = self._n.get(tur, 0) + 1
            return self._n[tur]

    def degerler(self) -> dict[str, int]:
        with self._kilit:
            return dict(self._n)

    def temizle(self) -> None:
        with self._kilit:
            self._n.clear()


DEGRADED_KABUL = _Sayac()


class _InvalidCaller:
    """Home `/v1/session/check` 401 (`invalid_caller`) sayacı: her yanıt sayılır, ERROR
    `aiprobe_check_invalid_caller` dakikada en çok bir kez loglanır (log tabanlı metrik)."""

    ARALIK_S = 60.0

    def __init__(self) -> None:
        self.toplam = 0
        self._son_log: float | None = None
        self._kilit = threading.Lock()

    def kaydet(self) -> bool:
        with self._kilit:
            self.toplam += 1
            an = time.monotonic()
            if self._son_log is not None and an - self._son_log < self.ARALIK_S:
                return False
            self._son_log, n = an, self.toplam
        log.error(
            "aiprobe_check_invalid_caller toplam=%d: aiprobe-home TP'nin servis kimliğini "
            "reddetti (AIPROBE_HOME_RUN_URL audience / servis hesabı yapılandırmasını denetleyin)",
            n,
        )
        return True

    def temizle(self) -> None:
        with self._kilit:
            self.toplam = 0
            self._son_log = None


INVALID_CALLER = _InvalidCaller()


def _degraded_baslat(session: Session, satir: Oturum | ApiToken, an: datetime) -> datetime:
    """Degraded başlangıcını ayrı işlemde yazar (istek geri alınsa da 10 dk sınırı kalıcı).

    Satır zaten bir başlangıç taşıyorsa (eşzamanlı istek) onu kullanır. Ayrı işlem satır
    kilidini bekleyemezse (bu isteğin işlemi satırı kilitlemiş) istek işleminde yazılır.
    """
    model = type(satir)
    try:
        with session_scope() as s:
            s.execute(text("SET LOCAL lock_timeout = '2s'"))
            s.execute(
                update(model)
                .where(model.id == satir.id, model.degraded_baslangic.is_(None))
                .values(degraded_baslangic=an)
            )
            bas = s.scalar(select(model.degraded_baslangic).where(model.id == satir.id))
    except DBAPIError:
        log.warning("degraded başlangıcı ayrı işlemde yazılamadı; istek işleminde yazılıyor")
        session.execute(update(model).where(model.id == satir.id).values(degraded_baslangic=an))
        bas = an
    bas = bas or an
    set_committed_value(satir, "degraded_baslangic", bas)
    return bas


def _degraded_kabul(tur: str, uid: str, baslangic: datetime) -> None:
    n = DEGRADED_KABUL.artir(tur)
    log.warning(
        "aiprobe_degraded_kabul tur=%s uid=%s sure_s=%d toplam=%d",
        tur,
        uid,
        int((simdi() - baslangic).total_seconds()),
        n,
    )


def _degraded_asildi(baslangic: datetime | None, an: datetime) -> bool:
    return baslangic is not None and an - baslangic >= timedelta(seconds=DEGRADED_MAX_S)


def kontrol_et(uid: str, kimlik: OturumKimligi, *, taze: bool = False) -> KontrolSonucu:
    """Önbellekli `/v1/session/check`; erişilemezse `HomeUlasilamaz`."""
    ttl = float(get_settings().aiprobe_session_check_s)
    anahtar = (uid, kimlik)
    if not taze:
        var, sonuc = ONBELLEK.al(anahtar, ttl)
        if var and sonuc is not None:
            return sonuc
        var, _ = ONBELLEK.al(anahtar, min(ttl, ULASILAMADI_S))
        if var:  # yakın zamanda erişilemedi (sonuç None)
            raise HomeUlasilamaz("yakın zamanda erişilemedi")
    try:
        sonuc = home().check(uid, kimlik)
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
        sonuc = kontrol_et(o.external_uid, OturumKimligi.of(o))
    except HomeUlasilamaz:
        # Degraded: oturum en çok DEGRADED_MAX_S korunur (başlangıç ilk erişilemeyen kontrolde
        # yazılır); aşılınca yalnız bu oturum iptal edilir (home'un iptal kararı değil).
        if o.degraded_baslangic is None:
            _degraded_baslat(session, o, an)
        elif _degraded_asildi(o.degraded_baslangic, an):
            log.error(
                "aiprobe-home %d sn'den uzun süredir erişilemiyor; oturum kapatıldı (uid=%s)",
                DEGRADED_MAX_S,
                o.external_uid,
            )
            with session_scope() as s:
                s.execute(update(Oturum).where(Oturum.id == o.id).values(iptal_zamani=an))
                audit_on_commit(
                    s,
                    AKTOR,
                    "auth.aiprobe_degraded_timeout",
                    f"app_user:{user.id}",
                    {"kanal": "oturum", "kimlik": o.external_uid},
                )
            return Kontrol.GECERSIZ
        _degraded_kabul("oturum", o.external_uid, o.degraded_baslangic)
        return Kontrol.ULASILAMADI
    if not sonuc.valid:
        iptal_et(o.external_uid, None, sonuc.reason or "gecersiz", kimlik=OturumKimligi.of(o))
        return Kontrol.GECERSIZ
    roller = tp_rolleri(sonuc.roles, o.acr)
    if user.rol not in roller:
        iptal_et(o.external_uid, roller, "rol_kaldirildi")
        return Kontrol.GECERSIZ
    degerler: dict[str, Any] = {"son_kontrol": an, "degraded_baslangic": None}
    o.degraded_baslangic = None
    if sonuc.products is not None and sonuc.products != o.urunler:
        degerler["urunler"] = sonuc.products
        o.urunler = sonuc.products
    session.execute(update(Oturum).where(Oturum.id == o.id).values(**degerler))
    return Kontrol.GECERLI


def sure_uzat(session: Session, o: Oturum) -> None:
    """Boşta süresini kaydırır (mutlak sınırı aşmadan); ≥ 60 sn fark yoksa yazmaz.

    Degraded iken (home doğrulayamıyor) süre degraded üst sınırının ötesine uzatılmaz.
    """
    ayar = get_settings()
    an = simdi()
    sinirlar = [
        o.olusturma + timedelta(seconds=ayar.aiprobe_absolute_s),
        an + timedelta(seconds=ayar.aiprobe_idle_s),
    ]
    if o.degraded_baslangic is not None:
        sinirlar.append(o.degraded_baslangic + timedelta(seconds=DEGRADED_MAX_S))
    hedef = min(sinirlar)
    if hedef - o.son_kullanma >= timedelta(seconds=60):
        session.execute(update(Oturum).where(Oturum.id == o.id).values(son_kullanma=hedef))


# home `revoked` kararı oturuma özgüdür (CONTRACT v1.4: R ≥ E ya da V > v0; E = bu oturumun devir
# anı): bir tarayıcıdaki eski oturumun iptali, home çıkışından SONRA başka bir cihazda açılmış
# oturumu geçersiz kılmaz. `disabled|expired|no_access|not_found` kişiye özgüdür.
OTURUMA_OZGU_NEDENLER = frozenset({"revoked"})


def kapsamli_iptal_mi(neden: str, kalan_roller: Iterable[str] | None, kimlik: Any) -> bool:
    """Yalnız bu ve daha eski oturumlar mı düşmeli (True) yoksa kişinin tüm oturumları mı?"""
    return (
        kalan_roller is None
        and neden in OTURUMA_OZGU_NEDENLER
        and kimlik is not None
        and bool(getattr(kimlik, "session_epoch_ms", None))
    )


def eski_oturumlari_iptal_et(s: Session, ids: list[uuid.UUID], epoch_ms: int) -> int:
    """`revoked`: devir anı (session_epoch_ms) iptal edilen oturumunkinden sonra OLMAYAN oturumlar
    düşer; sonra açılmış oturumlar (başka cihaz, yeniden giriş) kendi kontrollerinde karar
    alır. `auth_epoch` artırılmaz (artırmak her çerezi geçersiz kılardı)."""
    sonuc = s.execute(
        update(Oturum)
        .where(
            Oturum.user_id.in_(ids),
            Oturum.iptal_zamani.is_(None),
            or_(Oturum.session_epoch_ms.is_(None), Oturum.session_epoch_ms <= epoch_ms),
        )
        .values(iptal_zamani=simdi())
    )
    # Bu ve daha eski oturumlardan üretilmiş token'lar da kalıcı olarak düşer.
    s.execute(
        update(ApiToken)
        .where(
            ApiToken.user_id.in_(ids),
            ApiToken.iptal.is_(False),
            or_(ApiToken.session_epoch_ms.is_(None), ApiToken.session_epoch_ms <= epoch_ms),
        )
        .values(iptal=True)
    )
    return int(sonuc.rowcount or 0)


def iptal_et(
    external_uid: str,
    kalan_roller: Iterable[str] | None,
    neden: str,
    *,
    kimlik: OturumKimligi | None = None,
) -> int:
    """Kişinin bağlı hesaplarında `auth_epoch`'u artırır ve oturumlarını iptal eder.

    `kalan_roller` verilirse yalnız rolü artık listede olmayan hesaplar düşer (rol kaldırma).
    `kimlik` verilir ve neden oturuma özgüyse (`revoked`) yalnız bu ve daha eski oturumlar düşer
    (`eski_oturumlari_iptal_et`): paralel / başka cihazdaki yeni oturum kapanmaz.
    Ayrı işlemde commit edilir: istek 401 ile geri alınsa da iptal kalıcıdır.
    """
    kapsamli = kapsamli_iptal_mi(neden, kalan_roller, kimlik)
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
            ozet: dict[str, Any] = {
                "neden": neden,
                "hesaplar": sorted(h.kullanici_adi for h in hesaplar),
            }
            if kapsamli:
                assert kimlik is not None and kimlik.session_epoch_ms is not None
                ozet["kapsam"] = "bu_ve_onceki_oturumlar"
                ozet["oturum"] = eski_oturumlari_iptal_et(s, ids, kimlik.session_epoch_ms)
            else:
                epoch_artir(s, ids)
            audit_on_commit(s, AKTOR, "auth.aiprobe_revoked", f"kimlik:{external_uid}", ozet)
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


def token_kontrol(
    session: Session, user: AppUser, kimlik: OturumKimligi, tok: ApiToken | None = None
) -> bool:
    """`tpt_` token'ı: sahip bir AI Probe kişisine bağlıysa önbellekli oturum kontrolü.

    `kimlik`: token'ı üreten AI Probe oturumunun alanları (`api_token.auth_time`, `acr`,
    `session_epoch_ms`); token yerel oturumdan üretilmişse `auth_time` = üretim anı, `acr` "1",
    epoch yok. Erişilemezse token korunur, ama `tok` verilmişse token başına en çok
    `DEGRADED_MAX_S` (sonra home yeniden doğrulayana dek reddedilir).
    """
    uid = bagli_uid(session, user.id)
    if uid is None:
        # `aiprobe` kipinde yerel giriş yoktur: bağsız hesabın token'ı kabul edilmez (`both`
        # kipinde yerel hesabın token'ı yerel kural gibi geçer).
        return get_settings().auth_mode != "aiprobe"
    an = simdi()
    try:
        sonuc = kontrol_et(uid, kimlik)
    except HomeUlasilamaz:
        baslangic = an if tok is None else tok.degraded_baslangic
        if tok is not None and baslangic is None:
            baslangic = _degraded_baslat(session, tok, an)
        elif _degraded_asildi(baslangic, an):
            log.error(
                "aiprobe-home %d sn'den uzun süredir erişilemiyor; token reddedildi (uid=%s)",
                DEGRADED_MAX_S,
                uid,
            )
            return False
        assert baslangic is not None
        _degraded_kabul("token", uid, baslangic)
        return True
    if not sonuc.valid:
        iptal_et(uid, None, sonuc.reason or "gecersiz", kimlik=kimlik)
        return False
    roller = tp_rolleri(sonuc.roles, kimlik.acr)
    if user.rol not in roller:
        iptal_et(uid, roller, "rol_kaldirildi")
        return False
    if tok is not None and tok.degraded_baslangic is not None:
        session.execute(
            update(ApiToken).where(ApiToken.id == tok.id).values(degraded_baslangic=None)
        )
        tok.degraded_baslangic = None
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


def tp_rolleri(roller: Iterable[str], acr: str | None = None) -> tuple[str, ...]:
    """Devirdeki rollerden TP'nin tanıdıkları (sıra korunur, tekrarsız).

    Kaldırılan roller yerine geçen role çevrilir (`presenter` → `admin`, `yetki.ESKI_ROLLER`):
    AI Probe'daki canlı rol kayıtları güncellenene kadar hesap erişimini kaybetmez.

    Derinlemesine savunma: `acr` "2" (MFA) değilse yönetici rolleri (`ADMIN_ROLLERI`: `admin`,
    `po`) home göndermiş olsa bile düşülür (home `acr="1"`de zaten çıkarır; CONTRACT v1.2). Kontrol
    çevrilmiş role uygulanır: eski `presenter` da `admin` olarak MFA ister.
    """
    gorulen: list[str] = []
    for ham in roller:
        r = yetki.normalize_rol(ham)
        if r in ADMIN_ROLLERI and acr != "2":
            continue
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
    """Bağlı hesabı olmayan her TP rolü için yeni `app_user` + `kimlik_bagi` (JIT).

    Aynı kişinin eşzamanlı girişleri (iki sekme) çift hesap açmasın: kişi başına işlem kilidi
    (`pg_advisory_xact_lock`, işlem bitince bırakılır) alınır ve mevcut hesaplar kilitten **sonra**
    okunur; ikinci istek birincinin commit'ini bekler ve onun hesaplarını görür.
    """
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:u))"), {"u": f"tp-jit:{devir.uid}"}
    )
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
            # Ad, kişinin AI Probe hesabından gelir (TP doğrulamaz): portal bunu belirtir.
            ad_kaynak=AD_KAYNAGI if devir.name else None,
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
