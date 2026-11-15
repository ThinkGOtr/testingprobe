"""Bağlantı erişim token'ı: `POST /v1/connections/access-token` (UYGULAMA-PLANI-R1 §6).

Bağlantı kipi (`connections.<tur>.mode`, etkin config) `oauth` (Jira, Atlassian 3LO) ya da `app`
(GitHub App) iken Jira ve GitHub istemcileri sır yerine Home'un ürettiği kısa ömürlü token'ı
kullanır. `token` kipinde bu modül kullanılmaz (Home 409 `use_secret` döner → `TokenKipinde`).
GitHub App kipinde projede depo tanımlı değilse Home 409 `repo_required` döner →
`DepoTanimliDegil` ("Projede depo tanımlı değil").

**Yalnız yazma kimliği taşıyan süreç** (`TP_BAGLANTI_TOKENI=1`, compose'da yalnız core-worker)
token alabilir: OAuth/App token'ı okuma ile yazmayı ayırmaz; core-api'nin yazma kimliği taşımaması
kuralı (security-check 8) bu kipte de korunur. Not: aynı VM servis hesabı Home'u doğrudan
çağırabildiği için bu, savunma derinliğidir; asıl sınır konteyner ayrımıdır.

Önbellek: tür başına; `expires_at`ten `YENILEME_PAYI_S` önce yenilenir; 401 alan istemci
`gecersiz_kil()` ile bir kez yeniler.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Generator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from tp_core.home_config import durum
from tp_core.home_config import yukleyici as y

YETKI_ENV = "TP_BAGLANTI_TOKENI"
YENILEME_PAYI_S = 120.0
JIRA_OAUTH_TABANI = "https://api.atlassian.com/ex/jira/"
TURLER = frozenset({"jira", "github"})


class BaglantiHatasi(Exception):
    """Token alınamadı (yetkisiz süreç, Home erişilemedi/reddetti, sözleşme dışı yanıt)."""


class TokenKipinde(BaglantiHatasi):
    """Home 409 `use_secret`: bağlantı `token` kipinde (sır env'den okunur)."""


class DepoTanimliDegil(BaglantiHatasi):
    """Home 409 `repo_required`: GitHub App kipinde projede depo tanımlı değil (kurulumun tüm
    depolarına token basılmaz)."""


def _hata_kodu(r: y.HttpYanit) -> str:
    try:
        v = r.json()
    except y.SozlesmeHatasi:
        return ""
    return str(v.get("error") or "") if isinstance(v, dict) else ""


@dataclass(frozen=True)
class ErisimTokeni:
    kip: str
    access_token: str
    expires_at: float  # epoch sn
    base_url: str | None

    def __repr__(self) -> str:  # token loglara düşmesin
        return f"ErisimTokeni(kip={self.kip!r}, expires_at={self.expires_at!r})"


def _bitis(deger: Any) -> float:
    if isinstance(deger, int | float):
        return float(deger)
    if isinstance(deger, str) and deger:
        try:
            return float(deger)
        except ValueError:
            return datetime.fromisoformat(deger.replace("Z", "+00:00")).timestamp()
    raise ValueError("expires_at yok")


class BaglantiTokenIstemcisi:
    def __init__(
        self,
        base_url: str,
        proje: str,
        id_token: Callable[[str], str],
        *,
        audience: str | None = None,
        http: y.Http = y.urllib_http,
        saat: Callable[[], float] = time.time,
        zaman_asimi: float = y.ZAMAN_ASIMI_S,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.proje = proje
        self.audience = (audience or self.base_url).rstrip("/")
        self._id_token = id_token
        self._http = http
        self._saat = saat
        self._zaman_asimi = zaman_asimi
        self._onbellek: dict[str, ErisimTokeni] = {}
        self._kilit = threading.Lock()

    def _iste(self, tur: str) -> ErisimTokeni:
        import json

        try:
            token = self._id_token(self.audience)
            r = self._http(
                "POST",
                f"{self.base_url}/v1/connections/access-token",
                {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json.dumps({"project": self.proje, "type": tur}).encode(),
                self._zaman_asimi,
            )
        except y.Ulasilamaz as exc:
            raise BaglantiHatasi(f"{tur}: Home erişilemedi") from exc
        if r.durum == 409:
            kod = _hata_kodu(r)
            if kod == "use_secret":
                raise TokenKipinde(f"{tur}: bağlantı token kipinde (use_secret)")
            if kod == "repo_required":
                raise DepoTanimliDegil(f"{tur}: Projede depo tanımlı değil (repo_required)")
            raise BaglantiHatasi(f"{tur}: access-token 409 ({kod or 'kod yok'})")
        if r.durum != 200:
            raise BaglantiHatasi(f"{tur}: access-token {r.durum}")
        try:
            v = r.json()
            tok = ErisimTokeni(
                kip=str(v["mode"]),
                access_token=str(v["access_token"]),
                expires_at=_bitis(v.get("expires_at")),
                base_url=str(v["base_url"]) if v.get("base_url") else None,
            )
        except (KeyError, TypeError, ValueError, y.SozlesmeHatasi) as exc:
            raise BaglantiHatasi(f"{tur}: access-token yanıtı sözleşmeye uymuyor") from exc
        if not tok.access_token:
            raise BaglantiHatasi(f"{tur}: boş token")
        if tur == "jira" and not (tok.base_url or "").startswith(JIRA_OAUTH_TABANI):
            # Token yalnız Atlassian API ağ geçidine gider (başka adrese sızmasın).
            raise BaglantiHatasi("jira: base_url api.atlassian.com/ex/jira/… değil")
        return tok

    def al(self, tur: str) -> ErisimTokeni:
        if tur not in TURLER:
            raise BaglantiHatasi(f"bilinmeyen bağlantı türü: {tur}")
        with self._kilit:
            tok = self._onbellek.get(tur)
            if tok is not None and self._saat() < tok.expires_at - YENILEME_PAYI_S:
                return tok
            tok = self._iste(tur)
            self._onbellek[tur] = tok
            return tok

    def gecersiz_kil(self, tur: str) -> None:
        with self._kilit:
            self._onbellek.pop(tur, None)


_ISTEMCI: BaglantiTokenIstemcisi | None = None
_ISTEMCI_KILIDI = threading.Lock()


def configure(istemci: BaglantiTokenIstemcisi | None) -> None:
    """Testler: sahte Home ile kurulmuş istemci (None = sıfırla)."""
    global _ISTEMCI
    _ISTEMCI = istemci


def yetkili_surec() -> bool:
    return (os.environ.get(YETKI_ENV) or "").strip() == "1"


def istemci() -> BaglantiTokenIstemcisi:
    global _ISTEMCI
    if not yetkili_surec():
        raise BaglantiHatasi(
            "bağlantı token'ı yalnız yazma kimliği taşıyan süreçte (core-worker, "
            "TP_BAGLANTI_TOKENI=1) alınabilir"
        )
    with _ISTEMCI_KILIDI:
        if _ISTEMCI is None:
            proje = y.ayar(os.environ, y.PROJE_ENV)
            url, audience = y.home_adresi(os.environ)
            if not proje or not url:
                raise BaglantiHatasi("TP_HOME_PROJECT / AIPROBE_HOME_RUN_URL eksik")
            _ISTEMCI = BaglantiTokenIstemcisi(
                url, proje, durum._id_token, audience=audience,
                http=durum._YAPI.http or y.urllib_http,
            )  # fmt: skip
        return _ISTEMCI


def token_al(tur: str) -> ErisimTokeni:
    return istemci().al(tur)


def gecersiz_kil(tur: str) -> None:
    if _ISTEMCI is not None:
        _ISTEMCI.gecersiz_kil(tur)


# ------------------------------------------------------------------ istemci kimlik sarmalayıcıları


class HomeJiraAuth(httpx.Auth):
    """Jira OAuth (3LO): her istekte önbellekli Bearer; 401'de bir kez yeniler."""

    def __init__(self, saglayici: Callable[[], ErisimTokeni] | None = None) -> None:
        self._saglayici = saglayici or (lambda: token_al("jira"))

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = f"Bearer {self._saglayici().access_token}"
        yanit = yield request
        if yanit.status_code == 401:
            gecersiz_kil("jira")
            request.headers["Authorization"] = f"Bearer {self._saglayici().access_token}"
            yield request


class HomeGitHubAuth:
    """`GitHubAuth` protokolü (forge_github): GitHub App kurulum token'ı Home'dan."""

    def __init__(self, saglayici: Callable[[], ErisimTokeni] | None = None) -> None:
        self._saglayici = saglayici or (lambda: token_al("github"))

    def token(self, client: httpx.Client) -> str:
        return self._saglayici().access_token

    def invalidate(self) -> None:
        gecersiz_kil("github")


def jira_oauth_mu() -> bool:
    return durum.baglanti_kipi("jira") == "oauth"


def github_app_mi() -> bool:
    return durum.baglanti_kipi("github") == "app"
