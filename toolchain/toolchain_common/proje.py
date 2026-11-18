"""İstek gövdesindeki `proje` bloğu (TP-COK-PROJE-PLANI §4.4, K1/K2).

toolchain süreç ayarları (`settings.py`) kurulum düzeyidir (D). Çok projeli core, projeye özgü
değerleri her istekte `proje` bloğunda gönderir; `settings(proje)` bu değerleri ortamın üstüne
yazar. Blok yoksa ya da alan yoksa/None ise ortam değeri kullanılır (geriye uyum: core ve
toolchain ayrı dağıtılabilir).

- `forge_path` / `mirror_path` forge (resp. ayna) kökünün altında olmalıdır: kök, ortamdaki
  `TP_FORGE_PATH` (`TP_FORGE_MIRROR_PATH`) yolunun üst dizinidir (`/forge`, `/forge-mirror`).
- `app.<platform>` verilirse o platformun uygulama ayarları (`TP_APP_{ID,PATH,ACTIVITY,ARGS,
  WORKDIR}_<P>`) YALNIZ bloktan gelir (ortamla karışmaz). Cihaz/Appium ayarları (`APPIUM_URL_*`,
  `TP_DEVICE_*`, `TP_PLATFORM_VERSION`) paylaşımlı havuzdur (K2): her zaman ortamdan.
- `e2e_app_root` / `e2e_java_root` (Java test kökleri, `TP_E2E_APP_ROOT` / `TP_E2E_JAVA_ROOT`)
  ve `app_paths` (`TP_APP_PATHS`; boş liste = uygulama yolu karşılaştırması yok) ortamın üstüne
  yazılır. Platform ayrı GitHub deposundaysa core bu alanları ve o deponun `mirror_path` /
  `remote_url`'ini her zaman gönderir (platform-depo ANALIZ §3.2.9; ayna
  `/forge-mirror/_depolar/<pid>/<sahip>/<ad>.git`).
- `probe_password` ve `remote_token` repr'da görünmez (loglara düşmesin).
- `remote_token`: uzak depo (ayna) okuma token'ı. GitHub bağlantısı Home'da `app` kipindeyken
  core-worker projenin kısa ömürlü kurulum token'ını (`/v1/connections/access-token
  {type: github}`) basar ve burada iletir; ortamdaki `TP_FORGE_REMOTE_TOKEN`'ın yerine geçer.
  **test-runner'a iletilmez** (`TEST_RUNNER_HARIC`): test kodu koşan konteyner depo kimliği
  görmez.
- Token (bloktaki ya da ortamdaki) yalnız ayna adresi https ve GitHub host'undaysa kullanılır
  (`token_gonderilir_mi`; izinli host'lar `TP_GITHUB_HOSTS`, D, virgüllü; varsayılan `github.com`).
  Proje bloğu aynayı başka host'a çevirirse token oraya gönderilmez.
"""

from __future__ import annotations

import os
import re
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

PID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_KONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
KOSU_PAROLA_EN_COK = 100  # Home `tp.test_users.run_pool` ui.max_items
KOSU_KULLANICI_EN_UZUN = 200  # Home ui.max_item_length
KOSU_PAROLA_EN_UZUN = 1024


def kosu_parolalari(v: object) -> dict[str, str]:
    """Koşu hesabı başına parola haritası (`TP_RUN_DEALER_PASSWORDS`, Home
    `tp.test_users.run_pool_passwords`: JSON `{"<kullanıcı>": "<parola>"}`) doğrulaması.
    Hata iletileri değeri (parolayı) içermez."""
    if not isinstance(v, dict):
        raise ValueError("run_dealer_passwords bir nesne olmalı")
    if len(v) > KOSU_PAROLA_EN_COK:
        raise ValueError(f"run_dealer_passwords en fazla {KOSU_PAROLA_EN_COK} hesap")
    out: dict[str, str] = {}
    for ad, parola in v.items():
        if not isinstance(ad, str) or not isinstance(parola, str):
            raise ValueError("run_dealer_passwords anahtar ve değerleri metin olmalı")
        ad = ad.strip()
        if not ad or len(ad) > KOSU_KULLANICI_EN_UZUN or _KONTROL_RE.search(ad) or "," in ad:
            raise ValueError("run_dealer_passwords kullanıcı adı geçersiz")
        if not parola or len(parola) > KOSU_PAROLA_EN_UZUN or _KONTROL_RE.search(parola):
            raise ValueError("run_dealer_passwords parolası boş/çok uzun ya da denetim karakterli")
        out[ad] = parola
    return out


_PS_RE = re.compile(r"['‘’‚‛\x00-\x1f\x7f]")

# toolchain-worker'da kalan, test-runner'a iletilmeyen alanlar.
TEST_RUNNER_HARIC = frozenset({"remote_token"})

GITHUB_HOSTS_ENV = "TP_GITHUB_HOSTS"
VARSAYILAN_GITHUB_HOSTS = ("github.com",)

