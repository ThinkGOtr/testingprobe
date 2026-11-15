"""Home etkin config yükleyicisi — YALNIZ standart kütüphane (host python3 ≥ 3.9).

VM açılış betiği (`deploy/aiprobe/bin/up.sh`) bu modülü host'taki `python3` ile çalıştırır
(çekirdek imajı henüz derlenmemiştir); çalışan süreçler (`durum.py`) de aynı kodu kullanır.

Sözleşme (UYGULAMA-PLANI-R1 §6): `GET {home}/v1/config/effective?project={pid}` →
`{org, project, product, values, secrets, env, env_secrets, connections, etag}`; `If-None-Match`
ile 304. Çağrı, TP'nin mevcut ürün kimliğiyle yapılır: VM servis hesabının Google imzalı ID
token'ı, `audience` = `AIPROBE_HOME_RUN_URL` (redeem / session-check ile aynı).

Güvenlik kuralları:

- Home **korunan** (Deployment) anahtarları yazamaz (`KORUNAN`, `KORUNAN_ONEKLER`): veritabanı,
  oturum sırrı, kimlik bağları, config kaynağının kendisi … Ele geçirilmiş bir organizasyon
  yöneticisi TP'yi başka bir kimlik servisine ya da veritabanına yönlendiremez.
- Anahtar adı `^[A-Z][A-Z0-9_]{0,127}$`; değerde satır sonu / NUL yok (env dosyasına enjeksiyon).
- Sır referansı yalnız `projects/<p>/secrets/aiprobe-o…/versions/<v>` biçiminde ve (verilmişse)
  `SECRETS_PROJECT` projesinde olabilir; başka sır okunmaz.
- LKG dosyası yalnız Home yanıtını (sır **referansları**, değer değil) tutar; 0600.
- Hiçbir log satırı değer yazmaz; yalnız anahtar adları ve sayılar.
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger("tp_core.home_config")

KAYNAK_ENV = "CONFIG_SOURCE"
PROJE_ENV = "TP_HOME_PROJECT"
URL_ENV = "HOME_CONFIG_URL"
HOME_RUN_URL_ENV = "AIPROBE_HOME_RUN_URL"
SIR_PROJESI_ENV = "SECRETS_PROJECT"
LKG_ENV = "TP_CONFIG_LKG_PATH"
ZAMAN_ASIMI_S = 5.0

# Home'un hiçbir koşulda yazamayacağı anahtarlar (Deployment sınıfı ve güvenlik bayrakları).
KORUNAN: frozenset[str] = frozenset(
    {
        KAYNAK_ENV,
        PROJE_ENV,
        URL_ENV,
        SIR_PROJESI_ENV,
        LKG_ENV,
        "TP_BAGLANTI_TOKENI",
        "TP_CONFIG_YENILEME_S",
        "TP_DATABASE_URL",
        "TP_DB_REQUIRE_AUTH",
        "TP_SESSION_SECRET",
        "TP_SESSION_COOKIE_SECURE",
        "TP_AUTH_MODE",
        "TP_ALLOWED_ORIGINS",
        "TP_TRUSTED_PROXIES",
        "TP_TOOLCHAIN_TOKEN",
        "TP_TOOLCHAIN_REQUIRE_TOKEN",
        "TP_CHECKS_REQUIRE_MOUNT",
        "TP_TEST_TEK_HESAP",
        "TP_DEMO_MODE",
        "TP_ORTAM",
        "TP_MODEL_MODE",
        "TP_ASISTAN_DENETIM",
        "SEED_USER_PASSWORD",
        "JIRA_SIM_ADMIN_TOKEN",
        "GITHUB_MERGE_TOKEN",
        "DEMOAPP_TEST_TOKEN",
        "COMPOSE_FILE",
        "COMPOSE_PROFILES",
        "COMPOSE_PROJECT_NAME",
        "PATH",
        "HOME",
    }
)
KORUNAN_ONEKLER: tuple[str, ...] = (
    "AIPROBE_",
    "POSTGRES_",
    "TP_F0_",
    "DOCKER_",
    "PYTHON",
    "LD_",
    "UV_",
)
KORUNAN_SONEKLER: tuple[str, ...] = ("_PORT",)

# Hedef adres → o adrese gönderilen sırlar (Config R1 A1; registry `binds_secrets`in TP karşılığı,
# Home'un `env_unset`ine ek yerel derinlemesine savunma). Hedef Home'dan geliyorsa (varsayılan ya da
# Deployment'ın kendi değeri değilse) ve bağlı sır Home'dan gelmiyorsa sır KULLANILMAZ: ele
# geçirilmiş bir organizasyon yöneticisi hedefi değiştirip Deployment sırlarını (ör. korunan
# GITHUB_MERGE_TOKEN) kendi sunucusuna çektiremez. (varsayılan hedef, bağlı sırlar)
BAGLI_SIRLAR: dict[str, tuple[str | None, frozenset[str]]] = {
    "GITHUB_API_URL": (
        "https://api.github.com",
        frozenset(
            {"GITHUB_TOKEN", "GITHUB_READ_TOKEN", "GITHUB_ACTIONS_READ_TOKEN", "GITHUB_MERGE_TOKEN"}
        ),
    ),
    "TP_FORGE_REMOTE_URL": (None, frozenset({"TP_FORGE_REMOTE_TOKEN"})),
    "JIRA_BASE_URL": (None, frozenset({"JIRA_READ_TOKEN", "JIRA_WRITE_TOKEN"})),
    "XRAY_BASE_URL": (None, frozenset({"XRAY_CLIENT_ID", "XRAY_CLIENT_SECRET"})),
    "AZURE_OPENAI_ENDPOINT": (None, frozenset({"AZURE_OPENAI_API_KEY"})),
    "TP_DEMO_WEB_URL": (None, frozenset({"TP_PROBE_PASSWORD", "TP_AGENT_DEALER_PASSWORD"})),
    "DEMO_WEB_URL": (None, frozenset({"TP_PROBE_PASSWORD", "TP_AGENT_DEALER_PASSWORD"})),
    "BASE_URL": (None, frozenset({"TP_PROBE_PASSWORD", "TP_AGENT_DEALER_PASSWORD"})),
    "DEMO_API_URL": (None, frozenset({"TP_PROBE_PASSWORD", "TP_AGENT_DEALER_PASSWORD"})),
}
BAGLI_SIR_ADLARI: frozenset[str] = frozenset().union(*(s for _, s in BAGLI_SIRLAR.values()))

_ANAHTAR = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_SIR_REF = re.compile(
    r"^projects/(?P<proje>[a-z0-9][a-z0-9-]{0,62})/secrets/(?P<ad>aiprobe-o[a-z0-9-]{1,240})"
    r"/versions/(?P<surum>latest|[0-9]{1,10})$"
)
_YASAK_KARAKTER = re.compile(r"[\x00\r\n]")
OZELLIKLER: tuple[str, ...] = ("web", "android", "ios", "windows", "ai_agent")
KIPLER = frozenset({"token", "oauth", "app"})


def kaynak(env: Mapping[str, str] | None = None) -> str:
    """`home` yalnız açıkça istenirse; diğer her değer (boş dahil) `env`."""
    e = os.environ if env is None else env
    return "home" if (e.get(KAYNAK_ENV) or "").strip().lower() == "home" else "env"


def korunan_mi(anahtar: str) -> bool:
    return (
        anahtar in KORUNAN
        or anahtar.startswith(KORUNAN_ONEKLER)
        or anahtar.endswith(KORUNAN_SONEKLER)
    )


def gecerli_anahtar(anahtar: Any) -> bool:
    return isinstance(anahtar, str) and bool(_ANAHTAR.match(anahtar)) and not korunan_mi(anahtar)


def kaldirilabilir_mi(anahtar: Any) -> bool:
    """`env_unset` adı: geçerli (korunmayan) anahtar ya da hedefe bağlı bir sır (korunan olsa
    bile — ör. GITHUB_MERGE_TOKEN). Korunan başka bir ad (veritabanı, oturum sırrı …) silinemez."""
    return (
        isinstance(anahtar, str)
        and bool(_ANAHTAR.match(anahtar))
        and (anahtar in BAGLI_SIR_ADLARI or not korunan_mi(anahtar))
    )


def _url_norm(deger: Any) -> str:
    return str(deger or "").strip().rstrip("/").lower()


def bagli_sir_kaldirma(
    home_env: Mapping[str, str], home_sirlari: set[str] | frozenset[str], taban: Mapping[str, str]
) -> set[str]:
    """Yerel A1 kuralı: hedefi Home'dan gelen (varsayılan ya da tabandaki Deployment değeri
    olmayan) ve kendisi Home'dan gelmeyen bağlı sırların adları."""
    out: set[str] = set()
    for hedef, (varsayilan, sirlar) in BAGLI_SIRLAR.items():
        if hedef not in home_env:
            continue
        deger = _url_norm(home_env[hedef])
        if varsayilan is not None and deger == _url_norm(varsayilan):
            continue
        if hedef in taban and deger == _url_norm(taban[hedef]):
            continue
        out |= {s for s in sirlar if s not in home_sirlari}
    return out


