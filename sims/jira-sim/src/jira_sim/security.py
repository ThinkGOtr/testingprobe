"""Simülatörün kendi güvenliği: PO girişi, CSRF, köken (Origin) ve yönetim ucu koruması.

PO onayı (``tp-po-approved``) insan onay kapısıdır (anayasa I). Simülatörde de bu etiketi PO
adına yalnızca PO parolasını bilen kişi koyabilmelidir:

- Arayüzün yazma uçları imzalı bir PO oturum çerezi ve formda gizli bir CSRF belirteci ister;
  ayrıca ``Origin``/``Referer`` simülatörün kendi kökeni değilse istek reddedilir.
- REST API'de ``po@sim.local`` Basic auth parolası PO parolası olmalıdır (diğer simülatör
  kullanıcıları için her token kabul edilir).
- ``/sim/*`` yazma uçları ``JIRA_SIM_ADMIN_TOKEN`` tanımlıysa ``X-Sim-Admin-Token`` başlığı ister;
  her durumda tarayıcıdan gelen başka kökenli istekler reddedilir.

Ortam değişkenleri:
- ``JIRA_SIM_PO_PASSWORD``: PO parolası. Boşsa her açılışta rastgele üretilir ve loga yazılır.
- ``JIRA_SIM_ADMIN_TOKEN``: ``/sim/*`` yönetim ucu belirteci (boşsa yalnızca köken denetimi).
- ``JIRA_SIM_SECRET``: oturum imza anahtarı (boşsa her açılışta rastgele).

PO oturumları sunucu tarafında (bellekte) tutulur: imzalı çerez yalnızca kayıtlı ve süresi
dolmamış (``SESSION_TTL_S``, 8 saat) bir oturumu gösteriyorsa geçerlidir. ``/cikis`` oturumu
sunucudan siler; çerezin kopyası çıkıştan sonra işe yaramaz. Yeniden başlatma tüm oturumları
kapatır.
- ``JIRA_SIM_ALLOWED_HOSTS``: virgülle ek ``Host`` adları (DNS rebinding'e karşı izin listesi).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from starlette.requests import Request

log = logging.getLogger("jira_sim")

SESSION_COOKIE = "jsim_po"
ADMIN_HEADER = "X-Sim-Admin-Token"
SESSION_TTL_S = 8 * 60 * 60
DEFAULT_HOSTS = frozenset({"127.0.0.1", "localhost", "jira-sim", "testserver"})


def origin_of(url: str) -> str | None:
    """``scheme://host[:port]`` (varsayılan port yazılmaz); çözülemezse ``None``."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    default = 443 if parts.scheme == "https" else 80
    host = parts.hostname
    if ":" in host:  # IPv6
        host = f"[{host}]"
    suffix = f":{port}" if port and port != default else ""
    return f"{parts.scheme}://{host}{suffix}"