DEFAULT_FORGE_PATH = "/forge/demo-app.git"
DEFAULT_MIRROR_PATH = "/forge-mirror/demo-app.git"

AppPlatform = Literal["android", "ios", "windows"]
# Blok alanı → e2e-app ortam adı (runner/java_run.APP_ENV'in uygulama kısmı).
APP_ALANLARI: dict[str, str] = {
    "app_id": "APP_ID",
    "path": "APP_PATH",
    "activity": "APP_ACTIVITY",
    "args": "APP_ARGS",
    "workdir": "APP_WORKDIR",
}


def forge_koku() -> PurePosixPath:
    return PurePosixPath(os.environ.get("TP_FORGE_PATH") or DEFAULT_FORGE_PATH).parent


def ayna_koku() -> PurePosixPath:
    return PurePosixPath(os.environ.get("TP_FORGE_MIRROR_PATH") or DEFAULT_MIRROR_PATH).parent


def _mutlak_alt(deger: str, kok: PurePosixPath, ad: str) -> str:
    p = PurePosixPath(deger)
    if not p.is_absolute() or ".." in p.parts or _KONTROL_RE.search(deger):
        raise ValueError(f"{ad} mutlak ve '..' içermeyen bir yol olmalı")
    if p == kok or kok not in p.parents:
        raise ValueError(f"{ad} {kok} altında olmalı")
    return str(p)


def _goreli(deger: str, ad: str) -> str:
    """Depo içi göreli yol (mutlak değil, `..` yok, denetim karakteri yok)."""
    p = PurePosixPath(deger.strip())
    if not deger.strip() or p.is_absolute() or ".." in p.parts or _KONTROL_RE.search(deger):
        raise ValueError(f"{ad} göreli ve '..' içermeyen bir yol olmalı")
    return str(p)


def _url(deger: str, ad: str) -> str:
    v = deger.strip()
    if not re.match(r"^https?://[^\s/]+", v) or _KONTROL_RE.search(v):
        raise ValueError(f"{ad} http(s) adresi olmalı")
    return v.rstrip("/")


