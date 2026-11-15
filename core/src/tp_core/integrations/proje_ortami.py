"""Entegrasyon istemcilerinin proje başına config görünümü (TP-COK-PROJE-PLANI §3.3, §4).

Adaptör fabrikaları (`get_forge(env)`, `LocalForge.from_env(env)`, `GitHubForge.from_env(env)`,
`GitHubCiOkuyucu.kur(env)`) tarihsel olarak bir ad → değer haritası alır. `ProjeOrtami(pid)` bu
haritanın proje başına sürümüdür; fabrikalar `env` verilmezse `os.environ` yerine bunu kullanır:

- **Proje anahtarları** (`PROJE_ANAHTARLARI` T/A/P + `EK_PROJE_ANAHTARLARI`): `proje.ayar(ad,
  pid=pid)` — proje etkin config'i; varsayılan projede `os.environ`'a düşer (geriye uyum), diğer
  projelerde **düşmez** (Bayi Portalı'nın değeri başka projeye sızmaz; tanımsız = yok).
- **Forge yolları** (`TP_FORGE_PATH`, `TP_FORGE_PRS_PATH`, `TP_FORGE_MIRROR_PATH`):
  `forge_yollari` (varsayılan projede eski yollar).
- **Diğer adlar** (D: kurulum — zaman aşımları, artefakt yolu, GH_APP_ID …): `os.environ`.

Bağlantı kipi ve Home erişim token'ı da proje başınadır (§4.2; Config R1 `home_config.baglanti`):
`baglanti_kipi(tur, pid)`, `token_al(tur, pid)`, `gecersiz_kil(tur, pid)` ve istemci kimlik
sarmalayıcıları `ProjeJiraAuth` / `ProjeGitHubAuth`. Şerit 2 `baglanti.token_al(tur, pid)` ve
`durum.etkin(pid)`'i sağlayana dek varsayılan dışı proje token kipine düşer (sır `ayar()`'dan).
"""

from __future__ import annotations

import inspect
import os
from collections.abc import Callable, Generator, Iterator, Mapping
from functools import cache
from typing import TYPE_CHECKING, Any

import httpx

from tp_core.home_config import baglanti
from tp_core.integrations import forge_yollari
from tp_core.proje import ayar as _ayar
from tp_core.proje.ayar import PROJE_ANAHTARLARI
from tp_core.proje.baglam import varsayilan_pid

if TYPE_CHECKING:
    from tp_core.home_config.baglanti import ErisimTokeni

PLATFORMLAR = ("android", "ios", "windows")
APP_ALANLARI = {
    "app_id": "TP_APP_ID",
    "path": "TP_APP_PATH",
    "activity": "TP_APP_ACTIVITY",
    "args": "TP_APP_ARGS",
    "workdir": "TP_APP_WORKDIR",
}

# Şerit 3'ün eklediği T (proje) adları: toolchain `proje` bloğunun kaynakları (§4.4) ve forge
# kipinin proje ayarları. Şerit 0/2 `PROJE_ANAHTARLARI`'na katılmalı (statik test için).
EK_PROJE_ANAHTARLARI: frozenset[str] = frozenset(
    {
        "BASE_URL",
        "DEMO_API_URL",
        "TP_PROBE_USER",
        "TP_RUN_DEALERS",
        "TP_E2E_ROOT",
        *(f"{a}_{p.upper()}" for a in APP_ALANLARI.values() for p in PLATFORMLAR),
    }
)

FORGE_YOLLARI: dict[str, Callable[[str], Any]] = {
    "TP_FORGE_PATH": forge_yollari.depo_yolu,
    "TP_FORGE_PRS_PATH": forge_yollari.pr_dosyasi,
    "TP_FORGE_MIRROR_PATH": forge_yollari.ayna_yolu,
}


def proje_anahtari_mi(ad: str) -> bool:
    return ad in PROJE_ANAHTARLARI or ad in EK_PROJE_ANAHTARLARI


def pid_coz(pid: str | None = None) -> str:
    """`pid` verilmezse bağlamdaki proje (bağlam ve config kaynağı yoksa varsayılan)."""
    return _ayar._pid(pid)


