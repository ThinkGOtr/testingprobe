"""toolchain-worker dil eklentileri (014; sözleşme specs/014-test-dilleri/plan.md §3.1).

`worker/diller/<dil>.py` modül düzeyinde `EKLENTI` (`WorkerDili`) tanımlar; keşif otomatik
(`pkgutil`), `_` önekli modüller atlanır. `lang` alanı kayıtlı adlardan doğrulanır (`adlar()`).
ts ve java da eklenti olarak kayıtlıdır (`ts.py`, `java.py`); bugünkü yollarını sarmalar.
"""

from __future__ import annotations

import importlib
import logging
import os
import pkgutil
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    import httpx

    from toolchain_common import repos
    from toolchain_common.settings import Settings
    from worker.check import CheckRequest

log = logging.getLogger(__name__)

WEB = "web"
APP_PLATFORMS = ("android", "ios", "windows")
PLATFORMLAR = (WEB, *APP_PLATFORMS)


@runtime_checkable
class WorkerDili(Protocol):
    ad: str
    platformlar: tuple[str, ...]
    steps: tuple[str, ...]
    hat: str

    def validate_test_file(self, yol: str) -> str: ...

    def symbols(
        self, cfg: Settings, full_sha: str, repo: Path, platform: str
    ) -> dict[str, Any]: ...

    def guard(
        self, cfg: Settings, repo: Path, base: str, head: str, mode: str, platform: str
    ) -> dict[str, Any]: ...

    def run_static(
        self,
        cfg: Settings,
        req: CheckRequest,
        head: repos.Located,
        base: str | None,
        runner_client: httpx.Client | None,
        steps: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]: ...


_KILIT = threading.Lock()
_KAYIT: dict[str, WorkerDili] | None = None
_HATALAR: dict[str, str] = {}


def kayit() -> dict[str, WorkerDili]:
    global _KAYIT
    with _KILIT:
        if _KAYIT is None:
            k: dict[str, WorkerDili] = {}
            for mod in pkgutil.iter_modules(__path__):  # type: ignore[name-defined]
                if mod.name.startswith("_"):
                    continue
                try:
                    e = importlib.import_module(f"{__name__}.{mod.name}").EKLENTI
                except Exception as exc:
                    _HATALAR[mod.name] = f"{type(exc).__name__}: {exc}"
                    log.warning("worker dil eklentisi yüklenemedi: %s (%s)", mod.name, exc)
                    continue
                k[e.ad] = e
            _KAYIT = k
        return _KAYIT


def eklenti(dil: str | None) -> WorkerDili | None:
    return kayit().get(dil or "")


def adlar() -> tuple[str, ...]:
    return tuple(kayit())


def hatalar() -> dict[str, str]:
    kayit()
    return dict(_HATALAR)


def _sifirla() -> None:
    global _KAYIT
    with _KILIT:
        _KAYIT = None
        _HATALAR.clear()


def kok(cfg: Settings, kok_ayari: str, varsayilan: str, platform: str | None = None) -> str:
    """Dil test projesi kökü (plan.md §3.1): proje bloğu `dil_kokleri` > `<ayar>_<P>` env >
    `<ayar>` env > varsayılan."""
    bloktan = dict(getattr(cfg, "dil_kokleri", None) or {})
    if platform and platform != WEB:
        ad_p = f"{kok_ayari}_{platform.upper()}"
        if (bloktan.get(ad_p) or "").strip():
            return bloktan[ad_p].strip()
    if (bloktan.get(kok_ayari) or "").strip():
        return bloktan[kok_ayari].strip()
    if platform and platform != WEB:
        deger = os.environ.get(f"{kok_ayari}_{platform.upper()}", "").strip()
        if deger:
            return deger
    return os.environ.get(kok_ayari, "").strip() or varsayilan


def resolve_lang(lang: str | None, platform: str | None) -> str:
    """`lang`/`platform`'dan etkin dil. ts/java için `worker.java.resolve_lang` (davranış ve
    iletiler değişmez); diğer diller kayıtlı eklentiden ve eklentinin platformlarından."""
    from worker import java as javayol

    if lang in (None, "", "ts", "java"):
        return javayol.resolve_lang(lang or None, platform)
    if platform and platform not in PLATFORMLAR:
        raise ValueError(f"platform yalnızca {PLATFORMLAR} olabilir")
    e = eklenti(lang)
    if e is None:
        raise ValueError(f"lang yalnızca {adlar()} olabilir")
    p = platform or WEB
    if p not in e.platformlar:
        raise ValueError(f"lang={lang} ile platform={p} uyuşmuyor")
    return str(lang)


def resolve_platform(lang: str | None, platform: str | None) -> str:
    resolve_lang(lang, platform)
    return platform or WEB


def statik_yolu_ekle(cfg: Settings) -> None:
    """tree-sitter dilbilgileri (`TP_DIL_STATIK`, imajda `/opt/dil-statik`; Dockerfile
    `dil-statik` aşaması `pip --target`) içe aktarılabilsin: kotlin/swift eklentileri
    tree-sitter'ı içe aktarmadan önce çağırır. Dizin yoksa (geliştirme) dokunmaz."""
    import sys

    yol = str(getattr(cfg, "dil_statik", "") or "")
    if yol and Path(yol).is_dir() and yol not in sys.path:
        sys.path.append(yol)