class AppAyari(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_id: str | None = None
    path: str | None = None
    activity: str | None = None
    args: str | None = None
    workdir: str | None = None

    @field_validator("app_id", "path", "activity", "args", "workdir")
    @classmethod
    def _kontrol(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if _KONTROL_RE.search(v):
            raise ValueError("denetim karakteri içeremez")
        return v.strip() or None

    def ortam(self) -> dict[str, str]:
        """e2e-app ortam adlarıyla dolu alanlar."""
        return {
            hedef: getattr(self, alan)
            for alan, hedef in APP_ALANLARI.items()
            if getattr(self, alan)
        }


ORTAM_TURLERI = ("dev", "test", "staging", "prod")
CANLI_TUR = "prod"


class OrtamBilgisi(BaseModel):
    """Koşunun test ortamı (Home proje ortamı; core 0048). `tur=prod` = Canlı: uygulamanın test
    verisi uçları (DEMOAPP_TEST_TOKEN) test-runner'a iletilmez, kırma koşuları reddedilir."""

    model_config = ConfigDict(extra="forbid")

    eid: str = Field(pattern=r"^[0-9a-f]{12}$")
    ad: str = Field(default="", max_length=200)
    tur: Literal["dev", "test", "staging", "prod"] = "test"

    @field_validator("ad")
    @classmethod
    def _ad(cls, v: str) -> str:
        if _KONTROL_RE.search(v):
            raise ValueError("ortam adı denetim karakteri içeremez")
        return v.strip()

    @property
    def canli(self) -> bool:
        return self.tur == CANLI_TUR


DIL_KOK_ADI_RE = re.compile(r"\ATP_[A-Z0-9_]{1,60}_ROOT(?:_(?:ANDROID|IOS|WINDOWS))?\Z")


class ProjeBlogu(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pid: str
    forge_path: str | None = None
    mirror_path: str | None = None
    remote_url: str | None = None
    base_url: str | None = None
    demo_api_url: str | None = None
    probe_user: str | None = None
    probe_password: str | None = Field(default=None, repr=False)
    remote_token: str | None = Field(default=None, repr=False)
    run_dealers: list[str] | None = None
    # Koşu hesabı başına parola (yalnız girilenler; olmayan hesap ortak parolayla girer).
    run_dealer_passwords: dict[str, str] | None = Field(default=None, repr=False)
    e2e_root: str | None = None
    e2e_app_root: str | None = None
    e2e_java_root: str | None = None
    # 014 test dilleri: dil kökleri (anahtar = env adı, ör. TP_E2E_PYTHON_ROOT ya da
    # TP_E2E_APP_PYTHON_ROOT_ANDROID; değer depo köküne göre göreli yol).
    dil_kokleri: dict[str, str] | None = None
    base_ref: str | None = None
    app_paths: list[str] | None = None
    app: dict[AppPlatform, AppAyari] | None = None
    # Koşunun test ortamı (yoksa ortamsız: proje ayarları).
    ortam: OrtamBilgisi | None = None

    @field_validator("pid")
    @classmethod
    def _pid(cls, v: str) -> str:
        if not PID_RE.match(v) or ".." in v:
            raise ValueError("pid geçersiz")
        return v

    @field_validator("forge_path")
    @classmethod
    def _forge(cls, v: str | None) -> str | None:
        return None if v is None else _mutlak_alt(v, forge_koku(), "forge_path")

    @field_validator("mirror_path")
    @classmethod
    def _ayna(cls, v: str | None) -> str | None:
        return None if v is None else _mutlak_alt(v, ayna_koku(), "mirror_path")

    @field_validator("remote_url")
    @classmethod
    def _uzak(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return v if v is None else ""
        return _url(v, "remote_url")

    @field_validator("base_url", "demo_api_url")
    @classmethod
    def _adres(cls, v: str | None, info: ValidationInfo) -> str | None:
        return None if v is None else _url(v, info.field_name or "adres")

    @field_validator("probe_user", "probe_password", "remote_token")
    @classmethod
    def _kimlik(cls, v: str | None) -> str | None:
        if v is not None and _KONTROL_RE.search(v):
            raise ValueError("denetim karakteri içeremez")
        return v

    @field_validator("run_dealers")
    @classmethod
    def _bayiler(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        out = [d.strip() for d in v if d.strip()]
        if any(_KONTROL_RE.search(d) or "," in d for d in out):
            raise ValueError("run_dealers öğeleri denetim karakteri/virgül içeremez")
        return out

    @field_validator("run_dealer_passwords", mode="before")
    @classmethod
    def _parolalar(cls, v: object) -> dict[str, str] | None:
        return None if v is None else kosu_parolalari(v)

    @field_validator("e2e_root", "e2e_app_root", "e2e_java_root")
    @classmethod
    def _e2e(cls, v: str | None, info: ValidationInfo) -> str | None:
        if v is None:
            return None
        return _goreli(v, info.field_name or "e2e_root")

    @field_validator("dil_kokleri")
    @classmethod
    def _dil_kokleri(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is None:
            return None
        if len(v) > 32:
            raise ValueError("dil_kokleri en fazla 32 anahtar")
        out: dict[str, str] = {}
        for ad, yol in v.items():
            if not DIL_KOK_ADI_RE.match(ad):
                raise ValueError(f"dil_kokleri anahtarı geçersiz: {ad!r}")
            out[ad] = _goreli(yol, f"dil_kokleri.{ad}")
        return out

    @field_validator("base_ref")
    @classmethod
    def _base_ref(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if (
            not v
            or len(v) > 200
            or v.startswith(("-", "/"))
            or ".." in v
            or any(c in v for c in " ~^:?*[\\")
        ):
            raise ValueError("base_ref geçersiz dal adı")
        return v

    @field_validator("app_paths")
    @classmethod
    def _yollar(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        out = [y.strip() for y in v if y.strip()]
        for y in out:
            if "," in y:
                raise ValueError("app_paths öğeleri virgül içeremez")
        return [_goreli(y, "app_paths") for y in out]

    @field_validator("app")
    @classmethod
    def _app(cls, v: dict[str, AppAyari] | None) -> dict[str, AppAyari] | None:
        pencere = (v or {}).get("windows")
        if pencere is not None:
            for alan in ("path", "args", "workdir", "app_id"):
                deger = getattr(pencere, alan)
                if deger and _PS_RE.search(deger):
                    # NovaWindows PowerShell'e kaçışsız geçirir (app-mcp ile aynı kural).
                    raise ValueError(f"windows.{alan} tek tırnak içeremez")
        return v

    def app_ayarlari(self) -> dict[str, dict[str, str]] | None:
        if self.app is None:
            return None
        return {p: a.ortam() for p, a in self.app.items()}


def github_hostlari() -> frozenset[str]:
    """Ayna token'ının gönderilebileceği host'lar (`TP_GITHUB_HOSTS`, yoksa `github.com`)."""
    ham = os.environ.get(GITHUB_HOSTS_ENV) or ""
    hostlar = {h.strip().lower().rstrip(".") for h in ham.split(",") if h.strip()}
    return frozenset(hostlar or VARSAYILAN_GITHUB_HOSTS)


def token_gonderilir_mi(adres: str | None) -> bool:
    """Ayna adresi https ve izinli GitHub host'unda mı (kullanıcı bilgisi / özel port olmadan)?"""
    if not adres:
        return False
    try:
        parca = urlsplit(adres.strip())
        port = parca.port
    except ValueError:
        return False
    host = (parca.hostname or "").lower().rstrip(".")
    return (
        parca.scheme == "https"
        and not parca.username
        and port in (None, 443)
        and host in github_hostlari()
    )