def deger_metni(deger: Any) -> str | None:
    """Home değerini env metnine çevirir; `None` → yok. Satır sonu/NUL → `ValueError`."""
    if deger is None:
        return None
    if isinstance(deger, bool):
        metin = "1" if deger else "0"
    elif isinstance(deger, (int, float)):
        metin = str(deger)
    elif isinstance(deger, str):
        metin = deger
    elif isinstance(deger, (list, tuple)):
        metin = ",".join("" if x is None else str(x) for x in deger)
    elif isinstance(deger, dict):
        metin = json.dumps(deger, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    else:
        raise ValueError("desteklenmeyen değer türü")
    if _YASAK_KARAKTER.search(metin):
        raise ValueError("değer satır sonu ya da NUL içeriyor")
    return metin


def sir_ref_gecerli(ref: Any, sir_projesi: str | None = None) -> bool:
    if not isinstance(ref, str):
        return False
    m = _SIR_REF.match(ref)
    if m is None:
        return False
    return not sir_projesi or m.group("proje") == sir_projesi.strip()


# ------------------------------------------------------------------ HTTP (enjekte edilebilir)


class Ulasilamaz(Exception):
    """Home / metadata / Secret Manager erişilemedi (ağ, zaman aşımı, 5xx, 408, 429)."""


class Reddedildi(Exception):
    """Karşı taraf isteği reddetti (kalıcı 4xx)."""

    def __init__(self, durum: int, mesaj: str = "") -> None:
        super().__init__(f"{durum} {mesaj}".strip())
        self.durum = durum


class SozlesmeHatasi(Exception):
    """Yanıt sözleşmeye uymuyor."""


@dataclass(frozen=True)
class HttpYanit:
    durum: int
    basliklar: Mapping[str, str]
    govde: bytes

    def baslik(self, ad: str) -> str | None:
        return self.basliklar.get(ad.lower())

    def json(self) -> Any:
        try:
            return json.loads(self.govde.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise SozlesmeHatasi("JSON olmayan yanıt") from exc


# `Optional`: bu satır çalışma anında değerlendirilir; host python3 3.9'da `X | None` TypeError.
Http = Callable[[str, str, Mapping[str, str], Optional[bytes], float], HttpYanit]  # noqa: UP045
GECICI = frozenset({408, 429})


class _YonlendirmeYok(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a: Any, **kw: Any) -> None:
        return None  # Authorization başka adrese taşınmasın


_ACICI = urllib.request.build_opener(_YonlendirmeYok)


def urllib_http(
    yontem: str, url: str, basliklar: Mapping[str, str], govde: bytes | None, zaman_asimi: float
) -> HttpYanit:
    istek = urllib.request.Request(url, data=govde, method=yontem, headers=dict(basliklar))
    try:
        with _ACICI.open(istek, timeout=zaman_asimi) as r:
            return HttpYanit(
                r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(4 * 1024 * 1024)
            )
    except urllib.error.HTTPError as exc:
        return HttpYanit(
            exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, exc.read() or b""
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise Ulasilamaz(f"{yontem} {urllib.parse.urlsplit(url).netloc}: ağ hatası") from exc


# ------------------------------------------------------------------ GCE metadata kimliği


class MetadataKimligi:
    """VM servis hesabının ID token'ı (Home) ve erişim token'ı (Secret Manager); önbellekli."""

    TABAN = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default"
    ID_SURE_S = 50 * 60

    def __init__(self, http: Http = urllib_http, saat: Callable[[], float] = time.monotonic):
        self._http = http
        self._saat = saat
        self._id: dict[str, tuple[float, str]] = {}
        self._erisim: tuple[float, str] | None = None
        self._kilit = threading.Lock()

    def _al(self, yol: str) -> HttpYanit:
        r = self._http("GET", self.TABAN + yol, {"Metadata-Flavor": "Google"}, None, 3.0)
        if r.durum != 200 or not r.govde:
            raise Ulasilamaz("servis kimliği alınamadı")
        return r

    def id_token(self, audience: str) -> str:
        with self._kilit:
            kayit = self._id.get(audience)
            if kayit and self._saat() - kayit[0] < self.ID_SURE_S:
                return kayit[1]
        q = urllib.parse.urlencode({"audience": audience, "format": "full"})
        token = self._al(f"/identity?{q}").govde.decode().strip()
        with self._kilit:
            self._id[audience] = (self._saat(), token)
        return token

    def erisim_tokeni(self) -> str:
        with self._kilit:
            if self._erisim and self._saat() < self._erisim[0]:
                return self._erisim[1]
        v = self._al("/token").json()
        try:
            token, sure = str(v["access_token"]), float(v.get("expires_in") or 300)
        except (KeyError, TypeError, ValueError) as exc:
            raise SozlesmeHatasi("metadata token yanıtı") from exc
        with self._kilit:
            self._erisim = (self._saat() + max(30.0, sure - 60.0), token)
        return token


# ------------------------------------------------------------------ Secret Manager


class SecretManagerCozucu:
    """`projects/…/secrets/…/versions/…` → değer (REST `:access`). Biçim/proje denetimi burada da
    yapılır: çağıran ne verirse versin yalnız `aiprobe-o` önekli sırlar okunur."""

    URL = "https://secretmanager.googleapis.com/v1/"

    def __init__(
        self,
        erisim_tokeni: Callable[[], str],
        http: Http = urllib_http,
        sir_projesi: str | None = None,
        zaman_asimi: float = ZAMAN_ASIMI_S,
    ) -> None:
        self._token = erisim_tokeni
        self._http = http
        self._proje = sir_projesi
        self._zaman_asimi = zaman_asimi

    def __call__(self, ref: str) -> str:
        if not sir_ref_gecerli(ref, self._proje):
            raise Reddedildi(400, "sır referansı kabul edilmedi")
        r = self._http(
            "GET",
            f"{self.URL}{ref}:access",
            {"Authorization": f"Bearer {self._token()}", "Accept": "application/json"},
            None,
            self._zaman_asimi,
        )
        if r.durum >= 500 or r.durum in GECICI:
            raise Ulasilamaz(f"Secret Manager {r.durum}")
        if r.durum != 200:
            raise Reddedildi(r.durum, "Secret Manager")
        try:
            veri = r.json()["payload"]["data"]
            return base64.b64decode(veri).decode("utf-8")
        except (KeyError, TypeError, ValueError) as exc:
            raise SozlesmeHatasi("Secret Manager yanıtı") from exc


# ------------------------------------------------------------------ etkin config


@dataclass(frozen=True)
class EtkinConfig:
    ham: Mapping[str, Any]
    etag: str | None

    @classmethod
    def coz(cls, ham: Any, etag: str | None = None) -> EtkinConfig:
        if not isinstance(ham, Mapping):
            raise SozlesmeHatasi("yanıt nesne değil")
        for alan in ("env", "env_secrets", "connections", "values", "secrets"):
            if ham.get(alan) is not None and not isinstance(ham.get(alan), Mapping):
                raise SozlesmeHatasi(f"{alan} nesne değil")
        if ham.get("env_unset") is not None and not isinstance(ham.get("env_unset"), list):
            raise SozlesmeHatasi("env_unset liste değil")
        proje = ham.get("project")
        if not isinstance(proje, Mapping) or not isinstance(proje.get("pid"), str):
            raise SozlesmeHatasi("project.pid yok")
        if proje.get("features") is not None and not isinstance(proje.get("features"), Mapping):
            raise SozlesmeHatasi("project.features nesne değil")
        return cls(dict(ham), etag or (str(ham["etag"]) if ham.get("etag") else None))

    @property
    def env(self) -> Mapping[str, Any]:
        return self.ham.get("env") or {}

    @property
    def env_secrets(self) -> Mapping[str, Any]:
        return self.ham.get("env_secrets") or {}

    @property
    def env_unset(self) -> list[Any]:
        """Config R1 A1: Home'un "bu adları env görünümünden sil" listesi (hedefi Home'dan gelen,
        sırrı Home'dan gelmeyen bağlı sırlar)."""
        return list(self.ham.get("env_unset") or [])

    @property
    def proje(self) -> Mapping[str, Any]:
        return self.ham.get("project") or {}

    @property
    def org(self) -> Mapping[str, Any]:
        org = self.ham.get("org")
        return org if isinstance(org, Mapping) else {}

    @property
    def ozellikler(self) -> dict[str, bool]:
        """Bilinen beş özellik; yanıtta olmayan ya da `true` olmayan → kapalı (fail-closed)."""
        ham = self.proje.get("features") or {}
        return {o: ham.get(o) is True for o in OZELLIKLER}

    def baglanti(self, tur: str) -> Mapping[str, Any]:
        b = (self.ham.get("connections") or {}).get(tur)
        return b if isinstance(b, Mapping) else {}

    def baglanti_kipi(self, tur: str) -> str:
        """`token` | `oauth` | `app`; bağlantı yok ya da bilinmeyen kip → `token` (bugünkü yol)."""
        kip = str(self.baglanti(tur).get("mode") or "token").strip().lower()
        return kip if kip in KIPLER else "token"

    def baglanti_public(self, tur: str) -> Mapping[str, Any]:
        p = self.baglanti(tur).get("public")
        return p if isinstance(p, Mapping) else {}


class HomeConfigIstemcisi:
    """`GET /v1/config/effective` (ETag). 304 → `None`."""

    def __init__(
        self,
        base_url: str,
        proje: str,
        id_token: Callable[[str], str],
        *,
        audience: str | None = None,
        http: Http = urllib_http,
        zaman_asimi: float = ZAMAN_ASIMI_S,
    ) -> None:
        if not base_url or not proje:
            raise ValueError("Home adresi ve proje gerekli")
        self.base_url = base_url.rstrip("/")
        self.proje = proje
        self.audience = (audience or self.base_url).rstrip("/")
        self._id_token = id_token
        self._http = http
        self._zaman_asimi = zaman_asimi

    def cek(self, etag: str | None = None) -> EtkinConfig | None:
        token = self._id_token(self.audience)
        basliklar = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if etag:
            basliklar["If-None-Match"] = etag
        q = urllib.parse.urlencode({"project": self.proje})
        r = self._http(
            "GET", f"{self.base_url}/v1/config/effective?{q}", basliklar, None, self._zaman_asimi
        )
        if r.durum == 304:
            return None
        if r.durum >= 500 or r.durum in GECICI:
            raise Ulasilamaz(f"config/effective {r.durum}")
        if r.durum != 200:
            raise Reddedildi(r.durum, "config/effective")
        return EtkinConfig.coz(r.json(), r.baslik("etag"))


# ------------------------------------------------------------------ son bilinen iyi değer (LKG)

LKG_SURUM = 1


def lkg_oku(yol: str | None) -> EtkinConfig | None:
    if not yol:
        return None
    try:
        with open(yol, encoding="utf-8") as f:
            v = json.load(f)
        if v.get("surum") != LKG_SURUM:
            return None
        return EtkinConfig.coz(v["yanit"], v.get("etag"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError, AttributeError, SozlesmeHatasi):
        log.warning("home config LKG okunamadı (bozuk ya da eski biçim); yok sayılıyor")
        return None


def atomik_yaz(yol: str, metin: str, kip: int = 0o600) -> None:
    dizin = os.path.dirname(os.path.abspath(yol))
    os.makedirs(dizin, mode=0o700, exist_ok=True)
    fd, gecici = tempfile.mkstemp(prefix=".tp-", dir=dizin)
    try:
        os.fchmod(fd, kip)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(metin)
            f.flush()
            os.fsync(f.fileno())
        os.replace(gecici, yol)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(gecici)
        raise


def lkg_yaz(yol: str | None, cfg: EtkinConfig, saat: Callable[[], float] = time.time) -> None:
    if not yol:
        return
    kayit = {"surum": LKG_SURUM, "alindi": int(saat()), "etag": cfg.etag, "yanit": cfg.ham}
    try:
        atomik_yaz(yol, json.dumps(kayit, ensure_ascii=False, sort_keys=True))
    except OSError:
        log.warning("home config LKG yazılamadı (%s)", os.path.dirname(yol), exc_info=True)


@dataclass
class YuklemeSonucu:
    cfg: EtkinConfig | None
    # `home` (taze ya da 304), `lkg` (Home yok, diskteki son iyi değer), `env` (ikisi de yok).
    kaynak: str
    degisti: bool = False
    hata: str | None = None


class Yukleyici:
    """Home → (304 ise bellekteki/LKG) → LKG → env sırası. Yalnız başarılı 200 LKG'ye yazılır."""

    def __init__(self, istemci: HomeConfigIstemcisi, lkg_yolu: str | None) -> None:
        self.istemci = istemci
        self.lkg_yolu = lkg_yolu
        self.son: EtkinConfig | None = None

    def yukle(self) -> YuklemeSonucu:
        onceki = self.son or lkg_oku(self.lkg_yolu)
        try:
            yeni = self.istemci.cek(onceki.etag if onceki else None)
        except (Ulasilamaz, Reddedildi, SozlesmeHatasi) as exc:
            hata = f"{type(exc).__name__}: {exc}"
            log.warning("aiprobe-home config alınamadı (%s)", hata)
            if onceki is not None:
                self.son = onceki
                return YuklemeSonucu(onceki, "lkg", hata=hata)
            return YuklemeSonucu(None, "env", hata=hata)
        if yeni is None:  # 304
            if onceki is None:  # olmamalı: ETag göndermedik
                return YuklemeSonucu(None, "env", hata="304 ama önbellek yok")
            self.son = onceki
            return YuklemeSonucu(onceki, "home")
        degisti = onceki is None or dict(onceki.ham) != dict(yeni.ham)
        self.son = yeni
        lkg_yaz(self.lkg_yolu, yeni)
        return YuklemeSonucu(yeni, "home", degisti=degisti)


# ------------------------------------------------------------------ env görünümü


@dataclass
class EnvGorunumu:
    degerler: dict[str, str] = field(default_factory=dict)
    # Reddedilen (korunan/geçersiz ad, geçersiz değer/ref) ve çözülemeyen sır anahtarları (adlar).
    reddedilen: list[str] = field(default_factory=list)
    cozulemeyen: list[str] = field(default_factory=list)
    # Env görünümünden SİLİNECEK adlar (A1: Home `env_unset` ∪ yerel bağlı sır kuralı).
    kaldirilan: list[str] = field(default_factory=list)


def env_gorunumu(
    cfg: EtkinConfig,
    cozucu: Callable[[str], str] | None = None,
    *,
    sir_projesi: str | None = None,
    taban: Mapping[str, str] | None = None,
) -> EnvGorunumu:
    """`env` + (çözücü verilmişse) `env_secrets` → `{LEGACY: metin}`. Çözücü yoksa sırlar atlanır
    (çalışan süreç sırları yalnız açılışta alır).

    `kaldirilan` = Home `env_unset` ∪ `bagli_sir_kaldirma` (taban = Home uygulanmadan önceki env).
    Bir ad hem gelen değerlerde hem silinecekler listesindeyse silme kazanır (fail-closed)."""
    out = EnvGorunumu()
    for k, v in sorted(cfg.env.items()):
        if not gecerli_anahtar(k):
            out.reddedilen.append(str(k))
            continue
        try:
            metin = deger_metni(v)
        except ValueError:
            out.reddedilen.append(k)
            continue
        if metin is not None:
            out.degerler[k] = metin
    if cozucu is None:
        _kaldirilanlari_hesapla(out, cfg, False, taban or {})
        return out
    for k, ref in sorted(cfg.env_secrets.items()):
        if not gecerli_anahtar(k) or not sir_ref_gecerli(ref, sir_projesi):
            out.reddedilen.append(str(k))
            continue
        try:
            metin = cozucu(ref)
        except (Ulasilamaz, Reddedildi, SozlesmeHatasi):
            out.cozulemeyen.append(k)
            continue
        if _YASAK_KARAKTER.search(metin):
            out.reddedilen.append(k)
            continue
        out.degerler[k] = metin
    _kaldirilanlari_hesapla(out, cfg, cozucu is not None, taban or {})
    if out.reddedilen:
        log.warning("home config: reddedilen anahtarlar: %s", ", ".join(sorted(out.reddedilen)))
    if out.cozulemeyen:
        log.warning(
            "home config: çözülemeyen sırlar (env değeri kalır): %s",
            ", ".join(sorted(out.cozulemeyen)),
        )
    return out


def _kaldirilanlari_hesapla(
    out: EnvGorunumu, cfg: EtkinConfig, sirlar_cozuldu: bool, taban: Mapping[str, str]
) -> None:
    kaldir: set[str] = set()
    for ad in cfg.env_unset:
        if kaldirilabilir_mi(ad):
            kaldir.add(ad)
        else:
            out.reddedilen.append(str(ad))
    # Sır Home'dan "geliyor" sayılır: açılışta yalnız gerçekten çözülenler (çözülemeyen sırda taban
    # değeri kalırdı — o da Home hedefine gitmesin); çalışma anında referansı geçerli olanlar.
    if sirlar_cozuldu:
        home_sirlari = {k for k in cfg.env_secrets if k in out.degerler}
    else:
        home_sirlari = {k for k, r in cfg.env_secrets.items() if gecerli_anahtar(k) and r}
    kaldir |= bagli_sir_kaldirma(out.degerler, home_sirlari, taban)
    for ad in kaldir:
        out.degerler.pop(ad, None)
    out.kaldirilan = sorted(kaldir)
    if kaldir:
        log.warning(
            "home config: hedefe bağlı sırlar kullanılmayacak (env_unset): %s",
            ", ".join(out.kaldirilan),
        )


# ------------------------------------------------------------------ env dosyası

BLOK_BASI = "# --- aiprobe-home etkin config (CONFIG_SOURCE=home; elle düzenlemeyin) ---"
_SATIR = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def env_metni_coz(metin: str) -> dict[str, str]:
    """Basit .env ayrıştırıcı (KEY=VALUE, `export`, tek/çift tırnak); son tanım kazanır."""
    out: dict[str, str] = {}
    for satir in metin.splitlines():
        if not satir.strip() or satir.lstrip().startswith("#"):
            continue
        m = _SATIR.match(satir)
        if not m:
            continue
        deger = m.group(2).strip()
        if len(deger) >= 2 and deger[0] == deger[-1] and deger[0] in "'\"":
            deger = deger[1:-1]
            if m.group(2).strip()[0] == '"':
                deger = deger.replace('\\"', '"').replace("\\\\", "\\")
        else:
            deger = deger.split(" #", 1)[0].strip()
        out[m.group(1)] = deger
    return out


def env_satiri(anahtar: str, deger: str) -> str:
    """Hem compose `.env`/`--env-file` hem bash `source` için güvenli satır (genişletme yok)."""
    if _YASAK_KARAKTER.search(deger):
        raise ValueError("satır sonu")
    if "'" not in deger:
        return f"{anahtar}='{deger}'"
    if any(c in deger for c in '"\\$`'):
        raise ValueError("tırnaklanamayan değer")
    return f'{anahtar}="{deger}"'


def env_dosyasi_birlestir(
    taban: str, yeni: Mapping[str, str], kaldir: Iterable[str] = ()
) -> tuple[str, list[str]]:
    """Taban .env'den Home'un ezdiği anahtarların ve `kaldir` (A1 `env_unset`) adlarının
    satırlarını ve eski Home bloğunu çıkarır, sonuna yeni bloğu ekler. (metin, yazılamayan)."""
    sil = set(kaldir)
    satirlar: list[str] = []
    for satir in taban.splitlines():
        if satir.strip() == BLOK_BASI:
            break  # önceki Home bloğu (dosya kendi üzerine yeniden üretildiyse)
        m = _SATIR.match(satir)
        if m and (m.group(1) in yeni or m.group(1) in sil):
            continue
        satirlar.append(satir)
    while satirlar and not satirlar[-1].strip():
        satirlar.pop()
    blok: list[str] = []
    yazilamayan: list[str] = []
    for k in sorted(yeni):
        if k in sil:
            continue
        try:
            blok.append(env_satiri(k, yeni[k]))
        except ValueError:
            yazilamayan.append(k)
    if blok:
        satirlar += ["", BLOK_BASI, *blok]
    return "\n".join(satirlar) + "\n", yazilamayan


def ayar(env: Mapping[str, str], ad: str) -> str:
    return (env.get(ad) or "").strip()


def home_adresi(env: Mapping[str, str]) -> tuple[str, str]:
    """(çağrı adresi, ID token audience). Audience daima `AIPROBE_HOME_RUN_URL` (Home ürün uçları
    aynı audience'ı bekler); `HOME_CONFIG_URL` yalnız farklı bir taban gerekiyorsa."""
    run = ayar(env, HOME_RUN_URL_ENV)
    return (ayar(env, URL_ENV) or run, run or ayar(env, URL_ENV))