@dataclass
class SimSecurity:
    po_password: str
    secret: bytes
    admin_token: str | None = None
    extra_hosts: frozenset[str] = field(default_factory=frozenset)
    generated_password: bool = False
    session_ttl_s: float = SESSION_TTL_S
    clock: Callable[[], float] = time.monotonic
    # nonce → son geçerlilik anı (``clock`` cinsinden). Sunucu tarafı oturum kaydı.
    _sessions: dict[str, float] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def from_env(
        cls, po_password: str | None = None, admin_token: str | None = None
    ) -> SimSecurity:
        generated = False
        pw = po_password if po_password is not None else os.environ.get("JIRA_SIM_PO_PASSWORD")
        if not pw:
            pw = secrets.token_urlsafe(12)
            generated = True
        token = admin_token if admin_token is not None else os.environ.get("JIRA_SIM_ADMIN_TOKEN")
        secret_env = os.environ.get("JIRA_SIM_SECRET", "")
        secret = secret_env.encode() if secret_env else secrets.token_bytes(32)
        hosts = {
            h.strip().lower()
            for h in os.environ.get("JIRA_SIM_ALLOWED_HOSTS", "").split(",")
            if h.strip()
        }
        sec = cls(pw, secret, token or None, frozenset(hosts), generated)
        if generated:
            # Yalnızca konteyner logunda görünür (``docker compose logs jira-sim``).
            log.warning("JIRA_SIM_PO_PASSWORD tanımlı değil; bu açılışın PO parolası: %s", pw)
        return sec

    # ------------------------------------------------------------ parola / belirteç
    def check_po_password(self, candidate: str) -> bool:
        return hmac.compare_digest(candidate.encode(), self.po_password.encode())

    def check_admin(self, request: Request) -> bool:
        if not self.admin_token:
            return True
        given = request.headers.get(ADMIN_HEADER, "")
        return hmac.compare_digest(given.encode(), self.admin_token.encode())

    def _sign(self, purpose: str, nonce: str) -> str:
        return hmac.new(self.secret, f"{purpose}|{nonce}".encode(), hashlib.sha256).hexdigest()

    # ------------------------------------------------------------------- oturum
    def new_session(self) -> str:
        """Yeni PO oturumu açar ve sunucuda kaydeder; çerez değerini döner."""
        nonce = secrets.token_urlsafe(18)
        now = self.clock()
        with self._lock:
            self._sessions = {n: exp for n, exp in self._sessions.items() if exp > now}
            self._sessions[nonce] = now + self.session_ttl_s
        return f"{nonce}.{self._sign('session', nonce)}"

    def _verified_nonce(self, request: Request) -> str | None:
        value = request.cookies.get(SESSION_COOKIE, "")
        nonce, _, sig = value.rpartition(".")
        if not nonce or not sig:
            return None
        if not hmac.compare_digest(sig, self._sign("session", nonce)):
            return None
        return nonce

    def session_nonce(self, request: Request) -> str | None:
        """Geçerli oturumun nonce'u: imza doğru, sunucuda kayıtlı ve süresi dolmamış olmalı."""
        nonce = self._verified_nonce(request)
        if nonce is None:
            return None
        with self._lock:
            expires = self._sessions.get(nonce)
            if expires is None:
                return None
            if expires <= self.clock():
                del self._sessions[nonce]
                return None
        return nonce

    def end_session(self, request: Request) -> None:
        """Çıkış: oturumu sunucudan siler (çerezin kopyası da artık geçersizdir)."""
        nonce = self._verified_nonce(request)
        if nonce is not None:
            with self._lock:
                self._sessions.pop(nonce, None)

    def csrf_token(self, request: Request) -> str | None:
        nonce = self.session_nonce(request)
        return self._sign("csrf", nonce) if nonce else None

    def check_csrf(self, request: Request, token: str) -> bool:
        expected = self.csrf_token(request)
        return bool(expected and token) and hmac.compare_digest(token, expected or "")

    # ------------------------------------------------------------ köken / host
    def host_allowed(self, request: Request, base_url: str) -> bool:
        host = (request.url.hostname or "").lower()
        allowed = set(DEFAULT_HOSTS) | set(self.extra_hosts)
        if base_url:
            allowed.add((urlsplit(base_url).hostname or "").lower())
        return host in allowed

    def same_origin(self, request: Request, base_url: str) -> bool:
        """Tarayıcıdan gelen istek simülatörün kendi kökeninden mi?

        Tarayıcılar POST isteklerinde ``Origin`` (ya da ``Sec-Fetch-Site``) gönderir; başka bir
        kökenden (aynı makinedeki başka port dahil) gelen istek reddedilir. Bu başlıkların hiç
        olmadığı istemciler (curl, betikler) tarayıcı değildir; onlar için kimlik denetimi yeter.
        """
        allowed = {origin_of(str(request.base_url))}
        if base_url:
            allowed.add(origin_of(base_url))
        allowed.discard(None)
        site = request.headers.get("sec-fetch-site")
        if site and site not in ("same-origin", "none"):
            return False
        origin = request.headers.get("origin")
        if origin is not None:
            return origin in allowed
        referer = request.headers.get("referer")
        if referer:
            return origin_of(referer) in allowed
        return True