class ProjeOrtami(Mapping[str, str]):
    """Bir projenin legacy ad → değer görünümü (salt okunur)."""

    def __init__(self, pid: str | None = None) -> None:
        self.pid = pid_coz(pid)
        self.varsayilan = self.pid == varsayilan_pid()

    def get(self, ad: str, default: Any = None) -> Any:  # type: ignore[override]
        try:
            return self[ad]
        except KeyError:
            return default

    def __getitem__(self, ad: str) -> str:
        if ad in FORGE_YOLLARI:
            if self.varsayilan and ad not in os.environ:
                raise KeyError(ad)  # eski davranış: adaptör kendi varsayılanını kullanır
            return str(FORGE_YOLLARI[ad](self.pid))
        if proje_anahtari_mi(ad):
            deger = _ayar.ayar(ad, pid=self.pid)
            if deger is None:
                raise KeyError(ad)
            return deger
        return os.environ[ad]

    def _adlar(self) -> set[str]:
        adlar = {a for a in os.environ if not proje_anahtari_mi(a)}
        adlar |= {a for a in PROJE_ANAHTARLARI | EK_PROJE_ANAHTARLARI if a in self}
        adlar |= {a for a in FORGE_YOLLARI if a in self}
        return adlar

    def __contains__(self, ad: object) -> bool:
        if not isinstance(ad, str):
            return False
        try:
            self[ad]
        except KeyError:
            return False
        return True

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._adlar()))

    def __len__(self) -> int:
        return len(self._adlar())

    def __repr__(self) -> str:  # değerler (sırlar) loglara düşmesin
        return f"ProjeOrtami(pid={self.pid!r})"


# ------------------------------------------------------------ bağlantı kipi ve Home token'ı


@cache
def _pid_destekler(fn: Callable[..., Any]) -> bool:
    try:
        return "pid" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _cfg(pid: str) -> Any:
    """Projenin Home etkin config'i (yoksa None)."""
    from tp_core.home_config import durum

    if _pid_destekler(durum.etkin):
        return durum.etkin(pid=pid)
    return durum.etkin() if pid == varsayilan_pid() else None


def baglanti_kipi(tur: str, pid: str | None = None) -> str:
    """`token` | `oauth` | `app` (Home etkin config'i yoksa `token`)."""
    cfg = _cfg(pid_coz(pid))
    return "token" if cfg is None else str(cfg.baglanti_kipi(tur))


def baglanti_public(tur: str, pid: str | None = None) -> Mapping[str, Any]:
    cfg = _cfg(pid_coz(pid))
    return {} if cfg is None else cfg.baglanti_public(tur)


def token_al(tur: str, pid: str | None = None) -> ErisimTokeni:
    """Home'dan projenin bağlantı token'ı (`POST /v1/connections/access-token {project: pid}`)."""
    p = pid_coz(pid)
    if _pid_destekler(baglanti.token_al):
        return baglanti.token_al(tur, pid=p)
    if p != varsayilan_pid():
        raise baglanti.BaglantiHatasi(f"{tur}: proje başına bağlantı token'ı desteklenmiyor ({p})")
    return baglanti.token_al(tur)


def gecersiz_kil(tur: str, pid: str | None = None) -> None:
    p = pid_coz(pid)
    if _pid_destekler(baglanti.gecersiz_kil):
        baglanti.gecersiz_kil(tur, pid=p)
    elif p == varsayilan_pid():
        baglanti.gecersiz_kil(tur)


class ProjeJiraAuth(baglanti.HomeJiraAuth):
    """Jira OAuth (3LO) Bearer, projenin bağlantısından; 401'de bir kez yeniler."""

    def __init__(self, pid: str) -> None:
        super().__init__(lambda: token_al("jira", pid))
        self.pid = pid

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = f"Bearer {self._saglayici().access_token}"
        yanit = yield request
        if yanit.status_code == 401:
            gecersiz_kil("jira", self.pid)
            request.headers["Authorization"] = f"Bearer {self._saglayici().access_token}"
            yield request


class ProjeGitHubAuth(baglanti.HomeGitHubAuth):
    """`GitHubAuth` protokolü: projenin GitHub App kurulum token'ı Home'dan."""

    def __init__(self, pid: str) -> None:
        super().__init__(lambda: token_al("github", pid))
        self.pid = pid

    def invalidate(self) -> None:
        gecersiz_kil("github", self.pid)
