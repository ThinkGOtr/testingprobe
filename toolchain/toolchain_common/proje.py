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
- `probe_password` ve `remote_token` repr'da görünmez (loglara düşmesin).
- `remote_token`: uzak depo (ayna) okuma token'ı. GitHub bağlantısı Home'da `app` kipindeyken
  core-worker projenin kısa ömürlü kurulum token'ını (`/v1/connections/access-token
  {type: github}`) basar ve burada iletir; ortamdaki `TP_FORGE_REMOTE_TOKEN`'ın yerine geçer.
  **test-runner'a iletilmez** (`TEST_RUNNER_HARIC`): test kodu koşan konteyner depo kimliği
  görmez.
"""

from __future__ import annotations

import os
import re
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

PID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_KONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_PS_RE = re.compile(r"['‘’‚‛\x00-\x1f\x7f]")

# toolchain-worker'da kalan, test-runner'a iletilmeyen alanlar.
TEST_RUNNER_HARIC = frozenset({"remote_token"})

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
    e2e_root: str | None = None
    app: dict[AppPlatform, AppAyari] | None = None

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

    @field_validator("e2e_root")
    @classmethod
    def _e2e(cls, v: str | None) -> str | None:
        if v is None:
            return None
        p = PurePosixPath(v.strip())
        if not v.strip() or p.is_absolute() or ".." in p.parts or _KONTROL_RE.search(v):
            raise ValueError("e2e_root göreli ve '..' içermeyen bir yol olmalı")
        return str(p)

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
